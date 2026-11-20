"""设置页路由（04 §5.12：改密码/会话管理/显示偏好；P17：自助资料）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from contracts.customer import CustomerProfile, ProfileUpdateRequest
from contracts.groups_exports import (
    ChangePasswordRequest, PreferencesUpdate, SessionView,
)
from pandatrack_common import codes

from api.data import BRepository
from api.deps import Subject, get_repo, require_customer
from api.errors import ApiProblem

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


@router.get("/profile", response_model=CustomerProfile)
def get_profile(subject: Subject = Depends(require_customer),
                repo: BRepository = Depends(get_repo)):
    row = repo.get_customer_profile(subject.customer_id)
    if row is None:
        raise ApiProblem(codes.FORBIDDEN)
    return CustomerProfile(**row)


@router.patch("/profile", response_model=CustomerProfile)
def update_profile(payload: ProfileUpdateRequest,
                   subject: Subject = Depends(require_customer),
                   repo: BRepository = Depends(get_repo)):
    """客户自助资料维护（P17）：仅 name/phone/remark，邮箱不在自助范围。"""
    patch = {k: v.strip() for k, v in payload.model_dump().items() if v is not None}
    if not patch:
        raise ApiProblem(codes.INVALID_INPUT)
    return CustomerProfile(**repo.update_customer_profile_self(subject.customer_id, patch))


@router.post("/password")
def change_password(payload: ChangePasswordRequest,
                    subject: Subject = Depends(require_customer),
                    repo: BRepository = Depends(get_repo)):
    ok = repo.change_password(subject.customer_id, payload.old_password,
                              payload.new_password)
    if not ok:
        raise ApiProblem(codes.UNAUTHORIZED, {"message": "原密码不正确"})
    revoked = 0
    if payload.revoke_others:
        revoked = repo.revoke_other_sessions(
            subject.customer_id, current_token_hash=subject.token_hash)
    return {"ok": True, "revoked_sessions": revoked}


@router.get("/sessions", response_model=list[SessionView])
def list_sessions(subject: Subject = Depends(require_customer),
                  repo: BRepository = Depends(get_repo)):
    return [SessionView(**r) for r in repo.list_sessions(
        subject.customer_id, current_token_hash=subject.token_hash)]


@router.post("/sessions/revoke-others")
def revoke_others(subject: Subject = Depends(require_customer),
                  repo: BRepository = Depends(get_repo)):
    n = repo.revoke_other_sessions(
        subject.customer_id, current_token_hash=subject.token_hash)
    return {"ok": True, "revoked": n}


@router.get("/preferences")
def get_preferences(subject: Subject = Depends(require_customer),
                    repo: BRepository = Depends(get_repo)):
    return repo.get_preferences(subject.customer_id)


@router.patch("/preferences")
def set_preferences(payload: PreferencesUpdate,
                    subject: Subject = Depends(require_customer),
                    repo: BRepository = Depends(get_repo)):
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not patch:
        raise ApiProblem(codes.INVALID_INPUT)
    return repo.set_preferences(subject.customer_id, patch)
