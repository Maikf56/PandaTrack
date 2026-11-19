"""统一错误响应映射（09 §3.2/§4，契约源 packages/contracts/common.py）。

客户响应只含 detail.code + 白话 message；禁止泄露上游状态、代理、浏览器、
数据库或内部异常文本。内部异常经映射后以安全白话输出。
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from pandatrack_common import codes


class ApiProblem(Exception):
    """BFF 内部业务异常，携带稳定的对外错误码与可选扩展字段。

    用普通类（非 dataclass）：Exception 子类配 dataclass(slots) + 自定义 __init__
    在 Python 3.12 下 super() 会报 "obj must be instance or subtype"。
    """

    def __init__(self, error_code: codes.ErrorCode, extra: dict | None = None):
        super().__init__(error_code.code)
        self.error_code = error_code
        self.extra = extra


def problem_response(problem: ApiProblem) -> JSONResponse:
    detail = {"code": problem.error_code.code,
              "message": problem.error_code.default_message}
    if problem.extra:
        detail.update(problem.extra)  # 白名单扩展（如 required/available）
    return JSONResponse(status_code=problem.error_code.http_status,
                        content={"detail": detail})


async def api_problem_handler(_: Request, exc: ApiProblem) -> JSONResponse:
    return problem_response(exc)


# 业务异常 → 对外错误码（06/09 分类映射）。
def map_billing_error(exc: Exception) -> ApiProblem:
    name = type(exc).__name__
    mapping = {
        "IdempotencyConflict": codes.IDEMPOTENCY_CONFLICT,
        "InsufficientBalance": codes.INSUFFICIENT_POINTS,
        "RequestTooLarge": codes.REQUEST_TOO_LARGE,
        "InvalidInput": codes.INVALID_INPUT,
    }
    return ApiProblem(mapping.get(name, codes.INTERNAL_ERROR))
