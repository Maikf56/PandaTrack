"""BFF 集成测试（真实 B 库 PG，09 契约端到端）。

需 PT_DB_B_URL；未配置 skip。验证 login→me→submission→operation→ledger 链路
在真实 PG 上的 SQL/契约/事务正确性（本机单测用 TestClient+mock，这里用真库）。
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

DB_URL = os.environ.get("PT_DB_B_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="未设 PT_DB_B_URL，跳过 BFF 集成测试")

import psycopg  # noqa: E402

from api.app import create_app  # noqa: E402
from api.data import BRepository  # noqa: E402

EMAIL = f"bff-{uuid.uuid4().hex[:8]}@example.com"
PASSWORD = "password123"
CLEAN_NUM = "9400150206217997979667"


@pytest.fixture(scope="module")
def seeded():
    """创建独立客户 + 钱包（余额 100），结束清理。"""
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO customer (email, password_hash, status, role)
                   VALUES (%s,%s,'active','member') RETURNING customer_id""",
                (EMAIL, BRepository.hash_password(PASSWORD)),
            )
            cid = cur.fetchone()[0]
            cur.execute("INSERT INTO wallet (customer_id,balance) VALUES (%s,100)", (cid,))
            conn.commit()
    yield cid
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            # 由 operation 级联清离子表；先删无级联的流水/reservation。
            cur.execute(
                """DELETE FROM points_ledger WHERE customer_id=%s""", (cid,))
            cur.execute(
                """DELETE FROM billing_charge_window WHERE customer_id=%s""", (cid,))
            cur.execute(
                """DELETE FROM idempotency_record WHERE customer_id=%s""", (cid,))
            cur.execute(
                """DELETE FROM session WHERE customer_id=%s""", (cid,))
            # b/0004：受理挂默认组后，customer_tracking 也须先清。
            cur.execute(
                """DELETE FROM tracking_projection WHERE customer_tracking_id IN
                     (SELECT customer_tracking_id FROM customer_tracking
                      WHERE customer_id=%s)""", (cid,))
            cur.execute(
                "DELETE FROM customer_tracking WHERE customer_id=%s", (cid,))
            # 所有引用 operation 的子表须先删（按 operation 子查询）。
            sub = "SELECT operation_id FROM submission_operation WHERE customer_id=%s"
            for table in ("charge_reservation", "projection_event", "operation_snapshot",
                          "submission_item", "submission_batch"):
                if table == "submission_item":
                    cur.execute(
                        "DELETE FROM submission_item WHERE batch_id IN ("
                        "SELECT batch_id FROM submission_batch WHERE operation_id IN (" +
                        sub + "))", (cid,))
                elif table == "submission_batch":
                    cur.execute(
                        f"DELETE FROM submission_batch WHERE operation_id IN ({sub})", (cid,))
                else:
                    cur.execute(
                        f"DELETE FROM {table} WHERE operation_id IN ({sub})", (cid,))
            cur.execute(
                """DELETE FROM submission_operation WHERE customer_id=%s""", (cid,))
            cur.execute("DELETE FROM target_group WHERE customer_id=%s", (cid,))
            cur.execute("DELETE FROM wallet WHERE customer_id=%s", (cid,))
            cur.execute("DELETE FROM customer WHERE customer_id=%s", (cid,))
            conn.commit()


@pytest.fixture
def client(seeded):
    app = create_app(dsn=DB_URL)
    return TestClient(app)


class TestBffRealDb:
    def test_login_me_roundtrip(self, client):
        r = client.post("/api/v1/auth/login", json={
            "email": EMAIL, "password": PASSWORD,
            "client_request_id": "bff-login-0001"})
        assert r.status_code == 200, r.text
        assert "pt_session" in r.cookies
        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200, me.text
        assert me.json()["email"] == EMAIL
        assert me.json()["balance"] == 100

    def test_submission_creates_operation(self, client):
        client.post("/api/v1/auth/login", json={
            "email": EMAIL, "password": PASSWORD,
            "client_request_id": "bff-login-0002"})
        r = client.post("/api/v1/submissions", json={
            "source": "paste", "client_request_id": f"bff-submit-{uuid.uuid4().hex[:8]}",
            "lines": [CLEAN_NUM]})
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["valid_count"] == 1
        assert body["operation_id"]
        # 用返回的 operation_id 查进度（tenant scope 正确）。
        op = client.get(f"/api/v1/operations/{body['operation_id']}")
        assert op.status_code == 200, op.text
        assert op.json()["total_count"] == 1

    def test_redeem_appends_ledger(self, client):
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                code = f"{uuid.uuid4().hex[:4].upper()}-{uuid.uuid4().hex[:4].upper()}-XXXX"
                cur.execute(
                    "INSERT INTO redemption_code (code,points,status) VALUES (%s,50,'active')",
                    (code,))
                conn.commit()
        client.post("/api/v1/auth/login", json={
            "email": EMAIL, "password": PASSWORD,
            "client_request_id": "bff-login-0003"})
        r = client.post("/api/v1/billing/redemptions", json={"code": code})
        assert r.status_code == 200, r.text
        assert r.json()["points_added"] == 50
        # 钱包已加 50（可能有前面扣费，用 ledger 验证追加而非直接 patch）。
        led = client.get("/api/v1/billing/ledger")
        assert led.status_code == 200
        assert any(e["ledger_type"] == "redeem" for e in led.json())
