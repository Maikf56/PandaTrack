"""P3-b 验证：FetchJob 租约与状态机（07 §3.1，真实 A 库 PG）。"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))

pytest.importorskip("psycopg")
import psycopg  # noqa: E402

from worker.scheduler.lease import JobLease, TERMINAL_STATES  # noqa: E402

DB_URL = os.environ.get("PT_DB_A_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="未设 PT_DB_A_URL，跳过 A 库租约集成测试")


@pytest.fixture
def jobs():
    """每个测试创建独立 tracking + 若干 job，结束清理。"""
    created: list[int] = []
    tids: list[int] = []
    tag = uuid.uuid4().hex[:10]
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            for i in range(6):
                cur.execute(
                    """INSERT INTO tracking (normalized_number, carrier)
                       VALUES (%s,'usps') RETURNING tracking_id""",
                    (f"LEASE{tag}{i}",),
                )
                tid = cur.fetchone()[0]
                tids.append(tid)
                cur.execute(
                    """INSERT INTO fetch_job (tracking_id, state)
                       VALUES (%s,'pending') RETURNING job_id""",
                    (tid,),
                )
                created.append(cur.fetchone()[0])
            conn.commit()
    yield created
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            # 先删依赖 job 的表（若有），再删 job、tracking。
            cur.execute("DELETE FROM fetch_attempt_log WHERE job_id = ANY(%s)", (created,))
            cur.execute("DELETE FROM fetch_job WHERE job_id = ANY(%s)", (created,))
            cur.execute("DELETE FROM tracking WHERE tracking_id = ANY(%s)", (tids,))
            conn.commit()


class TestClaim:
    def test_claim_sets_lease_and_increments_attempt(self, jobs):
        with psycopg.connect(DB_URL) as conn:
            lease = JobLease(conn, lease_seconds=60)
            got = lease.claim("worker-A", limit=2)
            assert len(got) == 2
            assert all(g["attempt"] == 1 for g in got)
            j = lease.get(got[0]["job_id"])
            assert j["state"] == "claimed" and j["worker_id"] == "worker-A"
            assert j["lease_until"] is not None
            conn.commit()

    def test_claim_skip_locked_no_double_claim(self, jobs):
        # 两个连接并发领取，不能重复领到同一任务。
        with psycopg.connect(DB_URL) as c1, psycopg.connect(DB_URL) as c2:
            a = JobLease(c1).claim("w1", limit=3)
            b = JobLease(c2).claim("w2", limit=3)
            c1.commit(); c2.commit()
            ids_a = {g["job_id"] for g in a}
            ids_b = {g["job_id"] for g in b}
            assert not (ids_a & ids_b)
            assert len(ids_a | ids_b) == 6

    def test_claim_honors_retry_at_future(self, jobs, ):
        with psycopg.connect(DB_URL) as conn:
            lease = JobLease(conn)
            jid = jobs[0]
            lease.retry(jid, "upstream_5xx",
                        retry_at=__import__("datetime").datetime.now(
                            __import__("datetime").timezone.utc) + timedelta(hours=1))
            conn.commit()
            got = lease.claim("w1", limit=10)
            assert jid not in [g["job_id"] for g in got]  # 未来 retry_at 不可领


class TestTransitions:
    def test_ack_terminal(self, jobs):
        with psycopg.connect(DB_URL) as conn:
            lease = JobLease(conn)
            jid = lease.claim("w1")[0]["job_id"]
            lease.ack(jid)
            conn.commit()
            j = lease.get(jid)
            assert j["state"] == "succeeded" and j["finished_at"] is not None
            assert j["lease_until"] is None and j["worker_id"] is None

    def test_retry_scheduled_then_claimable(self, jobs):
        with psycopg.connect(DB_URL) as conn:
            lease = JobLease(conn)
            jid = lease.claim("w1")[0]["job_id"]
            lease.retry(jid, "challenge", retry_at=None)
            conn.commit()
            j = lease.get(jid)
            assert j["state"] == "retry_scheduled" and j["error_class"] == "challenge"
            assert j["lease_until"] is None
            got = lease.claim("w2", limit=10)
            assert jid in [g["job_id"] for g in got]  # retry_at 已到期可再领

    def test_dead_letter_terminal(self, jobs):
        with psycopg.connect(DB_URL) as conn:
            lease = JobLease(conn)
            jid = lease.claim("w1")[0]["job_id"]
            lease.dead_letter(jid, "rejected")
            conn.commit()
            j = lease.get(jid)
            assert j["state"] == "dead_letter" and j["finished_at"] is not None
            assert j["state"] in TERMINAL_STATES

    def test_attempt_increments_across_retry(self, jobs):
        with psycopg.connect(DB_URL) as conn:
            lease = JobLease(conn)
            jid = jobs[0]
            for expected in (1, 2, 3):
                got = lease.claim("w1", limit=10)
                assert jid in [g["job_id"] for g in got]
                assert lease.get(jid)["attempt"] == expected
                lease.retry(jid, "network_timeout", retry_at=None)
                conn.commit()


class TestReclaim:
    def test_reclaim_expired_lease(self, jobs):
        with psycopg.connect(DB_URL) as conn:
            lease = JobLease(conn, lease_seconds=0)
            jid = lease.claim("w1")[0]["job_id"]  # lease_until = now
            conn.commit()
        import time
        time.sleep(0.1)
        with psycopg.connect(DB_URL) as conn:
            lease = JobLease(conn)
            n = lease.reclaim_expired()
            conn.commit()
            assert n >= 1
            j = lease.get(jid)
            assert j["state"] == "pending" and j["lease_until"] is None

    def test_reclaim_does_not_touch_valid_lease(self, jobs):
        with psycopg.connect(DB_URL) as conn:
            # 清理本 worker id 的历史残留（此前运行 claim 未释放会形成
            # 僵尸租约，污染全库计数断言；w1 为测试专用 id）。
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE fetch_job SET state='succeeded', worker_id=NULL,
                             lease_until=NULL, finished_at=now()
                       WHERE worker_id='w1'
                         AND state NOT IN ('succeeded', 'dead_letter')""")
            conn.commit()
            lease = JobLease(conn, lease_seconds=3600)
            claimed = lease.claim("w1", limit=2)
            jids = [c["job_id"] for c in claimed]
            conn.commit()
        with psycopg.connect(DB_URL) as conn:
            n = JobLease(conn).reclaim_expired()
            conn.commit()
            # 其他测试可能留下过期租约，这里只要求未误伤本测试的活跃任务。
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT count(*) FROM fetch_job
                       WHERE job_id = ANY(%s)
                         AND worker_id='w1' AND lease_until>now()""",
                    (jids,))
                assert cur.fetchone()[0] == 2


class TestSingleFlight:
    def test_second_active_job_rejected_for_same_tracking(self, jobs):
        tag = uuid.uuid4().hex[:8]
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO tracking (normalized_number,carrier) VALUES (%s,'usps') RETURNING tracking_id",
                    (f"SF{tag}",),
                )
                tid = cur.fetchone()[0]
                cur.execute("INSERT INTO fetch_job (tracking_id,state) VALUES (%s,'pending')", (tid,))
                conn.commit()
                # 再插一个活跃态 job 应违反 partial unique index。
                with pytest.raises(psycopg.errors.UniqueViolation):
                    with conn.cursor() as cur2:
                        cur2.execute("INSERT INTO fetch_job (tracking_id,state) VALUES (%s,'claimed')", (tid,))
                    conn.commit()
                conn.rollback()
                # 终态不占唯一约束，可再插。
                cur.execute("UPDATE fetch_job SET state='succeeded' WHERE tracking_id=%s", (tid,))
                cur.execute("INSERT INTO fetch_job (tracking_id,state) VALUES (%s,'pending')", (tid,))
                conn.commit()
                cur.execute("DELETE FROM fetch_job WHERE tracking_id=%s", (tid,))
                cur.execute("DELETE FROM tracking WHERE tracking_id=%s", (tid,))
                conn.commit()
