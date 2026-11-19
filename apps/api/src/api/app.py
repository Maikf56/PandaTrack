"""BFF FastAPI 应用工厂（03/04/09）。

- 只持有 B 库 DSN（09 §3.3：BFF 不碰 A 库）；
- 统一错误体中间件：ApiProblem → detail.code/message，不泄露内部异常；
- 安全响应头（04 §安全），CSP 由 Nginx 补；
- DSN 从环境变量 DATABASE_B_URL 注入，代码无硬编码秘密。
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from pandatrack_common import codes

from api.data import BRepository
from api.errors import ApiProblem, api_problem_handler
from api.notify import DEFAULT_CHANNEL, NotifierHub, PgListener
from api.routes import auth, billing, events, meta, submissions, tracking


def _env_bool(name: str, default: str = "true") -> bool:
    return (os.environ.get(name, default) or default).strip().lower() in (
        "1", "true", "yes", "on")


def create_app(dsn: str | None = None, dsn_a: str | None = None) -> FastAPI:
    dsn = dsn or os.environ.get("DATABASE_B_URL", "")
    dsn_a = dsn_a or os.environ.get("DATABASE_A_URL", "")

    # SSE 推送：B 库 LISTEN/NOTIFY（b/0003 触发器）；未启用时路由降级轮询。
    event_hub = NotifierHub()
    listener: PgListener | None = None
    if dsn and _env_bool("PT_EVENT_LISTEN"):
        listener = PgListener(
            dsn, event_hub,
            channel=os.environ.get("PT_EVENT_CHANNEL", DEFAULT_CHANNEL))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        import asyncio
        event_hub.bind_loop(asyncio.get_running_loop())
        if listener is not None:
            listener.start()
        yield
        if listener is not None:
            listener.stop()

    app = FastAPI(title="PandaTrack BFF", version="0.1.0",
                  lifespan=lifespan)

    app.state.repo = (BRepository(dsn, dsn_a=dsn_a or None)
                      if dsn else None)
    app.state.event_hub = event_hub

    app.add_exception_handler(ApiProblem, api_problem_handler)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_, exc: RequestValidationError):
        # Pydantic 校验失败 → invalid_input，不回显内部字段名细节。
        return JSONResponse(
            status_code=codes.INVALID_INPUT.http_status,
            content={"detail": {"code": codes.INVALID_INPUT.code,
                                "message": codes.INVALID_INPUT.default_message}},
        )

    @app.middleware("http")
    async def security_headers(request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    for r in (auth, submissions, tracking, billing, events, meta):
        app.include_router(r.router)
    # 管理端路由（独立域名 + 独立鉴权，路径隔离 /api/v1/admin）
    from api.routes import admin_auth, admin_customers, admin_providers, admin_billing, admin_audit  # noqa: F401
    for r in (admin_auth, admin_customers, admin_providers, admin_billing, admin_audit):
        app.include_router(r.router)

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "b_configured": app.state.repo is not None}

    return app


app = create_app()
