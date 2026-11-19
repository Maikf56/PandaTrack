"""SSE 推送集成验证（真实 B 库）：b/0003 触发器 → LISTEN 收到 NOTIFY。

覆盖链路：INSERT projection_event → trg_projection_event_notify →
pg_notify('pandatrack_projection') → 本测试 LISTEN 连接 poll 到载荷。
（BFF 侧 LISTEN→Hub→路由由单测覆盖。）
"""
from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api" / "src"))

pytest.importorskip("psycopg")
import psycopg  # noqa: E402

from api.notify import parse_notification  # noqa: E402

DB_B = os.environ.get("PT_DB_B_URL")
pytestmark = pytest.mark.skipif(
    not DB_B, reason="未设 PT_DB_B_URL，跳过 SSE 触发器集成测试")

CHANNEL = "pandatrack_projection"


@pytest.fixture
def seeded():
    """B 侧：客户 + operation + 追加 projection_event 行，用后清理。"""
    tag = uuid.uuid4().hex[:12]
    ctx: dict = {}

    def _cleanup():
        with psycopg.connect(DB_B) as conn:
            with conn.cursor() as cur:
                if ctx.get("event_ids"):
                    cur.execute("DELETE FROM projection_event WHERE "
                                "event_id = ANY(%s)", (ctx["event_ids"],))
                if ctx.get("operation_id"):
                    cur.execute("DELETE FROM charge_reservation WHERE "
                                "operation_id=%s", (ctx["operation_id"],))
                    cur.execute("DELETE FROM billing_outbox WHERE "
                                "aggregate_id=%s AND aggregate_type='operation'",
                                (ctx["operation_id"],))
                    cur.execute("DELETE FROM submission_batch WHERE "
                                "operation_id=%s", (ctx["operation_id"],))
                    cur.execute("DELETE FROM idempotency_record WHERE "
                                "customer_id=%s", (ctx["customer_id"],))
                    cur.execute("DELETE FROM points_ledger WHERE "
                                "customer_id=%s", (ctx["customer_id"],))
                    cur.execute("DELETE FROM submission_operation WHERE "
                                "operation_id=%s", (ctx["operation_id"],))
                if ctx.get("customer_id"):
                    cur.execute("DELETE FROM wallet WHERE customer_id=%s",
                                (ctx["customer_id"],))
                    cur.execute("DELETE FROM customer WHERE customer_id=%s",
                                (ctx["customer_id"],))

    # 逐个 INSERT 并记 id，任何一步失败仍执行已写部分的清理。
    try:
        with psycopg.connect(DB_B) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO customer (email, password_hash)
                       VALUES (%s, 'x') RETURNING customer_id""",
                    (f"sse-{tag}@test.local",))
                cid = cur.fetchone()[0]
                ctx["customer_id"] = cid
                cur.execute(
                    """INSERT INTO wallet (customer_id, balance)
                       VALUES (%s, 0)""", (cid,))
                cur.execute(
                    """INSERT INTO submission_operation (customer_id,
                           total_count, valid_count)
                       VALUES (%s, 1, 1) RETURNING operation_id""",
                    (cid,))
                oid = cur.fetchone()[0]
                ctx["operation_id"] = oid
    except Exception:
        _cleanup()
        raise

    ctx["cleanup"] = _cleanup
    return ctx


def test_trigger_notifies_on_projection_event(seeded):
    oid = seeded["operation_id"]
    listener_conn, got = None, []
    try:
        listener_conn = psycopg.connect(DB_B, autocommit=True)
        listener_conn.execute(f"LISTEN {CHANNEL}")  # noqa: S608
        # psycopg3 官方模式：conn.notifies() 生成器迭代通知。
        def _reader():
            for n in listener_conn.notifies():
                got.append(n)
                if len(got) >= 5:
                    break

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        with psycopg.connect(DB_B) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO projection_event (operation_id,
                           aggregate_version, payload)
                       VALUES (%s, 1, %s) RETURNING event_id""",
                    (oid, json.dumps({"kind": "operation.progress",
                                      "summary": "1/1 处理完成"})))
                seeded["event_ids"] = [cur.fetchone()[0]]
        t.join(timeout=3.0)
        assert got, "未收到 NOTIFY"
        n = next(x for x in got if x.channel == CHANNEL)
        customer_id, data = parse_notification(n.payload)
        assert customer_id == seeded["customer_id"]
        assert data["operation_id"] == oid
        assert data["event_id"] == seeded["event_ids"][0]
    finally:
        if listener_conn is not None:
            listener_conn.close()
        seeded["cleanup"]()


def test_migrate_applied_trigger_exists():
    """触发器与函数已由 migrate.py 应用（0003 迁移幂等）。"""
    with psycopg.connect(DB_B) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT 1 FROM pg_trigger
                   WHERE tgname='trg_projection_event_notify'
                     AND tgrelid='projection_event'::regclass""")
            assert cur.fetchone() is not None
            cur.execute(
                """SELECT 1 FROM pg_proc p JOIN pg_namespace n
                   ON n.oid=p.pronamespace
                   WHERE p.proname='notify_projection_event'""")
            assert cur.fetchone() is not None
