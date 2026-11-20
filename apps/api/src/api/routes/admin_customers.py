"""管理端客户路由：/api/v1/admin/customers（03 §3.2/§3.4；RBAC 03 §2）。

权限点：customers:read（列表）/ customers:write（建号、资料维护、状态变更）/
customers:delete（注销，仅 super_admin）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from contracts.customer import AdminCustomerCreateRequest, AdminCustomerUpdateRequest

from api.authz import (P_CUSTOMERS_DELETE, P_CUSTOMERS_READ, P_CUSTOMERS_WRITE,
                       require_permission, role_can)
from api.data import BRepository
from api.deps import get_repo
from api.errors import ApiProblem
from pandatrack_common import codes

router = APIRouter(prefix="/api/v1/admin", tags=["admin-customers"])


@router.get("/customers")
def list_customers(tenant_id: int | None = None, status: str = "",
                   limit: int = 100, offset: int = 0,
                   admin=Depends(require_permission(P_CUSTOMERS_READ)),
                   repo: BRepository = Depends(get_repo)):
    rows, total = repo.list_customers(tenant_id=tenant_id, status=status or None,
                                      limit=limit, offset=offset)
    return {"items": rows, "total": total}


@router.post("/customers", status_code=201)
def create_customer(payload: AdminCustomerCreateRequest,
                    admin=Depends(require_permission(P_CUSTOMERS_WRITE)),
                    repo: BRepository = Depends(get_repo)):
    """管理端手动开户（P17）：建号即 active，可带初始积分（写台账+审计）。"""
    try:
        result = repo.create_customer_admin(
            email=str(payload.email), password_hash=BRepository.hash_password(payload.password),
            name=payload.name.strip(), phone=payload.phone.strip(),
            remark=payload.remark.strip(), initial_points=payload.initial_points,
            actor_id=admin["admin_id"], actor_role=admin["role"])
    except Exception as exc:
        if "duplicate key" in str(exc).lower() or "unique" in str(exc).lower():
            raise ApiProblem(codes.EMAIL_EXISTS) from exc
        raise
    return {**result, "status": "active"}


@router.patch("/customers/{customer_id}")
def update_customer(customer_id: int, payload: AdminCustomerUpdateRequest,
                    admin=Depends(require_permission(P_CUSTOMERS_WRITE)),
                    repo: BRepository = Depends(get_repo)):
    """管理端改客户资料/邮箱/重置密码（P17）：全部可选，至少一项；审计只记字段名。"""
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not patch:
        raise ApiProblem(codes.INVALID_INPUT)
    if "new_password" in patch:
        patch["password_hash"] = BRepository.hash_password(patch.pop("new_password"))
    if "name" in patch:
        patch["name"] = patch["name"].strip()
    if "phone" in patch:
        patch["phone"] = patch["phone"].strip()
    try:
        row = repo.update_customer_profile_admin(
            customer_id, patch, actor_id=admin["admin_id"], actor_role=admin["role"])
    except Exception as exc:
        if "duplicate key" in str(exc).lower() or "unique" in str(exc).lower():
            raise ApiProblem(codes.EMAIL_EXISTS) from exc
        raise
    if row is None:
        raise ApiProblem(codes.NOT_FOUND)
    return row


@router.patch("/customers/{customer_id}/status")
def update_customer_status(customer_id: int, status: str, reason: str = "",
                           admin=Depends(require_permission(P_CUSTOMERS_WRITE)),
                           repo: BRepository = Depends(get_repo)):
    if status not in ("active", "suspended", "deleted"):
        raise ApiProblem(codes.INVALID_INPUT, {"allowed": ["active", "suspended", "deleted"]})
    if status == "deleted":
        # 注销属高危操作：单列权限点，仅 super_admin（03 §2 高风险二次确认）。
        if not role_can(str(admin.get("role", "")), P_CUSTOMERS_DELETE):
            raise ApiProblem(codes.FORBIDDEN)
    ok = repo.update_customer_status(customer_id, status)
    if not ok:
        raise ApiProblem(codes.NOT_FOUND)
    # pending→active 即开放注册的"审核通过"动作（P16），复用同一审计动作。
    repo.write_audit(
        actor_id=admin["admin_id"], actor_role=admin["role"],
        action="customer_status_change", target=str(customer_id),
        detail={"new_status": status, "reason": reason},
    )
    return {"ok": True, "customer_id": customer_id, "status": status}
