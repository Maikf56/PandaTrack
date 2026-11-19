"""轨迹投影契约（04 §6 / 09 §5.5）。

白名单字段：客户只见 B 库投影，绝不含 USPS URL、代理、profile、
A 库表名、内部错误码、证据原文（00 §4 / 09 §3）。
轨迹 ID 一律 B 库 customer_tracking_id（对外 UUID）。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from contracts.common import PublicIdMixin


class TrackingEventView(BaseModel):
    """单条物流事件（投影白名单）。"""

    model_config = ConfigDict(extra="forbid")

    occurred_at: str | None = None       # ISO-8601；原始时间缺失时为 None
    occurred_at_local: str | None = None # 客户时区时间（04 §12.2 用例 11）
    time_confidence: str = "low"         # exact | low（闸门 6：只能是这两种）
    status_key: str                      # 12 态标准状态
    label_zh: str                        # 服务端白话标签
    description: str                     # 事件描述（原始/中文，由投影层定）
    location: str | None = None
    event_code: str | None = None


class TrackingView(PublicIdMixin):
    """GET /api/v1/trackings/{customer_tracking_id} 响应。"""

    model_config = ConfigDict(extra="forbid")

    normalized_number: str = Field(max_length=50)
    status_key: str                      # 12 态标准状态
    label_zh: str
    is_terminal: bool
    simulated: bool = False              # 正式客户页面必须为 false（04 §12.2 用例 12）
    events: list[TrackingEventView] = [] # 时间倒序


class CheckUpdatesRequest(BaseModel):
    """POST /api/v1/trackings/check-updates（04 §4 检查更新）。"""

    model_config = ConfigDict(extra="forbid")

    customer_tracking_ids: list[str] = Field(min_length=1, max_length=200)


class CheckUpdatesResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_tracking_id: str
    fresh: bool                          # True=沿用近期成功结果不触发采集
    will_fetch: bool                     # False=终态保护/预算限制下不再采集
