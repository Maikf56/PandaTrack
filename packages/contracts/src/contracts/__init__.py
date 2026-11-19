"""PandaTrack 权威契约包（模块 09 / 10 §4）。

本包是 API/SSE 契约的唯一权威源（11 号文档 D4 裁定）。
依赖方向约束：本包只依赖 pandatrack-common 与 pydantic，
禁止依赖任何 apps/*（10 §4）。
"""
from contracts.common import ApiError, ErrorBody
from contracts.auth import AuthMeResponse, LoginRequest, LoginResponse
from contracts.billing import (
    BillingSummary,
    LedgerEntry,
    RedemptionRequest,
    RedemptionResponse,
)
from contracts.events import SseEvent, SseEventType
from contracts.progress import BatchProgress, OperationProgress
from contracts.submission import (
    SubmissionAccepted,
    SubmissionCreate,
    SubmissionInvalidItem,
    SubmitSource,
)
from contracts.tracking import (
    CheckUpdatesRequest,
    CheckUpdatesResult,
    TrackingEventView,
    TrackingView,
)

__all__ = [
    "ApiError",
    "ErrorBody",
    "LoginRequest",
    "LoginResponse",
    "AuthMeResponse",
    "SubmissionCreate",
    "SubmissionAccepted",
    "SubmissionInvalidItem",
    "SubmitSource",
    "OperationProgress",
    "BatchProgress",
    "SseEvent",
    "SseEventType",
    "TrackingView",
    "TrackingEventView",
    "CheckUpdatesRequest",
    "CheckUpdatesResult",
    "BillingSummary",
    "LedgerEntry",
    "RedemptionRequest",
    "RedemptionResponse",
]
