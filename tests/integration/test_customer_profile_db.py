"""P17 客户管理闭环集成验证（真实 B 库 + TestClient）：

1. 管理端开户：建号即 active + 初始积分（wallet/台账/审计）+ 重复邮箱 409
2. 管理端改资料/改邮箱/重置密码：字段生效、审计只记字段名、新密码可登录
3. 注册带邀请码：invite_friend 记 pending；审核通过激活 → 邀请人 +500
   （invite_reward 台账 + rewarded，重复激活不重复发奖）；无效邀请码 400
4. 客户自助资料：GET/PATCH /settings/profile（name/phone/remark）
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
    not DB_B, reason="未设 PT_DB_B_URL，跳过客户管理集成测试")

ADMIN_PW = "admin-password-1"


@pytest.fixture(scope="module")
def client():
    app = create_app(DB_B)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def env():
    """种子 super_admin；收集测试产生的 customer_id 统一级联清理。"""
    tag = uuid.uuid4().hex[:12]
    ctx = {"tag": tag, "admin_id": None, "customer_ids": [], "email": ""}
    with psycopg.connect(DB_B) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO admin_user (username, password_hash, role, status)
                   VALUES (%s,%s,'super_admin','active') RETURNING admin_id""",
                (f"adm-{tag}", BRepository.hash_password(ADMIN_PW)))
            ctx["admin_id"] = cur.fetchone()[0]
            conn.commit()
    yield ctx
    ids = ctx["customer_ids"]
    with psycopg.connect(DB_B) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM session WHERE admin_id=%s", (ctx["admin_id"],))
            cur.execute("DELETE FROM audit_log WHERE actor_id=%s", (ctx["admin_id"],))
            if ids:
                cur.execute("DELETE FROM session WHERE customer_id=ANY(%s)", (ids,))
                cur.execute(
                    "DELETE FROM audit_log WHERE target=ANY(%s)",
                    ([str(i) for i in ids],))
                cur.execute("DELETE FROM points_ledger WHERE customer_id=ANY(%s)", (ids,))
                cur.execute(
                    """DELETE FROM invite_friend WHERE
                       inviter_customer_id=ANY(%s) OR friend_customer_id=ANY(%s)""",
                    (ids, ids))
                cur.execute("DELETE FROM invite_code WHERE customer_id=ANY(%s)", (ids,))
                cur.execute("DELETE FROM wallet WHERE customer_id=ANY(%s)", (ids,))
                cur.execute("DELETE FROM customer WHERE customer_id=ANY(%s)", (ids,))
            cur.execute("DELETE FROM admin_user WHERE admin_id=%s", (ctx["admin_id"],))
            conn.commit()


def _admin_login(client: TestClient, ctx: dict) -> None:
    r = client.post("/api/v1/admin/auth/login",
                    json={"username": f"adm-{ctx['tag']}", "password": ADMIN_PW})
    assert r.status_code == 200, r.text


def _customer_id_by_email(email: str) -> int:
    with psycopg.connect(DB_B) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT customer_id FROM customer WHERE email=%s", (email,))
            row = cur.fetchone()
    assert row is not None
    return row[0]


# ---- 1) 管理端开户 ----

