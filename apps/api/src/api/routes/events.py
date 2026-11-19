"""SSE 路由：GET /api/v1/events（09 §3.1/§5.4）。

触发式呈现：客户打开进度页才订阅。支持 Last-Event-ID 重连（不触发新业务）。
实现采用服务端节流轮询 projection_event（B 库），每个事件经白名单投影，
不含内部错误码/代理/A库信息。真实长连接推送在服务器验收区标定。
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from api.data import BRepository
from api.deps import Subject, current_subject, get_repo

router = APIRouter(prefix="/api/v1", tags=["events"])

_WHITELIST_KINDS = {"operation.progress", "tracking.updated", "batch.completed"}


@router.get("/events")
async def events(request: Request,
                 last_event_id: str | None = None,
                 subject: Subject = Depends(current_subject),
                 repo: BRepository = Depends(get_repo)):
    async def stream():
        cursor = int(last_event_id or 0)
        idle = 0
        while True:
            if await request.is_disconnected():
                break
            rows = repo.projection_events(subject.customer_id, after=cursor, limit=50)
            if rows:
                idle = 0
                for r in rows:
                    cursor = max(cursor, r["event_id"])
                    kind = r["payload"].get("kind", "")
                    if kind not in _WHITELIST_KINDS:
                        continue  # 白名单过滤，不泄露内部事件
                    payload = {k: r["payload"][k] for k in
                               ("operation_id", "customer_tracking_id", "summary")
                               if k in r["payload"]}
                    evt = {
                        "event_id": r["event_id"],
                        "type": kind,
                        "occurred_at": r["created_at"],
                        "payload": payload,
                    }
                    yield f"id: {r['event_id']}\nevent: {kind}\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"
            else:
                idle += 1
                if idle % 20 == 0:
                    yield ": keepalive\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
