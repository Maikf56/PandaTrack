"""P4-2 验证：管理端 API（03 §3.1/§3.2/§3.3，独立鉴权+审计+脱敏）。"""
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

ADMIN_SUB = {"admin_id": 10, "public_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
             "username": "admin1", "role": "super_admin"}  # b/0006 已归一 legacy admin


def client_with(repo):
    app = create_app(dsn="postgresql://x")
    app.state.repo = repo
    return TestClient(app)


def authed_client(repo):
    c = client_with(repo)
    c.cookies.set("pt_admin_session", "valid-token")
    # RBAC 后依赖需要真实角色字典；默认 super_admin（全权限）
    repo.resolve_admin_session.return_value = ADMIN_SUB
    return c


class TestAdminAuth:
    def test_login_success(self):
        repo = MagicMock()
        repo.authenticate_admin.return_value = ADMIN_SUB
        c = client_with(repo)
        r = c.post("/api/v1/admin/auth/login",
                   json={"username": "admin1", "password": "pw"})
        assert r.status_code == 200
        assert "pt_admin_session" in r.cookies

    def test_unauthorized_without_cookie(self):
        repo = MagicMock()
        c = client_with(repo)
        r = c.get("/api/v1/admin/customers")
        assert r.status_code == 401


class TestAdminCustomers:
    def test_list_customers(self):
        repo = MagicMock()
        repo.list_customers.return_value = ([{"customer_id": 1, "public_id": "x",
                                              "email": "u@e.com", "status": "active",
                                              "role": "member", "tenant_id": None,
                                              "created_at": ""}], 1)
        c = authed_client(repo)
        r = c.get("/api/v1/admin/customers")
        assert r.status_code == 200 and r.json()["total"] == 1
        assert "password" not in str(r.json()).lower()

    def test_update_customer_status_and_audit(self):
        repo = MagicMock()
        repo.update_customer_status.return_value = True
        c = authed_client(repo)
        r = c.patch("/api/v1/admin/customers/1/status?status=suspended&reason=test")
        assert r.status_code == 200 and r.json()["status"] == "suspended"
        # 审计已写入（通过 repo.write_audit 调用可验证）
        repo.write_audit.assert_called_once()
        args = repo.write_audit.call_args
        assert args.kwargs["action"] == "customer_status_change"
        assert args.kwargs["target"] == "1"


class TestAdminProviders:
    def test_list_providers(self):
        repo = MagicMock()
        repo.provider_health.return_value = [
            {"provider_code": "usps_web", "enabled": False,
             "circuit_open": False, "consecutive_failures": 0,
             "cooldown_until": None, "updated_at": ""}]
        c = authed_client(repo)
        r = c.get("/api/v1/admin/providers")
        assert r.status_code == 200
        assert r.json()["items"][0]["provider_code"] == "usps_web"

    def test_toggle_provider_with_audit(self):
        repo = MagicMock()
        repo.connect.return_value.__enter__ = MagicMock()
        repo.connect.return_value.__exit__ = MagicMock(return_value=False)
        c = authed_client(repo)
        r = c.post("/api/v1/admin/providers/usps_web/toggle?enabled=true&reason=验收")
        assert r.status_code == 200
        assert r.json()["enabled"] is True
        repo.toggle_provider.assert_called_once_with("usps_web", True)
        repo.write_audit.assert_called_once()


class TestAdminBilling:
    def test_adjust_points_appends_ledger(self):
        repo = MagicMock()
        repo.resolve_admin_session.return_value = ADMIN_SUB
        repo.admin_adjust_points.return_value = {
            "ledger_id": "llllllll-llll-llll-llll-llllllllllll",
            "new_balance": 150}
        c = authed_client(repo)
        r = c.post("/api/v1/admin/billing/adjust?customer_id=1&delta=50"
                   "&description=测试调整&reason=admin")
        assert r.status_code == 200
        assert r.json()["new_balance"] == 150
        # 不直接 patch 绝对值：新余额由 repo 计算返回（此处 mock 保证）
        repo.admin_adjust_points.assert_called_once_with(
            customer_id=1, delta=50,
            description="测试调整 | admin",
            actor_id=10, actor_role="super_admin")

    def test_adjust_zero_rejected(self):
        c = authed_client(MagicMock())
        r = c.post("/api/v1/admin/billing/adjust?customer_id=1&delta=0"
                   "&description=x")
        assert r.status_code == 400


class TestAdminAudit:
    def test_audit_log(self):
        repo = MagicMock()
        repo.audit_log.return_value = ([], 0)
        c = authed_client(repo)
        r = c.get("/api/v1/admin/audit")
        assert r.status_code == 200
        repo.audit_log.assert_called_once_with(limit=100, offset=0,
                                                actor_id=None, action=None,
                                                target=None)
