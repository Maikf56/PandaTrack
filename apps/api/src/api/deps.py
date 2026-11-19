"""BFF 鉴权依赖（09 §3.3：身份/租户从认证上下文取，不信任请求体）。"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request

from pandatrack_common import codes

from api.data import BRepository, token_hash
from api.errors import ApiProblem

SESSION_COOKIE = "pt_session"


@dataclass(frozen=True, slots=True)
class Subject:
    customer_id: int | None
    public_id: str | None
    email: str | None
    role: str
    tenant_id: int | None
    admin_id: int | None = None
    token_hash: str = ""  # 当前会话哈希（设置页会话管理用）


def get_repo(request: Request) -> BRepository:
    repo: BRepository | None = getattr(request.app.state, "repo", None)
    if repo is None:
        raise ApiProblem(codes.INTERNAL_ERROR)
    return repo


def current_subject(request: Request,
                    repo: BRepository = Depends(get_repo)) -> Subject:
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token:
        raise ApiProblem(codes.UNAUTHORIZED)
    s = repo.resolve_session(token)
    if s is None:
        raise ApiProblem(codes.SESSION_EXPIRED)
    return Subject(customer_id=s["customer_id"], public_id=s["public_id"],
                   email=s["email"], role=s["role"], tenant_id=s["tenant_id"],
                   admin_id=s["admin_id"], token_hash=token_hash(token))


def require_customer(subject: Subject = Depends(current_subject)) -> Subject:
    if subject.customer_id is None:
        raise ApiProblem(codes.FORBIDDEN)
    return subject


def require_admin(subject: Subject = Depends(current_subject)) -> Subject:
    if subject.admin_id is None and subject.role != "admin":
        raise ApiProblem(codes.FORBIDDEN)
    return subject
