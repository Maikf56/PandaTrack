"""BatchDispatcher.dispatch 编排（模块 07 §3.3.2 / §3.7）。

把 P2 的纯算法（consolidate/recent_checker/chunk/assign_slots/interval/
plan_next_round）组合成完整调度流程：

  多客户单号 → ①汇总去重 → ②库内近期去重 → ③35切片 → ④环境代分配
  → 线程池并发执行（每环境内标签页顺序、环境间并行） → ⑤多轮回炉

关键设计：
- executor 注入：一个 callable(batch: list[str]) -> list[dict]，返回逐项
  {number, error_class|None, ...}；由调用方绑定 UspsWebProvider.fetch。
  这样编排层不依赖浏览器，可离线纯逻辑单测。
- circuit 注入：每个批次执行前过门禁（§3.1 检查 Provider/熔断）。
- 线程池、sleeper 可注入，测试用同步执行器保证确定性。
- 基础设施失败与业务失败分离（§3.2.1）：executor 抛异常归 browser_crash
  回炉，不误判为业务终态、不冲正积分。
"""
from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from worker.provider.dispatcher import (
    consolidate, drop_recent, chunk, assign_slots, human_interval_ms,
    auto_max_environments, plan_next_round,
    PAGE_BATCH_LIMIT, TABS_PER_GENERATION, DEFAULT_TAB_INTERVAL_MS,
)


@dataclass(slots=True)
class DispatchConfig:
    """§3.3.2 DispatchConfig 关键参数（验收区可标定）。"""

    batch_size: int = PAGE_BATCH_LIMIT
    tabs_per_environment: int = TABS_PER_GENERATION
    tab_interval_requests: int = 10
    tab_interval_ms: int = DEFAULT_TAB_INTERVAL_MS
    max_rounds: int = 3
    recent_window_hours: int = 24
    max_environments: int | None = None  # None=按内存自动推算
    available_mb: int = 4096             # 自动推算用；生产读 /proc/meminfo

    def resolved_environments(self) -> int:
        return auto_max_environments(self.available_mb, self.max_environments)


@dataclass(slots=True)
class DispatchMetrics:
    """§3.5 调度质量观测（脱敏，不含单号/凭据）。"""

    submitted: int = 0
    dedup_removed: int = 0          # ① 跨客户汇总去重命中
    recent_skipped: int = 0         # ② 库内近期去重跳过
    page_batches: int = 0           # ③ 页面批次数
    generations: int = 0            # 环境代轮换次数
    rounds: int = 0                 # 实际执行轮数
    retry_dispatched: int = 0       # 各轮回炉单号数
    interval_inserted_ms: int = 0   # 人类间隔实际值累计
    results: dict[str, str] = field(default_factory=dict)  # number -> 终态/error

    def snapshot(self) -> dict:
        return {
            k: getattr(self, k) for k in (
                "submitted", "dedup_removed", "recent_skipped", "page_batches",
                "generations", "rounds", "retry_dispatched", "interval_inserted_ms")
        }


class _SyncPool:
    """同步执行器（测试注入）：executor.map 立即顺序执行。"""

    def __init__(self, fn):
        self._fn = fn

    def submit(self, fn, *args):
        return _SyncFuture(fn(*args))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _SyncFuture:
    def __init__(self, value):
        self._value = value

    def result(self):
        return self._value


