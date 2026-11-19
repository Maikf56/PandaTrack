"""管理端客户路由：/api/v1/admin/customers（03 §3.2/§3.4；RBAC 03 §2）。

权限点：customers:read（列表）/ customers:write（状态变更）/
customers:delete（注销，仅 super_admin）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from api.authz import (P_CUSTOMERS_DELETE, P_CUSTOMERS_READ, P_CUSTOMERS_WRITE,
                       require_permission, role_can)
from api.data import BRepository
from api.deps import get_repo
from api.errors import ApiProblem
from pandatrack_common import codes

router = APIRouter(prefix="/api/v1/admin", tags=["admin-customers"])


@router.get("/customers")
def list_customers(tenant_id: int | None = None, limit: int = 100, offset: int = 0,
                   admin=Depends(require_permission(P_CUSTOMERS_READ)),
                   repo: BRepository = Depends(get_repo)):
    rows, total = repo.list_customers(tenant_id=tenant_id, limit=limit, offset=offset)
    return {"items": rows, "total": total}


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
    repo.write_audit(
        actor_id=admin["admin_id"], actor_role=admin["role"],
        action="customer_status_change", target=str(customer_id),
        detail={"new_status": status, "reason": reason},
    )
    return {"ok": True, "customer_id": customer_id, "status": status}
