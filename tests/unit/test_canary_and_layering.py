"""金丝雀监控 / 未映射文本统计 / 分层刷新节奏 / 跟踪参数可配置化 的纯逻辑验证。

来源：吸收《USPS轨迹爬虫技术方案分析》对比结论的四个增强项。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "common" / "src"))

from worker.scheduler.canary import CanarySpec, evaluate, load_specs  # noqa: E402
from worker.scheduler.freshness import next_sync_for  # noqa: E402
from worker.provider.usps_web.parser import (  # noqa: E402
    UnmappedStatusStats, parse_html,
)
from worker.provider.usps_claw import track_url, _track_param  # noqa: E402

TN = "9400110200812345678901"


class TestCanary:
    def test_all_pass(self):
        specs = [CanarySpec(TN, "delivered")]
        assert evaluate({TN: "delivered"}, specs) == []

    def test_missing_number_is_mismatch(self):
        ms = evaluate({}, [CanarySpec(TN, "delivered")])
        assert len(ms) == 1 and ms[0].reason == "missing"

    def test_status_mismatch(self):
        ms = evaluate({TN: "in_transit"}, [CanarySpec(TN, "delivered")])
        assert ms[0].reason == "status_mismatch"
        assert ms[0].actual == "in_transit" and ms[0].expected == "delivered"

    def test_extra_results_do_not_fail(self):
        specs = [CanarySpec(TN, "delivered")]
        assert evaluate({TN: "delivered", "9400110200899999999999": "other"},
                        specs) == []

    def test_load_specs_valid(self, monkeypatch):
        monkeypatch.setenv("PT_CANARY_SPEC",
                           json.dumps([{"number": TN, "expected": "delivered"}]))
        specs = load_specs()
        assert specs == [CanarySpec(TN, "delivered")]

    def test_load_specs_broken_json_returns_empty(self, monkeypatch):
        monkeypatch.setenv("PT_CANARY_SPEC", "{not json")
        assert load_specs() == []

    def test_load_specs_empty_env(self, monkeypatch):
        monkeypatch.delenv("PT_CANARY_SPEC", raising=False)
        assert load_specs() == []

    def test_load_specs_filters_invalid_items(self, monkeypatch):
        monkeypatch.setenv("PT_CANARY_SPEC", json.dumps(
            [{"number": "", "expected": "delivered"},
             {"number": TN},
             "junk",
             {"number": TN, "expected": "in_transit"}]))
        assert load_specs() == [CanarySpec(TN, "in_transit")]


class TestUnmappedStatusStats:
    def test_record_top_total(self):
        s = UnmappedStatusStats()
        s.record("Arrived at USPS Regional Facility")
        s.record("Arrived at USPS Regional Facility")
        s.record("Delivered to Locker")
        assert s.total() == 3
        top = s.top(1)
        assert top[0][0] == "Arrived at USPS Regional Facility" and top[0][1] == 2

    def test_blank_ignored(self):
        s = UnmappedStatusStats()
        s.record("   ")
        assert s.total() == 0

    def _block_html(self, detail: str) -> str:
        return (
            '<div class="product_summary">'
            f'<span class="tracking-number">{TN}</span>'
            '<p class="banner-content statusSummaryText">In-Transit</p>'
            '<div class="update-banner-wrapper banner-2"></div>'
            '<div class="tb-step current-step">'
            f'<p class="tb-status-detail">{detail}</p>'
            '<p class="tb-location">Atlanta GA</p>'
            '<p class="tb-date"> November 10, 2026 11:06 AM </p>'
            '</div></div>'
        )

    def test_parse_html_records_unmapped(self):
        stats = UnmappedStatusStats()
        results = parse_html(self._block_html("Totally New Event Wording XYZ"),
                             stats)
        assert len(results) == 1
        assert results[0].current_status_key == "other"
        assert stats.total() == 1
        assert stats.top(1)[0][0] == "Totally New Event Wording XYZ"

    def test_parse_html_mapped_text_not_recorded(self):
        stats = UnmappedStatusStats()
        parse_html(self._block_html("Delivered"), stats)
        assert stats.total() == 0

    def test_parse_html_without_stats_still_works(self):
        results = parse_html(self._block_html("Totally New Event Wording XYZ"))
        assert results[0].current_status_key == "other"


class TestNextSyncLayering:
    NOW = datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc)

    def test_out_for_delivery_30min(self):
        nxt = next_sync_for("out_for_delivery", self.NOW)
        assert nxt == self.NOW + timedelta(minutes=30)

    def test_in_transit_4h(self):
        assert next_sync_for("in_transit", self.NOW) == \
            self.NOW + timedelta(hours=4)

    def test_non_terminal_default_24h(self):
        assert next_sync_for("accepted", self.NOW) == \
            self.NOW + timedelta(hours=24)
        assert next_sync_for("other", self.NOW) == \
            self.NOW + timedelta(hours=24)

    def test_terminal_never_refreshes(self):
        assert next_sync_for("delivered", self.NOW) is None
        assert next_sync_for("not_found", self.NOW) is None


class TestTrackParamConfig:
    def test_default_tlabels(self, monkeypatch):
        monkeypatch.delenv("PT_USPS_TRACK_PARAM", raising=False)
        assert _track_param() == "tLabels"
        assert track_url([TN]) == \
            f"https://tools.usps.com/go/TrackConfirmAction?tLabels={TN}"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("PT_USPS_TRACK_PARAM", "qtc_tLabels1")
        assert _track_param() == "qtc_tLabels1"
        assert "qtc_tLabels1=" in track_url([TN])

    def test_multiple_numbers_comma_joined(self):
        assert track_url(["9400110200811111111111", TN]).endswith(
            "9400110200811111111111," + TN)

    def test_blank_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("PT_USPS_TRACK_PARAM", "  ")
        assert _track_param() == "tLabels"
