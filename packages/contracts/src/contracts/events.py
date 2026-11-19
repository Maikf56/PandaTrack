"""SSE 事件契约（09 §5.4）。

- 事件由 projection_event 驱动，event_id 全局唯一；
- 客户重连带 Last-Event-ID = 事件序号，服务端从该序号重放，不触发新业务操作；
- 前端仅在进度页打开时订阅（触发式呈现，04 §1）。
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SseEventType(StrEnum):
    """投影事件类型（sync-agent 写入 projection_event 的 payload.kind）。"""

    OPERATION_PROGRESS = "operation.progress"      # 进度聚合变化
    TRACKING_UPDATED = "tracking.updated"          # 单号轨迹有新事实（不携带内容，客户主动拉）
    BATCH_COMPLETED = "batch.completed"            # 批次完成


class SseEvent(BaseModel):
    """SSE data 载荷；event: <event_id>，retry: 由 BFF 端设置。"""

    model_config = ConfigDict(extra="forbid")

    event_id: int = Field(ge=1)          # 全局唯一序号 = SSE id
    type: SseEventType
    operation_id: str | None = None      # 对外 UUID
    customer_tracking_id: str | None = None
    occurred_at: str                     # ISO-8601 UTC
    payload: dict = {}                   # 事件专属白名单字段；不含内部错误码/代理/A库信息
