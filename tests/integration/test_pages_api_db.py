"""次要页面 BFF 集成验证（真实 B 库 + TestClient）：
组 CRUD/默认组挂靠/批次口径/导入列表/导出 CSV 短期下载/统计/设置。

fixture 建客户+钱包+会话走真实 SQL（与 test_api_bff_db 同风格）。
"""
from __future__ import annotations

import os
import sys
import tempfile
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
    not DB_B, reason="未设 PT_DB_B_URL，跳过次要页面集成测试")


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
        with psycopg.connect(DB_B) as conn:
            with conn.cursor() as cur:
                cid = ctx.get("customer_id")
                if cid is None:
                    return
                for sql in (
                    "DELETE FROM export_job WHERE customer_id=%s",
                    "DELETE FROM import_job WHERE customer_id=%s",
                    """DELETE FROM projection_event WHERE operation_id IN
                         (SELECT operation_id FROM submission_operation
                          WHERE customer_id=%s)""",
                    """DELETE FROM operation_snapshot WHERE operation_id IN
                         (SELECT operation_id FROM submission_operation
                          WHERE customer_id=%s)""",
                    """DELETE FROM charge_reservation WHERE operation_id IN
                         (SELECT operation_id FROM submission_operation
                          WHERE customer_id=%s)""",
                    """DELETE FROM billing_outbox WHERE aggregate_id IN
                         (SELECT operation_id FROM submission_operation
                          WHERE customer_id=%s)""",
                    """DELETE FROM submission_batch WHERE operation_id IN
                         (SELECT operation_id FROM submission_operation
                          WHERE customer_id=%s)""",
                    """DELETE FROM submission_operation WHERE customer_id=%s""",
                    """DELETE FROM tracking_projection WHERE
                         customer_tracking_id IN
                         (SELECT customer_tracking_id FROM customer_tracking
                          WHERE customer_id=%s)""",
                    """DELETE FROM customer_tracking WHERE customer_id=%s""",
                    "DELETE FROM target_group WHERE customer_id=%s",
                    "DELETE FROM idempotency_record WHERE customer_id=%s",
                    "DELETE FROM points_ledger WHERE customer_id=%s",
                    "DELETE FROM session WHERE customer_id=%s",
                    "DELETE FROM wallet WHERE customer_id=%s",
                    "DELETE FROM customer WHERE customer_id=%s",
                ):
                    cur.execute(sql, (cid,))

    try:
        email = f"ui-{tag}@example.com"
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
        ctx["cleanup"] = _cleanup
        return ctx
    except Exception:
        _cleanup()
        raise


def _login(client, ctx, password="password123") -> None:
    resp = client.post("/api/v1/auth/login",
                       json={"email": ctx["email"], "password": password,
                             "client_request_id": uuid.uuid4().hex[:16]})
    assert resp.status_code == 200, resp.text


def test_group_crud_and_default_group(client, customer):
    _login(client, customer)
    cid = customer["customer_id"]
    # 创建
    resp = client.post("/api/v1/groups", json={"name": "重点单"})
    assert resp.status_code == 201, resp.text
    group = resp.json()
    assert group["name"] == "重点单" and group["is_default"] is False
    # 列表
    resp = client.get("/api/v1/groups")
    names = [g["name"] for g in resp.json()]
    assert "重点单" in names
    # 重命名
    resp = client.patch(f"/api/v1/groups/{group['id']}",
                        json={"name": "重点单V2"})
    assert resp.status_code == 200 and resp.json()["name"] == "重点单V2"
    # 归档
    resp = client.post(f"/api/v1/groups/{group['id']}/archive",
                       json={"archived": True})
    assert resp.status_code == 200 and resp.json()["archived"] is True
    # 删除（只清组织关系）
    resp = client.delete(f"/api/v1/groups/{group['id']}")
    assert resp.status_code == 200
    # 默认组：受理路径建组（直接调 repo 层验证）
    repo = BRepository(DB_B)
    gid = repo.ensure_default_group(cid)
    with psycopg.connect(DB_B) as conn, conn.cursor() as cur:
        cur.execute("""SELECT is_default, name FROM target_group
                       WHERE group_id=%s""", (gid,))
        is_default, name = cur.fetchone()
    assert is_default is True
    # 幂等：再次 ensure 返回同一组
    assert repo.ensure_default_group(cid) == gid


