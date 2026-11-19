"""管理端 Provider/任务路由：/api/v1/admin/providers、/tasks（03 §3.3/§3.4）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from api.authz import P_PROVIDERS_READ, P_PROVIDERS_WRITE, require_permission
from api.data import BRepository
from api.deps import get_repo
from api.errors import ApiProblem
from pandatrack_common import codes

router = APIRouter(prefix="/api/v1/admin", tags=["admin-providers"])


@router.get("/providers")
def list_providers(admin=Depends(require_permission(P_PROVIDERS_READ)),
                   repo: BRepository = Depends(get_repo)):
    return {"items": repo.provider_health()}


@router.post("/providers/{provider_code}/toggle")
def toggle_provider(provider_code: str, enabled: bool, reason: str = "",
                    admin=Depends(require_permission(P_PROVIDERS_WRITE)),
                    repo: BRepository = Depends(get_repo)):
    # 03 §3.3：Provider 启停仅允许对已验收配置操作；此处只改状态并强制审计。
    ok = repo.toggle_provider(provider_code, enabled)
    if not ok:
        raise ApiProblem(codes.NOT_FOUND)
    repo.write_audit(
        actor_id=admin["admin_id"], actor_role=admin["role"],
        action="provider_toggle", target=provider_code,
        detail={"enabled": enabled, "reason": reason},
    )
    return {"ok": True, "provider_code": provider_code, "enabled": enabled}


@router.get("/tasks")
def queue_snapshot(admin=Depends(require_permission(P_PROVIDERS_READ)),
                   repo: BRepository = Depends(get_repo)):
    return repo.queue_snapshot()
