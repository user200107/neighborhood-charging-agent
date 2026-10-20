"""审计日志写入。"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record_audit(
    db: Session,
    *,
    action: str,
    user: Optional[User] = None,
    tenant_id: Optional[int] = None,
    resource_type: str = "",
    resource_id: str | int = "",
    detail: Optional[dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    ip: Optional[str] = None,
    result: str = "success",
    actor_name: Optional[str] = None,
    actor_role: Optional[str] = None,
) -> AuditLog:
    log = AuditLog(
        tenant_id=tenant_id or (user.tenant_id if user else 0),
        trace_id=trace_id,
        actor_id=user.id if user else None,
        actor_name=actor_name or (user.display_name if user else "system"),
        actor_role=actor_role or (user.role if user else "system"),
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        detail=detail or {},
        ip=ip,
        result=result,
    )
    db.add(log)
    return log
