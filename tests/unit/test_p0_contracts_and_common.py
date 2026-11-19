"""P0 契约与公共逻辑测试：状态映射、错误码、契约模型、哈希工具。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from pandatrack_common import codes, status
from pandatrack_common.hashutil import (
    canonical_json,
    event_fingerprint,
    payload_digest,
    request_fingerprint,
    sha256_hex,
)


# ---------- 12 态状态字典 ----------

class TestStatusDict:
    def test_twelve_statuses_registered(self):
        # 04 §7.1：11 个具名标签 + 其他状态 = 12 态
        assert len(status.ALL_STATUSES) == 12

    def test_labels_align_with_client_dict(self):
        # 04 §7.1 白话标签逐项核对
        expected = {
            "delivered": "已签收", "in_transit": "运输中", "out_for_delivery": "派送中",
            "available_for_pickup": "到达待取", "accepted": "已揽收", "label_created": "已下单",
            "not_found": "未找到", "exception": "异常", "postage_due": "邮资未付",
            "delivery_attempted": "投递失败", "returned": "退回", "other": "其他状态",
        }
        assert {k: s.label_zh for k, s in status.ALL_STATUSES.items()} == expected

    def test_terminal_flags(self):
        assert status.DELIVERED.terminal and status.NOT_FOUND.terminal and status.RETURNED.terminal
        assert not status.IN_TRANSIT.terminal and not status.OTHER.terminal

    def test_unknown_status_not_registered(self):
        # 02 §5.3：未知原文不得强映射
        assert not status.is_registered("mystery_status")
        assert status.label_zh("mystery_status") == "其他状态"


# ---------- 错误码字典 ----------

class TestErrorCodes:
    def test_forbidden_codes_absent(self):
        # 09 §4：系统不设置 quote_expired / quote_conflict
        for bad in codes.FORBIDDEN_CODES:
            assert bad not in codes.ALL_ERROR_CODES
            assert codes.get(bad) is None

    def test_documented_codes_stable(self):
        # 09 §4 明确列出的错误码必须稳定存在
        for code in ("idempotency_conflict", "invalid_input", "request_too_large",
                     "insufficient_points", "rate_limited", "unauthorized",
                     "redemption_code_invalid"):
            assert codes.get(code) is not None, code

    def test_insufficient_points_http_status(self):
        assert codes.INSUFFICIENT_POINTS.http_status == 402

    def test_codes_unique(self):
        assert len(codes.ALL_ERROR_CODES) == len({
            e.code for e in codes.ALL_ERROR_CODES.values()
        })


# ---------- 契约模型 ----------

class TestContracts:
    def test_error_body_forbids_extra(self):
        with pytest.raises(ValidationError):
            from contracts.common import ErrorBody
            ErrorBody(code="invalid_input", message="x", upstream_status=500)  # type: ignore[call-arg]

    def test_api_error_from_registered_code(self):
        from contracts.common import ApiError
        err = ApiError.from_code("insufficient_points", required=1000, available=200)
        assert err.detail.code == "insufficient_points"
        assert err.detail.message == "积分余额不足"
        assert err.detail.extensions == {"required": 1000, "available": 200}
        assert err.http_status == 402

    def test_api_error_rejects_unregistered_code(self):
        from contracts.common import ApiError
        with pytest.raises(ValueError):
            ApiError.from_code("quote_expired")  # 废弃码必须被拒绝

    def test_submission_accepted_shape(self):
        import uuid

        from contracts.submission import SubmissionAccepted
        resp = SubmissionAccepted(
            operation_id=uuid.uuid4().hex,
            total_count=40, valid_count=38, invalid_count=2, points_charged=38, free_count=0,
        )
        assert resp.valid_count + resp.invalid_count == resp.total_count

    def test_submission_rejects_over_limit_lines(self):
        from contracts.submission import SubmissionCreate, SubmitSource
        with pytest.raises(ValidationError):
            SubmissionCreate(source=SubmitSource.PASTE, client_request_id="abc12345",
                             lines=[f"94001{i:05d}" for i in range(36)])  # >35 拒绝

    def test_redemption_code_pattern(self):
        from contracts.billing import RedemptionRequest
        assert RedemptionRequest(code="ABCD-1234-WXYZ").code == "ABCD-1234-WXYZ"
        with pytest.raises(ValidationError):
            RedemptionRequest(code="bad-format")

    def test_check_updates_uses_customer_tracking_ids(self):
        from contracts.tracking import CheckUpdatesRequest
        req = CheckUpdatesRequest(customer_tracking_ids=["a" * 32])
        assert all(len(x) in (32, 36) for x in req.customer_tracking_ids)

    def test_tracking_view_no_internal_fields(self):
        # 白名单守卫：内部字段（A 库 ID、代理、错误码原文）不允许出现在模型里
        from contracts.tracking import TrackingView
        fields = set(TrackingView.model_fields)
        for banned in ("tracking_id", "proxy", "profile", "error_class", "raw_html", "usps_url"):
            assert banned not in fields, banned


# ---------- 哈希工具 ----------

class TestHashUtil:
    def test_canonical_json_stable(self):
        a = canonical_json({"b": 1, "a": [2, 3]})
        b = canonical_json({"a": [2, 3], "b": 1})
        assert a == b and " " not in a

    def test_payload_digest_deterministic(self):
        assert payload_digest({"x": 1}) == payload_digest({"x": 1})
        assert payload_digest({"x": 1}) != payload_digest({"x": 2})

    def test_event_fingerprint_parts(self):
        f1 = event_fingerprint("94001", "2026-11-19T10:00:00Z", "DELIVERED")
        f2 = event_fingerprint("94001", "2026-11-19T10:00:00Z", "DELIVERED")
        f3 = event_fingerprint("94001", "2026-11-19T10:00:01Z", "DELIVERED")
        assert f1 == f2 and f1 != f3 and len(f1) == 64

    def test_request_fingerprint_binds_identity(self):
        a = request_fingerprint(1, "/api/v1/submissions", {"lines": ["94001"]})
        b = request_fingerprint(2, "/api/v1/submissions", {"lines": ["94001"]})
        c = request_fingerprint(1, "/api/v1/submissions", {"lines": ["94001"]})
        assert a != b and a == c

    def test_sha256_hex_matches_stdlib(self):
        import hashlib
        assert sha256_hex(b"panda") == hashlib.sha256(b"panda").hexdigest()