def test_admin_create_customer(client, env):
    _admin_login(client, env)
    email = f"new-{env['tag']}@example.com"
    env["email"] = email
    r = client.post("/api/v1/admin/customers", json={
        "email": email, "password": "password123",
        "name": "张三", "phone": "13800000000", "remark": "线下月结",
        "initial_points": 500,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "active"
    cid = body["customer_id"]
    env["customer_ids"].append(cid)

    with psycopg.connect(DB_B) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status, role, name, phone, remark FROM customer WHERE customer_id=%s", (cid,))
            assert cur.fetchone() == ("active", "member", "张三", "13800000000", "线下月结")
            cur.execute("SELECT balance FROM wallet WHERE customer_id=%s", (cid,))
            assert cur.fetchone()[0] == 500
            cur.execute("""SELECT ledger_type, points_change FROM points_ledger
                           WHERE customer_id=%s ORDER BY ledger_id DESC LIMIT 1""", (cid,))
            assert cur.fetchone() == ("admin_adjust", 500)
            cur.execute("SELECT action FROM audit_log WHERE target=%s", (str(cid),))
            assert cur.fetchone()[0] == "customer_created"

    # 重复邮箱 → 409
    r2 = client.post("/api/v1/admin/customers", json={
        "email": email, "password": "password123"})
    assert r2.status_code == 409
    assert "email_exists" in r2.text


# ---- 2) 管理端改资料/重置密码 ----

def test_admin_update_customer_profile(client, env):
    _admin_login(client, env)
    email = f"prof-{env['tag']}@example.com"
    r = client.post("/api/v1/admin/customers", json={
        "email": email, "password": "password123", "name": "旧名"})
    assert r.status_code == 201, r.text
    cid = r.json()["customer_id"]
    env["customer_ids"].append(cid)

    new_email = f"prof2-{env['tag']}@example.com"
    r = client.patch(f"/api/v1/admin/customers/{cid}", json={
        "name": "李四", "phone": "13900000000", "remark": "VIP",
        "email": new_email, "new_password": "newpassword9"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == new_email

    with psycopg.connect(DB_B) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name, phone, remark, email FROM customer WHERE customer_id=%s", (cid,))
            assert cur.fetchone() == ("李四", "13900000000", "VIP", new_email)
            # 审计只记字段名，不记密码值（detail 是 jsonb，序列化后做子串断言）
            cur.execute("""SELECT detail FROM audit_log WHERE target=%s AND action='customer_profile_update'
                           ORDER BY audit_id DESC LIMIT 1""", (str(cid),))
            import json as _json
            detail = _json.dumps(cur.fetchone()[0], ensure_ascii=False)
    assert "password" in detail and "newpassword9" not in detail
    assert "email" in detail and "name" in detail

    # 新密码可登录（旧密码失效）
    r = client.post("/api/v1/auth/login",
                    json={"email": new_email, "password": "newpassword9",
                          "client_request_id": uuid.uuid4().hex[:16]})
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/auth/login",
                    json={"email": new_email, "password": "password123",
                          "client_request_id": uuid.uuid4().hex[:16]})
    assert r.status_code == 401

    # 空补丁 → 400
    r = client.patch(f"/api/v1/admin/customers/{cid}", json={})
    assert r.status_code == 400


# ---- 3) 注册带邀请码 + 激活发奖 ----

def test_register_with_invite_and_reward(client, env):
    _admin_login(client, env)
    tag = env["tag"]
    # 邀请人：直接建（active + 钱包 0）+ 邀请码
    with psycopg.connect(DB_B) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO customer (email, password_hash, status, role)
                   VALUES (%s,'x','active','member') RETURNING customer_id""",
                (f"inviter-{tag}@example.com",))
            inviter_id = cur.fetchone()[0]
            cur.execute("INSERT INTO wallet (customer_id, balance) VALUES (%s, 0)", (inviter_id,))
            code = f"T{tag[:7].upper()}"
            cur.execute("INSERT INTO invite_code (customer_id, code) VALUES (%s,%s)",
                        (inviter_id, code))
            conn.commit()
    env["customer_ids"].append(inviter_id)

    # 无效邀请码 → 400，且不建号
    r = client.post("/api/v1/auth/register", json={
        "email": f"friend0-{tag}@example.com", "password": "password123",
        "client_request_id": uuid.uuid4().hex[:16], "invite_code": "NOPE1234"})
    assert r.status_code == 400, r.text
    with psycopg.connect(DB_B) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM customer WHERE email=%s",
                        (f"friend0-{tag}@example.com",))
            assert cur.fetchone()[0] == 0

    # 带有效邀请码注册 → pending + invite_friend(pending)
    friend_email = f"friend-{tag}@example.com"
    r = client.post("/api/v1/auth/register", json={
        "email": friend_email, "password": "password123",
        "client_request_id": uuid.uuid4().hex[:16], "invite_code": code.lower()})
    assert r.status_code == 201, r.text
    friend_id = _customer_id_by_email(friend_email)
    env["customer_ids"].append(friend_id)

    with psycopg.connect(DB_B) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT inviter_customer_id, status, points_awarded
                           FROM invite_friend WHERE friend_customer_id=%s""", (friend_id,))
            assert cur.fetchone() == (inviter_id, "pending", 0)

    # 审核通过（pending→active）→ 邀请人 +500（invite_reward 台账 + rewarded）
    r = client.patch(f"/api/v1/admin/customers/{friend_id}/status",
                     params={"status": "active", "reason": "注册审核通过"})
    assert r.status_code == 200, r.text
    with psycopg.connect(DB_B) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT balance FROM wallet WHERE customer_id=%s", (inviter_id,))
            assert cur.fetchone()[0] == 500
            cur.execute("""SELECT ledger_type, points_change FROM points_ledger
                           WHERE customer_id=%s ORDER BY ledger_id DESC LIMIT 1""",
                        (inviter_id,))
            assert cur.fetchone() == ("invite_reward", 500)
            cur.execute("""SELECT status, points_awarded FROM invite_friend
                           WHERE friend_customer_id=%s""", (friend_id,))
            assert cur.fetchone() == ("rewarded", 500)

    # 冻结后再次激活：不重复发奖
    client.patch(f"/api/v1/admin/customers/{friend_id}/status",
                 params={"status": "suspended", "reason": "测试"})
    client.patch(f"/api/v1/admin/customers/{friend_id}/status",
                 params={"status": "active", "reason": "测试恢复"})
    with psycopg.connect(DB_B) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT balance FROM wallet WHERE customer_id=%s", (inviter_id,))
            assert cur.fetchone()[0] == 500
            cur.execute("SELECT count(*) FROM points_ledger WHERE customer_id=%s "
                        "AND ledger_type='invite_reward'", (inviter_id,))
            assert cur.fetchone()[0] == 1


# ---- 4) 客户自助资料 ----

def test_self_profile(client, env):
    _admin_login(client, env)
    email = f"self-{env['tag']}@example.com"
    r = client.post("/api/v1/admin/customers", json={
        "email": email, "password": "password123", "name": "原名"})
    assert r.status_code == 201, r.text
    env["customer_ids"].append(r.json()["customer_id"])

    # 客户登录（独立 cookie 会话）
    c2 = TestClient(client.app)
    r = c2.post("/api/v1/auth/login",
                json={"email": email, "password": "password123",
                      "client_request_id": uuid.uuid4().hex[:16]})
    assert r.status_code == 200, r.text

    r = c2.get("/api/v1/settings/profile")
    assert r.status_code == 200, r.text
    assert r.json()["email"] == email
    assert r.json()["name"] == "原名"

    r = c2.patch("/api/v1/settings/profile", json={
        "name": "新名", "phone": "13700000000", "remark": "客户备注"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "新名"
    r = c2.get("/api/v1/settings/profile")
    assert (r.json()["name"], r.json()["phone"], r.json()["remark"]) == (
        "新名", "13700000000", "客户备注")

    # 空补丁 → 400
    r = c2.patch("/api/v1/settings/profile", json={})
    assert r.status_code == 400

    # 未登录 → 401
    c3 = TestClient(client.app)
    r = c3.get("/api/v1/settings/profile")
    assert r.status_code == 401
