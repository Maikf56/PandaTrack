"""邀请好友路由（P15 脚手架）。

只读为主：邀请码获取/重置、邀请统计、好友列表。
奖励结算依赖「开放注册」——注册开放前统计恒为 0（04 契约外增值项）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from contracts.invite import InviteFriendView, InviteSummary

from api.data import BRepository
from api.deps import Subject, get_repo, require_customer

router = APIRouter(prefix="/api/v1/invites", tags=["invites"])


@router.get("/me", response_model=InviteSummary)
def my_invite(subject: Subject = Depends(require_customer),
              repo: BRepository = Depends(get_repo)):
    return InviteSummary(**repo.invite_summary(subject.customer_id))


@router.post("/regenerate", response_model=InviteSummary)
def regenerate(subject: Subject = Depends(require_customer),
               repo: BRepository = Depends(get_repo)):
    return InviteSummary(**repo.regenerate_invite(subject.customer_id))


@router.get("/friends", response_model=list[InviteFriendView])
def friends(limit: int = 50,
            subject: Subject = Depends(require_customer),
            repo: BRepository = Depends(get_repo)):
    return [InviteFriendView(**r) for r in repo.list_invite_friends(
        subject.customer_id, limit=min(limit, 200))]
