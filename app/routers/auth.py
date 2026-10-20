"""认证接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth import (
    clear_login_failures,
    create_access_token,
    get_current_user,
    get_client_ip,
    hash_password,
    issue_refresh_token,
    login_rate_limited,
    record_login_failure,
    revoke_refresh_token,
    rotate_refresh_token,
    tenant_payload,
    verify_password,
)
from app.config import settings
from app.constants import MENU_PERMISSIONS
from app.db import get_db
from app.errors import ApiError, bad_request, unauthorized
from app.models import RefreshToken, Tenant, User
from app.schemas import LoginRequest, LogoutRequest, PasswordChangeRequest, RefreshRequest
from app.serializers import user_public
from app.services.audit import record_audit
from app.utils import iso, utcnow

router = APIRouter(prefix="/api/auth", tags=["认证"])


def menus_for(user: User) -> list[str]:
    return [key for key, roles in MENU_PERMISSIONS.items() if user.role in roles]


def session_payload(user: User, db: Session, access_token: str, expires_in: int, refresh_token: str) -> dict:
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": user_public(user, include_phone=True),
        "tenant": tenant_payload(user, db),
        "menus": menus_for(user),
        "demo_mode": settings.demo_mode,
    }


@router.post("/login", summary="登录并签发令牌")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    username = payload.username.strip().lower()
    if login_rate_limited(request, username):
        raise ApiError(429, "LOGIN_RATE_LIMITED", "登录失败次数过多，请 5 分钟后再试")

    if payload.tenant_code:
        tenant = (
            db.query(Tenant)
            .filter(Tenant.code == payload.tenant_code.strip().upper())
            .first()
        )
        if not tenant:
            raise unauthorized("用户名或密码错误", "INVALID_CREDENTIALS")
    else:
        tenant = db.query(Tenant).filter(Tenant.code == "NEIGHBOR").first()

    user = None
    if tenant:
        user = (
            db.query(User)
            .filter(User.tenant_id == tenant.id, User.username == username)
            .first()
        )

    if not user or not verify_password(payload.password, user.password_hash):
        record_login_failure(request, username)
        if tenant:
            record_audit(
                db,
                action="auth.login_failed",
                tenant_id=tenant.id,
                actor_name=username,
                actor_role="anonymous",
                result="failed",
                detail={"reason": "invalid_credentials"},
                ip=get_client_ip(request),
                trace_id=getattr(request.state, "trace_id", None),
            )
            db.commit()
        raise unauthorized("用户名或密码错误", "INVALID_CREDENTIALS")
    if user.status != "active":
        raise unauthorized("账号已停用，请联系管理员", "USER_DISABLED")
    if tenant is None or tenant.status != "active":
        raise unauthorized("租户已停用", "TENANT_DISABLED")

    clear_login_failures(request, username)
    user.last_login_at = utcnow()
    access_token, expires_in = create_access_token(user)
    refresh_token = issue_refresh_token(db, user, request)
    record_audit(
        db,
        action="auth.login",
        user=user,
        resource_type="session",
        resource_id=user.id,
        detail={"username": user.username, "role": user.role},
        ip=get_client_ip(request),
        trace_id=getattr(request.state, "trace_id", None),
    )
    db.commit()
    return session_payload(user, db, access_token, expires_in, refresh_token)


@router.post("/refresh", summary="续期访问令牌")
def refresh(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    user, refresh_token = rotate_refresh_token(db, payload.refresh_token, request)
    access_token, expires_in = create_access_token(user)
    record_audit(
        db,
        action="auth.refresh",
        user=user,
        resource_type="session",
        resource_id=user.id,
        ip=get_client_ip(request),
        trace_id=getattr(request.state, "trace_id", None),
    )
    db.commit()
    return session_payload(user, db, access_token, expires_in, refresh_token)


@router.post("/logout", summary="退出并撤销刷新令牌")
def logout(
    payload: LogoutRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if payload.refresh_token:
        revoke_refresh_token(db, payload.refresh_token)
    record_audit(
        db,
        action="auth.logout",
        user=user,
        resource_type="session",
        resource_id=user.id,
        ip=get_client_ip(request),
        trace_id=getattr(request.state, "trace_id", None),
    )
    db.commit()
    return {"message": "已退出登录"}


@router.get("/me", summary="读取当前用户与数据范围")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return {
        "user": user_public(user, include_phone=True),
        "tenant": tenant_payload(user, db),
        "menus": menus_for(user),
        "server_time": iso(utcnow()),
        "demo_mode": settings.demo_mode,
    }


@router.post("/change-password", summary="修改密码")
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not verify_password(payload.old_password, user.password_hash):
        raise bad_request("原密码不正确", "OLD_PASSWORD_INVALID")
    if verify_password(payload.new_password, user.password_hash):
        raise bad_request("新密码不能与原密码相同", "PASSWORD_UNCHANGED")
    user.password_hash = hash_password(payload.new_password)
    db.query(RefreshToken).filter(RefreshToken.user_id == user.id).update(
        {RefreshToken.revoked_at: utcnow()}
    )
    record_audit(
        db,
        action="auth.password_changed",
        user=user,
        resource_type="user",
        resource_id=user.id,
        ip=get_client_ip(request),
        trace_id=getattr(request.state, "trace_id", None),
    )
    db.commit()
    return {"message": "密码已更新，请重新登录"}
