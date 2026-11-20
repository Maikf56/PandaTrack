"""邀请好友契约（P15 脚手架；P17 接通闭环）。

奖励规则（P17 用户裁定）：好友注册（带邀请码）且管理员审核通过激活后，
邀请人获得 500 积分一次性奖励（invite_friend.status: pending → rewarded）。
充值返利（原方案 10% 返利）暂不做，recharged_count 恒 0，保留字段口径。
"""
from __future__ import annotations

from pydantic import BaseModel


class InviteSummary(BaseModel):
    code: str
    invited_count: int = 0
    recharged_count: int = 0
    awarded_points: int = 0


class InviteFriendView(BaseModel):
    friend_email: str
    status: str = "pending"
    points_awarded: int = 0
    created_at: str = ""
