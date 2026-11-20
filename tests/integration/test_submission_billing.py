"""提交计费事务集成测试（B 库真实 PG，方案 06 §3.4）。

需环境变量 PT_DB_B_URL；未配置则 skip（本机纯逻辑单测不依赖 DB）。
覆盖：原子扣费、幂等重放/冲突、余额不足整批失败、30 天免扣窗口、防双扣。
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))

DB_URL = os.environ.get("PT_DB_B_URL")
DB_A_URL = os.environ.get("PT_DB_A_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="未设 PT_DB_B_URL，跳过 DB 集成测试")

from _dbtest_cleanup import purge_a_numbers, purge_b_outbox_by_numbers  # noqa: E402

psycopg = pytest.importorskip("psycopg", reason="未安装 psycopg3，跳过 DB 集成测试")

from worker.billing import (  # noqa: E402
    submit, request_fingerprint, IdempotencyConflict, InsufficientBalance,
)

A = "9302010623396181820639"
B = "9400150206217997979667"
C = "9202090134607473901665"


def _cleanup(cid: int) -> None:
    """按外键从表到主表清理测试客户（charge_reservation/outbox 无 customer_id）。"""
    # worker 已常驻：先清 A 库与 billing_outbox，阻断真实代理采集。
    if DB_A_URL:
        purge_a_numbers(DB_A_URL, A, B, C)
        purge_b_outbox_by_numbers(DB_URL, A, B, C)
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM charge_reservation WHERE operation_id IN "
                "(SELECT operation_id FROM submission_operation WHERE customer_id=%s)", (cid,))
            cur.execute(
                "DELETE FROM billing_outbox WHERE aggregate_id IN "
                "(SELECT operation_id FROM submission_operation WHERE customer_id=%s)", (cid,))
            # 明细表先删（submit 现在会写 batch/item/customer_tracking，P14 断链修复）
            cur.execute(
                "DELETE FROM submission_item WHERE batch_id IN "
                "(SELECT batch_id FROM submission_batch WHERE operation_id IN "
                "(SELECT operation_id FROM submission_operation WHERE customer_id=%s))", (cid,))
            cur.execute(
                "DELETE FROM submission_batch WHERE operation_id IN "
                "(SELECT operation_id FROM submission_operation WHERE customer_id=%s)", (cid,))
            cur.execute(
                "DELETE FROM customer_tracking WHERE customer_id=%s", (cid,))
            for table in ("points_ledger", "billing_charge_window", "submission_operation",
                          "idempotency_record", "wallet"):
                cur.execute(f"DELETE FROM {table} WHERE customer_id=%s", (cid,))
            cur.execute("DELETE FROM customer WHERE customer_id=%s", (cid,))
            conn.commit()


def _make_customer(balance: int = 100) -> int:
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            email = f"test-{uuid.uuid4().hex[:12]}@example.com"
            cur.execute(
                "INSERT INTO customer (email, password_hash) VALUES (%s,'x') "
                "RETURNING customer_id", (email,),
            )
            cid = cur.fetchone()[0]
            cur.execute("INSERT INTO wallet (customer_id, balance) VALUES (%s,%s)", (cid, balance))
            conn.commit()
    return cid


@pytest.fixture
def customer():
    cid = _make_customer(100)
    yield cid
    _cleanup(cid)


class TestAtomicCharge:
    def test_charges_and_wallet_deducted(self, customer):
        with psycopg.connect(DB_URL) as conn:
            fp = request_fingerprint({"numbers": [A, B]})
            out = submit(conn, customer_id=customer, client_request_id="req-atomic-001",
                         fingerprint=fp, normalized_numbers=[A, B])
            conn.commit()
        assert out.billable_count == 2
        assert out.balance == 98
        assert not out.replayed
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT balance FROM wallet WHERE customer_id=%s", (customer,))
                assert cur.fetchone()[0] == 98
                cur.execute(
                    "SELECT points_change FROM points_ledger WHERE customer_id=%s "
                    "AND ledger_type='charge'", (customer,))
                assert cur.fetchone()[0] == -2

    def test_creates_tracking_and_batch_items(self, customer):
        """P14 断链修复：受理同事务建立 customer_tracking + 批次明细。

        投影扇出（sync-agent）按 customer_tracking 找客户，批次页按
        submission_batch/item 出进度——缺失则采集成功客户也看不到结果。
        """
        nums = [A, B]
        with psycopg.connect(DB_URL) as conn:
            fp = request_fingerprint({"numbers": nums})
            out = submit(conn, customer_id=customer, client_request_id="req-links-001",
                         fingerprint=fp, normalized_numbers=nums)
            conn.commit()
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                # 客户跟踪关系：两行，幂等不重复
                cur.execute(
                    "SELECT count(*) FROM customer_tracking WHERE customer_id=%s",
                    (customer,))
                assert cur.fetchone()[0] == 2
                # 批次：2 条 < 35 → 单批，item_count=2
                cur.execute(
                    """SELECT sb.batch_seq, sb.item_count, sb.state
                       FROM submission_batch sb
                       JOIN submission_operation so ON so.operation_id=sb.operation_id
                       WHERE so.public_id=%s ORDER BY sb.batch_seq""",
                    (out.operation_public_id,))
                rows = cur.fetchall()
                assert rows == [(1, 2, "accepted")]
                # 明细：两行，normalized_number 齐全
                cur.execute(
                    """SELECT si.item_seq, si.normalized_number, si.is_valid
                       FROM submission_item si
                       JOIN submission_batch sb ON sb.batch_id=si.batch_id
                       JOIN submission_operation so ON so.operation_id=sb.operation_id
                       WHERE so.public_id=%s ORDER BY si.item_seq""",
                    (out.operation_public_id,))
                items = cur.fetchall()
                assert [n for _, n, _ in items] == nums
                assert all(v for _, _, v in items)

    def test_insufficient_whole_batch_fails(self):
        cid = _make_customer(1)  # 余额 1，需扣 3 → 整批失败
        try:
            with psycopg.connect(DB_URL) as conn:
                fp = request_fingerprint({"numbers": [A, B, C]})
                with pytest.raises(InsufficientBalance):
                    submit(conn, customer_id=cid, client_request_id="req-poor-001",
                           fingerprint=fp, normalized_numbers=[A, B, C])
                conn.rollback()
            with psycopg.connect(DB_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT balance FROM wallet WHERE customer_id=%s", (cid,))
                    assert cur.fetchone()[0] == 1  # 余额未变
                    cur.execute(
                        "SELECT COUNT(*) FROM submission_operation WHERE customer_id=%s", (cid,))
                    assert cur.fetchone()[0] == 0  # 未建 operation
        finally:
            _cleanup(cid)


class TestIdempotency:
    def test_replay_no_double_charge(self, customer):
        fp = request_fingerprint({"numbers": [A]})
        with psycopg.connect(DB_URL) as conn:
            out1 = submit(conn, customer_id=customer, client_request_id="req-idem-001",
                          fingerprint=fp, normalized_numbers=[A])
            conn.commit()
        with psycopg.connect(DB_URL) as conn:
            out2 = submit(conn, customer_id=customer, client_request_id="req-idem-001",
                          fingerprint=fp, normalized_numbers=[A])
            conn.commit()
        assert not out1.replayed and out2.replayed
        assert out1.operation_public_id == out2.operation_public_id
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT balance FROM wallet WHERE customer_id=%s", (customer,))
                assert cur.fetchone()[0] == 99  # 只扣一次

    def test_same_key_different_content_conflict(self, customer):
        fp1 = request_fingerprint({"numbers": [A]})
        fp2 = request_fingerprint({"numbers": [B]})
        with psycopg.connect(DB_URL) as conn:
            submit(conn, customer_id=customer, client_request_id="req-idem-002",
                   fingerprint=fp1, normalized_numbers=[A])
            conn.commit()
        with psycopg.connect(DB_URL) as conn:
            with pytest.raises(IdempotencyConflict):
                submit(conn, customer_id=customer, client_request_id="req-idem-002",
                       fingerprint=fp2, normalized_numbers=[B])
            conn.rollback()


class TestWaiverWindow:
    def test_second_submit_within_window_free(self, customer):
        with psycopg.connect(DB_URL) as conn:
            out1 = submit(conn, customer_id=customer, client_request_id="req-win-001",
                          fingerprint=request_fingerprint({"numbers": [A]}),
                          normalized_numbers=[A])
            conn.commit()
        with psycopg.connect(DB_URL) as conn:
            out2 = submit(conn, customer_id=customer, client_request_id="req-win-002",
                          fingerprint=request_fingerprint({"numbers": [A]}),
                          normalized_numbers=[A])
            conn.commit()
        assert out1.billable_count == 1
        assert out2.billable_count == 0
        assert out2.waived_count == 1
        assert out2.balance == 99

    def test_other_customer_same_number_still_charged(self, customer):
        # 同单号不同客户：照扣（06 §3.6：其他客户已抓过仍扣费）
        cid2 = _make_customer(100)
        try:
            with psycopg.connect(DB_URL) as conn:
                submit(conn, customer_id=customer, client_request_id="req-c1-001",
                       fingerprint=request_fingerprint({"n": [A]}), normalized_numbers=[A])
                conn.commit()
            with psycopg.connect(DB_URL) as conn:
                out = submit(conn, customer_id=cid2, client_request_id="req-c2-001",
                             fingerprint=request_fingerprint({"n": [A]}), normalized_numbers=[A])
                conn.commit()
            assert out.billable_count == 1
        finally:
            _cleanup(cid2)
