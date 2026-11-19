"""账务契约（06 积分 / 09 §5）。

钱包余额、流水、兑换码；充值走套餐（06 §6 档位），对账/冲正仅管理端（03）。
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class LedgerType(StrEnum):
    CHARGE = "charge"                    # 扣费（负向）
    REFUND = "refund"                    # 冲正/退款（正向，只记一次）
    REDEEM = "redeem"                    # 兑换码充值
    ADMIN_ADJUST = "admin_adjust"        # 管理端调整


class BillingSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    balance: int = Field(ge=0)
    frozen: int = Field(ge=0)
    lifetime_consumed: int = Field(ge=0)


class LedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ledger_id: str                       # 对外 UUID
    ledger_type: LedgerType
    points_change: int                   # 正负皆可
    description: str | None = None
    created_at: str                      # ISO-8601 UTC


class RedemptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[A-Z0-9]{4}(-[A-Z0-9]{4}){2}$")  # XXXX-XXXX-XXXX（09 §示例）


class RedemptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points_added: int = Field(ge=0)
    balance: int = Field(ge=0)
