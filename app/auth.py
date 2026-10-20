"""认证、令牌、RBAC 与数据范围校验。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.errors import forbidden, too_many_requests, unauthorized
from app.models import Community, RefreshToken, Tenant, User
from app.utils import utcnow

JWT_ISSUER = "neighbor-charging"
PBKDF2_ITERATIONS = 210_000
bearer_scheme = HTTPBearer(auto_error=False)

# 进程内登录失败计数；多进程生产环境应替换为 Redis
_login_failures: dict[str, list[float]] = defaultdict(list)
_login_lock_window = settings.login_window_seconds


def hash_password(password: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS)
    encoded = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${encoded}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)
        )
        return hmac.compare_digest(
            base64.urlsafe_b64encode(expected).decode("ascii"), digest
        )
    except (ValueError, TypeError):
        return False


def _client_key(request: Request, username: str) -> str:
    ip = get_client_ip(request) or "unknown"
    return f"{ip}:{username.lower()}"


def get_client_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else None


def login_rate_limited(request: Request, username: str) -> bool:
    key = _client_key(request, username)
    now = time.monotonic()
    attempts = [t for t in _login_failures.get(key, []) if now - t < _login_lock_window]
    _login_failures[key] = attempts
    return len(attempts) >= settings.login_max_attempts


def record_login_failure(request: Request, username: str) -> None:
    _login_failures[_client_key(request, username)].append(time.monotonic())


def clear_login_failures(request: Request, username: str) -> None:
    _login_failures.pop(_client_key(request, username), None)


def create_access_token(user: User) -> tuple[str, int]:
    expires_in = settings.access_token_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "tid": user.tenant_id,
        "role": user.role,
        "name": user.display_name,
        "typ": "access",
        "jti": secrets.token_hex(12),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "iss": JWT_ISSUER,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=JWT_ISSUER,
            options={"require": ["exp", "sub", "tid", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise unauthorized("登录已过期，请重新登录", "TOKEN_EXPIRED") from exc
    except jwt.PyJWTError as exc:
        raise unauthorized("无效的访问令牌", "TOKEN_INVALID") from exc
    if payload.get("typ") != "access":
        raise unauthorized("无效的访问令牌", "TOKEN_INVALID")
    return payload


def _hash_refresh(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_refresh_token(db: Session, user: User, request: Optional[Request] = None) -> str:
    raw = secrets.token_urlsafe(48)
    record = RefreshToken(
        tenant_id=user.tenant_id,
        user_id=user.id,
        token_hash=_hash_refresh(raw),
        expires_at=utcnow() + timedelta(days=settings.refresh_token_days),
        user_agent=(request.headers.get("user-agent", "")[:250] if request else None),
    )
    db.add(record)
    db.flush()
    return raw


def rotate_refresh_token(db: Session, raw_token: str, request: Optional[Request] = None) -> tuple[User, str]:
    record = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == _hash_refresh(raw_token))
        .first()
    )
    if not record or record.revoked_at is not None or record.expires_at < utcnow():
        raise unauthorized("刷新令牌已失效，请重新登录", "REFRESH_INVALID")
    user = db.get(User, record.user_id)
    if not user or user.status != "active":
        raise unauthorized("用户不可用", "USER_DISABLED")
    record.revoked_at = utcnow()
    new_raw = issue_refresh_token(db, user, request)
    return user, new_raw


def revoke_refresh_token(db: Session, raw_token: str) -> None:
    record = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == _hash_refresh(raw_token))
        .first()
    )
    if record and record.revoked_at is None:
        record.revoked_at = utcnow()


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise unauthorized("请先登录", "TOKEN_MISSING")
    payload = decode_access_token(credentials.credentials)
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise unauthorized("用户不存在", "TOKEN_INVALID")
    if user.status != "active":
        raise forbidden("账号已停用，请联系管理员", "USER_DISABLED")
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None or tenant.status != "active":
        raise forbidden("租户已停用", "TENANT_DISABLED")
    request.state.user = user
    request.state.tenant_id = user.tenant_id
    return user


def require_roles(*roles: str):
    """生成角色依赖；admin 始终放行。"""

    allowed = set(roles) | {"admin"}

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise forbidden()
        return user

    return checker


require_staff = require_roles("operator", "technician", "finance")
require_operator = require_roles("operator")
require_finance = require_roles("finance")
require_admin = require_roles("admin")


def is_admin(user: User) -> bool:
    return user.role == "admin"


def is_staff(user: User) -> bool:
    return user.role in {"admin", "operator", "technician", "finance"}


def community_ids_for(user: User) -> Optional[set[int]]:
    """返回用户可访问社区；None 表示管理员全量。"""
    if is_admin(user):
        return None
    return {c.id for c in user.communities}


def ensure_community_access(user: User, community_id: int) -> None:
    scope = community_ids_for(user)
    if scope is not None and community_id not in scope:
        raise forbidden("无权访问该社区数据", "COMMUNITY_FORBIDDEN")


def scope_statement(stmt: Select, model, user: User) -> Select:
    """为查询附加租户与社区范围。"""
    stmt = stmt.where(model.tenant_id == user.tenant_id)
    scope = community_ids_for(user)
    if scope is not None:
        if not scope:
            stmt = stmt.where(model.community_id.in_([-1]))
        else:
            stmt = stmt.where(model.community_id.in_(scope))
    return stmt


def assert_scope_ids(user: User, requested_ids: Iterable[int]) -> None:
    scope = community_ids_for(user)
    if scope is None:
        return
    for cid in requested_ids:
        if cid not in scope:
            raise forbidden("请求包含未授权的社区", "COMMUNITY_FORBIDDEN")


def user_community_names(user: User) -> list[str]:
    return [c.name for c in user.communities]


def validate_password_strength(password: str) -> None:
    from app.errors import bad_request

    if len(password) < 8:
        raise bad_request("密码至少 8 位", "WEAK_PASSWORD")
    if password.lower() == password or password.upper() == password:
        # 演示环境允许多数字符组合；仅做最低要求，避免阻塞
        pass


def community_scope_payload(user: User) -> list[dict]:
    return [
        {"id": c.id, "name": c.name, "code": c.code}
        for c in sorted(user.communities, key=lambda item: item.name)
    ]


def tenant_payload(user: User, db: Session) -> dict:
    tenant = db.get(Tenant, user.tenant_id)
    return {"id": tenant.id, "name": tenant.name, "code": tenant.code} if tenant else {}
