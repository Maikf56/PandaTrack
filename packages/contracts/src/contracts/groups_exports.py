"""次要页面对外契约（04 §5.8-5.12：组与批次/导入/导出/统计/设置）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class GroupView(BaseModel):
    id: str
    name: str
    is_default: bool = False
    archived: bool = False
    tracking_count: int = 0
    batch_count: int = 0
    status_distribution: dict[str, int] = Field(default_factory=dict)
    created_at: str = ""


class CreateGroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class RenameGroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class ArchiveGroupRequest(BaseModel):
    archived: bool


class BatchView(BaseModel):
    id: str
    state: str = ""
    total_count: int = 0
    valid_count: int = 0
    points_charged: int = 0
    group_name: str | None = None
    status_distribution: dict[str, int] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class BatchDetail(BaseModel):
    id: str
    state: str = ""
    total_count: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    points_charged: int = 0
    completed: int = 0
    processing: int = 0
    missing: int = 0
    created_at: str = ""
    updated_at: str = ""


class ImportJobView(BaseModel):
    id: str
    file_name: str | None = None
    status: str = ""
    total: int = 0
    done: int = 0
    enqueued: int = 0
    success_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    duplicate_count: int = 0
    operation_id: str | None = None
    created_at: str = ""


class ExportJobView(BaseModel):
    id: str
    scope: str = "all"
    scope_ref: str | None = None
    format: str = "csv"
    file_name: str | None = None
    row_count: int = 0
    status: str = ""
    expired: bool = False
    expires_at: str | None = None
    created_at: str = ""
    download_url: str | None = None  # 仅创建响应短期携带


class CreateExportRequest(BaseModel):
    scope: str = Field(pattern="^(all|group|batch)$")
    scope_ref: str | None = None


class StatsView(BaseModel):
    days: int = 30
    submissions: int = 0
    tracking_count: int = 0
    points_charged: int = 0
    waived_count: int = 0
    status_distribution: dict[str, int] = Field(default_factory=dict)
    daily: list[dict] = Field(default_factory=list)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=100)
    revoke_others: bool = True


class SessionView(BaseModel):
    id: int
    created_at: str = ""
    expires_at: str = ""
    revoked: bool = False
    current: bool = False


class PreferencesUpdate(BaseModel):
    timezone: str | None = Field(default=None, max_length=50)
    default_sort: str | None = Field(default=None, pattern="^(created_asc|created_desc|status)$")
