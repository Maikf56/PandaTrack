"""管理端系统运行日志路由：/api/v1/admin/runlog（worker 运行日志查询）。

- run_log：worker 每轮 cycle 的领取/成功/重试/死信/事实落库计数（A 库 run_log）；
- runlog/attempts：最近采集明细（单号 + 任务状态 + 错误类别）。
权限沿用 audit:read（运行日志为只读观察面，与审计同级）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from api.authz import P_AUDIT_READ, require_permission
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
