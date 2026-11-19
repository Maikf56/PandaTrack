"""认证路由：/api/v1/auth/login、/me（09 §5.1）。"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Request, Response

from contracts.auth import AuthMeResponse, LoginRequest, LoginResponse
from pandatrack_common import codes

from api.data import BRepository
from api.deps import SESSION_COOKIE, Subject, current_subject, get_repo
from api.errors import ApiProblem
from api.throttle import (MAX_ATTEMPTS, WINDOW_SECONDS, client_ip,
                          locked_retry_after, throttle_keys)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, response: Response,
          repo: BRepository = Depends(get_repo)):
    # 防爆破（09 §5.1）：单源 ip|email 与跨源 *|email 两级计数，锁定期 429。
    ip = client_ip(request)
    email = str(payload.email).strip().lower()
    for key in throttle_keys(ip, email):
        retry = locked_retry_after(
            repo.login_throttle_locked_until("customer", key))
        if retry is not None:
            raise ApiProblem(codes.RATE_LIMITED, {"retry_after_seconds": retry})
    subject = repo.authenticate(str(payload.email), payload.password)
    if subject is None:
        for key in throttle_keys(ip, email):
            repo.login_throttle_record_fail("customer", key,
                                            window_seconds=WINDOW_SECONDS,
                                            max_attempts=MAX_ATTEMPTS)
        raise ApiProblem(codes.UNAUTHORIZED)
    for key in throttle_keys(ip, email):
        repo.login_throttle_reset("customer", key)
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
