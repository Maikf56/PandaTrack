"""管理端账务路由：/api/v1/admin/billing/*（03 §3.2，积分调整/冲正/审计）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.authz import P_BILLING_READ, P_BILLING_WRITE, require_permission
from api.data import BRepository
from api.deps import get_repo
from api.routes.admin_auth import get_admin_subject
from api.errors import ApiProblem
from pandatrack_common import codes

router = APIRouter(prefix="/api/v1/admin/billing", tags=["admin-billing"])


@router.post("/adjust")
def adjust_points(customer_id: int, delta: int, description: str = "",
                  reason: str = "",
                  admin=Depends(require_permission(P_BILLING_WRITE)),
                  repo: BRepository = Depends(get_repo)):
    """积分调整：只追加 PointsLedger，不直接 patch 钱包余额绝对值。"""
    if delta == 0:
        raise ApiProblem(codes.INVALID_INPUT, {"reason": "delta_zero"})
    if not description:
        raise ApiProblem(codes.INVALID_INPUT, {"reason": "description_required"})
    try:
        result = repo.admin_adjust_points(
            customer_id=customer_id, delta=delta,
            description=f"{description} | {reason}",
            actor_id=admin["admin_id"], actor_role=admin["role"],
        )
    except ValueError as e:
        raise ApiProblem(codes.NOT_FOUND, {"reason": str(e)})
    # 高风险操作强制审计（03 §3.1/§3.4）
    result["customer_id"] = customer_id
    result["reason"] = reason
    result["actor"] = admin["public_id"]
    return result


@router.get("/ledger")
def ledger(customer_id: int, limit: int = 100,
           admin=Depends(require_permission(P_BILLING_READ)),
           repo: BRepository = Depends(get_repo)):
    return {"items": repo.ledger_entries(customer_id, limit=limit)}
