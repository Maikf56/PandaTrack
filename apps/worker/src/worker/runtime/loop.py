"""Worker 运行时：事实落库 + 调度主循环（模块 05 §事务 / 07 Worker 驱动）。

facts.FactStore —— A 库事实写入（05 权威规格）：
- 单事务写 tracking_fact + tracking_event（指纹去重）+ a_outbox；
- 写前 assert_source_valid（02 §4.3，simulated/mock 拒绝入库）；
- 同步刷新 tracking.next_sync_at（分层节奏，freshness.next_sync_for）、
  last_success_at、version；
- a_outbox 载荷 sha256 摘要，供 sync-agent 用 event_id+aggregate_version
  幂等投影到 B 库（05 §数据链路）。

loop.WorkerLoop —— 主循环一个 tick：
  reclaim 过期租约 → 金丝雀预检 → claim 租约 → dispatch 采集 →
  熔断钩子 → 事实落库 → job ack/retry/dead_letter。
  所有协作者（连接工厂/Provider/熔断器/金丝雀采集）可注入，纯逻辑可单测。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from worker.provider.errors import next_task_state, backoff_seconds
from worker.provider.contracts import ProviderItem, ProviderResult
from worker.scheduler.canary import CanarySpec, evaluate as canary_evaluate
from worker.scheduler.freshness import next_sync_for
from worker.scheduler.lease import JobLease

DEFAULT_WORKER_ID = "worker-1"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _payload_digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False,
                   default=str).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class WriteStats:
    facts_written: int = 0
    events_written: int = 0
    outbox_written: int = 0


class FactStore:
    """A 库事实写入；conn 由调用方传入（与 JobLease 同风格）。"""

    def __init__(self, conn: Any):
        self.conn = conn

    def numbers_for(self, tracking_ids: Iterable[int]) -> dict[int, str]:
        """tracking_id → normalized_number（claim 结果转 ProviderInput 用）。"""
        ids = list(tracking_ids)
        if not ids:
            return {}
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT tracking_id, normalized_number FROM tracking
                   WHERE tracking_id = ANY(%s)""", (ids,))
            return {r[0]: r[1] for r in cur.fetchall()}

    def write_facts(self, items: list[ProviderItem],
                    *, now: datetime | None = None) -> WriteStats:
        """成功事实单事务落库（05：事实+事件+outbox 同事务）。"""
        now = now or _utcnow()
        stats = WriteStats()
        with self.conn.cursor() as cur:
            for item in items:
                if item.error_class is not None or item.item_error_class is not None:
                    continue  # 只写成功事实；失败走任务重试，不入事实源
                item.assert_source_valid()
                cur.execute(
                    """INSERT INTO tracking (normalized_number, carrier)
                       VALUES (%s, 'usps')
                       ON CONFLICT (normalized_number, carrier)
                       DO UPDATE SET updated_at = now()
                       RETURNING tracking_id, version""",
                    (item.normalized_number,))
                tracking_id, version = cur.fetchone()
                new_version = version + 1
                cur.execute(
                    """INSERT INTO tracking_fact
                       (tracking_id, source, simulated, raw_status, status,
                        quality_gates, collected_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (tracking_id, item.source, item.simulated, item.raw_status,
                     item.status,
                     json.dumps({"parser_version": item.parser_version,
                                 "page_class": item.page_class,
                                 "confidence": item.confidence}),
                     item.fetched_at or now))
                stats.facts_written += 1
                for ev in item.events:
                    cur.execute(
                        """INSERT INTO tracking_event
                           (tracking_id, event_fingerprint, occurred_at, status,
                            description_raw, description_zh, location,
                            event_code, time_confidence)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (tracking_id, event_fingerprint)
                           DO NOTHING""",
                        (tracking_id, ev.event_fingerprint, ev.occurred_at,
                         ev.status, ev.description_raw, ev.description_zh,
                         (ev.location or "")[:500] or None,  # 防御：location 列 VARCHAR(500)，超长截断
                         ev.event_code, ev.time_confidence))
                    stats.events_written += cur.rowcount
                cur.execute(
                    """UPDATE tracking
                       SET version=%s, last_success_at=%s, next_sync_at=%s,
                           updated_at=%s
                       WHERE tracking_id=%s""",
                    (new_version, now,
                     next_sync_for(item.status, now), now, tracking_id))
                payload = {"tracking_id": tracking_id,
                           "status": item.status,
                           "simulated": item.simulated,
                           "event_count": len(item.events),
                           "collected_at": (item.fetched_at or now).isoformat()}
                cur.execute(
                    """INSERT INTO a_outbox
                       (aggregate_id, aggregate_type, aggregate_version,
                        payload, payload_digest)
                       VALUES (%s, 'tracking', %s, %s, %s)
                       ON CONFLICT (aggregate_id, aggregate_type,
                                    aggregate_version) DO NOTHING""",
                    (tracking_id, new_version,
                     json.dumps(payload, ensure_ascii=False, default=str),
                     _payload_digest(payload)))
                stats.outbox_written += 1
        return stats


@dataclass(slots=True)
class TickReport:
    reclaimed: int = 0
    claimed: int = 0
    succeeded: int = 0
    retried: int = 0
    dead_lettered: int = 0
    facts: WriteStats = field(default_factory=WriteStats)
    canary_halt: bool = False
    canary_mismatches: list = field(default_factory=list)
    error_class: str | None = None   # 整批失败时的错误类别


class WorkerLoop:
    """调度主循环；协作者全部注入（07：Worker 驱动租约+算法+熔断）。"""

    def __init__(self, *, connect: Callable[[], Any],
                 fetch: Callable[[list[str]], ProviderResult],
                 circuit: Any,
                 canary_fetch: Callable[[list[str]], dict[str, str]] | None = None,
                 canary_specs: list[CanarySpec] | None = None,
                 worker_id: str = DEFAULT_WORKER_ID,
                 claim_limit: int = 10):
        self._connect = connect
        self._fetch = fetch
        self._circuit = circuit
        self._canary_fetch = canary_fetch
        self._canary_specs = canary_specs or []
        self.worker_id = worker_id
        self.claim_limit = claim_limit

    # ---- 任务结局（02 §5.1 权威矩阵 errors.next_task_state + 退避序列）----
    @staticmethod
    def _settle(lease: JobLease, job: dict, error_class: str) -> str:
        state = next_task_state(error_class, job["attempt"], job["max_attempts"])
        if state == "succeeded":  # not_found 是有效事实
            lease.ack(job["job_id"])
            return "succeeded"
        if state == "dead_letter":
            lease.dead_letter(job["job_id"], error_class)
            return "dead_lettered"
        lease.retry(job["job_id"], error_class, retry_at=_utcnow() + timedelta(
            seconds=backoff_seconds(error_class, job["attempt"])))
        return "retried"

    def tick(self) -> TickReport:
        """主循环一轮；无任务/金丝雀拦截/整批失败都会给完整报告。"""
        report = TickReport()

        # 1) 回收过期租约 + 领取（同事务提交，07 §3.1）。
        with self._connect() as conn:
            lease = JobLease(conn)
            report.reclaimed = lease.reclaim_expired()
            jobs = lease.claim(self.worker_id, limit=self.claim_limit)
        report.claimed = len(jobs)
        if not jobs:
            return report

        # 2) 金丝雀预检（吸收方案分析：改版脏页不进事实源）。
        if self._canary_specs and self._canary_fetch is not None:
            spec_numbers = [s.number for s in self._canary_specs]
            statuses = self._canary_fetch(spec_numbers)
            report.canary_mismatches = canary_evaluate(statuses, self._canary_specs)
            if report.canary_mismatches:
                report.canary_halt = True
                return report  # 领取的任务等租约过期自动回收，不丢单

        # 3) 单号解析与采集。
        with self._connect() as conn:
            store = FactStore(conn)
            number_by_tid = store.numbers_for(j["tracking_id"] for j in jobs)
        inputs: list[tuple[dict, str]] = []   # (job, normalized_number)
        missing: list[dict] = []
        for j in jobs:
            n = number_by_tid.get(j["tracking_id"])
            (inputs.append((j, n)) if n else missing.append(j))

        if missing:  # 防御：任务引用不存在的事实（不应发生，发生即终态）
            with self._connect() as conn:
                lease = JobLease(conn)
                for j in missing:
                    lease.dead_letter(j["job_id"], "tracking_missing")
                    report.dead_lettered += 1

        if not inputs:
            return report

        try:
            result = self._fetch([n for _, n in inputs])
        except Exception as exc:  # ProviderError 等：整批按错误类别结算
            ec = getattr(exc, "error_class", None) or "provider_unavailable"
            if ec != "circuit_open":
                self._circuit.on_failure(ec)  # 自反馈不计数（07 §3.4）
            with self._connect() as conn:
                lease = JobLease(conn)
                for j, _n in inputs:
                    outcome = self._settle(lease, j, ec)
                    setattr(report, outcome, getattr(report, outcome) + 1)
                report.error_class = ec
            return report

        # 4) 熔断钩子：成功复位 / 失败计数（circuit_open 自反馈除外）。
        item_by_number = {i.normalized_number: i for i in result.items}
        ok_items: list[ProviderItem] = []
        fail_numbers: dict[str, str] = {}
        for _j, n in inputs:
            item = item_by_number.get(n)
            if item is None or item.error_class or item.item_error_class:
                ec = (item.error_class or item.item_error_class
                      if item else "provider_unavailable")
                fail_numbers[n] = ec
                if ec != "circuit_open":
                    self._circuit.on_failure(ec)
            else:
                ok_items.append(item)
                self._circuit.on_success()

        # 5) 成功事实落库（同事务：事实+事件+outbox）。
        if ok_items:
            with self._connect() as conn:
                report.facts = FactStore(conn).write_facts(ok_items)

        # 6) 任务结算：成功 ack；失败按分类矩阵 retry/dead_letter。
        with self._connect() as conn:
            lease = JobLease(conn)
            for j, n in inputs:
                if n in fail_numbers:
                    outcome = self._settle(lease, j, fail_numbers[n])
                else:
                    lease.ack(j["job_id"])
                    outcome = "succeeded"
                setattr(report, outcome, getattr(report, outcome) + 1)
        return report
