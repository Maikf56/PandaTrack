"""进度快照契约（04 批次/导入任务页 / 09 §5）。

客户触发式呈现：前端轮询 GET /api/v1/operations/{operation_id}，
不推送不弹窗；SSE 仅在客户主动打开进度页时使用。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from contracts.common import PublicIdMixin
from pandatrack_common.status import BATCH_ITEM_STATES


class BatchProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_seq: int = Field(ge=1)
    item_count: int = Field(ge=0)
    done: int = Field(ge=0)
    processing: int = Field(ge=0)
    deferred: int = Field(ge=0)          # 暂未获取
    suspended: int = Field(ge=0)         # 服务暂停（全局刷新预算耗尽等）


class OperationProgress(PublicIdMixin):
    """GET /api/v1/operations/{public_id} 响应（白名单字段）。"""

    model_config = ConfigDict(extra="forbid")

    state: str                            # accepted | processing | completed
    total_count: int = Field(ge=0)
    valid_count: int = Field(ge=0)
    invalid_count: int = Field(ge=0)
    points_charged: int = Field(ge=0)
    batches: list[BatchProgress] = []
    item_state_enum: list[str] = list(BATCH_ITEM_STATES)  # 供前端对齐枚举


class OperationSummary(BaseModel):
    """GET /api/v1/operations 列表项（04 §5.9 提交记录；按当前客户过滤）。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$|^[0-9a-f]{32}$")
    state: str
    total_count: int = Field(ge=0)
    valid_count: int = Field(ge=0)
    invalid_count: int = Field(ge=0)
    points_charged: int = Field(ge=0)
    created_at: str = ""                  # ISO-8601 UTC
