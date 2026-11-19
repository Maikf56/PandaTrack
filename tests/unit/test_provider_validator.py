"""P2-b 验证：页面校验(02 §5.2)与八道质量闸门(§5.3.2)。"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))

from worker.provider.contracts import ProviderEvent, ProviderItem  # noqa: E402
from worker.provider.usps_web.validator import (  # noqa: E402
    verify_page, quality_gates,
)

TNO = "9400150206217997979667"
RESULTS_HTML = (
    "<html><head><title>USPS Tracking</title></head><body>"
    '<div class="product_summary"><span class="tracking-number">'
    f"{TNO}</span>"
    '<p class="banner-content statusSummaryText">Delivered</p>'
    '<div class="tb-step current-step"><p class="tb-status-detail">Delivered</p>'
    '<p class="tb-date">November 10, 2026 11:06 AM</p></div></div></body></html>'
)
BIG_SCRIPT = "<script>" + "x" * 150_000 + "</script>"


def good_item(**kw):
    ev = ProviderEvent(
        event_fingerprint="fp1",
        occurred_at=datetime(2026, 11, 10, 11, 6),
        status="delivered", description_raw="Delivered",
        description_zh="已签收", location="", event_code="",
        time_confidence="exact",
    )
    defaults = dict(
        normalized_number=TNO, source="usps_web", status="delivered",
        raw_status="Delivered", events=[ev], page_valid=True,
        page_class="results", http_status=200, confidence=1.0,
        parser_version="v1", raw_payload_ref="ref://sha256:abc",
    )
    defaults.update(kw)
    return ProviderItem.succeed(**defaults)


class TestVerifyPage:
    def test_results_page_valid(self):
        v = verify_page(RESULTS_HTML)
        assert v.valid and v.page_class == "results" and v.error_class is None

    def test_http_403_is_rejected(self):
        v = verify_page("", http_status=403)
        assert v.error_class == "rejected" and not v.valid

    def test_http_429_is_quota(self):
        v = verify_page("", http_status=429)
        assert v.error_class == "quota"

    def test_http_5xx_is_upstream(self):
        v = verify_page("", http_status=503)
        assert v.error_class == "upstream_5xx"

    def test_empty_body_is_probe_failure(self):
        v = verify_page("   ", http_status=200)
        assert v.error_class == "probe_empty_body"
        assert v.page_class == "blocked"

    def test_unwarmed_hard_block_not_challenge(self):
        # 未暖场：空标题 + 大脚本 → 探针失败，不归 challenge、不等待。
        html = "<html><head></head><body>" + BIG_SCRIPT + "</body></html>"
        v = verify_page(html, warmed_up=False)
        assert v.error_class == "probe_empty_body"
        assert v.page_class == "blocked"

    def test_warmed_same_page_is_challenge(self):
        # 已暖场仍遇同样页面 → challenge，可换出口回炉。
        html = "<html><head></head><body>" + BIG_SCRIPT + "</body></html>"
        v = verify_page(html, warmed_up=True)
        assert v.error_class == "challenge"
        assert v.page_class == "challenge"

    def test_access_denied_text(self):
        v = verify_page("<html><head><title>x</title></head><body>Access Denied</body></html>")
        assert v.error_class == "rejected"

    def test_captcha_is_challenge(self):
        v = verify_page("<html><head><title>x</title></head><body>Press & Hold to confirm</body></html>")
        assert v.error_class == "challenge"

    def test_not_found_page_valid(self):
        v = verify_page("<html><head><title>x</title></head><body>We could not find a record</body></html>")
        assert v.valid and v.page_class == "not_found" and v.error_class is None

    def test_unknown_page_fail_closed(self):
        v = verify_page("<html><head><title>x</title></head><body>random</body></html>")
        assert v.error_class == "page_type_unknown" and not v.valid

    def test_evidence_serializable(self):
        v = verify_page("", http_status=403)
        assert json.loads(json.dumps(v.to_evidence()))["error_class"] == "rejected"


class TestQualityGates:
    def test_all_pass(self):
        g = quality_gates(good_item(), expected_number=TNO)
        assert g.passed and not g.failed_gates and g.error_class is None
        assert json.loads(g.to_json())["passed"] is True

    def test_gate1_target_mismatch(self):
        g = quality_gates(good_item(), expected_number="9200000000000000000000")
        assert not g.passed and "1_target_match" in g.failed_gates
        assert g.error_class == "quality_gate_rejected"

    def test_gate2_invalid_page(self):
        g = quality_gates(good_item(page_valid=False))
        assert "2_page_valid" in g.failed_gates

    def test_gate3_missing_fields(self):
        g = quality_gates(good_item(status="", events=[]))
        assert "3_fields_complete" in g.failed_gates
        assert g.error_class == "parse_failed"

    def test_not_found_item_passes_field_gate(self):
        g = quality_gates(good_item(status="not_found", events=[]))
        assert g.passed  # not_found 允许无事件

    def test_gate4_terminal_protect(self):
        # 库内已签收（终态），低置信新结果不得改写。
        g = quality_gates(good_item(status="in_transit", confidence=0.6),
                          existing_status="delivered")
        assert "4_terminal_protect" in g.failed_gates

    def test_gate4_high_confidence_same_status_ok(self):
        g = quality_gates(good_item(status="delivered", confidence=1.0),
                          existing_status="delivered")
        assert "4_terminal_protect" not in g.failed_gates

    def test_gate5_duplicate_event_fingerprint(self):
        ev = ProviderEvent("fp1", None, "delivered", "D", "已签收", "", "", "exact")
        g = quality_gates(good_item(events=[ev, ev]))
        assert "5_events_consistent" in g.failed_gates

    def test_gate5_existing_events_but_empty_new(self):
        g = quality_gates(good_item(status="in_transit", events=[]),
                          existing_has_events=True)
        assert "5_events_consistent" in g.failed_gates

    def test_gate6_bad_time_confidence(self):
        ev = ProviderEvent("fp1", None, "delivered", "D", "已签收", "", "", "precise")
        g = quality_gates(good_item(events=[ev]))
        assert "6_time_confidence" in g.failed_gates

    def test_gate7_missing_evidence(self):
        g = quality_gates(good_item(parser_version="", raw_payload_ref=""))
        assert "7_parse_evidence" in g.failed_gates

    def test_gate7_accepts_external_params(self):
        g = quality_gates(good_item(parser_version="", raw_payload_ref=""),
                          parser_version="v2", payload_ref="ref://x")
        assert "7_parse_evidence" not in g.failed_gates

    def test_gate8_transaction(self):
        g = quality_gates(good_item(), transaction_atomic=False)
        assert "8_transaction_atomic" in g.failed_gates

    def test_failure_keeps_evidence(self):
        g = quality_gates(good_item(events=[]), existing_has_events=True,
                          expected_number=TNO)
        ev = json.loads(g.to_json())
        assert ev["failed_gates"] and ev["item_ref"].startswith("9400")
