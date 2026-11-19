"""计费规则验证（方案 06 §3.3/3.4/3.6）。"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))

from worker.billing import (  # noqa: E402
    PACKAGES, package_for_points, redeemed_points,
    WATERSHED_HOURS, is_waived, compute_charge,
)

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
A = "9302010623396181820639"
B = "9400150206217997979667"


class TestPackages:
    def test_six_tiers(self):
        assert len(PACKAGES) == 6
        assert [p.points for p in PACKAGES] == [3000, 5000, 10000, 30000, 50000, 100000]

    def test_total_matches_unit_times_points(self):
        for p in PACKAGES:
            assert abs(p.total_yuan - p.points * p.unit_price_yuan) < 0.01

    def test_over_limit_manual_quote(self):
        assert package_for_points(200_000) is None
        assert package_for_points(100_000) is not None

    def test_first_recharge_bonus(self):
        pkg = package_for_points(10_000)
        assert redeemed_points(pkg, first_recharge=True) == 11_000
        assert redeemed_points(pkg, first_recharge=False) == 10_000


class TestWaiver:
    def test_no_record_not_waived(self):
        assert not is_waived(None, NOW)

    def test_within_30d_waived(self):
        charged = NOW - timedelta(hours=WATERSHED_HOURS - 1)
        assert is_waived(charged, NOW)

    def test_beyond_30d_not_waived(self):
        charged = NOW - timedelta(hours=WATERSHED_HOURS + 1)
        assert not is_waived(charged, NOW)

    def test_boundary_exact_not_waived(self):
        charged = NOW - timedelta(hours=WATERSHED_HOURS)
        assert not is_waived(charged, NOW)

    def test_naive_datetime_treated_as_utc(self):
        charged = (NOW - timedelta(days=1)).replace(tzinfo=None)
        assert is_waived(charged, NOW)


class TestComputeCharge:
    def test_new_number_charges_one(self):
        d = compute_charge([A], recent_charged={}, now=NOW, balance=100)
        assert d.billable_count == 1
        assert d.sufficient
        assert d.would_be_balance == 99

    def test_waived_number_free(self):
        d = compute_charge([A], recent_charged={A: NOW - timedelta(days=2)},
                           now=NOW, balance=100)
        assert d.billable_count == 0
        assert d.waived_count == 1

    def test_duplicate_only_charged_once(self):
        d = compute_charge([A, A, A], recent_charged={}, now=NOW, balance=100)
        assert d.billable_count == 1
        assert d.duplicate_count == 2

    def test_invalid_not_charged(self):
        d = compute_charge([A, None, B], recent_charged={}, now=NOW, balance=100)
        assert d.billable_count == 2
        assert d.invalid_count == 1

    def test_insufficient_balance_whole_batch_fails(self):
        d = compute_charge([A, B], recent_charged={}, now=NOW, balance=1)
        assert d.billable_count == 2
        assert not d.sufficient
        assert d.would_be_balance == 1  # 余额不变（整批原子失败）

    def test_mixed_counts(self):
        recent = {A: NOW - timedelta(days=2)}
        d = compute_charge([A, A, B, None, B], recent_charged=recent,
                           now=NOW, balance=10)
        assert d.waived_count == 1
        assert d.duplicate_count == 2      # A 第二次 + B 第二次
        assert d.billable_count == 1       # 仅 B 首次
        assert d.invalid_count == 1
