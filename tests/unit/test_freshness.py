"""P3-d 验证：四分支判定与刷新预算(07 §3.7)。"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))

from worker.scheduler.freshness import (  # noqa: E402
    Fact, UpstreamState, Budget, Branch, decide, within_active_window,
)

NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)


def upstream(**kw):
    return UpstreamState(**kw)


class TestFourBranches:
    def test_branch1_missing_fact_creates_job(self):
        d = decide(Fact(exists=False), upstream(), now=NOW)
        assert d.branch == Branch.NEED_FETCH and d.create_job
        assert d.upstream_requests == 1
        assert d.keep_customer_relation  # 关键：抓取与否都要建客户关系

    def test_branch2_terminal_reused(self):
        for st in ("delivered", "not_found", "returned"):
            d = decide(Fact(exists=True, status=st), upstream(), now=NOW)
            assert d.branch == Branch.REUSE_TERMINAL, st
            assert not d.create_job and d.upstream_requests == 0
            assert d.keep_customer_relation

    def test_branch3_fresh_reused_zero_requests(self):
        fact = Fact(exists=True, status="in_transit",
                    next_sync_at=NOW + timedelta(hours=6))
        d = decide(fact, upstream(), now=NOW)
        assert d.branch == Branch.REUSE_FRESH and d.upstream_requests == 0
        assert not d.create_job

    def test_branch1_expired_creates_refresh(self):
        fact = Fact(exists=True, status="in_transit",
                    next_sync_at=NOW - timedelta(hours=1))
        d = decide(fact, upstream(), now=NOW, reason_code="refresh")
        assert d.branch == Branch.NEED_FETCH and d.create_job
        assert d.upstream_requests == 1

    def test_branch4_paused_defers(self):
        d = decide(Fact(exists=False), upstream(paused=True), now=NOW)
        assert d.branch == Branch.DEFER and not d.create_job
        assert d.upstream_requests == 0 and d.keep_customer_relation

    def test_branch4_circuit_open_defers(self):
        d = decide(Fact(exists=True, status="in_transit", next_sync_at=NOW - timedelta(hours=1)),
                   upstream(circuit_open=True), now=NOW, reason_code="refresh")
        assert d.branch == Branch.DEFER

    def test_branch4_quota_defers(self):
        d = decide(Fact(exists=False), upstream(quota_exhausted=True), now=NOW)
        assert d.branch == Branch.DEFER

    def test_branch4_takes_priority_over_terminal(self):
        # 即使事实已终态，上游熔断时也走 defer（保留任务，不惊扰用户）。
        d = decide(Fact(exists=True, status="delivered"), upstream(paused=True), now=NOW)
        assert d.branch == Branch.DEFER

    def test_no_next_sync_at_treats_as_expired(self):
        fact = Fact(exists=True, status="in_transit", next_sync_at=None)
        d = decide(fact, upstream(), now=NOW, reason_code="refresh")
        assert d.branch == Branch.NEED_FETCH


class TestRefreshBudget:
    def test_budget_allows_within_cap(self):
        b = Budget(date_key="2026-11-19", used=99, cap=100)
        assert b.allows("2026-11-19")   # 99 < 100
        b.used = 100
        assert not b.allows("2026-11-19")  # 达上限拒绝

    def test_budget_exhausted_defers(self):
        b = Budget(date_key="2026-11-19", used=100, cap=100)
        fact = Fact(exists=True, status="in_transit", next_sync_at=NOW - timedelta(hours=1))
        d = decide(fact, upstream(), now=NOW, reason_code="refresh",
                   budget=b, budget_date_key="2026-11-19")
        assert d.branch == Branch.DEFER and "预算" in d.reason

    def test_budget_resets_new_day(self):
        b = Budget(date_key="2026-11-18", used=999, cap=100)
        assert b.allows("2026-11-19")  # 新日期自动放行

    def test_budget_not_applied_to_initial(self):
        # 初始抓取不受每日刷新预算约束（预算只管后台刷新）。
        b = Budget(date_key="2026-11-19", used=999, cap=100)
        d = decide(Fact(exists=False), upstream(), now=NOW,
                   reason_code="initial", budget=b, budget_date_key="2026-11-19")
        assert d.branch == Branch.NEED_FETCH


class TestActiveWindow:
    def test_within_7_days(self):
        assert within_active_window(NOW - timedelta(days=6), now=NOW)
        assert not within_active_window(NOW - timedelta(days=8), now=NOW)
        assert not within_active_window(None, now=NOW)

    def test_custom_window(self):
        assert not within_active_window(NOW - timedelta(days=3), now=NOW, days=2)
