"""客户资料契约（P17）：管理端建号/改资料 + 客户自助资料。

customer 表资料字段（b/0008）：name/phone/remark，均 NOT NULL DEFAULT ''。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AdminCustomerCreateRequest(BaseModel):
    """管理端手动开户（P17）：建号即 active，可指定初始积分（写 admin_adjust 台账）。"""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=100)
    phone: str = Field(default="", max_length=30)
    remark: str = Field(default="", max_length=500)
    initial_points: int = Field(default=0, ge=0, le=100_000_000)


class AdminCustomerUpdateRequest(BaseModel):
    """管理端改客户资料/邮箱/重置密码：全部可选，至少提供一项。

    审计只记变更字段名，不记密码值。
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=30)
    remark: str | None = Field(default=None, max_length=500)
    email: EmailStr | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=128)


class ProfileUpdateRequest(BaseModel):
    """客户自助资料维护（设置页）：仅 name/phone/remark，不可改邮箱。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=30)
    remark: str | None = Field(default=None, max_length=500)


class CustomerProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    name: str = ""
    phone: str = ""
    remark: str = ""
