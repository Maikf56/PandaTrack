"""进度/轨迹/检查更新路由（09 §3.1/§5，消费 P3 freshness 四分支）。

对外 tracking ID 一律 B 库 customer_tracking_id 的 public_id UUID（09 §3.1）。
白名单投影：不含 USPS URL、代理、profile、A 库表名、内部错误码、证据原文。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from contracts.progress import BatchProgress, OperationProgress
from contracts.tracking import (
    CheckUpdatesRequest, CheckUpdatesResult, TrackingEventView, TrackingView,
)
from pandatrack_common import codes, status as status_dict
from worker.scheduler.freshness import Fact, UpstreamState, decide, Branch

from api.data import BRepository
from api.deps import Subject, get_repo, require_customer
from api.errors import ApiProblem

router = APIRouter(prefix="/api/v1", tags=["tracking"])


@router.get("/operations/{operation_id}", response_model=OperationProgress)
def get_operation(operation_id: str,
                  subject: Subject = Depends(require_customer),
                  repo: BRepository = Depends(get_repo)):
    op = repo.operation(operation_id, subject.customer_id)
    if op is None:
        raise ApiProblem(codes.NOT_FOUND)
    batches = repo.operation_batches(op["operation_id"])
    bp = [BatchProgress(batch_seq=b["batch_seq"], item_count=b["item_count"],
                        done=b["done"], processing=b["processing"],
                        deferred=b["deferred"], suspended=b["suspended"])
          for b in batches]
    return OperationProgress(
        id=op["public_id"], state=op["state"],
        total_count=op["total_count"], valid_count=op["valid_count"],
        invalid_count=op["invalid_count"], points_charged=op["points_charged"],
        batches=bp,
    )


@router.get("/trackings", response_model=list[TrackingView])
def list_trackings(subject: Subject = Depends(require_customer),
                   repo: BRepository = Depends(get_repo)):
    return [_to_view(r) for r in repo.list_trackings(subject.customer_id)]


@router.get("/trackings/{tracking_uuid}", response_model=TrackingView)
def get_tracking(tracking_uuid: str,
                 subject: Subject = Depends(require_customer),
                 repo: BRepository = Depends(get_repo)):
    row = repo.tracking(tracking_uuid, subject.customer_id)
    if row is None:
        raise ApiProblem(codes.NOT_FOUND)
    return _to_view(row)


@router.post("/check-updates", response_model=list[CheckUpdatesResult])
def check_updates(payload: CheckUpdatesRequest,
                  subject: Subject = Depends(require_customer),
                  repo: BRepository = Depends(get_repo)):
    """主动检查：四分支判定，fresh 命中 will_fetch=false 且 0 上游请求（07 §3.7）。"""
    out: list[CheckUpdatesResult] = []
    for uid in payload.customer_tracking_ids:
        row = repo.tracking(uid, subject.customer_id)
        if row is None:
            raise ApiProblem(codes.NOT_FOUND)
        decision = decide(
            Fact(exists=True, status=row.get("status") or "",
                 next_sync_at=row.get("next_sync_at"),
                 last_success_at=row.get("last_success_at")),
            UpstreamState(), reason_code="refresh",
        )
        out.append(CheckUpdatesResult(
            customer_tracking_id=uid,
            fresh=(decision.branch == Branch.REUSE_FRESH),
            will_fetch=(decision.branch == Branch.NEED_FETCH),
        ))
    return out


def _to_view(row: dict) -> TrackingView:
    key = row.get("status") or "other"
    std = status_dict.ALL_STATUSES.get(key, status_dict.OTHER)
    events = [TrackingEventView(
        occurred_at=e.get("occurred_at") or e.get("date"),
        time_confidence=e.get("time_confidence", "low"),
        status_key=e.get("status_key", e.get("status", "other")),
        label_zh=e.get("label_zh", std.label_zh),
        description=e.get("description", e.get("description_zh", "")),
        location=e.get("location"),
        event_code=e.get("event_code"),
    ) for e in (row.get("events") or []) if isinstance(e, dict)]
    return TrackingView(
        id=row["customer_tracking_id"],
        normalized_number=row.get("normalized_number", ""),
        status_key=std.key, label_zh=std.label_zh,
        is_terminal=std.key in status_dict.TERMINAL_STATUSES,
        simulated=False,  # 生产客户页面的投影恒为真实来源
        events=events,
    )