class BatchDispatcher:
    """完整 dispatch 编排；不写库、不计费，只产出逐项结果与指标。"""

    def __init__(self, *, config: DispatchConfig | None = None,
                 executor=None, circuit=None, sleeper=None,
                 randomizer=None, pool_factory=None) -> None:
        self.cfg = config or DispatchConfig()
        self.executor = executor            # callable(batch) -> list[dict]
        self.circuit = circuit              # 可选，有 allows_request 门禁
        self._sleep = sleeper or time.sleep
        self._rand = randomizer or random.Random()
        self._pool_factory = pool_factory  # 可选，注入同步池用于测试

    def _run_batch(self, batch: list[str]) -> list[dict]:
        """单批次执行：过熔断门禁 → 调 Provider → 异常归 browser_crash 回炉。"""
        if self.circuit is not None and not self.circuit.allows_request:
            return [{"number": n, "error_class": "circuit_open"} for n in batch]
        if self.circuit is not None:
            self.circuit.on_request_started()
        try:
            items = self.executor(batch)
        except Exception:
            # 基础设施/浏览器异常：不误判业务失败，按可回炉类处理（§3.2.1）。
            if self.circuit is not None:
                self.circuit.on_failure("browser_crash")
            return [{"number": n, "error_class": "browser_crash"} for n in batch]
        normal = [
            {"number": it["number"], "error_class": it.get("error_class")}
            for it in items
        ]
        if self.circuit is not None:
            if all(it["error_class"] is None for it in normal):
                self.circuit.on_success()
            else:
                for it in normal:
                    if it["error_class"]:
                        self.circuit.on_failure(it["error_class"])
        return normal

    def dispatch(self, submissions: list[list[str]],
                 *, recently_ok: set[str] | None = None,
                 max_environments: int | None = None) -> tuple[dict[str, str], DispatchMetrics]:
        """执行完整多轮 dispatch，返回 (number->终态, 指标)。

        recently_ok=None 表示去重服务不可用 → 退化为不去重（§3.3.2）。
        """
        metrics = DispatchMetrics()
        merged = consolidate([n for sub in submissions for n in sub])
        metrics.dedup_removed = sum(len(sub) for sub in submissions) - len(merged)
        metrics.submitted = len(merged)
        if recently_ok is None:
            todo = merged  # 去重服务异常，退化为不去重，不阻断主流程
        else:
            todo = drop_recent(merged, recently_ok)
            metrics.recent_skipped = len(merged) - len(todo)
            # 近期跳过的单号沿用库中事实：记为 succeeded（客户关系另行建立）。
            for n in merged:
                if n in recently_ok:
                    metrics.results[n] = "succeeded"

        current = todo
        envs = max_environments or self.cfg.resolved_environments()
        for round_no in range(1, self.cfg.max_rounds + 1):
            if not current:
                break
            metrics.rounds = round_no
            batches = chunk(current, self.cfg.batch_size)
            metrics.page_batches += len(batches)
            slots = assign_slots(batches, envs)
            metrics.generations = max(metrics.generations, slots.generation_count)

            round_items: list[dict] = []
            pool_factory = self._pool_factory or (
                lambda: ThreadPoolExecutor(max_workers=envs))
            with pool_factory() as pool:
                futures = [pool.submit(self._run_batch, b) for b in batches]
                tab_done = 0
                for fut in as_completed(futures) if self._pool_factory is None else futures:
                    round_items.extend(fut.result())
                    tab_done += 1
                    if tab_done % self.cfg.tab_interval_requests == 0:
                        gap = human_interval_ms(self.cfg.tab_interval_ms, self._rand)
                        metrics.interval_inserted_ms += gap
                        self._sleep(gap / 1000.0)

            # 记录本轮结果，分出成功/终态与可回炉。
            plan = plan_next_round(round_items, self.cfg.max_rounds, round_no)
            for it in round_items:
                ec = it["error_class"]
                if ec is None:
                    metrics.results[it["number"]] = "succeeded"
                elif it["number"] in plan.terminal_numbers:
                    # 记错误类别（不在此决定终态）——终态转换由 JobLease 负责，
                    # 保持"基础设施失败与业务失败分离"（§3.2.1）。
                    metrics.results[it["number"]] = ec
            metrics.retry_dispatched += len(plan.retry_numbers)
            current = plan.retry_numbers

        # 兜底：多轮后仍未有结论的（如未知类），标记 dead_letter 不丢单。
        for n in current:
            metrics.results.setdefault(n, "dead_letter")
        return dict(metrics.results), metrics
