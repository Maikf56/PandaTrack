"""管理端审计路由：/api/v1/admin/audit（03 §3.4，操作审计查询）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from api.authz import P_AUDIT_READ, require_permission
from api.data import BRepository
from api.deps import get_repo

router = APIRouter(prefix="/api/v1/admin", tags=["admin-audit"])


@router.get("/audit")
def audit_log(limit: int = 100, offset: int = 0, actor_id: int | None = None,
              action: str | None = None,
              admin=Depends(require_permission(P_AUDIT_READ)),
              repo: BRepository = Depends(get_repo)):
    rows, total = repo.audit_log(limit=limit, offset=offset,
                                 actor_id=actor_id, action=action)
    return {"items": rows, "total": total}
