"""提交契约（06 §直接提交事务 / 09 §5）。

- 无预览步骤：POST /api/v1/submissions 直接受理 → 202；
- 单次 ≤35 条（SUBMIT_SINGLE_LIMIT），批量受理总量 ≤1,000,000；
- 幂等键 client_request_id：网络重试复用同一 ID；同 ID 不同内容 → idempotency_conflict；
- 计费由服务端完成，响应只回实际扣费（前端不自算）。
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SubmitSource(StrEnum):
    """提交来源：粘贴文本行 或 文件上传（04 §2）。"""

    PASTE = "paste"
    FILE = "file"


class SubmissionCreate(BaseModel):
    """客户提交请求体（body 为文本行；文件走 multipart，服务端同样按行解析）。"""

    model_config = ConfigDict(extra="forbid")

    source: SubmitSource
    client_request_id: str = Field(min_length=8, max_length=50)
    # 粘贴来源：原始行数组，每行 ≤100 字符，总行数 ≤35（即时结果路径）
    lines: list[str] | None = Field(default=None, max_length=35)
    # 文件来源：导入任务引用（>35 条走异步导入，04 §2 大批量分路径）
    import_file_ref: str | None = Field(default=None, max_length=200)
    target_group_name: str | None = Field(default=None, max_length=50)


class SubmissionInvalidItem(BaseModel):
    """清洗后无效行（06 Cleaner v1 产出）。"""

    model_config = ConfigDict(extra="forbid")

    line_no: int = Field(ge=1)
    raw: str = Field(max_length=100)
    reason: str = Field(max_length=50)   # empty | too_long | bad_chars | bad_format | duplicate_in_request


UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$|^[0-9a-f]{32}$"


class SubmissionAccepted(BaseModel):
    """202 受理响应：直接提交事务完成后返回。"""

    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(pattern=UUID_PATTERN)  # 对外 UUID（operation.public_id）
    total_count: int = Field(ge=0)
    valid_count: int = Field(ge=0)
    invalid_count: int = Field(ge=0)
    points_charged: int = Field(ge=0)    # 实际扣费（免扣窗口判定后）
    free_count: int = Field(default=0, ge=0)   # 滚动 30 天免扣条数
    invalid_items: list[SubmissionInvalidItem] = []
    batches: list[int] = []              # 批次序号（35 切片）


class SubmissionEstimateRequest(BaseModel):
    """预估请求（04 §5.4 实时解析面板；09 §5.2.1）：幂等、不入账、不构成报价。"""

    model_config = ConfigDict(extra="forbid")

    lines: list[str] = Field(max_length=100_000)  # 预估可覆盖大批量粘贴
    target_group_name: str | None = Field(default=None, max_length=50)


class SubmissionEstimate(BaseModel):
    """预估响应：分类计数 + 预估消耗 + 服务端余额快照（缺口不由前端计算）。"""

    model_config = ConfigDict(extra="forbid")

    total_count: int = Field(ge=0)
    billable_count: int = Field(ge=0)
    free_count: int = Field(ge=0)          # 30 天窗口内免扣
    points_estimate: int = Field(ge=0)     # billable - free
    balance: int = Field(ge=0)             # 服务端余额快照
    insufficient: bool = False
    result_counts: dict[str, int] = Field(default_factory=dict)  # 清洗结果码分布
    invalid_items: list[SubmissionInvalidItem] = []
    estimated: bool = True                 # 常驻标注「预估，以提交结果为准」


class ImportCreate(BaseModel):
    """大批量导入创建（04 §5.4 文件路径 / §5.9 导入任务）：行数组一次受理。"""

    model_config = ConfigDict(extra="forbid")

    file_name: str | None = Field(default=None, max_length=200)
    client_request_id: str = Field(min_length=8, max_length=50)
    lines: list[str] = Field(max_length=100_000)   # 单请求上限；更大拆分多次
    target_group_name: str | None = Field(default=None, max_length=50)


class ImportAccepted(BaseModel):
    """导入受理响应（202）：关联 import_job 与 operation，结果后台逐步更新。"""

    model_config = ConfigDict(extra="forbid")

    import_job_id: str = Field(pattern=UUID_PATTERN)
    operation_id: str = Field(pattern=UUID_PATTERN)
    total_count: int = Field(ge=0)
    valid_count: int = Field(ge=0)
    invalid_count: int = Field(ge=0)
    points_charged: int = Field(ge=0)
    free_count: int = Field(ge=0)
