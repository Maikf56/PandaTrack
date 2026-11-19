"""统一错误码字典（权威源：09 §4）。

对外错误体格式固定：{"detail": {"code": "...", "message": "..."}}。
code 值 snake_case 稳定不变；message 为白话，不得泄露上游状态码、
代理、浏览器、内部数据库信息（09 §3）。
分类：身份/权限、输入、幂等、余额、Provider/任务、系统。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ErrorCode:
    """错误码定义：code 稳定 + 默认白话 message + HTTP 状态码。"""

    code: str
    default_message: str
    http_status: int


# ---- 身份 / 权限（09 分类 1）----
UNAUTHORIZED = ErrorCode("unauthorized", "邮箱或密码不正确", 401)
SESSION_EXPIRED = ErrorCode("session_expired", "登录已过期，请重新登录", 401)
FORBIDDEN = ErrorCode("forbidden", "没有权限执行此操作", 403)

# ---- 输入（09 分类 2）----
INVALID_INPUT = ErrorCode("invalid_input", "提交的内容有误", 400)
REQUEST_TOO_LARGE = ErrorCode("request_too_large", "单次提交数量超出上限", 413)
NOT_FOUND = ErrorCode("not_found", "没有找到对应记录", 404)

# ---- 幂等（09 分类 2）----
IDEMPOTENCY_CONFLICT = ErrorCode(
    "idempotency_conflict", "该请求编号已用于另一份提交内容，请重新发起", 409
)

# ---- 余额（09 分类 3；可附加 required/available 扩展字段）----
INSUFFICIENT_POINTS = ErrorCode("insufficient_points", "积分余额不足", 402)
REDEMPTION_CODE_INVALID = ErrorCode("redemption_code_invalid", "兑换码无效或已核销", 400)

# ---- Provider / 任务（09 分类 4；fail-closed 不回退 mock）----
PROVIDER_DISABLED = ErrorCode("provider_disabled", "查询服务暂未开放", 503)
PROVIDER_UNAVAILABLE = ErrorCode("provider_unavailable", "查询服务暂时不可用，已提交任务会保留", 503)
PROCESSING_FAILED = ErrorCode("processing_failed", "任务处理失败，请联系支持", 500)

# ---- 系统 / 限流（09 分类 5）----
RATE_LIMITED = ErrorCode("rate_limited", "操作过于频繁，请稍后再试", 429)
INTERNAL_ERROR = ErrorCode("internal_error", "系统繁忙，请稍后再试", 500)

ALL_ERROR_CODES: dict[str, ErrorCode] = {
    e.code: e
    for e in (
        UNAUTHORIZED, SESSION_EXPIRED, FORBIDDEN,
        INVALID_INPUT, REQUEST_TOO_LARGE, NOT_FOUND,
        IDEMPOTENCY_CONFLICT,
        INSUFFICIENT_POINTS, REDEMPTION_CODE_INVALID,
        PROVIDER_DISABLED, PROVIDER_UNAVAILABLE, PROCESSING_FAILED,
        RATE_LIMITED, INTERNAL_ERROR,
    )
}

# 09 §4 明确废弃的码：系统不设置 quote_expired / quote_conflict
FORBIDDEN_CODES = frozenset({"quote_expired", "quote_conflict"})


def get(code: str) -> ErrorCode | None:
    return ALL_ERROR_CODES.get(code)
