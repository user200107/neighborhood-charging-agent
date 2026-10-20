"""用户与角色管理（管理员）。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.auth import community_ids_for, get_current_user, hash_password, require_roles
from app.constants import ROLE_LABELS
from app.db import get_db
from app.errors import bad_request, conflict, forbidden, not_found
from app.models import Community, User
from app.schemas import UserCreateRequest, UserUpdateRequest
from app.serializers import user_public
from app.services.audit import record_audit

router = APIRouter(prefix="/api/users", tags=["用户与角色"])


@router.get("/roles", summary="角色字典")
def list_roles(user: User = Depends(get_current_user)) -> dict:
    return {"items": [{"key": key, "label": label} for key, label in ROLE_LABELS.items()]}


@router.get("", summary="用户列表")
def list_users(
    role: Optional[str] = None,
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_roles("operator")),
    db: Session = Depends(get_db),
) -> dict:
    scope = community_ids_for(user)
    query = db.query(User).filter(User.tenant_id == user.tenant_id)
    if user.role != "admin":
        # 运营人员只能看到自己授权社区内的用户
        if scope is not None:
            query = query.filter(User.communities.any(Community.id.in_(scope or [-1])))
    if role:
        query = query.filter(User.role == role)
    if status:
        query = query.filter(User.status == status)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter((User.display_name.ilike(like)) | (User.username.ilike(like)))
    total = query.count()
    users = (
        query.order_by(User.role, User.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [user_public(u, include_phone=True) for u in users],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@router.post("", summary="创建用户", status_code=201)
def create_user(
    payload: UserCreateRequest,
    request: Request,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    username = payload.username.strip().lower()
    exists = (
        db.query(User)
        .filter(User.tenant_id == user.tenant_id, User.username == username)
        .first()
    )
    if exists:
        raise conflict("用户名已存在", "USERNAME_EXISTS")
    communities = (
        db.query(Community)
        .filter(
            Community.tenant_id == user.tenant_id,
            Community.id.in_(payload.community_ids or []),
        )
        .all()
    )
    if len(communities) != len(set(payload.community_ids or [])):
        raise bad_request("包含无效的社区", "COMMUNITY_INVALID")
    new_user = User(
        tenant_id=user.tenant_id,
        username=username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        role=payload.role,
        phone=payload.phone,
        email=payload.email,
        status="active",
    )
    new_user.communities = communities
    db.add(new_user)
    db.flush()
    record_audit(
        db,
        action="user.created",
        user=user,
        resource_type="user",
        resource_id=new_user.id,
        detail={"username": username, "role": payload.role},
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return user_public(new_user, include_phone=True)


@router.patch("/{user_id}", summary="更新用户")
def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    request: Request,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    target = db.get(User, user_id)
    if not target or target.tenant_id != user.tenant_id:
        raise not_found("用户不存在")
    if target.id == user.id and payload.status == "disabled":
        raise bad_request("不能停用自己", "SELF_DISABLE_FORBIDDEN")
    if payload.display_name is not None:
        target.display_name = payload.display_name
    if payload.role is not None:
        target.role = payload.role
    if payload.status is not None:
        target.status = payload.status
        if payload.status == "disabled":
            from app.models import RefreshToken
            from app.utils import utcnow

            db.query(RefreshToken).filter(RefreshToken.user_id == target.id).update(
                {RefreshToken.revoked_at: utcnow()}
            )
    if payload.phone is not None:
        target.phone = payload.phone
    if payload.email is not None:
        target.email = payload.email
    if payload.community_ids is not None:
        communities = (
            db.query(Community)
            .filter(
                Community.tenant_id == user.tenant_id,
                Community.id.in_(payload.community_ids),
            )
            .all()
        )
        if len(communities) != len(set(payload.community_ids)):
            raise bad_request("包含无效的社区", "COMMUNITY_INVALID")
        target.communities = communities
    record_audit(
        db,
        action="user.updated",
        user=user,
        resource_type="user",
        resource_id=target.id,
        detail=payload.model_dump(exclude_none=True),
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return user_public(target, include_phone=True)
