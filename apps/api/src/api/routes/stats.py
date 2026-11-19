"""查询统计路由（04 §5.10：服务端口径，客户只看自己的历史汇总）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from contracts.groups_exports import StatsView

from api.data import BRepository
from api.deps import Subject, get_repo, require_customer

router = APIRouter(prefix="/api/v1", tags=["stats"])


@router.get("/stats", response_model=StatsView)
def stats(days: int = Query(default=30, ge=1, le=365),
          subject: Subject = Depends(require_customer),
          repo: BRepository = Depends(get_repo)):
    return StatsView(**repo.stats_summary(subject.customer_id, days=days))
