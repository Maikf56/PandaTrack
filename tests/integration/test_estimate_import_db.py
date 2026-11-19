"""预估与导入端点集成验证（真实 B 库 + TestClient，04 §5.4/§5.9）：
- POST /submissions/estimate：分类计数 + 30 天免扣窗口 + 余额快照，只读不入账；
- POST /imports：大批量一次受理，import_job 落库关联 operation，幂等重放不重复建。
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
DB_A = os.environ.get("PT_DB_A_URL")
pytestmark = pytest.mark.skipif(
    not DB_B, reason="未设 PT_DB_B_URL，跳过预估/导入集成测试")

from _dbtest_cleanup import purge_a_numbers, purge_b_outbox_by_numbers  # noqa: E402

A = "9302010623396181820639"   # 与 test_submission_billing 同源样本
B = "9400150206217997979667"


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
        # worker 已常驻：先清 A 库与 billing_outbox，阻断真实代理采集。
        if DB_A:
            purge_a_numbers(DB_A, A, B)
            purge_b_outbox_by_numbers(DB_B, A, B)
        with psycopg.connect(DB_B) as conn:
            with conn.cursor() as cur:
                cid = ctx.get("customer_id")
                if cid is None:
                    return
                for sql in (
                    """DELETE FROM import_job WHERE customer_id=%s""",
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
                    """DELETE FROM billing_charge_window WHERE customer_id=%s""",
                    """DELETE FROM submission_operation WHERE customer_id=%s""",
                    "DELETE FROM target_group WHERE customer_id=%s",
                    "DELETE FROM idempotency_record WHERE customer_id=%s",
                    "DELETE FROM points_ledger WHERE customer_id=%s",
                    "DELETE FROM session WHERE customer_id=%s",
                    "DELETE FROM wallet WHERE customer_id=%s",
                    "DELETE FROM customer WHERE customer_id=%s",
                ):
                    cur.execute(sql, (cid,))

    try:
        email = f"est-{tag}@example.com"
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
        yield ctx
    except Exception:
        _cleanup()
        raise
    finally:
        _cleanup()


def _login(client, ctx) -> None:
    resp = client.post("/api/v1/auth/login",
                       json={"email": ctx["email"], "password": "password123",
                             "client_request_id": uuid.uuid4().hex[:16]})
    assert resp.status_code == 200, resp.text


def test_estimate_classification_window_and_readonly(client, customer):
    _login(client, customer)
    # 混合输入：2 有效 + 1 请求内重复 + 1 无效
    lines = [A, B, A, "not-a-number!!"]
    resp = client.post("/api/v1/submissions/estimate",
                       json={"lines": lines})
    assert resp.status_code == 200, resp.text
    est = resp.json()
    assert est["estimated"] is True
    assert est["total_count"] == 4
    assert est["billable_count"] == 2          # 去重后 2 个有效单号
    assert est["free_count"] == 0              # 无历史窗口
    assert est["points_estimate"] == 2
    assert est["balance"] == 500               # 服务端余额快照
    assert est["insufficient"] is False
    assert est["invalid_items"], "无效行应出现在失败清单"

    # 正式提交后同内容预估：30 天窗口命中 → free_count=2（submit 写窗口）
    rid = uuid.uuid4().hex[:16]
    resp = client.post("/api/v1/submissions",
                       json={"source": "paste", "client_request_id": rid,
                             "lines": [A, B]})
    assert resp.status_code == 202, resp.text
    assert resp.json()["points_charged"] == 2
    resp = client.post("/api/v1/submissions/estimate",
                       json={"lines": [A, B]})
    est2 = resp.json()
    assert est2["free_count"] == 2
    assert est2["points_estimate"] == 0
    assert est2["balance"] == 498

    # 只读性：estimate 不写任何 ledger/operation（余额已验证 498 不变）
    resp = client.post("/api/v1/submissions/estimate",
                       json={"lines": [A, B]})
    assert resp.json()["balance"] == 498


def test_import_create_counts_and_idempotent_replay(client, customer):
    _login(client, customer)
    # 40 行（>35 走导入路径）：38 有效 + 2 无效
    lines = [A, B] * 19 + ["bad-1", "bad-2"]
    rid = uuid.uuid4().hex[:16]
    resp = client.post("/api/v1/imports",
                       json={"file_name": "batch1.txt",
                             "client_request_id": rid, "lines": lines})
    assert resp.status_code == 202, resp.text
    acc = resp.json()
    assert acc["total_count"] == 40
    assert acc["valid_count"] == 38
    assert acc["invalid_count"] == 2
    assert acc["points_charged"] == 38
    operation_id = acc["operation_id"]
    import_job_id = acc["import_job_id"]

    with psycopg.connect(DB_B) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT status, total, done, success_count, failed_count,
                      duplicate_count, file_name, operation_id
               FROM import_job WHERE public_id=%s""", (import_job_id,))
        row = cur.fetchone()
        assert row is not None
        status, total, done, success, failed, dup, fname, opid = row
        assert status == "accepted" and total == 40 and done == 38
        assert success == 38 and failed == 2 and dup == 0
        assert fname == "batch1.txt"
        cur.execute("SELECT public_id FROM submission_operation WHERE operation_id=%s",
                    (opid,))
        assert str(cur.fetchone()[0]) == operation_id

    # 幂等重放：同键同内容 → 同 operation、同 import_job，不重复扣费
    resp = client.post("/api/v1/imports",
                       json={"file_name": "batch1.txt",
                             "client_request_id": rid, "lines": lines})
    assert resp.status_code == 202, resp.text
    replay = resp.json()
    assert replay["operation_id"] == operation_id
    assert replay["import_job_id"] == import_job_id
    assert replay["points_charged"] == 38

    with psycopg.connect(DB_B) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM import_job WHERE operation_id IN "
                    "(SELECT operation_id FROM submission_operation WHERE public_id=%s)",
                    (operation_id,))
        assert cur.fetchone()[0] == 1  # 只有一条 import_job
        cur.execute("SELECT balance FROM wallet WHERE customer_id=%s",
                    (customer["customer_id"],))
        assert cur.fetchone()[0] == 500 - 38  # 未二次扣费