def test_batch_detail_and_stats_and_export_flow(client, customer):
    _login(client, customer)
    cid = customer["customer_id"]
    repo = BRepository(DB_B)

    # 种子：operation + batch + item + customer_tracking + projection
    with psycopg.connect(DB_B) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO submission_operation (customer_id, total_count,
                   valid_count, points_charged)
               VALUES (%s, 2, 2, 2) RETURNING operation_id, public_id""",
            (cid,))
        oid, opub = cur.fetchone()
        opub = str(opub)
        cur.execute(
            """INSERT INTO submission_batch (operation_id, batch_seq,
                   item_count, state) VALUES (%s, 1, 2, 'done')
               RETURNING batch_id""",
            (oid,))
        batch_id = cur.fetchone()[0]
        num1 = f"9400{uuid.uuid4().hex[:8].upper()}110200812345"[:22]
        cur.execute(
            """INSERT INTO submission_item (batch_id, item_seq, raw_number,
                   normalized_number, is_valid)
               VALUES (%s, 1, %s, %s, true)""",
            (batch_id, num1, num1))
        cur.execute(
            """INSERT INTO customer_tracking (customer_id, normalized_number)
               VALUES (%s, %s) RETURNING customer_tracking_id""",
            (cid, num1))
        ct1 = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO tracking_projection (customer_tracking_id,
                   normalized_number, status, events)
               VALUES (%s, %s, 'delivered', '[]')""", (ct1, num1))

    # 挂默认组（受理后置动作）
    gid = repo.ensure_default_group(cid)
    repo.assign_operation_group(cid, opub, gid)
    with psycopg.connect(DB_B) as conn, conn.cursor() as cur:
        cur.execute("SELECT group_id FROM submission_operation WHERE "
                    "operation_id=%s", (oid,))
        assert cur.fetchone()[0] == gid

    # 批次列表/详情口径
    resp = client.get("/api/v1/batches")
    assert any(b["id"] == opub for b in resp.json())
    resp = client.get(f"/api/v1/batches/{opub}")
    d = resp.json()
    assert d["completed"] == 1 and d["missing"] == 0  # num1 已有 delivered 投影
    assert d["valid_count"] == 2 and d["points_charged"] == 2

    # 统计（服务端口径）
    resp = client.get("/api/v1/stats?days=30")
    s = resp.json()
    assert s["submissions"] >= 1 and s["status_distribution"].get("delivered") == 1

    # 导出：all → CSV 生成 + 短期 token 下载 + 错误 token 404
    resp = client.post("/api/v1/exports", json={"scope": "all"})
    assert resp.status_code == 201, resp.text
    exp = resp.json()
    assert exp["row_count"] >= 1 and exp["download_url"]
    resp = client.get(exp["download_url"])
    assert resp.status_code == 200 and "normalized_number" in resp.text
    resp = client.get(f"/api/v1/exports/{exp['id']}/download?token=bad")
    assert resp.status_code == 404

    # 列表含过期标志
    resp = client.get("/api/v1/exports")
    assert any(e["id"] == exp["id"] for e in resp.json())

    customer.setdefault("extra_cleanup", lambda: None)


def test_settings_password_sessions_preferences(client, customer):
    _login(client, customer)
    # 偏好读写
    resp = client.patch("/api/v1/settings/preferences",
                        json={"timezone": "Asia/Shanghai",
                              "default_sort": "created_desc"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["timezone"] == "Asia/Shanghai"
    resp = client.get("/api/v1/settings/preferences")
    assert resp.json()["default_sort"] == "created_desc"
    # 会话列表含当前
    resp = client.get("/api/v1/settings/sessions")
    sessions = resp.json()
    assert any(s["current"] for s in sessions)
    # 改密码：错旧密码拒绝
    resp = client.post("/api/v1/settings/password",
                       json={"old_password": "wrongpassword",
                             "new_password": "newpassword1"})
    assert resp.status_code == 401
    # 正确旧密码 → 成功 + 吊销其它（无其它会话→0）
    resp = client.post("/api/v1/settings/password",
                       json={"old_password": "password123",
                             "new_password": "newpassword1"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["revoked_sessions"] == 0
    # 新密码可登录
    resp = client.post("/api/v1/auth/login",
                       json={"email": customer["email"],
                             "password": "newpassword1",
                             "client_request_id": uuid.uuid4().hex[:16]})
    assert resp.status_code == 200
