"""P2-a 验证：错误分类矩阵(02 §5.1)、Provider 契约(§4)、fail-closed。"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))

from worker.provider import (  # noqa: E402
    RULES, RETRYABLE, TERMINAL, COUNTS_FAILURE,
    ProviderError, is_retryable, next_task_state, backoff_seconds, rule_for,
)
from worker.provider.contracts import (  # noqa: E402
    ProviderInput, ProviderItem, ProviderEvent, ProviderResult, tracking_ref,
)
from worker.provider.usps_web.provider import UspsWebProvider  # noqa: E402


class TestErrorClassification:
    def test_all_02_classes_registered(self):
        # 02 §5.1 矩阵的 20 个类别（含 not_found 有效结果与 source_invalid）。
        expected = {
            "provider_disabled", "provider_unavailable", "provider_config_unavailable",
            "runtime_missing", "not_accepted", "circuit_open", "challenge",
            "rejected", "quota", "upstream_5xx", "network_timeout", "browser_crash",
            "proxy_gateway_unreachable", "probe_bad_status", "probe_empty_body",
            "soft_throttled", "page_type_unknown", "parse_failed",
            "quality_gate_rejected", "not_found", "db_or_outbox_error", "source_invalid",
        }
        assert expected <= set(RULES)

    def test_terminal_classes_no_retry(self):
        for ec in ("rejected", "quota", "page_type_unknown",
                   "quality_gate_rejected", "source_invalid", "runtime_missing"):
            assert not is_retryable(ec), ec
            assert next_task_state(ec, 1) == "dead_letter"

    def test_challenge_retry_within_max_attempts(self):
        # attempt = 已完成尝试次数；max_attempts=3 表示总尝试上限。
        assert "challenge" in RETRYABLE
        assert next_task_state("challenge", 1) == "retry_scheduled"
        assert next_task_state("challenge", 2) == "retry_scheduled"
        assert next_task_state("challenge", 3) == "dead_letter"
        assert next_task_state("challenge", 4) == "dead_letter"

    def test_circuit_open_half_open_not_counted(self):
        assert "circuit_open" not in COUNTS_FAILURE
        assert next_task_state("circuit_open", 99) == "retry_scheduled"
        assert next_task_state("circuit_open", 99) != "dead_letter"

    def test_not_found_is_success(self):
        assert next_task_state("not_found", 1) == "succeeded"
        assert rule_for("not_found").alert == "INFO"

    def test_backoff_sequence(self):
        assert backoff_seconds("upstream_5xx", 1) == 5
        assert backoff_seconds("upstream_5xx", 2) == 15
        assert backoff_seconds("upstream_5xx", 3) == 45
        assert backoff_seconds("upstream_5xx", 4) == 45  # 封顶
        assert backoff_seconds("challenge", 1) == 0      # 换出口立即重试

    def test_unknown_class_safe_downgrade(self):
        # 未登记类按 page_type_unknown 安全降级，不猜。
        assert rule_for("never_seen").error_class == "page_type_unknown"
        assert not is_retryable("never_seen")

    def test_provider_error_carries_class(self):
        err = ProviderError("challenge", "abck", evidence={"tb": 0})
        assert err.error_class == "challenge"
        assert err.evidence == {"tb": 0}
        with pytest.raises(ValueError):
            ProviderError("not_a_class")


class TestProviderContracts:
    def test_tracking_ref_masked(self):
        ref = tracking_ref("9400150206217997979667")
        assert ref.startswith("9400")
        assert len(ref) == 12  # 4 + 8
        assert "1502" not in ref  # 中间原文不出现

    def test_item_fail_batch_vs_item_level(self):
        batch = ProviderItem.fail("9400", "rejected", batch_level=True)
        item = ProviderItem.fail("9400", "not_found")
        assert batch.error_class == "rejected" and batch.item_error_class is None
        assert item.item_error_class == "not_found" and item.error_class is None

    def test_source_validation(self):
        good = ProviderItem.succeed("9400", source="usps_web", simulated=False)
        good.assert_source_valid()  # 不抛
        for bad in (
            ProviderItem.succeed("9400", source="usps_web", simulated=True),
            ProviderItem.succeed("9400", source="mock"),
            ProviderItem.succeed("9400", source=""),
        ):
            with pytest.raises(ProviderError) as ei:
                bad.assert_source_valid()
            assert ei.value.error_class == "source_invalid"

    def test_result_ok(self):
        ok = ProviderResult(items=[ProviderItem.succeed(
            "9400", source="usps_web", page_valid=True)])
        assert ok.ok
        bad = ProviderResult(items=[ProviderItem.fail("9400", "parse_failed")])
        assert not bad.ok
        batch_bad = ProviderResult(batch_error_class="rejected", items=[])
        assert not batch_bad.ok


class TestFailClosed:
    def test_default_disabled(self):
        p = UspsWebProvider()
        with pytest.raises(ProviderError) as ei:
            p.fetch([ProviderInput(normalized_number="9400", job_ref="j1")])
        assert ei.value.error_class == "provider_disabled"

    def test_enabled_but_no_executor_is_runtime_missing(self):
        p = UspsWebProvider(enabled=True)
        with pytest.raises(ProviderError) as ei:
            p.fetch([ProviderInput(normalized_number="9400", job_ref="j1")])
        assert ei.value.error_class == "runtime_missing"

    def test_emergency_stop_and_circuit(self):
        p = UspsWebProvider(enabled=True, emergency_stop=True, executor=object())
        with pytest.raises(ProviderError) as ei:
            p.fetch([])
        assert ei.value.error_class == "provider_unavailable"
        p2 = UspsWebProvider(enabled=True, circuit_open=True, executor=object())
        with pytest.raises(ProviderError) as ei:
            p2.fetch([])
        assert ei.value.error_class == "circuit_open"

    def test_no_mock_fallback_ever(self):
        # 空 HTML 页面校验失败 → 整批失败项，不伪造任何成功轨迹、不回退 mock。
        p = UspsWebProvider(enabled=True, executor=_EmptyPageExecutor())
        out = p.fetch([ProviderInput(normalized_number="9400", job_ref="j1")])
        assert not out.ok
        assert out.batch_error_class is not None
        # 失败项也标真实来源，绝不出现 mock/simulated=true。
        assert all(i.source == "usps_web" and not i.simulated for i in out.items)
        assert all(i.status == "" for i in out.items)

    def test_source_always_real(self):
        # Provider 产出的成功项固定 source=usps_web，来源闸门由 item 自校验兜底。
        html = ("<html><head><title>x</title></head><body>"
                '<div class="product_summary"><span class="tracking-number">'
                "9400150206217997979667</span>"
                '<div class="tb-step current-step">'
                '<p class="tb-status-detail">Delivered</p>'
                '<p class="tb-date">November 10, 2026 11:06 AM</p>'
                "</div></div></body></html>")
        p = UspsWebProvider(enabled=True, executor=_PageExecutor(html))
        out = p.fetch([ProviderInput(normalized_number="9400150206217997979667",
                                     job_ref="j1")])
        item = out.items[0]
        assert item.source == "usps_web" and not item.simulated
        item.assert_source_valid()  # 不抛


class _EmptyPageExecutor:
    def collect_page(self, numbers):
        from worker.provider.usps_claw import CollectedPage
        return CollectedPage(html="", http_status=200, warmed_up=False,
                             exit_region="us", exit_ref="x", profile_ref="p",
                             exit_attempt=1)


class _PageExecutor:
    def __init__(self, html):
        self.html = html

    def collect_page(self, numbers):
        from worker.provider.usps_claw import CollectedPage
        return CollectedPage(html=self.html, http_status=200, warmed_up=True,
                             exit_region="us", exit_ref="x", profile_ref="p",
                             exit_attempt=1)
