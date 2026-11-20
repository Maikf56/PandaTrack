"""邀请好友 BFF 集成验证（真实 B 库 + TestClient，P15 脚手架）：
邀请码获取幂等/重置失效/统计与好友列表只读。
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
from api.data import BRepository  # noqa: E402

DB_B = os.environ.get("PT_DB_B_URL")
pytestmark = pytest.mark.skipif(
    not DB_B, reason="未设 PT_DB_B_URL，跳过邀请集成测试")


@pytest.fixture(scope="module")
def client():
    app = create_app(DB_B)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def customer():
    tag = uuid.uuid4().hex[:12]
    ctx: dict = {}

    def _cleanup():
        cid = ctx.get("customer_id")
        if cid is None:
            return
        with psycopg.connect(DB_B) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM invite_friend WHERE inviter_customer_id=%s", (cid,))
                cur.execute("DELETE FROM invite_code WHERE customer_id=%s", (cid,))
                cur.execute("DELETE FROM points_ledger WHERE customer_id=%s", (cid,))
                cur.execute("DELETE FROM session WHERE customer_id=%s", (cid,))
                cur.execute("DELETE FROM wallet WHERE customer_id=%s", (cid,))
                cur.execute("DELETE FROM customer WHERE customer_id=%s", (cid,))

    try:
        email = f"inv-{tag}@example.com"
        with psycopg.connect(DB_B) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO customer (email, password_hash)
                       VALUES (%s, %s) RETURNING customer_id""",
                    (email, BRepository.hash_password("password123")))
                cid = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO wallet (customer_id, balance) VALUES (%s, 500)",
                    (cid,))
        ctx["customer_id"] = cid
        ctx["email"] = email
        try:
            yield ctx
        finally:
            _cleanup()
    except Exception:
        _cleanup()
        raise


def _login(client, ctx) -> None:
    resp = client.post("/api/v1/auth/login",
                       json={"email": ctx["email"], "password": "password123",
                             "client_request_id": uuid.uuid4().hex[:16]})
    assert resp.status_code == 200, resp.text


def test_invite_code_lifecycle(client, customer):
    _login(client, customer)
    # 首次获取：生成 8 位码
    resp = client.get("/api/v1/invites/me")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    code1 = body["code"]
    assert len(code1) == 8
    # 幂等：再次获取同一码
    resp = client.get("/api/v1/invites/me")
    assert resp.json()["code"] == code1
    # 统计初始为 0（无注册闭环）
    assert body["invited_count"] == 0 and body["awarded_points"] == 0
    # 重置：换新码
    resp = client.post("/api/v1/invites/regenerate")
    assert resp.status_code == 200, resp.text
    code2 = resp.json()["code"]
    assert code2 != code1 and len(code2) == 8
    resp = client.get("/api/v1/invites/me")
    assert resp.json()["code"] == code2
    # 好友列表为空
    resp = client.get("/api/v1/invites/friends")
    assert resp.status_code == 200 and resp.json() == []


def test_invite_unauthorized(client):
    resp = client.get("/api/v1/invites/me")
    assert resp.status_code == 401
