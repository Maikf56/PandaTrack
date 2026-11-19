"""管理端认证路由：/api/v1/admin/auth/*（03 §3.1，独立域名+独立会话）。"""
from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Body, Depends, Request, Response

from pandatrack_common import codes

from api.data import BRepository
from api.deps import get_repo
from api.errors import ApiProblem

router = APIRouter(prefix="/api/v1/admin/auth", tags=["admin-auth"])

ADMIN_COOKIE = "pt_admin_session"


@router.post("/login")
def admin_login(
    response: Response,
    payload: dict[str, Any] = Body(...),
    repo: BRepository = Depends(get_repo),
):
    """管理端登录（JSON body：username + password）。"""
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    if not username or not password:
        raise ApiProblem(codes.INVALID_INPUT)
    subject = repo.authenticate_admin(username, password)
    if subject is None:
        raise ApiProblem(codes.UNAUTHORIZED)
    token = secrets.token_urlsafe(32)
    repo.create_admin_session(subject, token, ttl_seconds=1800)
    response.set_cookie(ADMIN_COOKIE, token, httponly=True,
                        samesite="lax", max_age=1800, path="/api/v1/admin")
    return {"admin_id": subject["public_id"], "username": subject["username"],
            "role": subject["role"]}


@router.post("/logout")
def admin_logout(response: Response):
    response.delete_cookie(ADMIN_COOKIE, path="/api/v1/admin")
    return {"ok": True}


def get_admin_subject(request: Request, repo: BRepository = Depends(get_repo)):
    token = request.cookies.get(ADMIN_COOKIE, "")
    if not token:
        raise ApiProblem(codes.UNAUTHORIZED)
    s = repo.resolve_admin_session(token)
    if s is None:
        raise ApiProblem(codes.SESSION_EXPIRED)
    return s

