"""FastAPI 应用入口。"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.config import BASE_DIR, settings
from app.db import SessionLocal, database_label, init_db, ping_db
from app.errors import ApiError
from app.routers import agent, approvals, audit, auth, dashboard, events, orders, piles, reports, tickets, users
from app.seed import seed_demo_data
from app.services.simulator import simulator
from app.utils import iso, new_trace_id, utcnow

logger = logging.getLogger("charging.api")
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.seed_demo_data and settings.demo_mode:
        with SessionLocal() as db:
            created = seed_demo_data(db)
            if created:
                logger.info("demo data seeded")
    if settings.demo_mode:
        simulator.start()
    logger.info(
        "application started env=%s db=%s demo=%s",
        settings.app_env,
        database_label(),
        settings.demo_mode,
    )
    yield
    if settings.demo_mode:
        simulator.stop()
    logger.info("application stopped")


docs_enabled = not settings.is_production
app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description=(
        "邻里充电运营平台 API。所有业务接口需要 Bearer Token；写接口支持 Idempotency-Key，"
        "响应头 X-Trace-Id 可用于链路追踪。"
    ),
    lifespan=lifespan,
    docs_url="/docs" if docs_enabled else None,
    redoc_url="/redoc" if docs_enabled else None,
    openapi_url="/openapi.json" if docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=settings.cors_origin_list != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id", "Idempotency-Replayed"],
)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id") or new_trace_id()
    request.state.trace_id = trace_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled request error trace_id=%s path=%s", trace_id, request.url.path)
        raise
    duration_ms = int((time.perf_counter() - started) * 1000)
    response.headers["X-Trace-Id"] = trace_id
    response.headers["X-Response-Time"] = f"{duration_ms}ms"
    if request.url.path not in {"/api/health", "/api/health/live"}:
        logger.info(
            "request method=%s path=%s status=%s duration_ms=%s trace_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            trace_id,
        )
    return response


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if path not in {"/docs", "/redoc", "/openapi.json"}:
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
            "frame-ancestors 'self'; base-uri 'self'; form-action 'self'",
        )
    if settings.is_production and request.url.scheme == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


def _error_payload(request: Request, code: str, message: str, details=None) -> dict:
    payload = {
        "detail": message,
        "code": code,
        "trace_id": getattr(request.state, "trace_id", None),
    }
    if details is not None:
        payload["details"] = details
    return payload


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(request, exc.code, exc.message, exc.details),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = [
        {
            "field": ".".join(str(part) for part in error.get("loc", []) if part != "body"),
            "message": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_error_payload(request, "VALIDATION_ERROR", "参数校验失败", errors),
    )


@app.exception_handler(SQLAlchemyError)
async def database_exception_handler(request: Request, exc: SQLAlchemyError):
    logger.exception("database error trace_id=%s", getattr(request.state, "trace_id", None))
    return JSONResponse(
        status_code=503,
        content=_error_payload(
            request,
            "DATABASE_UNAVAILABLE",
            "数据库暂时不可用，请稍后重试",
        ),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled exception trace_id=%s", getattr(request.state, "trace_id", None))
    return JSONResponse(
        status_code=500,
        content=_error_payload(request, "INTERNAL_ERROR", "服务器内部错误，请联系管理员"),
    )


for router in (
    auth.router,
    piles.router,
    orders.router,
    tickets.router,
    approvals.router,
    dashboard.router,
    reports.router,
    audit.router,
    agent.router,
    events.router,
    users.router,
):
    app.include_router(router)


@app.get("/api", tags=["系统"], summary="API 信息")
def api_info() -> dict:
    return {
        "name": settings.app_name,
        "version": __version__,
        "docs": "/docs" if docs_enabled else None,
        "time": iso(utcnow()),
    }


@app.get("/api/health", tags=["系统"], summary="健康检查")
def health():
    ok = ping_db()
    payload = {
        "status": "ok" if ok else "degraded",
        "database": database_label(),
        "database_ok": ok,
        "version": __version__,
        "env": settings.app_env,
        "demo_mode": settings.demo_mode,
        "time": iso(utcnow()),
    }
    return JSONResponse(status_code=200 if ok else 503, content=payload)


@app.get("/api/health/live", tags=["系统"], summary="存活检查")
def liveness() -> dict:
    return {"status": "ok", "time": iso(utcnow())}


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return JSONResponse({"message": settings.app_name, "api": "/api"}, status_code=200)
    return FileResponse(index_file, headers={"Cache-Control": "no-cache"})


@app.get("/favicon.svg", include_in_schema=False)
def favicon():
    favicon_file = STATIC_DIR / "assets" / "favicon.svg"
    if favicon_file.exists():
        return FileResponse(favicon_file, media_type="image/svg+xml")
    return JSONResponse({"detail": "not found"}, status_code=404)


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    if full_path.startswith(("api/", "docs", "redoc", "openapi.json")):
        return JSONResponse({"detail": "not found"}, status_code=404)
    candidate = (STATIC_DIR / full_path).resolve()
    try:
        candidate.relative_to(STATIC_DIR.resolve())
    except ValueError:
        return JSONResponse({"detail": "not found"}, status_code=404)
    if candidate.is_file():
        return FileResponse(candidate)
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"detail": "not found"}, status_code=404)

