"""SSE 路由：GET /api/v1/events（09 §3.1/§5.4）。

触发式呈现：客户打开进度页才订阅。
推送链路（b/0003 触发器 + api.notify）：
  projection_event 新行 → pg_notify → PgListener(LISTEN) → NotifierHub
  按 customer_id 扇出 → 本路由即时回读该客户的投影事件并推送。
事件正文始终按租户权限回读 B 库，NOTIFY 载荷只作唤醒信号。
Last-Event-ID 重连语义不变：游标推进只依赖 B 库行序，重放不触发新业务。
监听不可用时自动降级为节流轮询（每 2s，与旧实现一致），不丢事件。
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from api.data import BRepository
from api.deps import Subject, current_subject, get_repo

router = APIRouter(prefix="/api/v1", tags=["events"])

_WHITELIST_KINDS = {"operation.progress", "tracking.updated", "batch.completed"}
_KEEPALIVE_S = 25.0
_FALLBACK_POLL_S = 2.0


def _frame(r: dict) -> str:
    """一行 SSE 事件帧（id/event/data，白名单过滤 + 白名单字段投影）。"""
    kind = r["payload"].get("kind", "")
    if kind not in _WHITELIST_KINDS:
        return ""  # 白名单外：游标已推进但不推送（不泄露内部事件）
    payload = {k: r["payload"][k] for k in
               ("operation_id", "customer_tracking_id", "summary")
               if k in r["payload"]}
    evt = {"event_id": r["event_id"], "type": kind,
           "occurred_at": r["created_at"], "payload": payload}
    return (f"id: {r['event_id']}\nevent: {kind}\n"
            f"data: {json.dumps(evt, ensure_ascii=False)}\n\n")


async def sse_stream(repo: BRepository, customer_id: int, hub,
                     last_event_id: str | None,
                     disconnected) -> "asyncio.Generator[str, None, None]":
    """SSE 事件流（推送为主、轮询兜底）；disconnected 为可注入断连探针。"""
    cursor = int(last_event_id or 0)
    queue = hub.subscribe(customer_id) if hub is not None else None
    try:
        # 连接即追赶：新订阅补发积压 + Last-Event-ID 重放。
        for r in repo.projection_events(customer_id, after=cursor, limit=50):
            cursor = max(cursor, r["event_id"])
            frame = _frame(r)
            if frame:
                yield frame
        while True:
            if await disconnected():
                break
            if queue is not None:
                try:
                    await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_S)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
            else:
                await asyncio.sleep(_FALLBACK_POLL_S)
            # 唤醒后回读（可能积压多条，一次取尽游标）。
            for r in repo.projection_events(customer_id, after=cursor, limit=50):
                cursor = max(cursor, r["event_id"])
                frame = _frame(r)
                if frame:
                    yield frame
    finally:
        if queue is not None:
            hub.unsubscribe(customer_id, queue)


@router.get("/events")
async def events(request: Request,
                 last_event_id: str | None = None,
                 subject: Subject = Depends(current_subject),
                 repo: BRepository = Depends(get_repo)):
    hub = getattr(request.app.state, "event_hub", None)

    async def stream():
        async def _disconnected():
            return await request.is_disconnected()
        async for chunk in sse_stream(repo, subject.customer_id, hub,
                                      last_event_id, _disconnected):
            yield chunk

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
