"""管理端系统运行日志路由：/api/v1/admin/runlog（worker 运行日志查询）。

- run_log：worker 每轮 cycle 的领取/成功/重试/死信/事实落库计数（A 库 run_log）；
- runlog/attempts：最近采集明细（爬虫日志：单号 + 页面证据 + 错误类别）；
- runlog/deadletters：死信任务明细 + 复活重排（写操作强制审计）。
运行日志查询沿用 audit:read；死信复活为运维写操作，要求 providers:write。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.authz import P_AUDIT_READ, P_PROVIDERS_WRITE, require_permission
from api.data import BRepository
from api.deps import get_repo

router = APIRouter(prefix="/api/v1/admin", tags=["admin-runlog"])


@router.get("/runlog")
def run_log(limit: int = 100, offset: int = 0, level: str | None = None,
            admin=Depends(require_permission(P_AUDIT_READ)),
            repo: BRepository = Depends(get_repo)):
    rows, total = repo.run_log(limit=min(limit, 200), offset=max(offset, 0),
                               level=level)
    return {"items": rows, "total": total}


@router.get("/runlog/attempts")
def runlog_attempts(limit: int = 50,
                    admin=Depends(require_permission(P_AUDIT_READ)),
                    repo: BRepository = Depends(get_repo)):
    return {"items": repo.recent_attempts(limit=min(limit, 100))}


@router.get("/runlog/deadletters")
def runlog_deadletters(limit: int = 200,
                       admin=Depends(require_permission(P_AUDIT_READ)),
                       repo: BRepository = Depends(get_repo)):
    items, total = repo.dead_letters(limit=min(limit, 500))
    return {"items": items, "total": total}


class RequeueBody(BaseModel):
    job_ids: list[int] | None = None   # 不传=全部死信复活
    reason: str = ""


@router.post("/runlog/deadletters/requeue")
def runlog_requeue(body: RequeueBody,
                   admin=Depends(require_permission(P_PROVIDERS_WRITE)),
                   repo: BRepository = Depends(get_repo)):
    n = repo.requeue_dead_letters(body.job_ids)
    repo.write_audit(
        actor_id=admin["admin_id"], actor_role=admin["role"],
        action="dead_letter_requeue", target=f"jobs={n}",
        detail={"reason": body.reason, "count": n,
                "job_ids": body.job_ids})
    return {"ok": True, "requeued": n}
