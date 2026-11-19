"""RBAC 权限矩阵离线单测（03 §2）：纯函数，不碰库。

fail-closed 原则：未知角色/未知权限点一律 False。
"""
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "apps" / "api" / "src"),
                str(Path(__file__).resolve().parents[2] / "packages" / "common" / "src")]

from api.authz import (  # noqa: E402
    ALL_ROLES, P_AUDIT_READ, P_BILLING_READ, P_BILLING_WRITE,
    P_CUSTOMERS_DELETE, P_CUSTOMERS_READ, P_CUSTOMERS_WRITE,
    P_PROVIDERS_READ, P_PROVIDERS_WRITE, ROLE_PERMISSIONS, permissions_for,
    role_can,
)

EXPECTED_ROLES = {"super_admin", "finance", "provider_ops", "support", "readonly"}


def test_five_roles_defined():
    assert ALL_ROLES == EXPECTED_ROLES
    assert set(ROLE_PERMISSIONS) == EXPECTED_ROLES


def test_super_admin_has_all():
    perms = ROLE_PERMISSIONS["super_admin"]
    for p in (P_CUSTOMERS_READ, P_CUSTOMERS_WRITE, P_CUSTOMERS_DELETE,
              P_BILLING_READ, P_BILLING_WRITE,
              P_PROVIDERS_READ, P_PROVIDERS_WRITE, P_AUDIT_READ):
        assert role_can("super_admin", p), p


def test_readonly_cannot_write_anything():
    for p in (P_CUSTOMERS_WRITE, P_CUSTOMERS_DELETE,
              P_BILLING_WRITE, P_PROVIDERS_WRITE):
        assert not role_can("readonly", p), p
    for p in (P_CUSTOMERS_READ, P_BILLING_READ, P_PROVIDERS_READ, P_AUDIT_READ):
        assert role_can("readonly", p), p


def test_finance_only_billing_write():
    assert role_can("finance", P_BILLING_WRITE)
    assert not role_can("finance", P_CUSTOMERS_WRITE)
    assert not role_can("finance", P_PROVIDERS_WRITE)
    assert not role_can("finance", P_CUSTOMERS_DELETE)


def test_provider_ops_only_providers_write():
    assert role_can("provider_ops", P_PROVIDERS_WRITE)
    assert not role_can("provider_ops", P_BILLING_WRITE)
    assert not role_can("provider_ops", P_CUSTOMERS_WRITE)


def test_support_only_customers_write_no_delete():
    assert role_can("support", P_CUSTOMERS_WRITE)
    # 注销（deleted）是 super_admin 专属高危权限
    assert not role_can("support", P_CUSTOMERS_DELETE)
    assert not role_can("finance", P_CUSTOMERS_DELETE)
    assert role_can("super_admin", P_CUSTOMERS_DELETE)


def test_fail_closed_unknown_role_or_permission():
    assert not role_can("admin", P_CUSTOMERS_READ)      # legacy 值已归一，矩阵无此角色
    assert not role_can("", P_CUSTOMERS_READ)
    assert not role_can("super_admin", "customers:drop")
    assert not role_can("super_admin", "")


def test_permissions_for_export():
    assert set(permissions_for("readonly")) == {
        P_CUSTOMERS_READ, P_BILLING_READ, P_PROVIDERS_READ, P_AUDIT_READ}
    assert permissions_for("unknown_role") == []
