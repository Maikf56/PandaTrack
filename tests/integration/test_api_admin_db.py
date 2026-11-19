"""P4-2 管理端集成测试（真实 A/B 库 PG，03 管理端）。

需 PT_DB_B_URL + PT_DB_A_URL；未配置 skip。
验证 admin 登录→客户列表→Provider 启停→积分调整→审计查询 全链路
在真实 PG 上的 SQL/鉴权/审计正确性。
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

DB_B = os.environ.get("PT_DB_B_URL")
DB_A = os.environ.get("PT_DB_A_URL")
pytestmark = pytest.mark.skipif(
    not (DB_B and DB_A), reason="未设 PT_DB_B_URL/PT_DB_A_URL，跳过管理端集成测试")

import psycopg  # noqa: E402

from api.app import create_app  # noqa: E402
from api.data import BRepository  # noqa: E402

ADMIN_NAME = f"adm-{uuid.uuid4().hex[:8]}"
ADMIN_PW = "admin-password-1"
ADMIN_COOKIE = "pt_admin_session"


@pytest.fixture(scope="module")
def seeded():
    """种子：B 库 admin_user + customer/wallet；A 库 provider_health。结束清理。"""
    with psycopg.connect(DB_B) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO admin_user (username, password_hash, role, status)
                   VALUES (%s,%s,'super_admin','active') RETURNING admin_id""",
                (ADMIN_NAME, BRepository.hash_password(ADMIN_PW)),
            )
            aid = cur.fetchone()[0]
            email = f"adm-cust-{uuid.uuid4().hex[:8]}@example.com"
            cur.execute(
                """INSERT INTO customer (email, password_hash, status, role)
                   VALUES (%s,'x','active','member') RETURNING customer_id""",
                (email,),
            )
            cid = cur.fetchone()[0]
            cur.execute("INSERT INTO wallet (customer_id,balance) VALUES (%s,100)", (cid,))
            conn.commit()
    code = f"tst{uuid.uuid4().hex[:8]}"
    with psycopg.connect(DB_A) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO provider_health (provider_code, enabled)
                   VALUES (%s,false)""", (code,))
            conn.commit()
    yield {"admin_id": aid, "customer_id": cid, "email": email, "provider_code": code}
    # 清理：B 库
    with psycopg.connect(DB_B) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM session WHERE admin_id=%s", (aid,))
            cur.execute("DELETE FROM audit_log WHERE actor_id=%s", (aid,))
            cur.execute("DELETE FROM points_ledger WHERE customer_id=%s", (cid,))
            cur.execute("DELETE FROM wallet WHERE customer_id=%s", (cid,))
            cur.execute("DELETE FROM customer WHERE customer_id=%s", (cid,))
            cur.execute("DELETE FROM admin_user WHERE admin_id=%s", (aid,))
            conn.commit()
    # A 库
    with psycopg.connect(DB_A) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM provider_health WHERE provider_code=%s", (code,))
            conn.commit()


class TestAdminApi:
    def test_admin_full_chain(self, seeded):
        app = create_app(dsn=DB_B, dsn_a=DB_A)
        c = TestClient(app)

        # 1) 错误密码 → 401
        r = c.post("/api/v1/admin/auth/login",
                   json={"username": ADMIN_NAME, "password": "wrong"})
        assert r.status_code == 401

        # 2) 正确登录 → cookie
        r = c.post("/api/v1/admin/auth/login",
                   json={"username": ADMIN_NAME, "password": ADMIN_PW})
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "super_admin"

        # 3) 客户列表（应含种子客户；带钱包余额——LEFT JOIN wallet）
        r = c.get("/api/v1/admin/customers")
        assert r.status_code == 200, r.text
        items = {it["customer_id"]: it for it in r.json()["items"]}
        assert seeded["customer_id"] in items
        assert items[seeded["customer_id"]]["balance"] == 100

        # 4) 未登录访问 → 401
        c2 = TestClient(app)
        r = c2.get("/api/v1/admin/customers")
        assert r.status_code == 401

        # 5) Provider 启停 + 审计
        code = seeded["provider_code"]
        r = c.post(f"/api/v1/admin/providers/{code}/toggle?enabled=true&reason=验收")
        assert r.status_code == 200, r.text
        assert r.json()["enabled"] is True
        with psycopg.connect(DB_A) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT enabled FROM provider_health WHERE provider_code=%s", (code,))
                assert cur.fetchone()[0] is True
        # 不存在的 Provider → 404
        r = c.post("/api/v1/admin/providers/nope_x/toggle?enabled=true")
        assert r.status_code == 404

        # 6) 积分调整 +50（追加流水，余额 100→150）
        cid = seeded["customer_id"]
        r = c.post(f"/api/v1/admin/billing/adjust?customer_id={cid}"
                   "&delta=50&description=测试调整&reason=admin")
        assert r.status_code == 200, r.text
        assert r.json()["new_balance"] == 150
        r = c.post(f"/api/v1/admin/billing/adjust?customer_id={cid}&delta=0&description=x")
        assert r.status_code == 400

        # 7) 审计查询（应含 provider_toggle 与 admin_adjust_points；target 过滤）
        r = c.get("/api/v1/admin/audit")
        assert r.status_code == 200, r.text
        actions = {it["action"] for it in r.json()["items"]}
        assert "provider_toggle" in actions
        assert "admin_adjust_points" in actions
        r = c.get(f"/api/v1/admin/audit?target={cid}")
        assert r.status_code == 200, r.text
        assert r.json()["items"]
        assert all(it["target"] == str(cid) for it in r.json()["items"])

    def test_status_dict_public(self, seeded):
        """状态字典是公开端点，无需鉴权。"""
        app = create_app(dsn=DB_B, dsn_a=DB_A)
        c = TestClient(app)
        r = c.get("/api/v1/status-dict")
        assert r.status_code == 200
