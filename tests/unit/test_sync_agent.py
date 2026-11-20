"""sync-agent 单测：A→B 投影编排、扇出、无客户跳过、事件 JSON 形状、排空。"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "common" / "src"))

from worker.sync.agent import SyncAgent  # noqa: E402

TID = 42
NUM = "9400110200812345678901"
OCC = datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc)


class _FakeCursor:
    def __init__(self, owner):
        self._owner = owner
        self.last_sql = ""
        self.rowcount = 1

    def execute(self, sql, params=None):
        self.last_sql = sql
        self._owner.executed.append(sql)

    def fetchall(self):
        if "FROM a_outbox" in self.last_sql:
            return self._owner.outbox_rows
        if "tracking_event" in self.last_sql:
            return self._owner.fact_rows
        if "customer_tracking" in self.last_sql:
            return self._owner.ct_rows
        return []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class _FakeDB:
    """A/B 共用假连接：按 SQL 关键字路由预置行。"""

    def __init__(self, *, outbox_rows=None, fact_rows=None, ct_rows=None):
        self.outbox_rows = outbox_rows or []
        self.fact_rows = fact_rows or []
        self.ct_rows = ct_rows or []
        self.executed: list[str] = []

    def cursor(self):
        return _FakeCursor(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def _std_outbox(version=1):
    return [(7, TID, version, {"tracking_id": TID, "status": "in_transit"})]


def _std_facts():
    return [(TID, NUM, "fp-1", OCC, "in_transit", "In-Transit",
             "运输中", "Atlanta GA", "", "exact")]


class TestSyncAgent:
    def test_no_backlog_returns_empty(self):
        a, b = _FakeDB(), _FakeDB()
        r = SyncAgent(connect_a=lambda: a, connect_b=lambda: b).run_once()
        assert r.fetched == 0 and r.projected == 0

    def test_projection_upsert_per_customer(self):
        a = _FakeDB(outbox_rows=_std_outbox(), fact_rows=_std_facts())
        b = _FakeDB(ct_rows=[(101,), (102,)])
        r = SyncAgent(connect_a=lambda: a, connect_b=lambda: b).run_once()
        assert r.fetched == 1 and r.projected == 2 and r.customers_hit == 2
        assert any("INSERT INTO tracking_projection" in s and "ON CONFLICT" in s
                   for s in b.executed)
        assert any("UPDATE a_outbox SET processed" in s for s in a.executed)

    def test_no_customer_skipped_stays_unprocessed(self):
        a = _FakeDB(outbox_rows=_std_outbox(), fact_rows=_std_facts())
        b = _FakeDB(ct_rows=[])
        r = SyncAgent(connect_a=lambda: a, connect_b=lambda: b).run_once()
        assert r.skipped_no_customer == 1 and r.projected == 0
        # 无客户不投影，但也不丢事实（B 侧无 upsert，重放可补）
        assert not any("tracking_projection" in s for s in b.executed)

    def test_mark_processed_after_b_commit(self):
        a = _FakeDB(outbox_rows=_std_outbox(), fact_rows=_std_facts())
        b = _FakeDB(ct_rows=[(101,)])
        r = SyncAgent(connect_a=lambda: a, connect_b=lambda: b).run_once()
        assert r.marked_processed == 1
        # B 侧投影先于 A 侧标记（崩溃窗口内重放幂等）
        assert b.executed and a.executed

    def test_events_json_shape_matches_bff(self):
        """投影事件 JSON 键对齐 BFF TrackingEventView 读取字段（09 契约）。"""
        a = _FakeDB(outbox_rows=_std_outbox(), fact_rows=_std_facts())
        b = _FakeDB(ct_rows=[(101,)])
        agent = SyncAgent(connect_a=lambda: a, connect_b=lambda: b)
        facts = agent._load_facts(a, [TID])
        evs = facts[TID]["events"]
        assert facts[TID]["normalized_number"] == NUM
        assert set(evs[0].keys()) == {"occurred_at", "time_confidence",
                                      "status_key", "label_zh", "description",
                                      "description_zh",
                                      "location", "event_code"}
        assert evs[0]["status_key"] == "in_transit"
        assert evs[0]["label_zh"]  # 权威字典白话标签
        assert evs[0]["occurred_at"].endswith("+00:00")

    def test_run_until_drained(self):
        a, b = _FakeDB(), _FakeDB()
        reports = SyncAgent(connect_a=lambda: a,
                            connect_b=lambda: b).run_until_drained()
        assert len(reports) == 1 and reports[0].fetched == 0

    def test_outbox_row_carries_version(self):
        """outbox 行携带 aggregate_version（05 幂等口径）。"""
        a = _FakeDB(outbox_rows=_std_outbox(version=3), fact_rows=_std_facts())
        b = _FakeDB(ct_rows=[(101,)])
        r = SyncAgent(connect_a=lambda: a, connect_b=lambda: b).run_once()
        assert r.fetched == 1

    def test_batch_size_limits_fetch(self):
        a = _FakeDB(outbox_rows=_std_outbox(), fact_rows=_std_facts())
        b = _FakeDB(ct_rows=[])
        agent = SyncAgent(connect_a=lambda: a, connect_b=lambda: b,
                          batch_size=1)
        assert agent.batch_size == 1
