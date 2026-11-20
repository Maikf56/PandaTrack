"""登录/会话契约（04 公共路由 / 09 §5）。

会话经 HttpOnly Cookie；登录速率限制与安全响应头由 BFF 层落实。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    client_request_id: str = Field(min_length=8, max_length=50)


class LoginResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str          # 对外 UUID
    email: EmailStr
    role: str = "member"      # member | tenant_admin
    tenant_id: str | None = None


class AuthMeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str
    email: EmailStr
    role: str
    tenant_id: str | None = None
    balance: int = Field(ge=0)


class RegisterRequest(BaseModel):
    """开放注册（P16）：注册即建号，status=pending，管理员审核通过后才可登录。

    invite_code 可选（P17 邀请闭环）：有效邀请码记入 invite_friend（邀请关系），
    好友审核通过激活时邀请人获 500 积分奖励；无效邀请码拒绝注册（提前暴露笔误）。
    """

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    client_request_id: str = Field(min_length=8, max_length=50)
    invite_code: str | None = Field(default=None, max_length=16)


class RegisterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "pending"   # 恒为 pending：审核由管理端完成
