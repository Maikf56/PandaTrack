"""Worker 运行时验证：主循环编排（mock 协作者）+ 事实落库 SQL 行为（mock conn）。"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "common" / "src"))

import worker.runtime.loop as loop_mod  # noqa: E402
from worker.runtime.loop import FactStore, WorkerLoop  # noqa: E402
from worker.provider.contracts import (  # noqa: E402
    ProviderEvent, ProviderItem, ProviderResult,
)
from worker.provider.errors import ProviderError  # noqa: E402
from worker.scheduler.canary import CanarySpec  # noqa: E402

NOW = datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc)


def _ok_item(n: str, status: str = "in_transit") -> ProviderItem:
    return ProviderItem.succeed(
        normalized_number=n, source="usps_web", status=status,
        raw_status="In-Transit", events=[ProviderEvent(
            event_fingerprint=f"fp-{n}", occurred_at=NOW,
            status=status, description_raw="In-Transit", description_zh="运输中",
            location="Atlanta GA", event_code="", time_confidence="exact")],
        parser_version="v1", page_class="results", confidence=0.9,
        fetched_at=NOW)


def _fail_item(n: str, ec: str, batch: bool = False) -> ProviderItem:
    return ProviderItem.fail(n, ec, batch_level=batch, source="usps_web",
                             fetched_at=NOW)


class _FakeCircuit:
    def __init__(self):
        self.successes = 0
        self.failures = []

    def on_success(self):
        self.successes += 1

    def on_failure(self, ec):
        self.failures.append(ec)


def _mock_lease(monkeypatch, jobs_by_claim):
    """mock JobLease：claim 返回队列，其余记录调用。"""
    lease = MagicMock()
    lease.reclaim_expired.return_value = 0
    lease.claim.side_effect = lambda *a, **kw: jobs_by_claim.pop(0)
    factory = MagicMock(return_value=lease)
    monkeypatch.setattr(loop_mod, "JobLease", factory)
    return lease


def _mock_store(monkeypatch, number_by_tid=None, facts=loop_mod.WriteStats()):
    store = MagicMock()
    store.numbers_for.return_value = number_by_tid or {}
    store.write_facts.return_value = facts
    factory = MagicMock(return_value=store)
    monkeypatch.setattr(loop_mod, "FactStore", factory)
    return store


@contextmanager
def _fake_conn():
    yield MagicMock()


def _loop(fetch, circuit, monkeypatch, jobs, tids_numbers, **kw):
    lease = _mock_lease(monkeypatch, jobs)
    store = _mock_store(monkeypatch, tids_numbers)
    lp = WorkerLoop(connect=_fake_conn, fetch=fetch, circuit=circuit,
                    **kw)
    return lp, lease, store


class TestLoopOrchestration:
    def test_no_jobs_returns_empty_report(self, monkeypatch):
        _mock_lease(monkeypatch, [[]])
        lp = WorkerLoop(connect=_fake_conn, fetch=lambda ns: None,
                        circuit=_FakeCircuit())
        r = lp.tick()
        assert r.claimed == 0 and not r.canary_halt

    def test_success_and_retry_settlement(self, monkeypatch):
        job = {"job_id": 1, "tracking_id": 10, "attempt": 1, "max_attempts": 3}
        _mock_lease(monkeypatch, [[job]])
        _mock_store(monkeypatch, {10: "9400110200812345678901"})
        circ = _FakeCircuit()

        def fetch(ns):
            return ProviderResult(items=[_ok_item("9400110200812345678901")])

        lp, lease, store = _loop(fetch, circ, monkeypatch, [[job]], {10: "9400110200812345678901"})
        r = lp.tick()
        assert r.succeeded == 1
        lease.ack.assert_called_once_with(1)
        assert circ.successes == 1 and circ.failures == []
        store.write_facts.assert_called_once()

    def test_retryable_failure_goes_to_retry_with_backoff(self, monkeypatch):
        job = {"job_id": 2, "tracking_id": 10, "attempt": 1, "max_attempts": 3}
        _mock_lease(monkeypatch, [[job]])
        circ = _FakeCircuit()

        def fetch(ns):
            return ProviderResult(items=[_fail_item("9400110200812345678901",
                                                    "browser_crash")])

        lp, lease, _ = _loop(fetch, circ, monkeypatch, [[job]],
                             {10: "9400110200812345678901"})
        r = lp.tick()
        assert r.retried == 1 and r.facts.facts_written == 0
        lease.retry.assert_called_once()
        assert lease.retry.call_args.kwargs.get("retry_at") is not None
        assert circ.failures == ["browser_crash"]

    def test_max_attempts_reached_dead_letters(self, monkeypatch):
        job = {"job_id": 3, "tracking_id": 10, "attempt": 3, "max_attempts": 3}
        _mock_lease(monkeypatch, [[job]])
        circ = _FakeCircuit()

        def fetch(ns):
            return ProviderResult(items=[_fail_item("9400110200812345678901",
                                                    "browser_crash")])

        lp, lease, _ = _loop(fetch, circ, monkeypatch, [[job]],
                             {10: "9400110200812345678901"})
        r = lp.tick()
        assert r.dead_lettered == 1
        lease.dead_letter.assert_called_once_with(3, "browser_crash")

    def test_circuit_open_exception_no_self_feedback(self, monkeypatch):
        """circuit_open 拒绝不计失败（07 §3.4），任务回炉探路。"""
        job = {"job_id": 4, "tracking_id": 10, "attempt": 3, "max_attempts": 3}
        _mock_lease(monkeypatch, [[job]])
        circ = _FakeCircuit()

        def fetch(ns):
            raise ProviderError("circuit_open", "熔断中")

        lp, lease, _ = _loop(fetch, circ, monkeypatch, [[job]],
                             {10: "9400110200812345678901"})
        r = lp.tick()
        assert r.retried == 1 and r.error_class == "circuit_open"
        assert circ.failures == []  # 自反馈不计
        # attempt=3 >= max，但 circuit_open 特例仍回炉探路
        lease.retry.assert_called_once()

    def test_not_found_counts_as_success(self, monkeypatch):
        """not_found 是有效事实 → ack 成功（02 §5.1）。"""
        job = {"job_id": 5, "tracking_id": 10, "attempt": 1, "max_attempts": 3}
        _mock_lease(monkeypatch, [[job]])
        circ = _FakeCircuit()

        def fetch(ns):
            return ProviderResult(items=[_ok_item("9400110200812345678901",
                                                  status="not_found")])

        lp, lease, store = _loop(fetch, circ, monkeypatch, [[job]],
                                 {10: "9400110200812345678901"})
        r = lp.tick()
        assert r.succeeded == 1
        lease.ack.assert_called_once_with(5)
        store.write_facts.assert_called_once()  # not_found 也落事实

    def test_canary_mismatch_halts_before_fetch(self, monkeypatch):
        job = {"job_id": 6, "tracking_id": 10, "attempt": 1, "max_attempts": 3}
        _mock_lease(monkeypatch, [[job]])
        store = _mock_store(monkeypatch, {10: "9400110200812345678901"})
        circ = _FakeCircuit()
        fetch_calls = []

        def fetch(ns):
            fetch_calls.append(ns)
            raise AssertionError("金丝雀拦截后不应采集")

        def canary_fetch(ns):
            return {"9400110200899999999999": "in_transit"}  # 预期 delivered

        lp = WorkerLoop(connect=_fake_conn, fetch=fetch, circuit=circ,
                        canary_fetch=canary_fetch,
                        canary_specs=[CanarySpec("9400110200899999999999",
                                                 "delivered")])
        r = lp.tick()
        assert r.canary_halt and len(r.canary_mismatches) == 1
        assert fetch_calls == [] and store.write_facts.call_count == 0

    def test_canary_pass_proceeds(self, monkeypatch):
        job = {"job_id": 7, "tracking_id": 10, "attempt": 1, "max_attempts": 3}
        _mock_lease(monkeypatch, [[job]])
        _mock_store(monkeypatch, {10: "9400110200812345678901"})
        circ = _FakeCircuit()

        def fetch(ns):
            return ProviderResult(items=[_ok_item("9400110200812345678901")])

        def canary_fetch(ns):
            return {"9400110200899999999999": "delivered"}

        lp = WorkerLoop(connect=_fake_conn, fetch=fetch, circuit=circ,
                        canary_fetch=canary_fetch,
                        canary_specs=[CanarySpec("9400110200899999999999",
                                                 "delivered")])
        r = lp.tick()
        assert not r.canary_halt and r.succeeded == 1

    def test_missing_tracking_dead_letters(self, monkeypatch):
        job = {"job_id": 8, "tracking_id": 99, "attempt": 1, "max_attempts": 3}
        _mock_lease(monkeypatch, [[job]])
        _mock_store(monkeypatch, {})  # tracking 不存在
        circ = _FakeCircuit()
        fetch_calls = []

        def fetch(ns):
            fetch_calls.append(ns)
            return ProviderResult(items=[])

        lp, lease, _ = _loop(fetch, circ, monkeypatch, [[job]], {})
        lp.tick()
        lease.dead_letter.assert_called_once_with(8, "tracking_missing")
        assert fetch_calls == []


class TestFactStoreSql:
    def _mock_conn(self, fetchone_seq, rowcounts=None):
        cur = MagicMock()
        cur.fetchone.side_effect = fetchone_seq
        cur.rowcount = 1
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        return conn, cur

    def test_write_success_item_sql_chain(self):
        conn, cur = self._mock_conn([(42, 3)])
        item = _ok_item("9400110200812345678901")
        stats = FactStore(conn).write_facts([item], now=NOW)
        assert stats.facts_written == 1 and stats.events_written == 1
        assert stats.outbox_written == 1
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        assert any("INSERT INTO tracking" in s for s in sqls)
        assert any("INSERT INTO tracking_fact" in s for s in sqls)
        assert any("INSERT INTO tracking_event" in s for s in sqls)
        assert any("INSERT INTO a_outbox" in s for s in sqls)
        # next_sync_at 分层：in_transit → +4h
        upd = [c for c in cur.execute.call_args_list
               if "UPDATE tracking" in c.args[0]][0]
        assert upd.args[1][2] == NOW + __import__("datetime").timedelta(hours=4)

    def test_event_dedup_on_conflict(self):
        conn, cur = self._mock_conn([(42, 3)])
        cur.rowcount = 0  # 指纹冲突 DO NOTHING
        stats = FactStore(conn).write_facts([_ok_item("9400110200812345678901")])
        assert stats.events_written == 0

    def test_failed_items_skipped(self):
        conn, cur = self._mock_conn([])
        stats = FactStore(conn).write_facts(
            [_fail_item("9400110200812345678901", "browser_crash")])
        assert stats.facts_written == 0 and cur.execute.call_count == 0

    def test_simulated_item_rejected(self):
        conn, cur = self._mock_conn([])
        item = _ok_item("9400110200812345678901")
        item.simulated = True
        with pytest.raises(ProviderError):
            FactStore(conn).write_facts([item])
        assert cur.execute.call_count == 0

    def test_outbox_payload_digest_stable(self):
        from worker.runtime.loop import _payload_digest
        p = {"a": 1, "b": "x"}
        assert _payload_digest(p) == _payload_digest({"b": "x", "a": 1})
        assert _payload_digest(p) != _payload_digest({"a": 2, "b": "x"})
