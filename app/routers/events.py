"""设备事件接入与查询。"""

from __future__ import annotations

import hmac
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload

from app.auth import bearer_scheme, community_ids_for, forbidden, get_current_user, require_roles
from app.config import settings
from app.db import get_db
from app.models import DeviceEvent, Pile, Tenant, User
from app.schemas import DeviceEventRequest
from app.serializers import event_public
from app.services.events import process_event
from app.utils import paginate

router = APIRouter(prefix="/api/device-events", tags=["设备事件"])


def get_event_actor(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    provided = request.headers.get("x-device-key", "")
    if settings.device_api_key and provided and hmac.compare_digest(provided, settings.device_api_key):
        return None
    user = get_current_user(request, credentials, db)
    if user.role not in {"admin", "operator", "technician"}:
        raise forbidden("当前角色不能接入设备事件", "ROLE_FORBIDDEN")
    return user


@router.post("", summary="设备事件接入", status_code=200)
def ingest_event(
    payload: DeviceEventRequest,
    request: Request,
    actor: Optional[User] = Depends(get_event_actor),
    db: Session = Depends(get_db),
) -> dict:
    if actor is not None:
        tenant_id = actor.tenant_id
    else:
        code = (payload.tenant_code or "NEIGHBOR").upper()
        tenant = db.query(Tenant).filter(Tenant.code == code).first()
        if not tenant:
            raise forbidden("设备网关租户无效", "TENANT_INVALID")
        tenant_id = tenant.id
    result = process_event(
        db,
        actor,
        payload.model_dump(),
        tenant_id=tenant_id,
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return result


@router.get("", summary="设备事件列表")
def list_events(
    pile_id: Optional[int] = None,
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_roles("operator", "technician", "finance")),
    db: Session = Depends(get_db),
) -> dict:
    scope = community_ids_for(user)
    query = db.query(DeviceEvent).filter(DeviceEvent.tenant_id == user.tenant_id)
    if scope is not None:
        query = query.filter(DeviceEvent.pile.has(Pile.community_id.in_(scope or [-1])))
    if pile_id:
        query = query.filter(DeviceEvent.pile_id == pile_id)
    if event_type:
        query = query.filter(DeviceEvent.event_type == event_type)
    if severity:
        query = query.filter(DeviceEvent.severity == severity)
    total = query.count()
    events = (
        query.options(joinedload(DeviceEvent.pile))
        .order_by(DeviceEvent.occurred_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return paginate([event_public(e) for e in events], total, page, page_size)
