"""管理端 RBAC（03 §2：角色 × 权限点矩阵）。

角色（定稿方案 03 §2"至少分为"）：
  super_admin   系统管理员——全部权限（含客户注销等高危操作）
  finance       账务操作——账务读写
  provider_ops  Provider 运维——Provider 读写、任务快照
  support       客户支持——客户读写（状态变更）
  readonly      只读运营——全部只读

规则：
- 权限点 snake pair（资源:动作）；矩阵是唯一权威源，路由只引用不自行判断。
- 未声明角色一律拒绝（fail-closed）；超集角色不隐式继承，矩阵显式列出。
- legacy 'admin' 由迁移 b/0006 归一化为 'super_admin'。
"""
from __future__ import annotations

from fastapi import Depends

from api.errors import ApiProblem
from api.routes.admin_auth import get_admin_subject
from pandatrack_common import codes

# ---- 权限点 ----
P_CUSTOMERS_READ = "customers:read"
P_CUSTOMERS_WRITE = "customers:write"      # 状态变更 active/suspended
P_CUSTOMERS_DELETE = "customers:delete"    # 注销（高危，仅 super_admin）
P_BILLING_READ = "billing:read"
P_BILLING_WRITE = "billing:write"          # 积分调整/冲正
P_PROVIDERS_READ = "providers:read"
P_PROVIDERS_WRITE = "providers:write"      # Provider 启停
P_AUDIT_READ = "audit:read"

_READONLY = {
    P_CUSTOMERS_READ, P_BILLING_READ, P_PROVIDERS_READ, P_AUDIT_READ,
}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "super_admin": frozenset(_READONLY | {
        P_CUSTOMERS_WRITE, P_CUSTOMERS_DELETE,
        P_BILLING_WRITE, P_PROVIDERS_WRITE,
    }),
    "finance": frozenset(_READONLY | {P_BILLING_WRITE}),
    "provider_ops": frozenset(_READONLY | {P_PROVIDERS_WRITE}),
    "support": frozenset(_READONLY | {P_CUSTOMERS_WRITE}),
    "readonly": frozenset(_READONLY),
}

ALL_ROLES = frozenset(ROLE_PERMISSIONS)


def role_can(role: str, permission: str) -> bool:
    """纯函数判定（供单测与前端矩阵导出复用）。"""
    perms = ROLE_PERMISSIONS.get(role)
    return perms is not None and permission in perms


def require_permission(permission: str):
    """FastAPI 依赖工厂：校验当前管理员具备权限点，否则 403（fail-closed）。"""

    def dep(admin: dict = Depends(get_admin_subject)) -> dict:
        if not role_can(str(admin.get("role", "")), permission):
            raise ApiProblem(codes.FORBIDDEN)
        return admin

    return dep


def permissions_for(role: str) -> list[str]:
    """导出某角色的权限点列表（管理端前端矩阵展示用）。"""
    return sorted(ROLE_PERMISSIONS.get(role, frozenset()))
