"""社区、充电桩、枪口与可用性查询。"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload, selectinload

from app.auth import community_ids_for, ensure_community_access, get_current_user
from app.db import get_db
from app.errors import not_found
from app.models import Community, Connector, DeviceEvent, Order, Pile, Ticket, User, Zone
from app.serializers import (
    community_public,
    connector_public,
    event_public,
    order_public,
    pile_public,
    ticket_public,
    zone_public,
)
from app.services.orders import has_time_conflict
from app.utils import iso, paginate, parse_datetime, utcnow

router = APIRouter(prefix="/api", tags=["设备与社区"])


@router.get("/communities", summary="社区列表")
def list_communities(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    scope = community_ids_for(user)
    query = db.query(Community).filter(Community.tenant_id == user.tenant_id)
    if scope is not None:
        query = query.filter(Community.id.in_(scope or [-1]))
    communities = query.order_by(Community.name).all()
    return {"items": [community_public(c) for c in communities], "total": len(communities)}


@router.get("/communities/{community_id}/zones", summary="社区区域")
def list_zones(
    community_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    ensure_community_access(user, community_id)
    zones = (
        db.query(Zone)
        .filter(Zone.tenant_id == user.tenant_id, Zone.community_id == community_id)
        .order_by(Zone.code)
        .all()
    )
    return {"items": [zone_public(z) for z in zones]}


@router.get("/piles", summary="充电桩列表")
def list_piles(
    community_id: Optional[int] = None,
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if community_id is not None:
        ensure_community_access(user, community_id)
    scope = community_ids_for(user)
    query = db.query(Pile).filter(Pile.tenant_id == user.tenant_id)
    if scope is not None:
        query = query.filter(Pile.community_id.in_(scope or [-1]))
    if community_id is not None:
        query = query.filter(Pile.community_id == community_id)
    if status:
        query = query.filter(Pile.status == status)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter((Pile.code.ilike(like)) | (Pile.name.ilike(like)))
    total = query.count()
    piles = (
        query.options(
            joinedload(Pile.community),
            joinedload(Pile.zone),
            selectinload(Pile.connectors),
        )
        .order_by(Pile.community_id, Pile.code)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return paginate([pile_public(p) for p in piles], total, page, page_size)


@router.get("/piles/{pile_id}", summary="充电桩详情")
def get_pile(
    pile_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    pile = (
        db.query(Pile)
        .options(joinedload(Pile.community), joinedload(Pile.zone), selectinload(Pile.connectors))
        .filter(Pile.id == pile_id, Pile.tenant_id == user.tenant_id)
        .first()
    )
    if not pile:
        raise not_found("设备不存在")
    ensure_community_access(user, pile.community_id)
    events = (
        db.query(DeviceEvent)
        .filter(DeviceEvent.tenant_id == user.tenant_id, DeviceEvent.pile_id == pile.id)
        .order_by(DeviceEvent.occurred_at.desc())
        .limit(20)
        .all()
    )
    tickets = (
        db.query(Ticket)
        .filter(Ticket.tenant_id == user.tenant_id, Ticket.pile_id == pile.id)
        .order_by(Ticket.created_at.desc())
        .limit(5)
        .all()
    )
    orders = (
        db.query(Order)
        .filter(Order.tenant_id == user.tenant_id, Order.pile_id == pile.id)
        .order_by(Order.created_at.desc())
        .limit(5)
        .all()
    )
    data = pile_public(pile)
    data["events"] = [event_public(e) for e in events]
    data["tickets"] = [ticket_public(t) for t in tickets]
    data["recent_orders"] = [order_public(o) for o in orders]
    return data


@router.get("/availability", summary="查询可用枪口")
def availability(
    community_id: Optional[int] = None,
    starts_at: Optional[str] = None,
    ends_at: Optional[str] = None,
    limit: int = Query(default=12, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if community_id is not None:
        ensure_community_access(user, community_id)
    scope = community_ids_for(user)
    starts = parse_datetime(starts_at) or utcnow()
    ends = parse_datetime(ends_at) or (starts + timedelta(hours=2))
    if ends <= starts:
        ends = starts + timedelta(hours=2)

    query = (
        db.query(Connector)
        .join(Pile, Connector.pile_id == Pile.id)
        .options(joinedload(Connector.pile).joinedload(Pile.community))
        .filter(
            Connector.tenant_id == user.tenant_id,
            Pile.status == "online",
            Connector.status == "idle",
        )
    )
    if scope is not None:
        query = query.filter(Pile.community_id.in_(scope or [-1]))
    if community_id is not None:
        query = query.filter(Pile.community_id == community_id)

    connectors = query.order_by(Pile.community_id, Pile.code, Connector.code).limit(200).all()
    available = [c for c in connectors if not has_time_conflict(db, c.id, starts, ends)][:limit]
    items = []
    for connector in available:
        pile = connector.pile
        items.append(
            {
                **connector_public(connector),
                "pile": {
                    "id": pile.id,
                    "code": pile.code,
                    "name": pile.name,
                    "community_id": pile.community_id,
                    "community_name": pile.community.name if pile.community else None,
                    "zone_name": pile.zone.name if pile.zone else "未分区",
                    "rated_power_kw": pile.rated_power_kw,
                    "status": pile.status,
                },
            }
        )
    return {
        "items": items,
        "total": len(items),
        "starts_at": iso(starts),
        "ends_at": iso(ends),
    }
