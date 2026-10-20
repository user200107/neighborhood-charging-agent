"""预约、订单领域服务。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.auth import community_ids_for
from app.constants import ORDER_TRANSITIONS
from app.errors import bad_request, conflict, forbidden, not_found
from app.models import Community, Connector, Order, Pile, Reservation, User
from app.services.audit import record_audit
from app.utils import gen_order_no, money, parse_datetime, utcnow


def _unique_order_no(db: Session, tenant_id: int) -> str:
    for _ in range(5):
        candidate = gen_order_no()
        exists = (
            db.query(Order.id).filter(Order.tenant_id == tenant_id, Order.order_no == candidate).first()
        )
        if not exists:
            return candidate
    raise conflict("订单号生成冲突，请重试", "ORDER_NO_CONFLICT")


def _assert_connector(db: Session, user: User, connector_id: int) -> tuple[Connector, Pile, Community]:
    connector = db.get(Connector, connector_id)
    if not connector:
        raise not_found("枪口不存在", "CONNECTOR_NOT_FOUND")
    pile = db.get(Pile, connector.pile_id)
    if not pile or pile.tenant_id != user.tenant_id:
        raise not_found("设备不存在", "PILE_NOT_FOUND")
    community = db.get(Community, pile.community_id)
    if not community or community.tenant_id != user.tenant_id:
        raise not_found("社区不存在", "COMMUNITY_NOT_FOUND")
    scope = community_ids_for(user)
    if scope is not None and community.id not in scope:
        raise forbidden("无权在该社区下单", "COMMUNITY_FORBIDDEN")
    return connector, pile, community


def has_time_conflict(
    db: Session,
    connector_id: int,
    starts_at: datetime,
    ends_at: datetime,
    exclude_reservation_id: Optional[int] = None,
) -> bool:
    reservation_query = db.query(Reservation.id).filter(
        Reservation.connector_id == connector_id,
        Reservation.status == "active",
        Reservation.starts_at < ends_at,
        Reservation.ends_at > starts_at,
    )
    if exclude_reservation_id:
        reservation_query = reservation_query.filter(Reservation.id != exclude_reservation_id)
    if reservation_query.first():
        return True

    # 已占用式订单（预约/充电）也参与冲突判断
    order_conflict = (
        db.query(Order.id)
        .filter(
            Order.connector_id == connector_id,
            Order.status.in_(["reserved", "charging"]),
            Order.starts_at.isnot(None),
            Order.starts_at < ends_at,
            or_(Order.ended_at.is_(None), Order.ended_at > starts_at),
        )
        .first()
    )
    return order_conflict is not None


def create_order(
    db: Session,
    user: User,
    *,
    connector_id: int,
    mode: str = "now",
    starts_at: Optional[datetime] = None,
    ends_at: Optional[datetime] = None,
    payment_method: str = "wechat",
    note: Optional[str] = None,
    trace_id: Optional[str] = None,
    ip: Optional[str] = None,
) -> Order:
    connector, pile, community = _assert_connector(db, user, connector_id)
    now = utcnow()

    if mode not in {"now", "reserved"}:
        raise bad_request("mode 只能为 now 或 reserved", "MODE_INVALID")
    if pile.status in {"offline", "fault", "maintenance"}:
        raise conflict("设备当前不可用", "PILE_UNAVAILABLE", {"status": pile.status})
    if connector.status in {"fault", "offline"}:
        raise conflict("枪口当前不可用", "CONNECTOR_UNAVAILABLE")

    reservation: Optional[Reservation] = None
    if mode == "now":
        if connector.status != "idle":
            raise conflict("枪口正在使用中，请选择其他枪口", "CONNECTOR_BUSY")
        starts = now
        ends = None
        if has_time_conflict(db, connector.id, now - timedelta(minutes=1), now + timedelta(minutes=30)):
            raise conflict("该枪口已有预约，请选择其他时间或枪口", "RESERVATION_CONFLICT")
        status = "charging"
    else:
        starts = starts_at or (now + timedelta(hours=1))
        ends = ends_at or (starts + timedelta(hours=2))
        if starts < now - timedelta(minutes=5):
            raise bad_request("预约开始时间不能早于当前时间", "START_IN_PAST")
        if ends <= starts:
            raise bad_request("预约结束时间必须晚于开始时间", "INVALID_TIME_RANGE")
        if (ends - starts) > timedelta(hours=8):
            raise bad_request("单次预约最长 8 小时", "RESERVATION_TOO_LONG")
        if has_time_conflict(db, connector.id, starts, ends):
            raise conflict("该时段已被预约，请选择其他时间", "RESERVATION_CONFLICT")
        status = "reserved"

    order = Order(
        tenant_id=user.tenant_id,
        order_no=_unique_order_no(db, user.tenant_id),
        user_id=user.id,
        community_id=community.id,
        pile_id=pile.id,
        connector_id=connector.id,
        status=status,
        starts_at=starts,
        ended_at=ends,
        unit_price=connector.price_per_kwh,
        service_fee=connector.service_fee,
        payment_method=payment_method,
        source="web",
    )
    db.add(order)
    db.flush()

    if mode == "reserved":
        reservation = Reservation(
            tenant_id=user.tenant_id,
            community_id=community.id,
            user_id=user.id,
            connector_id=connector.id,
            starts_at=starts,
            ends_at=ends,
            status="active",
            note=note,
        )
        db.add(reservation)
        db.flush()
        order.reservation_id = reservation.id
        # 临近开始的预约才占用枪口状态，远期预约通过时段冲突校验避免重复
        if starts <= now + timedelta(hours=2):
            connector.status = "reserved"
    else:
        connector.status = "charging"
        pile.current_power_kw = connector.power_kw * 0.72

    record_audit(
        db,
        action="order.created",
        user=user,
        resource_type="order",
        resource_id=order.order_no,
        detail={
            "connector": connector.id,
            "mode": mode,
            "starts_at": starts.isoformat(),
            "amount": order.amount,
        },
        trace_id=trace_id,
        ip=ip,
    )
    return order


def start_order(
    db: Session, order: Order, actor: User, *, trace_id: Optional[str] = None, ip: Optional[str] = None
) -> Order:
    if order.status == "charging":
        return order
    if order.status != "reserved":
        raise conflict("只有已预约订单可以开始充电", "ORDER_STATUS_CONFLICT")
    order.status = "charging"
    order.starts_at = utcnow()
    connector = db.get(Connector, order.connector_id)
    if connector:
        connector.status = "charging"
        pile = db.get(Pile, order.pile_id)
        if pile:
            pile.current_power_kw = connector.power_kw * 0.72
    record_audit(
        db, action="order.started", user=actor, resource_type="order",
        resource_id=order.order_no, detail={}, trace_id=trace_id, ip=ip,
    )
    return order


def complete_order(
    db: Session,
    order: Order,
    actor: User,
    *,
    energy_kwh: Optional[float] = None,
    trace_id: Optional[str] = None,
    ip: Optional[str] = None,
) -> Order:
    if order.status == "completed":
        return order
    if order.status not in {"charging", "abnormal"}:
        raise conflict("只有充电中订单可以结束", "ORDER_STATUS_CONFLICT")

    connector = db.get(Connector, order.connector_id)
    now = utcnow()
    if energy_kwh is None:
        started = order.starts_at or now
        hours = max((now - started).total_seconds() / 3600, 0.03)
        power = connector.power_kw if connector else 7
        energy_kwh = round(min(power * hours * 0.85, 120), 2)
    if energy_kwh < 0 or energy_kwh > 200:
        raise bad_request("电量数值超出合理范围", "ENERGY_INVALID")

    order.energy_kwh = round(float(energy_kwh), 2)
    order.ended_at = now
    order.amount = money(order.energy_kwh * (order.unit_price + order.service_fee))
    order.status = "completed"
    if connector:
        connector.status = "idle"
        connector.total_energy_kwh = round((connector.total_energy_kwh or 0) + order.energy_kwh, 1)
    pile = db.get(Pile, order.pile_id)
    if pile:
        pile.current_power_kw = 0
    if order.reservation_id:
        reservation = db.get(Reservation, order.reservation_id)
        if reservation and reservation.status == "active":
            reservation.status = "completed"

    record_audit(
        db,
        action="order.completed",
        user=actor,
        resource_type="order",
        resource_id=order.order_no,
        detail={"energy_kwh": order.energy_kwh, "amount": order.amount},
        trace_id=trace_id,
        ip=ip,
    )
    return order


def cancel_order(
    db: Session,
    order: Order,
    actor: User,
    reason: str,
    *,
    trace_id: Optional[str] = None,
    ip: Optional[str] = None,
) -> Order:
    if order.status == "cancelled":
        return order
    if order.status not in {"pending_payment", "reserved"}:
        raise conflict("充电中或已完成订单不能直接取消", "ORDER_STATUS_CONFLICT")
    order.status = "cancelled"
    order.cancel_reason = reason[:255]
    order.ended_at = utcnow()
    connector = db.get(Connector, order.connector_id)
    if connector and connector.status == "reserved":
        connector.status = "idle"
    if order.reservation_id:
        reservation = db.get(Reservation, order.reservation_id)
        if reservation:
            reservation.status = "cancelled"
    record_audit(
        db,
        action="order.cancelled",
        user=actor,
        resource_type="order",
        resource_id=order.order_no,
        detail={"reason": order.cancel_reason},
        trace_id=trace_id,
        ip=ip,
    )
    return order


def cancel_reservation(
    db: Session,
    reservation: Reservation,
    actor: User,
    *,
    trace_id: Optional[str] = None,
    ip: Optional[str] = None,
) -> Reservation:
    if reservation.status != "active":
        raise conflict("预约已失效，无法取消", "RESERVATION_INACTIVE")
    reservation.status = "cancelled"
    connector = db.get(Connector, reservation.connector_id)
    if connector and connector.status == "reserved":
        connector.status = "idle"
    linked = (
        db.query(Order)
        .filter(Order.reservation_id == reservation.id, Order.status == "reserved")
        .first()
    )
    if linked:
        linked.status = "cancelled"
        linked.cancel_reason = "用户取消预约"
        linked.ended_at = utcnow()
    record_audit(
        db, action="reservation.cancelled", user=actor, resource_type="reservation",
        resource_id=reservation.id, detail={}, trace_id=trace_id, ip=ip,
    )
    return reservation


def check_transition(current: str, target: str) -> bool:
    return target in ORDER_TRANSITIONS.get(current, frozenset())


def active_charging_count(db: Session, connector_ids: list[int]) -> int:
    if not connector_ids:
        return 0
    return (
        db.query(Order)
        .filter(Order.connector_id.in_(connector_ids), Order.status == "charging")
        .count()
    )


def reservation_overview(db: Session, reservation: Reservation) -> dict:
    return {
        "id": reservation.id,
        "connector_id": reservation.connector_id,
        "connector_code": reservation.connector.code if reservation.connector else None,
        "pile_id": reservation.connector.pile_id if reservation.connector else None,
        "pile_code": reservation.connector.pile.code if reservation.connector and reservation.connector.pile else None,
        "community_id": reservation.community_id,
        "community_name": reservation.community.name if reservation.community else None,
        "starts_at": reservation.starts_at,
        "ends_at": reservation.ends_at,
        "status": reservation.status,
        "note": reservation.note,
    }
