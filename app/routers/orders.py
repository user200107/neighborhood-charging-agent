"""订单与预约接口。"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.orm import Session, joinedload

from app.auth import community_ids_for, ensure_community_access, get_current_user
from app.db import get_db
from app.errors import forbidden, not_found
from app.models import AuditLog, Connector, Order, Pile, Reservation, User
from app.schemas import (
    OrderCancelRequest,
    OrderCompleteRequest,
    OrderCreateRequest,
    ReservationCreateRequest,
)
from app.serializers import order_public
from app.services.audit import record_audit
from app.services.idempotency import lookup, store
from app.services.orders import cancel_order, cancel_reservation, complete_order, create_order, start_order
from app.utils import iso, paginate, parse_datetime, utcnow

router = APIRouter(prefix="/api", tags=["订单与预约"])


def _get_order(db: Session, user: User, order_id: int) -> Order:
    order = (
        db.query(Order)
        .options(
            joinedload(Order.community),
            joinedload(Order.pile),
            joinedload(Order.connector),
            joinedload(Order.user),
        )
        .filter(Order.id == order_id, Order.tenant_id == user.tenant_id)
        .first()
    )
    if not order:
        raise not_found("订单不存在")
    ensure_community_access(user, order.community_id)
    if user.role == "resident" and order.user_id != user.id:
        raise forbidden("无权查看他人订单", "ORDER_FORBIDDEN")
    return order


def _reservation_payload(reservation: Reservation) -> dict:
    connector = reservation.connector
    pile = connector.pile if connector else None
    return {
        "id": reservation.id,
        "community_id": reservation.community_id,
        "community_name": reservation.community.name if reservation.community else None,
        "connector_id": reservation.connector_id,
        "connector_code": connector.code if connector else None,
        "pile_id": pile.id if pile else None,
        "pile_code": pile.code if pile else None,
        "pile_name": pile.name if pile else None,
        "user_id": reservation.user_id,
        "user_name": reservation.user.display_name if reservation.user else None,
        "starts_at": iso(reservation.starts_at),
        "ends_at": iso(reservation.ends_at),
        "status": reservation.status,
        "note": reservation.note,
        "created_at": iso(reservation.created_at),
    }


@router.get("/orders", summary="订单列表")
def list_orders(
    community_id: Optional[int] = None,
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    user_id: Optional[int] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=15, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if community_id is not None:
        ensure_community_access(user, community_id)
    scope = community_ids_for(user)
    query = db.query(Order).filter(Order.tenant_id == user.tenant_id)
    if scope is not None:
        query = query.filter(Order.community_id.in_(scope or [-1]))
    if community_id is not None:
        query = query.filter(Order.community_id == community_id)
    if status:
        query = query.filter(Order.status == status)
    if user.role == "resident":
        query = query.filter(Order.user_id == user.id)
    elif user_id:
        query = query.filter(Order.user_id == user_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            (Order.order_no.ilike(like))
            | Order.pile.has(Pile.code.ilike(like))
            | Order.user.has(User.display_name.ilike(like))
        )
    total = query.count()
    orders = (
        query.options(
            joinedload(Order.community),
            joinedload(Order.pile),
            joinedload(Order.connector),
            joinedload(Order.user),
        )
        .order_by(Order.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return paginate([order_public(o) for o in orders], total, page, page_size)


@router.get("/orders/{order_id}", summary="订单详情")
def get_order(
    order_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    order = _get_order(db, user, order_id)
    timeline = (
        db.query(AuditLog)
        .filter(
            AuditLog.tenant_id == user.tenant_id,
            AuditLog.resource_type == "order",
            AuditLog.resource_id == order.order_no,
        )
        .order_by(AuditLog.created_at.asc())
        .limit(50)
        .all()
    )
    data = order_public(order)
    data["timeline"] = [
        {
            "action": log.action,
            "at": iso(log.created_at),
            "actor": log.actor_name,
            "detail": log.detail,
        }
        for log in timeline
    ]
    return data


@router.post("/orders", summary="创建充电订单/预约", status_code=201)
def create_order_endpoint(
    payload: OrderCreateRequest,
    request: Request,
    response: Response,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    endpoint = "POST /api/orders"
    body = payload.model_dump(mode="json")
    existing = lookup(db, user, endpoint, idempotency_key, body)
    if existing:
        response.headers["Idempotency-Replayed"] = "true"
        return existing.response

    order = create_order(
        db,
        user,
        connector_id=payload.connector_id,
        mode=payload.mode,
        starts_at=parse_datetime(payload.starts_at),
        ends_at=parse_datetime(payload.ends_at),
        payment_method=payload.payment_method,
        note=payload.note,
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    result = order_public(order)
    store(
        db,
        user,
        endpoint,
        idempotency_key,
        body,
        result,
        status_code=201,
    )
    db.commit()
    return result


@router.post("/orders/{order_id}/cancel", summary="取消订单")
def cancel_order_endpoint(
    order_id: int,
    payload: OrderCancelRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    order = _get_order(db, user, order_id)
    if user.role == "resident" and order.user_id != user.id:
        raise forbidden()
    cancel_order(
        db,
        order,
        user,
        payload.reason,
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return order_public(order)


@router.post("/orders/{order_id}/start", summary="开始充电")
def start_order_endpoint(
    order_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    order = _get_order(db, user, order_id)
    start_order(
        db,
        order,
        user,
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return order_public(order)


@router.post("/orders/{order_id}/complete", summary="结束充电")
def complete_order_endpoint(
    order_id: int,
    request: Request,
    payload: OrderCompleteRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    order = _get_order(db, user, order_id)
    complete_order(
        db,
        order,
        user,
        energy_kwh=payload.energy_kwh if payload else None,
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return order_public(order)


@router.get("/reservations", summary="预约列表")
def list_reservations(
    status: Optional[str] = "active",
    community_id: Optional[int] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=15, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if community_id is not None:
        ensure_community_access(user, community_id)
    scope = community_ids_for(user)
    query = db.query(Reservation).filter(Reservation.tenant_id == user.tenant_id)
    if scope is not None:
        query = query.filter(Reservation.community_id.in_(scope or [-1]))
    if community_id is not None:
        query = query.filter(Reservation.community_id == community_id)
    if status:
        query = query.filter(Reservation.status == status)
    if user.role == "resident":
        query = query.filter(Reservation.user_id == user.id)
    total = query.count()
    reservations = (
        query.options(
            joinedload(Reservation.connector).joinedload(Connector.pile),
            joinedload(Reservation.community),
            joinedload(Reservation.user),
        )
        .order_by(Reservation.starts_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return paginate([_reservation_payload(r) for r in reservations], total, page, page_size)


@router.post("/reservations", summary="创建预约", status_code=201)
def create_reservation_endpoint(
    payload: ReservationCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    order = create_order(
        db,
        user,
        connector_id=payload.connector_id,
        mode="reserved",
        starts_at=parse_datetime(payload.starts_at),
        ends_at=parse_datetime(payload.ends_at),
        note=payload.note,
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    db.commit()
    reservation = db.get(Reservation, order.reservation_id) if order.reservation_id else None
    result = _reservation_payload(reservation) if reservation else {}
    result["order"] = order_public(order)
    return result


@router.delete("/reservations/{reservation_id}", summary="取消预约")
def cancel_reservation_endpoint(
    reservation_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    reservation = (
        db.query(Reservation)
        .options(joinedload(Reservation.connector).joinedload(Connector.pile))
        .filter(Reservation.id == reservation_id, Reservation.tenant_id == user.tenant_id)
        .first()
    )
    if not reservation:
        raise not_found("预约不存在")
    ensure_community_access(user, reservation.community_id)
    if user.role == "resident" and reservation.user_id != user.id:
        raise forbidden("无权取消他人预约")
    cancel_reservation(
        db,
        reservation,
        user,
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return _reservation_payload(reservation)
