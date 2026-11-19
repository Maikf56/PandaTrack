"""Worker 运行时集成验证（真实 A 库）：事实落库/事件指纹去重/outbox/任务结算。

覆盖 WorkerLoop 完整 tick：claim → 采集(mock provider) → 落库(事实+事件+
outbox 同事务) → ack/retry；FactStore 幂等性（事件指纹去重）。
"""
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

from worker.provider.contracts import (  # noqa: E402
    ProviderEvent, ProviderItem, ProviderResult,
)
from worker.provider.errors import ProviderError  # noqa: E402
from worker.runtime.loop import FactStore, WorkerLoop  # noqa: E402

DB_URL = os.environ.get("PT_DB_A_URL")
pytestmark = pytest.mark.skipif(
    not DB_URL, reason="未设 PT_DB_A_URL，跳过运行时集成测试")


class _FakeCircuit:
    def __init__(self):
        self.successes = 0
        self.failures = []

    def on_success(self):
        self.successes += 1

    def on_failure(self, ec):
        self.failures.append(ec)


def _ok_item(n: str, status: str = "in_transit", fp: str = "") -> ProviderItem:
    return ProviderItem.succeed(
        normalized_number=n, source="usps_web", status=status,
        raw_status="In-Transit",
        events=[ProviderEvent(
            event_fingerprint=fp or f"fp-{n}-{status}",
            occurred_at=None, status=status,
            description_raw="In-Transit", description_zh="运输中",
            location="Atlanta GA", event_code="", time_confidence="exact")],
        parser_version="v1", page_class="results", confidence=0.9)


@pytest.fixture
def tracked_job():
    """创建 tracking + pending fetch_job，结束清理全部关联行。"""
    tag = uuid.uuid4().hex[:12]
    number = f"94{tag}110200812345678"[:22]
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO tracking (normalized_number, carrier)
                   VALUES (%s, 'usps') RETURNING tracking_id""",
                (number,))
            tid = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO fetch_job (tracking_id, state, max_attempts)
                   VALUES (%s, 'pending', 3) RETURNING job_id""",
                (tid,))
            job_id = cur.fetchone()[0]
    ctx = {"tag": tag, "number": number, "tracking_id": tid, "job_id": job_id}
    yield ctx
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM a_outbox WHERE aggregate_id=%s", (tid,))
            cur.execute("DELETE FROM tracking_event WHERE tracking_id=%s", (tid,))
            cur.execute("DELETE FROM tracking_fact WHERE tracking_id=%s", (tid,))
            cur.execute("DELETE FROM fetch_job WHERE tracking_id=%s", (tid,))
            cur.execute("DELETE FROM tracking WHERE tracking_id=%s", (tid,))


class TestRuntimeTick:
    def test_success_tick_writes_facts_events_outbox(self, tracked_job):
        ctx = tracked_job
        circuit = _FakeCircuit()

        def fetch(ns):
            assert ns == [ctx["number"]]
            return ProviderResult(items=[_ok_item(ctx["number"])])

        loop = WorkerLoop(connect=lambda: psycopg.connect(DB_URL),
                          fetch=fetch, circuit=circuit,
                          worker_id=f"it-{ctx['tag']}")
        report = loop.tick()

        assert report.claimed == 1 and report.succeeded == 1
        assert report.facts.facts_written == 1
        assert report.facts.events_written == 1
        assert report.facts.outbox_written == 1
        assert circuit.successes == 1 and circuit.failures == []
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT state FROM fetch_job WHERE job_id=%s",
                            (ctx["job_id"],))
                assert cur.fetchone()[0] == "succeeded"
                cur.execute("""SELECT count(*) FROM tracking_fact
                               WHERE tracking_id=%s""", (ctx["tracking_id"],))
                assert cur.fetchone()[0] == 1
                cur.execute("""SELECT version, next_sync_at FROM tracking
                               WHERE tracking_id=%s""", (ctx["tracking_id"],))
                version, next_sync = cur.fetchone()
                assert version == 1 and next_sync is not None
                # in_transit 分层 → next_sync_at ≈ now+4h
                cur.execute("""SELECT count(*) FROM a_outbox
                               WHERE aggregate_id=%s
                                 AND aggregate_type='tracking'""",
                            (ctx["tracking_id"],))
                assert cur.fetchone()[0] == 1

    def test_event_fingerprint_dedup(self, tracked_job):
        """同一事件指纹重复采集 → 不重复落事件（05 幂等）。"""
        ctx = tracked_job
        fp = f"stable-{ctx['tag']}"

        def fetch(ns):
            return ProviderResult(items=[_ok_item(ctx["number"], fp=fp)])

        loop = WorkerLoop(connect=lambda: psycopg.connect(DB_URL),
                          fetch=fetch, circuit=_FakeCircuit(),
                          worker_id=f"it-{ctx['tag']}")
        loop.tick()
        # 第二轮：重建 pending job（模拟重新触发同一单号）
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO fetch_job (tracking_id, state, max_attempts)
                       VALUES (%s, 'pending', 3) RETURNING job_id""",
                    (ctx["tracking_id"],))
                job2 = cur.fetchone()[0]
        loop2 = WorkerLoop(connect=lambda: psycopg.connect(DB_URL),
                           fetch=fetch, circuit=_FakeCircuit(),
                           worker_id=f"it2-{ctx['tag']}")
        r2 = loop2.tick()
        assert r2.succeeded == 1
        assert r2.facts.events_written == 0  # 指纹去重
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT count(*) FROM tracking_event
                               WHERE tracking_id=%s""", (ctx["tracking_id"],))
                assert cur.fetchone()[0] == 1
                cur.execute("DELETE FROM a_outbox WHERE aggregate_id=%s "
                            "AND aggregate_version > 1", (ctx["tracking_id"],))
                cur.execute("DELETE FROM fetch_job WHERE job_id=%s", (job2,))

    def test_retryable_failure_schedules_backoff(self, tracked_job):
        ctx = tracked_job

        def fetch(ns):
            raise ProviderError("browser_crash", "浏览器崩溃")

        loop = WorkerLoop(connect=lambda: psycopg.connect(DB_URL),
                          fetch=fetch, circuit=_FakeCircuit(),
                          worker_id=f"it-{ctx['tag']}")
        report = loop.tick()
        assert report.retried == 1 and report.error_class == "browser_crash"
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT state, error_class, retry_at FROM fetch_job
                       WHERE job_id=%s""", (ctx["job_id"],))
                state, ec, retry_at = cur.fetchone()
                assert state == "retry_scheduled" and ec == "browser_crash"
                assert retry_at is not None

    def test_not_found_is_success_fact(self, tracked_job):
        ctx = tracked_job

        def fetch(ns):
            return ProviderResult(items=[_ok_item(ctx["number"],
                                                  status="not_found",
                                                  fp=f"nf-{ctx['tag']}")])

        loop = WorkerLoop(connect=lambda: psycopg.connect(DB_URL),
                          fetch=fetch, circuit=_FakeCircuit(),
                          worker_id=f"it-{ctx['tag']}")
        report = loop.tick()
        assert report.succeeded == 1
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT status FROM tracking_fact
                               WHERE tracking_id=%s""", (ctx["tracking_id"],))
                assert cur.fetchone()[0] == "not_found"
                cur.execute("SELECT next_sync_at FROM tracking "
                            "WHERE tracking_id=%s", (ctx["tracking_id"],))
                assert cur.fetchone()[0] is None  # 终态不刷新
                # 终态任务从 outbox 不投影刷新（但首轮事件仍入 outbox）
