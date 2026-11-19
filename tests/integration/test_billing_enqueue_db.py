"""billing_outbox 消费者真实库集成：事件种子 → FetchJob 入队 → 重放幂等。

覆盖 P7 关键缺口：受理（billing_outbox）→ 入队（A 库 fetch_job）全链路。
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

pytest.importorskip("psycopg")
import psycopg  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "apps" / "worker" / "src"),
                str(ROOT / "packages" / "common" / "src")]

from pandatrack_common.hashutil import payload_digest  # noqa: E402

from worker.billing.consumer import BillingOutboxConsumer  # noqa: E402

DB_A = os.environ.get("PT_DB_A_URL") or pytest.skip(
    "需要 PT_DB_A_URL", allow_module_level=True)
DB_B = os.environ.get("PT_DB_B_URL") or pytest.skip(
    "需要 PT_DB_B_URL", allow_module_level=True)

TAG = uuid.uuid4().hex[:10]
# 测试专用单号段（含 hex 字母，与生产数据可区分）
NUM1 = f"94{TAG.upper()}0000000001"
NUM2 = f"94{TAG.upper()}0000000002"


def _cleanup_a():
    with psycopg.connect(DB_A) as conn, conn.cursor() as cur:
        cur.execute(
            """DELETE FROM fetch_job WHERE tracking_id IN
                 (SELECT tracking_id FROM tracking
                   WHERE normalized_number IN (%s, %s))""", (NUM1, NUM2))
        cur.execute(
            "DELETE FROM tracking WHERE normalized_number IN (%s, %s)",
            (NUM1, NUM2))
        conn.commit()


def _cleanup_b():
    with psycopg.connect(DB_B) as conn, conn.cursor() as cur:
        cur.execute(
            """DELETE FROM billing_outbox WHERE payload->>'candidates'
                 LIKE %s""", (f"%{TAG.upper()}%",))
        conn.commit()


@pytest.fixture()
def seeded():
    op_id = None
    try:
        with psycopg.connect(DB_B) as conn:
            with conn.cursor() as cur:
                payload = {"operation_id": 0, "customer_id": 0,
                           "candidates": [NUM1, NUM2]}
                cur.execute(
                    """INSERT INTO billing_outbox
                         (aggregate_id, aggregate_type, aggregate_version,
                          payload, payload_digest)
                       VALUES (0, 'submission_operation', 1, %s::jsonb, %s)
                       RETURNING event_id, aggregate_id""",
                    (json_dumps(payload), payload_digest(payload)))
                event_id, op_id = cur.fetchone()
            conn.commit()
        yield {"event_id": event_id, "op_id": op_id}
    finally:
        _cleanup_a()
        _cleanup_b()


def json_dumps(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


def _jobs():
    with psycopg.connect(DB_A) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT f.state, f.queue, t.normalized_number
               FROM fetch_job f JOIN tracking t ON t.tracking_id=f.tracking_id
               WHERE t.normalized_number IN (%s, %s)
               ORDER BY t.normalized_number, f.job_id""", (NUM1, NUM2))
        return cur.fetchall()


def test_enqueue_creates_jobs_and_marks_processed(seeded):
    c = BillingOutboxConsumer(lambda: psycopg.connect(DB_A),
                              lambda: psycopg.connect(DB_B))
    stats = c.run_once()
    assert stats.scanned >= 1
    # 本事件两个单号均入队（可能混入其它 pending 事件的单号，只断言我们这两个）
    jobs = _jobs()
    nums = {j[2] for j in jobs}
    assert NUM1 in nums and NUM2 in nums
    for j in jobs:
        if j[2] in (NUM1, NUM2):
            assert j[0] == "pending" and j[1] == "Q_SCHEDULED"
    # B 库已标记 processed
    with psycopg.connect(DB_B) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT processed, last_error FROM billing_outbox WHERE event_id=%s",
            (seeded["event_id"],))
        processed, last_error = cur.fetchone()
    assert processed is True and last_error is None


def test_replay_is_idempotent(seeded):
    c = BillingOutboxConsumer(lambda: psycopg.connect(DB_A),
                              lambda: psycopg.connect(DB_B))
    first = c.run_once()
    assert first.scanned >= 1
    jobs_before = len([j for j in _jobs()
                       if j[2] in (NUM1, NUM2)])
    # 重放：事件已 processed，不会再产生新 job
    second = c.run_once()
    jobs_after = len([j for j in _jobs()
                      if j[2] in (NUM1, NUM2)])
    assert jobs_after == jobs_before
    # single-flight：同 tracking 只有一个活跃 job
    assert jobs_after == 2


def test_digest_mismatch_abandons(seeded):
    # 伪造坏 digest 事件（单号含 TAG 便于清理；不会真实入队）
    bad_num = f"94{TAG.upper()}0000000003"
    payload = {"operation_id": 0, "customer_id": 0, "candidates": [bad_num]}
    with psycopg.connect(DB_B) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO billing_outbox
                 (aggregate_id, aggregate_type, aggregate_version,
                  payload, payload_digest)
               VALUES (990001, 'submission_operation', 1, %s::jsonb, %s)""",
            (json_dumps(payload), "0" * 64))
        conn.commit()
    c = BillingOutboxConsumer(lambda: psycopg.connect(DB_A),
                              lambda: psycopg.connect(DB_B),
                              max_attempts=1)
    stats = c.run_once()
    assert stats.scanned >= 2
    assert stats.abandoned >= 1
    with psycopg.connect(DB_B) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT processed, last_error FROM billing_outbox
               WHERE payload->>'candidates' LIKE %s""",
            (f"%{bad_num}%",))
        rows = cur.fetchall()
    assert rows and rows[0][0] is True and rows[0][1] == "digest_mismatch"
