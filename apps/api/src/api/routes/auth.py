"""认证路由：/api/v1/auth/login、/me（09 §5.1）。"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Response

from contracts.auth import AuthMeResponse, LoginRequest, LoginResponse
from pandatrack_common import codes

from api.data import BRepository
from api.deps import SESSION_COOKIE, Subject, current_subject, get_repo
from api.errors import ApiProblem

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, response: Response,
          repo: BRepository = Depends(get_repo)):
    subject = repo.authenticate(str(payload.email), payload.password)
    token = secrets.token_urlsafe(32)
    repo.create_session(subject, token, ttl_seconds=3600)
    # HttpOnly + SameSite=Lax；生产由 Nginx 加 Secure（04 §安全）。
    response.set_cookie(SESSION_COOKIE, token, httponly=True,
                        samesite="lax", max_age=3600, path="/")
    return LoginResponse(customer_id=subject["public_id"], email=subject["email"],
                         role=subject["role"],
                         tenant_id=str(subject["tenant_id"])
                         if subject["tenant_id"] else None)


@router.get("/me", response_model=AuthMeResponse)
def me(subject: Subject = Depends(current_subject),
       repo: BRepository = Depends(get_repo)):
    if subject.customer_id is None:
        raise ApiProblem(codes.FORBIDDEN)
    return AuthMeResponse(customer_id=subject.public_id, email=subject.email,
                          role=subject.role,
                          tenant_id=str(subject.tenant_id) if subject.tenant_id else None,
                          balance=repo.wallet_balance(subject.customer_id))


@router.post("/logout")
def logout(response: Response,
           subject: Subject = Depends(current_subject)):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}
