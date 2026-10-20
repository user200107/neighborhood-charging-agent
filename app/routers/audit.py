"""审计日志查询。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.db import get_db
from app.models import AuditLog, User
from app.serializers import audit_public
from app.utils import paginate, parse_datetime

router = APIRouter(prefix="/api/audit", tags=["审计"])


@router.get("", summary="审计日志")
def list_audit(
    action: Optional[str] = None,
    actor: Optional[str] = None,
    result: Optional[str] = None,
    keyword: Optional[str] = None,
    starts_at: Optional[str] = None,
    ends_at: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(AuditLog).filter(AuditLog.tenant_id == user.tenant_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if actor:
        query = query.filter(AuditLog.actor_name.ilike(f"%{actor}%"))
    if result:
        query = query.filter(AuditLog.result == result)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (AuditLog.resource_id.ilike(like))
            | (AuditLog.actor_name.ilike(like))
            | (AuditLog.trace_id.ilike(like))
        )
    start = parse_datetime(starts_at)
    end = parse_datetime(ends_at)
    if start:
        query = query.filter(AuditLog.created_at >= start)
    if end:
        query = query.filter(AuditLog.created_at <= end)
    total = query.count()
    logs = (
        query.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return paginate([audit_public(log) for log in logs], total, page, page_size)


@router.get("/actions", summary="审计动作列表")
def list_actions(
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    rows = (
        db.query(AuditLog.action)
        .filter(AuditLog.tenant_id == user.tenant_id)
        .distinct()
        .order_by(AuditLog.action)
        .all()
    )
    return {"items": [row[0] for row in rows]}
