"""Provider 输入/输出契约（模块 02 §4，内部数据类，非对外 API）。

设计要点：
- 输入只接受规范化单号（06 Cleaner 产物），禁止客户原文直接送上游；
- 批量返回 items[]，每项独立携带结果或 item_error_class，不允许只报
  "整批成功"而无逐项映射（02 §4.2 / §5.4）；
- 写库前检查 simulated/source，生产启用时 simulated=true 或来源缺失按
  source_invalid 拒绝（02 §4.3）；
- 单号/证据引用一律脱敏：对外 tracking_ref = 前4位 + 8位哈希。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from worker.provider.errors import ProviderError


def tracking_ref(normalized_number: str) -> str:
    """脱敏单号引用：前 4 位 + 8 位 sha256（02 §5.5.1）。"""
    if not normalized_number:
        return ""
    h = hashlib.sha256(normalized_number.encode()).hexdigest()[:8]
    return f"{normalized_number[:4]}{h}"


@dataclass(frozen=True, slots=True)
class ProviderInput:
    """单次页面查询输入（02 §4.1）。"""

    normalized_number: str            # 06 清洗后的规范单号
    job_ref: str                      # FetchJob 脱敏引用，不暴露给客户
    reason: str = "initial"           # initial / refresh / manual_recheck
    provider_config_version: str = ""
    parser_version: str = ""
    session_ref: str = ""             # profile/会话脱敏标识，禁止 Cookie 原文


@dataclass(slots=True)
class ProviderEvent:
    """标准事件事实（对齐 05 tracking_event 字段与 02 §4.2）。"""

    event_fingerprint: str            # 稳定去重键
    occurred_at: datetime | None      # 页面本地时间，未确认时区不伪造 UTC
    status: str
    description_raw: str
    description_zh: str
    location: str
    event_code: str
    time_confidence: str              # exact | low


@dataclass(slots=True)
class ProviderItem:
    """单号级结果（成功或失败二选一，02 §4.2）。"""

    normalized_number: str
    source: str = ""                  # usps_web | mock
    simulated: bool = False
    raw_status: str = ""
    status: str = ""
    events: list[ProviderEvent] = field(default_factory=list)
    http_status: int | None = None
    page_class: str = ""
    page_valid: bool = False
    confidence: float = 0.0
    parser_version: str = ""
    raw_payload_ref: str = ""         # 脱敏证据引用，非原始HTML
    fetched_at: datetime | None = None
    error_class: str | None = None    # 整批级错误时为批次错误；成功为 None
    item_error_class: str | None = None  # 单项失败类别（02 §4.2）

    @property
    def ref(self) -> str:
        return tracking_ref(self.normalized_number)

    @classmethod
    def succeed(cls, normalized_number: str, **kw) -> "ProviderItem":
        return cls(normalized_number=normalized_number, **kw)

    @classmethod
    def fail(cls, normalized_number: str, error_class: str,
             *, batch_level: bool = False, **kw) -> "ProviderItem":
        item = cls(normalized_number=normalized_number, **kw)
        if batch_level:
            item.error_class = error_class
        else:
            item.item_error_class = error_class
        return item

    def assert_source_valid(self) -> None:
        """生产写库前来源校验（02 §4.3），不合格按 source_invalid 拒绝。"""
        if self.simulated or self.source != "usps_web" or not self.source:
            raise ProviderError("source_invalid", f"来源无效: {self.ref}")


@dataclass(slots=True)
class ProviderResult:
    """一次 Provider.fetch 的返回值（02 §4.2 批量契约）。"""

    items: list[ProviderItem] = field(default_factory=list)
    provider_config_version: str = ""
    fetched_at: datetime | None = field(default_factory=lambda: datetime.now(timezone.utc))
    # 批次级错误：整批拒绝时设置，items 内各项也带 error_class。
    batch_error_class: str | None = None

    @property
    def ok(self) -> bool:
        return self.batch_error_class is None and all(
            i.item_error_class is None and i.error_class is None for i in self.items)
