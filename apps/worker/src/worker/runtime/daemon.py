"""Worker 常驻入口：CLI + 调度循环 + A→B 投影（模块 07 Worker 驱动 / 05 数据链路）。

组装方式：
- run    常驻循环：reclaim→金丝雀→claim→采集(真实 ClawExecutor)→落库→结算，
         周期性把 A 库 outbox 投影到 B 库（SyncAgent）；
- once   单轮：执行一次 tick + 排空投影（验收/手工补跑用）；
- sync   只排空 A→B 投影，不采集（sync-agent 独立部署形态）。

设计要点：
- 所有协作者可注入，纯逻辑（周期调度/适配器/配置解析）可离线单测；
- 生产连接用 PersistentConnect：单线程复用一条连接、断线重连、
  事务异常后 reset() 回滚防「aborted transaction」传染下一轮；
- 金丝雀采集失败按 fail-closed 处理：返回空映射 → 全部 missing → 本轮拦截
  （改版/上游不可达时不把脏页放进事实源）；
- Provider 门禁默认 enabled=true（常驻形态即验收启用形态），可用
  PT_USPS_ENABLED=false 显式关闭（此时 tick 内采集 fail-closed 报错结算，
  不丢单、不伪造事实）。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("pandatrack.worker")

TICK_INTERVAL_S = 20
SYNC_INTERVAL_S = 30
CLAIM_LIMIT = 10
LEASE_SECONDS = 300


# ---------------------------------------------------------------- 配置 ----
@dataclass(slots=True)
class WorkerSettings:
    """常驻进程运行配置（全部可经环境变量覆盖）。"""

    dsn_a: str = ""
    dsn_b: str = ""
    worker_id: str = "worker-1"
    tick_interval_s: int = TICK_INTERVAL_S
    sync_interval_s: int = SYNC_INTERVAL_S
    claim_limit: int = CLAIM_LIMIT
    lease_seconds: int = LEASE_SECONDS
    enqueue_batch: int = 50
    usps_enabled: bool = True
    claw_bin: str = "clawctl"
    claw_profile: str = "smoke1"
    relay_env_file: str = "~/.pandatrack-secrets/relay.env"
    relay_service: str = "pandatrack-relay"
    relay_socks5: str = "127.0.0.1:1080"

    @classmethod
    def from_env(cls, env: dict | None = None) -> "WorkerSettings":
        e = os.environ if env is None else env

        def _get(name: str, default: str) -> str:
            return (e.get(name, "") or default).strip()

        def _int(name: str, default: int) -> int:
            raw = _get(name, str(default))
            try:
                return max(1, int(raw))
            except ValueError:
                log.warning("invalid %s=%r, fallback %s", name, raw, default)
                return default

        def _bool(name: str, default: bool) -> bool:
            raw = _get(name, "true" if default else "false").lower()
            return raw in ("1", "true", "yes", "on")

        return cls(
            dsn_a=_get("PT_DB_A_URL", ""),
            dsn_b=_get("PT_DB_B_URL", ""),
            worker_id=_get("PT_WORKER_ID", "worker-1"),
            tick_interval_s=_int("PT_TICK_INTERVAL_S", TICK_INTERVAL_S),
            sync_interval_s=_int("PT_SYNC_INTERVAL_S", SYNC_INTERVAL_S),
            claim_limit=_int("PT_CLAIM_LIMIT", CLAIM_LIMIT),
            lease_seconds=_int("PT_LEASE_SECONDS", LEASE_SECONDS),
            enqueue_batch=_int("PT_ENQUEUE_BATCH", 50),
            usps_enabled=_bool("PT_USPS_ENABLED", True),
            claw_bin=_get("PT_CLAW_BIN", "clawctl"),
            claw_profile=_get("PT_CLAW_PROFILE", "smoke1"),
            relay_env_file=_get(
                "PT_RELAY_ENV_FILE", "~/.pandatrack-secrets/relay.env"),
            relay_service=_get("PT_RELAY_SERVICE", "pandatrack-relay"),
            relay_socks5=_get("PT_RELAY_SOCKS5", "127.0.0.1:1080"),
        )


# ------------------------------------------------------------ 连接工厂 ----
class PersistentConnect:
    """复用单条 psycopg 连接的连接工厂（单线程常驻进程）。

    - `with conn:`（psycopg3 事务上下文）退出不关连接，复用即不泄漏；
    - 连接已断（closed）时下次调用自动重连；
    - 事务中途抛异常后由 reset() 回滚，避免 aborted 状态污染下一轮。
    """

    def __init__(self, dsn: str, connect: Callable[[str], Any] | None = None):
        self._dsn = dsn
        self._connect_fn = connect or _psycopg_connect
        self._conn: Any = None

    def __call__(self) -> Any:
        if self._conn is None or self._conn.closed:
            self._conn = self._connect_fn(self._dsn)
        return self._conn

    def reset(self) -> None:
        """事务异常后回滚；连接不可用时丢弃待重连。"""
        if self._conn is None:
            return
        try:
            if not self._conn.closed:
                self._conn.rollback()
        except Exception:
            self._conn = None

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = None


def _psycopg_connect(dsn: str) -> Any:
    import psycopg
    return psycopg.connect(dsn)


# ------------------------------------------------------------- 适配器 ----
def make_fetch(provider) -> Callable[[list[str]], Any]:
    """单号列表 → Provider.fetch（WorkerLoop.fetch 协议）。"""

    def fetch(numbers: list[str]):
        from worker.provider.contracts import ProviderInput
        inputs = [ProviderInput(normalized_number=n, job_ref="")
                  for n in numbers]
        return provider.fetch(inputs)

    return fetch


def make_canary_fetch(provider) -> Callable[[list[str]], dict[str, str]]:
    """金丝雀采集：走同一管线；上游失败 fail-closed 返回空映射（全部 missing）。"""

    def canary_fetch(numbers: list[str]) -> dict[str, str]:
        from worker.provider.contracts import ProviderInput
        try:
            result = provider.fetch(
                [ProviderInput(normalized_number=n, job_ref="canary")
                 for n in numbers])
        except Exception as exc:
            ec = getattr(exc, "error_class", "provider_unavailable")
            log.warning("canary collect failed (%s), fail-closed halt", ec)
            return {}
        return {i.normalized_number: i.status for i in result.items
                if not i.error_class and not i.item_error_class and i.status}

    return canary_fetch


# --------------------------------------------------------------- 守护 ----
@dataclass(slots=True)
class CycleReport:
    """一轮常驻循环的报告（日志落 stdout，可被 journalctl 检索）。"""

    cycle: int = 0
    tick: dict | None = None
    enqueue_summary: dict | None = None
    sync_rounds: int = 0
    sync_summary: dict | None = None
    error: str | None = None

    def to_log(self) -> str:
        return json.dumps(
            {k: v for k, v in {
                "cycle": self.cycle, "tick": self.tick,
                "enqueue": self.enqueue_summary,
                "sync_rounds": self.sync_rounds,
                "sync_summary": self.sync_summary,
                "error": self.error}.items() if v is not None},
            ensure_ascii=False, default=str)


class WorkerDaemon:
    """常驻调度：tick + 周期投影；clock/sleeper 注入便于离线测试。"""

    def __init__(self, *, loop, sync: Any,
                 enqueue: Any | None = None,
                 tick_interval_s: int = TICK_INTERVAL_S,
                 sync_interval_s: int = SYNC_INTERVAL_S,
                 clock: Callable[[], float] | None = None,
                 sleeper: Callable[[float], None] | None = None,
                 reset: Callable[[], None] | None = None,
                 logger=None):
        self._loop = loop
        self._sync = sync
        self._enqueue = enqueue
        self._tick_interval = tick_interval_s
        self._sync_interval = sync_interval_s
        self._clock = clock or time.monotonic
        self._sleep = sleeper or time.sleep
        self._reset = reset or (lambda: None)
        self._log = logger or log
        self._next_sync_at: float = self._clock() + sync_interval_s
        self._cycle_no = 0
        self._stop = False

    # ---- 控制面 ----
    def stop(self) -> None:
        """优雅停机标记（run_forever 在本轮结束后退出）。"""
        self._stop = True

    @property
    def stopped(self) -> bool:
        return self._stop

    # ---- 执行面 ----
    def run_cycle(self) -> CycleReport:
        """一轮：入队消费 → tick 采集 → 到期则排空 A→B 投影。异常不致命。"""
        self._cycle_no += 1
        report = CycleReport(cycle=self._cycle_no)
        if self._enqueue is not None:
            try:
                report.enqueue_summary = self._enqueue.run_once().to_dict()
            except Exception as exc:
                self._log.exception("enqueue failed (non-fatal)")
                report.enqueue_summary = {"error": str(exc)[:80]}
        try:
            report.tick = _report_dict(self._loop.tick())
        except Exception as exc:
            report.error = f"tick: {type(exc).__name__}: {exc}"
            self._log.exception("tick failed")
            self._reset()
            return report
        if self._clock() >= self._next_sync_at:
            self._run_sync(report)
            self._next_sync_at = self._clock() + self._sync_interval
        self._log.info("cycle %s", report.to_log())
        return report

    def _run_sync(self, report: CycleReport) -> None:
        rounds = self._sync.run_until_drained()
        report.sync_rounds = len(rounds)
        if rounds:
            report.sync_summary = {
                "fetched": sum(r.fetched for r in rounds),
                "projected": sum(r.projected for r in rounds),
                "skipped_no_customer": sum(r.skipped_no_customer for r in rounds),
            }

    def run_forever(self, *, max_cycles: int | None = None) -> int:
        """常驻主循环；max_cycles 供测试/验收限定轮数。返回实际执行轮数。"""
        done = 0
        try:
            while not self._stop:
                if max_cycles is not None and done >= max_cycles:
                    break
                self.run_cycle()
                done += 1
                if self._stop:
                    break
                if max_cycles is not None and done >= max_cycles:
                    break
                self._sleep(self._tick_interval)
        except KeyboardInterrupt:
            self._log.info("interrupted, graceful shutdown after %s cycles", done)
        return done


def _report_dict(tick_report: Any) -> dict:
    """TickReport → 可序列化日志字典（脱敏，只有计数与状态）。"""
    out = {
        "reclaimed": tick_report.reclaimed,
        "claimed": tick_report.claimed,
        "succeeded": tick_report.succeeded,
        "retried": tick_report.retried,
        "dead_lettered": tick_report.dead_lettered,
        "facts": {
            "facts_written": tick_report.facts.facts_written,
            "events_written": tick_report.facts.events_written,
            "outbox_written": tick_report.facts.outbox_written,
        },
    }
    if tick_report.canary_halt:
        out["canary_halt"] = True
        out["canary_mismatches"] = [
            {"number": m.number, "reason": m.reason}
            for m in tick_report.canary_mismatches]
    if tick_report.error_class:
        out["error_class"] = tick_report.error_class
    return out


# --------------------------------------------------------- 生产组装 ----
def build_components(settings: WorkerSettings) -> dict[str, Any]:
    """按配置组装真实组件（loop/sync/circuit/provider/reset/close）。"""
    if not settings.dsn_a or not settings.dsn_b:
        raise ValueError("PT_DB_A_URL / PT_DB_B_URL 未配置")

    from worker.scheduler.circuit import CircuitBreaker
    from worker.scheduler.canary import load_specs
    from worker.provider.usps_claw import (
        ClawExecutor, ExecutorConfig, SubprocessRunner, SystemdRelayControl)
    from worker.provider.usps_web.provider import UspsWebProvider
    from worker.runtime.loop import WorkerLoop
    from worker.sync.agent import SyncAgent

    connect_a = PersistentConnect(settings.dsn_a)
    connect_b = PersistentConnect(settings.dsn_b)

    executor = ClawExecutor(
        SubprocessRunner(),
        SystemdRelayControl(
            env_file=os.path.expanduser(settings.relay_env_file),
            service=settings.relay_service,
            socks5=settings.relay_socks5),
        config=ExecutorConfig(
            claw_bin=settings.claw_bin, profile=settings.claw_profile),
    )
    provider = UspsWebProvider(enabled=settings.usps_enabled, executor=executor)
    circuit = CircuitBreaker()

    loop = WorkerLoop(
        connect=connect_a,
        fetch=make_fetch(provider),
        circuit=circuit,
        canary_fetch=make_canary_fetch(provider),
        canary_specs=load_specs(),
        worker_id=settings.worker_id,
        claim_limit=settings.claim_limit,
    )
    sync = SyncAgent(connect_a, connect_b)

    from worker.billing.consumer import BillingOutboxConsumer
    enqueue = BillingOutboxConsumer(connect_a, connect_b,
                                    batch_size=settings.enqueue_batch)

    def reset() -> None:
        connect_a.reset()
        connect_b.reset()

    return {"loop": loop, "sync": sync, "enqueue": enqueue,
            "circuit": circuit,
            "provider": provider, "reset": reset,
            "close": lambda: (connect_a.close(), connect_b.close())}


# ---------------------------------------------------------------- CLI ----
def build_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pandatrack-worker",
        description="PandaTrack worker 常驻入口：采集调度 + A→B 投影")
    parser.add_argument("mode", nargs="?", default="run",
                        choices=("run", "once", "sync", "enqueue"),
                        help="run=常驻循环(默认) once=单轮验收 sync=只排空投影 "
                             "enqueue=只消费 billing_outbox 入队")
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    build_logging(args.verbose)
    settings = WorkerSettings.from_env()
    components = build_components(settings)
    daemon = WorkerDaemon(
        loop=components["loop"], sync=components["sync"],
        enqueue=components["enqueue"],
        tick_interval_s=settings.tick_interval_s,
        sync_interval_s=settings.sync_interval_s,
        reset=components["reset"])
    try:
        if args.mode == "sync":
            rounds = components["sync"].run_until_drained()
            log.info("sync drained: %s rounds, projected=%s",
                     len(rounds),
                     sum(r.projected for r in rounds))
        elif args.mode == "enqueue":
            stats = components["enqueue"].run_once()
            log.info("enqueue drained: %s", json.dumps(stats.to_dict()))
        elif args.mode == "once":
            daemon.run_cycle()
        else:
            log.info("worker starting (id=%s, tick=%ss, sync=%ss)",
                     settings.worker_id, settings.tick_interval_s,
                     settings.sync_interval_s)
            daemon.run_forever()
    finally:
        components["close"]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
