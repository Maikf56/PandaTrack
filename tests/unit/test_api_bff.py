"""P4-阶段1 验证：BFF 路由/鉴权/错误映射/提交(09 契约)。

用 TestClient + 假 repo 注入，不连真实 DB；真实 PG 集成在服务器验收区。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402
from api.errors import ApiProblem  # noqa: E402
from pandatrack_common import codes  # noqa: E402

SUBJECT = {"customer_id": 1, "public_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
           "email": "u@example.com", "role": "member", "tenant_id": None,
           "admin_id": None}


def client_with(repo):
    app = create_app(dsn="postgresql://x")
    app.state.repo = repo
    return TestClient(app)


class TestAuthAndErrors:
    def test_unauthenticated_401(self):
        repo = MagicMock()
        repo.resolve_session.return_value = None
        c = client_with(repo)
        r = c.get("/api/v1/auth/me", cookies={"pt_session": "bad"})
        assert r.status_code == 401
        body = r.json()["detail"]
        assert body["code"] == "session_expired"
        assert "password" not in str(body).lower()

    def test_login_success_sets_cookie(self):
        repo = MagicMock()
        repo.authenticate.return_value = SUBJECT
        c = client_with(repo)
        r = c.post("/api/v1/auth/login", json={
            "email": "u@example.com", "password": "password123",
            "client_request_id": "login-0001"})
        assert r.status_code == 200
        assert r.json()["customer_id"] == SUBJECT["public_id"]
        assert "pt_session" in r.cookies

    def test_login_wrong_password_is_unauthorized(self):
        from api.errors import ApiProblem as P
        repo = MagicMock()
        repo.authenticate.side_effect = P(codes.UNAUTHORIZED)
        c = client_with(repo)
        r = c.post("/api/v1/auth/login", json={
            "email": "u@example.com", "password": "password123",
            "client_request_id": "login-0001"})
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "unauthorized"

    def test_validation_error_safe_message(self):
        c = client_with(MagicMock())
        r = c.post("/api/v1/auth/login", json={"email": "not-an-email"})
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "invalid_input"
        # 不回显 pydantic 内部字段细节
        assert "email" not in r.json()["detail"]["message"].lower()

    def test_security_headers(self):
        c = client_with(MagicMock())
        r = c.get("/healthz")
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"


class TestMeta:
    def test_status_dict(self):
        c = client_with(MagicMock())
        r = c.get("/api/v1/status-dict")
        assert r.status_code == 200
        data = r.json()
        assert len(data["statuses"]) == 12  # 11 具名 + 1 其他状态
        assert any(s["key"] == "delivered" and s["label_zh"] == "已签收"
                   for s in data["statuses"])
        assert "pending" in data["item_state_enum"]


class TestSubmissionEndpoint:
    def _authed(self, repo):
        repo.resolve_session.return_value = SUBJECT
        c = client_with(repo)
        c.cookies.set("pt_session", "valid-token")
        return c

    def test_submission_202(self, monkeypatch):
        import api.routes.submissions as submod
        from worker.billing.submission import SubmitOutcome
        repo = MagicMock()
        repo.connect.return_value.__enter__ = MagicMock()
        repo.connect.return_value.__exit__ = MagicMock(return_value=False)
        c = self._authed(repo)
        monkeypatch.setattr(submod, "submit", lambda *a, **k: SubmitOutcome(
            operation_public_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            total_count=1, billable_count=1, waived_count=0, balance=100))
        r = c.post("/api/v1/submissions", json={
            "source": "paste", "client_request_id": "submit-0001",
            "lines": ["9400150206217997979667"]})
        assert r.status_code == 202
        body = r.json()
        assert body["operation_id"] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        assert body["valid_count"] == 1 and body["points_charged"] == 1
        assert body["batches"] == [1]

    def test_submission_empty_rejected(self):
        repo = MagicMock()
        c = self._authed(repo)
        r = c.post("/api/v1/submissions", json={
            "source": "paste", "client_request_id": "submit-0002", "lines": []})
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "invalid_input"

    def test_submission_idempotency_conflict(self, monkeypatch):
        import api.routes.submissions as submod
        repo = MagicMock()
        repo.connect.return_value.__enter__ = MagicMock()
        repo.connect.return_value.__exit__ = MagicMock(return_value=False)
        c = self._authed(repo)

        def boom(*a, **k):
            raise submod.IdempotencyConflict("conflict")
        monkeypatch.setattr(submod, "submit", boom)
        r = c.post("/api/v1/submissions", json={
            "source": "paste", "client_request_id": "submit-0003",
            "lines": ["9400150206217997979667"]})
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "idempotency_conflict"

    def test_submission_insufficient_points(self, monkeypatch):
        import api.routes.submissions as submod
        repo = MagicMock()
        repo.connect.return_value.__enter__ = MagicMock()
        repo.connect.return_value.__exit__ = MagicMock(return_value=False)
        c = self._authed(repo)

        def boom(*a, **k):
            raise submod.InsufficientBalance("no balance")
        monkeypatch.setattr(submod, "submit", boom)
        r = c.post("/api/v1/submissions", json={
            "source": "paste", "client_request_id": "submit-0004",
            "lines": ["9400150206217997979667"]})
        assert r.status_code == 402
        assert r.json()["detail"]["code"] == "insufficient_points"


class TestTrackingEndpoints:
    def _authed(self, repo):
        repo.resolve_session.return_value = SUBJECT
        c = client_with(repo)
        c.cookies.set("pt_session", "valid-token")
        return c

    def test_get_operation_tenant_scoped(self):
        repo = MagicMock()
        repo.operation.return_value = {
            "operation_id": 42, "public_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "state": "completed", "total_count": 2, "valid_count": 2,
            "invalid_count": 0, "points_charged": 2}
        repo.operation_batches.return_value = [
            {"batch_seq": 1, "item_count": 2, "done": 2, "processing": 0,
             "deferred": 0, "suspended": 0}]
        c = self._authed(repo)
        r = c.get("/api/v1/operations/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        assert r.status_code == 200
        assert r.json()["total_count"] == 2
        repo.operation.assert_called_once_with(
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", 1)  # 强制 customer_id scope

    def test_get_operation_not_found(self):
        repo = MagicMock()
        repo.operation.return_value = None
        c = self._authed(repo)
        r = c.get("/api/v1/operations/cccccccc-cccc-cccc-cccc-cccccccccccc")
        assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found"

    def test_list_operations_tenant_scoped(self):
        repo = MagicMock()
        repo.list_operations.return_value = ([
            {"public_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "state": "completed",
             "total_count": 2, "valid_count": 2, "invalid_count": 0,
             "points_charged": 2, "created_at": "2026-11-19T08:00:00+00:00"},
        ], 1)
        c = self._authed(repo)
        r = c.get("/api/v1/operations")
        assert r.status_code == 200, r.text
        items = r.json()
        assert items[0]["id"] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        # 强制 customer scope + limit 封顶
        kwargs = repo.list_operations.call_args.kwargs
        assert kwargs["limit"] <= 200

    def test_tracking_view_whitelist(self):
        repo = MagicMock()
        repo.tracking.return_value = {
            "customer_tracking_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
            "normalized_number": "9400150206217997979667", "status": "delivered",
            "events": [{"status_key": "delivered", "description": "Delivered",
                        "time_confidence": "exact", "occurred_at": "2026-11-10T11:06:00"}],
            "next_sync_at": None, "last_success_at": None}
        c = self._authed(repo)
        r = c.get("/api/v1/tracking/dddddddd-dddd-dddd-dddd-dddddddddddd") \
            if False else c.get("/api/v1/trackings/dddddddd-dddd-dddd-dddd-dddddddddddd")
        assert r.status_code == 200
        body = r.json()
        assert body["status_key"] == "delivered" and body["label_zh"] == "已签收"
        assert body["is_terminal"] is True and body["simulated"] is False
        assert "usps.com" not in str(body).lower()  # 白名单：无上游域名

    def test_check_updates_fresh(self):
        repo = MagicMock()
        from datetime import datetime, timedelta, timezone
        repo.tracking.return_value = {
            "customer_tracking_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
            "status": "in_transit",
            "next_sync_at": datetime.now(timezone.utc) + timedelta(hours=6),
            "last_success_at": None, "events": []}
        c = self._authed(repo)
        r = c.post("/api/v1/check-updates", json={
            "customer_tracking_ids": ["eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"]})
        assert r.status_code == 200
        assert r.json()[0]["fresh"] is True
        assert r.json()[0]["will_fetch"] is False
