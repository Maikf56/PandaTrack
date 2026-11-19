"""FetchJob 事实源与租约（模块 07 §3.1，基于 05 A 库 schema）。

关键不变量：
- PostgreSQL FetchJob 是任务事实源，Redis 只承载可恢复队列（本类只碰 PG）；
- claim 用 SELECT ... FOR UPDATE SKIP LOCKED 取可领取任务并写 lease_until，
  避免多 Worker 抢占；租约过期由 reclaim 回收，不丢任务；
- single-flight 由 A 库 partial unique index 保证（活跃态唯一，终态不占）；
- ack/retry/dead_letter 按 02 §5.1 错误分类矩阵决策，写 finished_at/retry_at。

本类只做 DB 原语，不决定业务（重试次数/错误分类由调用方传入）。所有 SQL
参数绑定，防注入。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

# 07 §3.1 任务状态机（与 05 single-flight 索引的活跃态集合一致）。
ACTIVE_STATES = (
    "pending", "claimed", "running", "waiting_for_session",
    "retry_scheduled", "collecting_response", "parsing", "validating", "writing",
)
CLAIMABLE_STATES = ("pending", "retry_scheduled")
TERMINAL_STATES = ("succeeded", "dead_letter")

# single-flight 索引实际覆盖的活跃态（迁移文件 uq_fetch_job_single_flight）。
SINGLE_FLIGHT_STATES = (
    "pending", "claimed", "running", "waiting_for_session",
    "retry_scheduled", "collecting_response",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JobLease:
    """FetchJob 租约服务；conn 由调用方在事务中传入。"""

    def __init__(self, conn: Any, *, lease_seconds: int = 300):
        self.conn = conn
        self.lease_seconds = lease_seconds

    def claim(self, worker_id: str, *, limit: int = 1,
              queues: tuple[str, ...] | None = None) -> list[dict]:
        """领取任务：SKIP LOCKED 并发安全，写 worker_id 与 lease_until。

        retry_scheduled 任务只有 retry_at 到期才可被领取。
        """
        now = _now()
        until = now + timedelta(seconds=self.lease_seconds)
        queue_clause = ""
        select_params: list[Any] = [list(CLAIMABLE_STATES), now, until]
        if queues:
            queue_clause = " AND queue = ANY(%s)"
            select_params.append(list(queues))
        select_params.append(limit)  # LIMIT %s
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT job_id, tracking_id, attempt, max_attempts, queue
                    FROM fetch_job
                    WHERE state = ANY(%s)
                      AND (retry_at IS NULL OR retry_at <= %s)
                      AND (lease_until IS NULL OR lease_until <= %s)
                      {queue_clause}
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s""",
                select_params,
            )
            rows = cur.fetchall()
            if not rows:
                return []
            ids = [r[0] for r in rows]
            cur.execute(
                """UPDATE fetch_job
                   SET state='claimed', worker_id=%s, lease_until=%s,
                       attempt=attempt+1, updated_at=now()
                   WHERE job_id = ANY(%s)""",
                (worker_id, until, ids),
            )
        return [
            {"job_id": r[0], "tracking_id": r[1], "attempt": r[2] + 1,
             "max_attempts": r[3], "queue": r[4]}
            for r in rows
        ]

    def transition(self, job_id: int, state: str, *,
                   error_class: str | None = None,
                   retry_at: datetime | None = None,
                   clear_lease: bool = True) -> None:
        """通用状态流转；终态自动写 finished_at。"""
        with self.conn.cursor() as cur:
            cur.execute(
                """UPDATE fetch_job
                   SET state=%s, error_class=%s, retry_at=%s,
                       lease_until=CASE WHEN %s THEN NULL ELSE lease_until END,
                       worker_id=CASE WHEN %s THEN NULL ELSE worker_id END,
                       finished_at=CASE WHEN %s THEN now() ELSE finished_at END,
                       updated_at=now()
                   WHERE job_id=%s""",
                (state, error_class, retry_at, clear_lease, clear_lease,
                 state in TERMINAL_STATES, job_id),
            )

    def ack(self, job_id: int) -> None:
        """成功确认：终态 succeeded，清租约。"""
        self.transition(job_id, "succeeded")

    def retry(self, job_id: int, error_class: str,
              *, retry_at: datetime | None = None) -> None:
        """可重试失败：回 retry_scheduled，按 retry_at 延迟。"""
        self.transition(job_id, "retry_scheduled", error_class=error_class,
                        retry_at=retry_at or _now())

    def dead_letter(self, job_id: int, error_class: str) -> None:
        """终态失败：dead_letter，终态写 finished_at。"""
        self.transition(job_id, "dead_letter", error_class=error_class)

    def reclaim_expired(self, *, limit: int = 100) -> int:
        """回收过期租约：活跃态但 lease_until 已过 → 回 pending 待重新领取。

        返回回收数量；不丢任务、不计业务失败（基础设施失败分离，07 §3.2.1）。
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """UPDATE fetch_job
                   SET state='pending', lease_until=NULL, worker_id=NULL,
                       updated_at=now()
                   WHERE job_id IN (
                       SELECT job_id FROM fetch_job
                       WHERE state = ANY(%s) AND lease_until IS NOT NULL
                         AND lease_until <= now()
                       ORDER BY lease_until
                       FOR UPDATE SKIP LOCKED
                       LIMIT %s
                   )""",
                (list(ACTIVE_STATES), limit),
            )
            return cur.rowcount

    def get(self, job_id: int) -> dict | None:
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT job_id, state, attempt, max_attempts, error_class,
                          worker_id, lease_until, retry_at, finished_at
                   FROM fetch_job WHERE job_id=%s""",
                (job_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            keys = ("job_id", "state", "attempt", "max_attempts", "error_class",
                    "worker_id", "lease_until", "retry_at", "finished_at")
            return dict(zip(keys, row))
