"""sync-agent 集成验证（真实 A+B 库）：投影落库/扇出/重放幂等/processed 标记。"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))

pytest.importorskip("psycopg")
import psycopg  # noqa: E402

from worker.sync.agent import SyncAgent  # noqa: E402

DB_A = os.environ.get("PT_DB_A_URL")
DB_B = os.environ.get("PT_DB_B_URL")
pytestmark = pytest.mark.skipif(
    not (DB_A and DB_B), reason="未设 PT_DB_A_URL/PT_DB_B_URL，跳过投影集成测试")


@pytest.fixture
def seeded():
    """A 侧：tracking+event+outbox；B 侧：两个客户各跟踪同一单号。

    用 addfinalizer 注册清理：setup 中途失败（如 B 侧约束冲突）也能
    清掉已写入的 A 侧行，不残留影响后续批次。
    """
    tag = uuid.uuid4().hex[:12]
    number = f"94{tag}110200812345"[:22]
    ctx = {"number": number, "a": {}, "b": {}}

    def _cleanup():
        a, b = ctx["a"], ctx["b"]
        if a.get("tracking_id") is not None:
            with psycopg.connect(DB_A) as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM a_outbox WHERE aggregate_id=%s",
                                (a["tracking_id"],))
                    cur.execute(
                        "DELETE FROM tracking_event WHERE tracking_id=%s",
                        (a["tracking_id"],))
                    cur.execute("DELETE FROM tracking WHERE tracking_id=%s",
                                (a["tracking_id"],))
        if b.get("ct_ids"):
            with psycopg.connect(DB_B) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """DELETE FROM tracking_projection WHERE
                           customer_tracking_id = ANY(%s)""", (b["ct_ids"],))
                    cur.execute(
                        """DELETE FROM customer_tracking WHERE customer_id
                           = ANY(%s)""", (b["customer_ids"],))
                    cur.execute(
                        """DELETE FROM customer WHERE customer_id = ANY(%s)""",
                        (b["customer_ids"],))

    with psycopg.connect(DB_A) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO tracking (normalized_number, carrier)
                   VALUES (%s, 'usps') RETURNING tracking_id""", (number,))
            tid = cur.fetchone()[0]
            ctx["a"] = {"tracking_id": tid}
            cur.execute(
                """INSERT INTO tracking_event
                   (tracking_id, event_fingerprint, occurred_at, status,
                    description_raw, description_zh, location, event_code,
                    time_confidence)
                   VALUES (%s, %s, now(), 'in_transit', 'In-Transit',
                           '运输中', 'Atlanta GA', '', 'exact')""",
                (tid, f"fp-{tag}"))
            cur.execute(
                """INSERT INTO a_outbox (aggregate_id, aggregate_type,
                       aggregate_version, payload, payload_digest)
                   VALUES (%s, 'tracking', 1, %s, %s) RETURNING event_id""",
                (tid, f'{{"tracking_id": {tid}, "status": "in_transit"}}',
                 f"digest-{tag}"))
            ctx["a"]["event_id"] = cur.fetchone()[0]
    with psycopg.connect(DB_B) as conn:
        with conn.cursor() as cur:
            ct_ids, cids = [], []
            try:
                for i in range(2):  # 两个不同客户跟踪同一单号 → 扇出
                    email = f"sync-{tag}-{i}@test.local"
                    cur.execute(
                        """INSERT INTO customer (email, password_hash,
                               status, role) VALUES (%s, 'x', 'active',
                               'customer') RETURNING customer_id""", (email,))
                    cid = cur.fetchone()[0]
                    cids.append(cid)
                    cur.execute(
                        """INSERT INTO customer_tracking (customer_id,
                               normalized_number) VALUES (%s, %s)
                           RETURNING customer_tracking_id""", (cid, number))
                    ct_ids.append(cur.fetchone()[0])
            except Exception:
                _cleanup()
                raise
            ctx["b"] = {"customer_ids": cids, "ct_ids": ct_ids}
    yield ctx
    _cleanup()


class TestSyncAgentDb:
    def test_projection_fanout_and_mark(self, seeded):
        ctx = seeded
        agent = SyncAgent(connect_a=lambda: psycopg.connect(DB_A),
                          connect_b=lambda: psycopg.connect(DB_B))
        r = agent.run_once()
        assert r.fetched == 1 and r.projected == 2 and r.customers_hit == 2
        assert r.marked_processed == 1
        with psycopg.connect(DB_B) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT status, jsonb_array_length(events)
                       FROM tracking_projection
                       WHERE customer_tracking_id = ANY(%s)""",
                    (ctx["b"]["ct_ids"],))
                rows = cur.fetchall()
                assert len(rows) == 2
                for status, ev_count in rows:
                    assert status == "in_transit" and ev_count == 1
        with psycopg.connect(DB_A) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT processed FROM a_outbox WHERE event_id=%s",
                            (ctx["a"]["event_id"],))
                assert cur.fetchone()[0] is True

    def test_replay_idempotent(self, seeded):
        """B 提交后 A 未标记（崩溃窗口）→ 重放 upsert 结果不变、不重复。"""
        ctx = seeded
        agent = SyncAgent(connect_a=lambda: psycopg.connect(DB_A),
                          connect_b=lambda: psycopg.connect(DB_B))
        agent.run_once()
        # 模拟崩溃窗口：把 outbox 回置未处理，重放
        with psycopg.connect(DB_A) as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE a_outbox SET processed=false "
                            "WHERE aggregate_id=%s",
                            (ctx["a"]["tracking_id"],))
        r2 = agent.run_once()
        assert r2.projected == 2  # 重放再次 upsert 两行
        with psycopg.connect(DB_B) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT count(*) FROM tracking_projection
                       WHERE customer_tracking_id = ANY(%s)""",
                    (ctx["b"]["ct_ids"],))
                assert cur.fetchone()[0] == 2  # UNIQUE 约束，不重复

    def test_drain_second_round_empty(self, seeded):
        ctx = seeded
        agent = SyncAgent(connect_a=lambda: psycopg.connect(DB_A),
                          connect_b=lambda: psycopg.connect(DB_B))
        reports = agent.run_until_drained()
        assert reports[0].projected == 2
        assert reports[-1].fetched == 0  # 第二轮无积压
