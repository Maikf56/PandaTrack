"""billing_outbox 消费者：受理事件 → A 库 FetchJob 入队（07 排队消费）。

链路缺口修复：受理事务写 billing_outbox（payload 含 operation_id/customer_id/
candidates），本消费者异步把候选单号入队为 A 库 fetch_job(pending)，
使 WorkerLoop.claim 可领取采集。

幂等与一致性：
- A 库先写（tracking upsert + fetch_job ON CONFLICT DO NOTHING，single-flight
  部分唯一索引天然防重复活跃 job），后 B 库标记 processed；
- B 标记失败 → 事件重放，A 侧重放无害（upsert/ON CONFLICT 均幂等）；
- digest 校验失败视为载荷被篡改 → 直接放弃（attempts 不再重试）；
- 处理失败 attempts+1，达 max_attempts 后放弃（processed=true + last_error
  留痕），健康巡检统计死信。

digest 统一说明：P7 起写入端（billing/submission.py）改用
pandatrack_common.hashutil.payload_digest（canonical_json 紧凑分隔符），
消费者校验同源；存量行已在迁移时重算。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from pandatrack_common.hashutil import payload_digest

log = logging.getLogger("pandatrack.billing.consumer")

MAX_ATTEMPTS = 5
DIGEST_MISMATCH = "digest_mismatch"
PAYLOAD_MALFORMED = "payload_malformed"


@dataclass(slots=True)
class EnqueueStats:
    """一次 run_once 的处理统计（脱敏，只有计数）。"""

    scanned: int = 0            # 取到的待处理事件数
    enqueued: int = 0           # 新建 fetch_job 数
    skipped_active: int = 0     # single-flight 命中跳过（已有活跃 job）
    skipped_terminal: int = 0   # 已有终态 job → 重建 pending 计入 enqueued
    processed: int = 0          # 成功标记 processed 的事件数
    retried: int = 0            # 失败 attempts+1 的事件数
    abandoned: int = 0          # 达上限放弃（含 digest 校验失败）的事件数
    skipped_env: int = 0        # 环境黑名单命中（测试单号等）不入队
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in {
            "scanned": self.scanned, "enqueued": self.enqueued,
            "skipped_active": self.skipped_active,
            "skipped_env": self.skipped_env,
            "processed": self.processed, "retried": self.retried,
            "abandoned": self.abandoned}.items() if v}
        if self.errors:
            d["errors"] = self.errors[:5]
        return d


def extract_candidates(payload: Any) -> list[str]:
    """从事件载荷取候选单号（去重保序）；格式非法抛 ValueError。"""
    if not isinstance(payload, dict):
        raise ValueError(PAYLOAD_MALFORMED)
    cands = payload.get("candidates")
    if not isinstance(cands, list) or not cands:
        raise ValueError(PAYLOAD_MALFORMED)
    seen: set[str] = set()
    out: list[str] = []
    for c in cands:
        if not isinstance(c, str) or not c:
            raise ValueError(PAYLOAD_MALFORMED)
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


class BillingOutboxConsumer:
    """把 billing_outbox 未处理事件入队为 A 库 FetchJob。

    connect_a / connect_b 返回原生连接（PersistentConnect 兼容）；
    事件级隔离：单事件失败只影响自身，不阻塞批次。

    skip_numbers：环境级单号黑名单（PT_ENQUEUE_SKIP_NUMBERS，逗号分隔）。
    命中的候选不建 tracking/fetch_job，事件仍标记 processed。用途：真库
    集成测试与 worker 常驻共用一套库时，阻断测试单号触发真实代理采集
    （teardown 删 outbox 存在竞态窗口：daemon 可能已取走事件）。
    """

    def __init__(self, connect_a: Callable[[], Any], connect_b: Callable[[], Any],
                 *, batch_size: int = 50, max_attempts: int = MAX_ATTEMPTS,
                 skip_numbers: frozenset[str] = frozenset()):
        self._ca = connect_a
        self._cb = connect_b
        self._batch = max(1, batch_size)
        self._max_attempts = max(1, max_attempts)
        self._skip_numbers = frozenset(skip_numbers)

    # ---- 主流程 ----
    def run_once(self) -> EnqueueStats:
        stats = EnqueueStats()
        events = self._fetch_batch()
        for ev in events:
            stats.scanned += 1
            try:
                self._process_event(ev, stats)
            except Exception as exc:  # noqa: BLE001 事件级隔离
                self._mark_failed(
                    ev["event_id"],
                    (str(exc) or type(exc).__name__)[:60], stats)
        return stats

    # ---- 取批 ----
    def _fetch_batch(self) -> list[dict]:
        with self._cb() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT event_id, aggregate_id, payload, payload_digest,
                              attempts
                       FROM billing_outbox
                       WHERE processed = false AND attempts < %s
                       ORDER BY event_id
                       FOR UPDATE SKIP LOCKED
                       LIMIT %s""",
                    (self._max_attempts, self._batch))
                rows = cur.fetchall()
            conn.commit()
        return [{"event_id": r[0], "operation_id": r[1],
                 "payload": r[2], "digest": r[3], "attempts": r[4]}
                for r in rows]

    # ---- 单事件 ----
    def _process_event(self, ev: dict, stats: EnqueueStats) -> None:
        payload = ev["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if payload_digest(payload) != ev["digest"]:
            raise ValueError(DIGEST_MISMATCH)
        candidates = extract_candidates(payload)
        blocked = [c for c in candidates if c in self._skip_numbers]
        if blocked:
            stats.skipped_env += len(blocked)
            candidates = [c for c in candidates if c not in self._skip_numbers]
            log.info("enqueue skip (env blacklist): %d candidate(s)", len(blocked))

        enqueued, skipped_active, skipped_terminal = self._enqueue_all(
            candidates)
        stats.enqueued += enqueued
        stats.skipped_active += skipped_active
        stats.skipped_terminal += skipped_terminal

        self._mark_processed(ev["event_id"], stats)

    def _enqueue_all(self, candidates: list[str]) -> tuple[int, int, int]:
        """A 库单事务：tracking upsert + fetch_job 入队。返回计数三元组。"""
        enqueued = skipped_active = skipped_terminal = 0
        with self._ca() as conn:
            with conn.cursor() as cur:
                for number in candidates:
                    cur.execute(
                        """INSERT INTO tracking (normalized_number, carrier)
                           VALUES (%s, 'usps')
                           ON CONFLICT (normalized_number, carrier)
                           DO UPDATE SET updated_at = now()
                           RETURNING tracking_id""",
                        (number,))
                    tid = cur.fetchone()[0]
                    cur.execute(
                        """SELECT state FROM fetch_job
                           WHERE tracking_id = %s
                           ORDER BY job_id DESC LIMIT 1""", (tid,))
                    # single-flight 判定：有活跃 job 则跳过；
                    # 只有终态 job 则可重建 pending。
                    row = cur.fetchone()
                    if row is not None and row[0] in (
                            "pending", "claimed", "running",
                            "waiting_for_session", "retry_scheduled",
                            "collecting_response"):
                        skipped_active += 1
                        continue
                    if row is not None:
                        skipped_terminal += 1
                    cur.execute(
                        """INSERT INTO fetch_job
                               (tracking_id, state, queue)
                           VALUES (%s, 'pending', 'Q_SCHEDULED')
                           ON CONFLICT DO NOTHING""",
                        (tid,))
                    enqueued += 1
            conn.commit()
        return enqueued, skipped_active, skipped_terminal

    # ---- 状态标记 ----
    def _mark_processed(self, event_id: int, stats: EnqueueStats) -> None:
        with self._cb() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE billing_outbox SET processed = true,
                              last_error = NULL
                       WHERE event_id = %s AND processed = false""",
                    (event_id,))
                done = cur.rowcount == 1
            conn.commit()
        if done:
            stats.processed += 1

    def _mark_failed(self, event_id: int, error: str,
                     stats: EnqueueStats) -> None:
        with self._cb() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE billing_outbox
                       SET attempts = attempts + 1,
                           last_error = %s,
                           processed = (attempts + 1) >= %s
                       WHERE event_id = %s AND processed = false
                       RETURNING processed, attempts >= %s""",
                    (error, self._max_attempts, event_id,
                     self._max_attempts))
                row = cur.fetchone()
            conn.commit()
        if row is None:
            stats.retried += 1
            stats.errors.append(f"event#{event_id}:{error}")
            log.warning("outbox event %s failed: %s", event_id, error)
            return
        abandoned, at_max = row[0], row[1]
        if abandoned and at_max:
            stats.abandoned += 1
            log.error("outbox event %s abandoned after %s attempts: %s",
                      event_id, self._max_attempts, error)
        else:
            stats.retried += 1
        stats.errors.append(f"event#{event_id}:{error}")
