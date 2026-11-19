"""统一错误契约与通用字段（09 §4）。

错误体格式：{"detail": {"code": "...", "message": "...", ...扩展}}
错误码字典在 pandatrack_common.codes；本文件只定义传输结构。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from pandatrack_common import codes as error_codes


class ErrorBody(BaseModel):
    """detail 载荷：code 稳定、message 白话、可选扩展字段（如 required/available）。"""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=3, max_length=50)
    message: str = Field(min_length=1, max_length=200)
    extensions: dict[str, Any] | None = None


class ApiError(BaseModel):
    """对外统一错误响应（HTTP 非 2xx 的 JSON body）。"""

    model_config = ConfigDict(extra="forbid")

    detail: ErrorBody

    @classmethod
    def from_code(cls, code: str, *, message_override: str | None = None, **ext: Any) -> "ApiError":
        ec = error_codes.get(code)
        if ec is None:
            raise ValueError(f"未登记的错误码: {code}（错误码必须先在 pandatrack_common.codes 登记）")
        return cls(detail=ErrorBody(
            code=ec.code,
            message=message_override or ec.default_message,
            extensions=ext or None,
        ))

    @property
    def http_status(self) -> int:
        ec = error_codes.get(self.detail.code)
        return ec.http_status if ec else 500


class PublicIdMixin(BaseModel):
    """对外 ID 约定：一律 UUID 字符串（05 §3 / 11 号文档裁定）。"""

    id: str = Field(pattern=r"^[0-9a-f]{32}$|^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
