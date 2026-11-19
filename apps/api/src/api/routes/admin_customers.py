"""管理端客户路由：/api/v1/admin/customers（03 §3.2/§3.4）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.data import BRepository
from api.deps import get_repo
from api.errors import ApiProblem
from pandatrack_common import codes
from api.routes.admin_auth import get_admin_subject

router = APIRouter(prefix="/api/v1/admin", tags=["admin-customers"])


@router.get("/customers")
def list_customers(tenant_id: int | None = None, limit: int = 100, offset: int = 0,
                   admin=Depends(get_admin_subject),
                   repo: BRepository = Depends(get_repo)):
    rows, total = repo.list_customers(tenant_id=tenant_id, limit=limit, offset=offset)
    return {"items": rows, "total": total}


@router.patch("/customers/{customer_id}/status")
def update_customer_status(customer_id: int, status: str, reason: str = "",
                           admin=Depends(get_admin_subject),
                           repo: BRepository = Depends(get_repo)):
    if status not in ("active", "suspended", "deleted"):
        raise ApiProblem(codes.INVALID_INPUT, {"allowed": ["active", "suspended", "deleted"]})
    ok = repo.update_customer_status(customer_id, status)
    if not ok:
        raise ApiProblem(codes.NOT_FOUND)
    repo.write_audit(
        actor_id=admin["admin_id"], actor_role=admin["role"],
        action="customer_status_change", target=str(customer_id),
        detail={"new_status": status, "reason": reason},
    )
    return {"ok": True, "customer_id": customer_id, "status": status}
