"""邀请好友契约（P15 脚手架）。

奖励闭环依赖「开放注册」——当前系统账号由管理员开通，注册开放前
统计恒为 0，页面文案明确说明。奖励规则（对齐竞品口径，未生效）：
好友注册并领取体验积分后，邀请人获得 1000 积分一次性奖励；
好友每次充值按金额 10% 积分返利（赠送积分不计入）。
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
