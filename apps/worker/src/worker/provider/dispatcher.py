"""BatchDispatcher：批量调度算法（模块 02 §3.2 / §3.3，对应 07 调度器）。

本模块只实现纯算法（去重/切片/分槽/间隔/并发推算/回炉判定），不做 I/O，
便于离线单测；真正的并发执行与租约由模块 07 Worker 驱动。

关键口径（02 §3.2）：
- 跨客户汇总保序去重 + 库内近期去重（24h）是两层独立去重；
- 页面请求批次固定 ≤35 条 = 一个标签页一次查询；
- 每 10 个标签页为一代，代内复用、代间换指纹+出口；
- 人类间隔 0.6~1.4 倍随机化，是工程节流起点，不是上游安全额度；
- auto_max_environments 按内存推算，无硬上限，显式配置优先。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

PAGE_BATCH_LIMIT = 35
TABS_PER_GENERATION = 10
DEFAULT_TAB_INTERVAL_MS = 2500
RECENT_DEDUP_HOURS = 24
MEMORY_PER_ENV_MB = 550
MEMORY_BASELINE_MB = 900
MIN_ENVIRONMENTS = 2


def consolidate(numbers: list[str]) -> list[str]:
    """① 跨客户汇总 + 保序去重（02 §3.2）。相同单号只查一次，保持首次顺序。"""
    seen: set[str] = set()
    out: list[str] = []
    for n in numbers:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def drop_recent(numbers: list[str], recently_ok: set[str]) -> list[str]:
    """② 库内近期去重（24h 已成功跳过上游）。去重服务不可用时传空集即退化为不去重。"""
    return [n for n in numbers if n not in recently_ok]


def chunk(numbers: list[str], size: int = PAGE_BATCH_LIMIT) -> list[list[str]]:
    """③ 按 35 切片；每片 = 一个标签页一次页面查询。"""
    if size < 1:
        raise ValueError("size 必须 ≥1")
    return [numbers[i:i + size] for i in range(0, len(numbers), size)]


@dataclass(slots=True)
class SlotAssignment:
    """④ 环境槽分配结果：每 10 标签页一代，代间换指纹+出口。"""

    slots: list[dict] = field(default_factory=list)

    @property
    def generation_count(self) -> int:
        return len({s["generation"] for s in self.slots})


def assign_slots(batches: list[list[str]], max_environments: int) -> SlotAssignment:
    """把页面批次分配到环境槽，round-robin 轮询并发环境。

    每 TABS_PER_GENERATION 个标签页为一代；代间换指纹/出口（generation+1）。
    """
    if max_environments < 1:
        raise ValueError("max_environments 必须 ≥1")
    assignment = SlotAssignment()
    for i, batch in enumerate(batches):
        tab_index = i % TABS_PER_GENERATION
        generation = i // TABS_PER_GENERATION
        assignment.slots.append({
            "batch_index": i,
            "environment": i % max_environments,
            "generation": generation,
            "tab_in_generation": tab_index,
            "numbers": batch,
        })
    return assignment


def human_interval_ms(base_ms: int = DEFAULT_TAB_INTERVAL_MS,
                      rng: random.Random | None = None,
                      every: int = TABS_PER_GENERATION) -> int:
    """每约 every 个标签页插入的随机化间隔（0.6~1.4 倍）。"""
    r = rng or random
    factor = 0.6 + r.random() * 0.8
    return int(base_ms * factor)


def auto_max_environments(available_mb: int,
                          explicit: int | None = None) -> int:
    """并发环境数：显式优先；否则 max(2,(可用内存MB-900)//550)，无硬上限。"""
    if explicit is not None and explicit > 0:
        return explicit
    return max(MIN_ENVIRONMENTS, (available_mb - MEMORY_BASELINE_MB) // MEMORY_PER_ENV_MB)


# 回炉判定：可回炉 vs fail-closed（02 §3.3 RETRYABLE/TERMINAL）。
from worker.provider.errors import RETRYABLE, TERMINAL  # noqa: E402

RETRYABLE_ERRORS = RETRYABLE
TERMINAL_ERRORS = TERMINAL


@dataclass(slots=True)
class RoundPlan:
    """多轮回炉计划：失败项进入下一轮，成功/终态项不再重查。"""

    retry_numbers: list[str] = field(default_factory=list)
    terminal_numbers: list[str] = field(default_factory=list)


def plan_next_round(items: list[dict], max_rounds: int,
                    current_round: int) -> RoundPlan:
    """按逐项结果决定哪些单号进入下一轮回炉（02 §5.4 单项重试）。

    items: [{number, error_class|None}]。error_class=None 视为成功不再查；
    可重试类且未到 max_rounds 才回炉；终态类直接计入 terminal。
    """
    plan = RoundPlan()
    for it in items:
        ec = it.get("error_class")
        if ec is None:
            continue
        if ec in TERMINAL_ERRORS or current_round >= max_rounds:
            plan.terminal_numbers.append(it["number"])
        elif ec in RETRYABLE_ERRORS:
            plan.retry_numbers.append(it["number"])
        else:
            # 未知类别按终态处理，不猜、不无限回炉。
            plan.terminal_numbers.append(it["number"])
    return plan


def consolidate_all(
    submissions: list[list[str]], recently_ok: set[str] | None = None
) -> list[str]:
    """组合两层去重（跨客户汇总 → 库内近期），返回待查单号保序列表。"""
    merged = consolidate([n for sub in submissions for n in sub])
    return drop_recent(merged, recently_ok or set())
