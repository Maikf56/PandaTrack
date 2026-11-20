"""开放注册集成验证（真实 B 库 + TestClient，P16）：
注册建 pending 账号 + 0 余额钱包 / 重复邮箱 409 / pending 登录 403 account_pending /
管理员审核通过后可登录。审核动作复用 PATCH /admin/customers/{id}/status。
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "contracts" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "common" / "src"))

pytest.importorskip("psycopg")
import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402

DB_B = os.environ.get("PT_DB_B_URL")
pytestmark = pytest.mark.skipif(
    not DB_B, reason="未设 PT_DB_B_URL，跳过注册集成测试")


@pytest.fixture(scope="module")
def client():
    app = create_app(DB_B)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def reg_ctx():
    """注册一个临时账号并保证清理（含 admin 会话可能写入的行）。"""
    tag = uuid.uuid4().hex[:12]
    ctx = {"email": f"reg-{tag}@example.com", "tag": tag, "customer_id": None}
    yield ctx
    cid = ctx["customer_id"]
    if cid is None:
        return
    with psycopg.connect(DB_B) as conn:
        with conn.cursor() as cur:
            for sql, params in (
                ("DELETE FROM audit_log WHERE target=%s", (str(cid),)),
                ("DELETE FROM session WHERE customer_id=%s", (cid,)),
                ("DELETE FROM wallet WHERE customer_id=%s", (cid,)),
                ("DELETE FROM customer WHERE customer_id=%s", (cid,)),
            ):
                cur.execute(sql, params)


def _register(client, ctx) -> None:
    resp = client.post("/api/v1/auth/register", json={
        "email": ctx["email"], "password": "password123",
        "client_request_id": uuid.uuid4().hex[:16],
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "pending"
    with psycopg.connect(DB_B) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT customer_id, status FROM customer WHERE email=%s",
                        (ctx["email"],))
            row = cur.fetchone()
    assert row is not None and row[1] == "pending"
    ctx["customer_id"] = row[0]
    with psycopg.connect(DB_B) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT balance FROM wallet WHERE customer_id=%s",
                        (row[0],))
            assert cur.fetchone()[0] == 0


def test_register_creates_pending_account(client, reg_ctx):
    _register(client, reg_ctx)


def test_register_duplicate_email_conflict(client, reg_ctx):
    _register(client, reg_ctx)
    resp = client.post("/api/v1/auth/register", json={
        "email": reg_ctx["email"], "password": "password456",
        "client_request_id": uuid.uuid4().hex[:16],
    })
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "email_exists"


def test_pending_login_forbidden_with_clear_code(client, reg_ctx):
    _register(client, reg_ctx)
    resp = client.post("/api/v1/auth/login", json={
        "email": reg_ctx["email"], "password": "password123",
        "client_request_id": uuid.uuid4().hex[:16],
    })
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "account_pending"


def test_admin_approve_then_login_ok(client, reg_ctx):
    _register(client, reg_ctx)
    # 管理员登录 → 审核通过（PATCH status=active，理由必填语义在前端）
    resp = client.post("/api/v1/admin/auth/login", json={
        "username": os.environ.get("PT_TEST_ADMIN_USER", "admin"),
        "password": os.environ.get("PT_TEST_ADMIN_PASSWORD", "admin-password"),
    })
    if resp.status_code != 200:
        pytest.skip("测试环境无管理员账号，跳过审核通过路径")
    resp = client.patch(
        f"/api/v1/admin/customers/{reg_ctx['customer_id']}/status"
        "?status=active&reason=注册审核通过",
    )
    assert resp.status_code == 200, resp.text
    resp = client.post("/api/v1/auth/login", json={
        "email": reg_ctx["email"], "password": "password123",
        "client_request_id": uuid.uuid4().hex[:16],
    })
    assert resp.status_code == 200, resp.text


def test_register_contract_rejects_short_password(client, reg_ctx):
    resp = client.post("/api/v1/auth/register", json={
        "email": reg_ctx["email"], "password": "short",
        "client_request_id": uuid.uuid4().hex[:16],
    })
    # 契约校验失败由全局错误处理统一映射为 400 invalid_input（09 §4）
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_input"
