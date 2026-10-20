"""运营指标与报表计算。"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.auth import community_ids_for
from app.errors import forbidden
from app.models import Approval, Community, Connector, DeviceEvent, Order, Pile, Reservation, Ticket, User
from app.serializers import metric_cards, order_public, ticket_public
from app.utils import date_range, iso, money, ratio, utcnow


def scoped_community_ids(db: Session, user: User, community_id: Optional[int] = None) -> list[int]:
    scope = community_ids_for(user)
    if community_id is not None:
        if scope is not None and community_id not in scope:
            raise forbidden("无权访问该社区数据", "COMMUNITY_FORBIDDEN")
        return [community_id]
    if scope is not None:
        return sorted(scope)
    rows = db.query(Community.id).filter(Community.tenant_id == user.tenant_id).all()
    return [row[0] for row in rows]


def _orders_in_range(
    db: Session,
    user: User,
    community_ids: list[int],
    start: datetime,
    end: datetime,
) -> list[Order]:
    query = db.query(Order).filter(
        Order.tenant_id == user.tenant_id,
        Order.community_id.in_(community_ids),
        Order.created_at >= start,
        Order.created_at <= end,
    )
    if user.role == "resident":
        query = query.filter(Order.user_id == user.id)
    return query.order_by(Order.created_at.desc()).all()


def _tickets_in_range(
    db: Session, user: User, community_ids: list[int], start: datetime, end: datetime
) -> list[Ticket]:
    query = db.query(Ticket).filter(
        Ticket.tenant_id == user.tenant_id,
        Ticket.community_id.in_(community_ids),
        Ticket.created_at >= start,
        Ticket.created_at <= end,
    )
    if user.role == "resident":
        query = query.filter(Ticket.reporter_id == user.id)
    return query.order_by(Ticket.created_at.desc()).all()


def _day_key(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


def dashboard(
    db: Session,
    user: User,
    *,
    days: int = 7,
    community_id: Optional[int] = None,
) -> dict[str, Any]:
    days = max(1, min(days, 90))
    community_ids = scoped_community_ids(db, user, community_id)
    start, end = date_range(days)
    now = utcnow()

    piles = (
        db.query(Pile)
        .filter(Pile.tenant_id == user.tenant_id, Pile.community_id.in_(community_ids))
        .all()
        if community_ids
        else []
    )
    pile_ids = [p.id for p in piles]
    connectors = (
        db.query(Connector).filter(Connector.tenant_id == user.tenant_id, Connector.pile_id.in_(pile_ids)).all()
        if pile_ids
        else []
    )
    orders = _orders_in_range(db, user, community_ids, start, end)
    tickets = _tickets_in_range(db, user, community_ids, start, end)

    total_piles = len(piles)
    online_piles = sum(1 for p in piles if p.online and p.status == "online")
    fault_piles = sum(1 for p in piles if p.status == "fault")
    offline_piles = sum(1 for p in piles if p.status == "offline")
    maintenance_piles = sum(1 for p in piles if p.status == "maintenance")
    charging_connectors = sum(1 for c in connectors if c.status == "charging")

    availability = ratio(online_piles, total_piles)
    utilization = ratio(charging_connectors, len(connectors))
    fault_rate = ratio(fault_piles, total_piles)
    revenue = money(sum(o.amount for o in orders if o.status == "completed"))
    refund = money(sum(o.refund_amount for o in orders))
    energy = round(sum(o.energy_kwh for o in orders if o.status in {"completed", "charging"}), 1)

    fulfilled = [o for o in orders if o.status in {"completed", "charging"}]
    unsuccessful = [o for o in orders if o.status in {"cancelled", "abnormal"}]
    reservation_success = ratio(len(fulfilled), len(fulfilled) + len(unsuccessful))
    completed_orders = sum(1 for o in orders if o.status == "completed")
    avg_order_amount = money(revenue / completed_orders) if completed_orders else 0.0

    closed_tickets = [t for t in tickets if t.status == "closed" and t.closed_at]
    mttr_hours = (
        round(
            sum((t.closed_at - t.created_at).total_seconds() for t in closed_tickets)
            / len(closed_tickets)
            / 3600,
            1,
        )
        if closed_tickets
        else 0.0
    )
    pending_tickets = sum(1 for t in tickets if t.status not in {"closed", "cancelled"})
    overdue_tickets = sum(
        1 for t in tickets if t.sla_due_at and t.status not in {"closed", "cancelled"} and t.sla_due_at < now
    )

    trend_map: dict[str, dict[str, float]] = {}
    for offset in range(days - 1, -1, -1):
        day = (end - timedelta(days=offset)).strftime("%Y-%m-%d")
        trend_map[day] = {"date": day, "orders": 0, "revenue": 0.0, "energy": 0.0, "tickets": 0}
    for order in orders:
        key = _day_key(order.created_at)
        if key in trend_map:
            trend_map[key]["orders"] += 1
            if order.status == "completed":
                trend_map[key]["revenue"] += order.amount
            trend_map[key]["energy"] += order.energy_kwh
    for ticket in tickets:
        key = _day_key(ticket.created_at)
        if key in trend_map:
            trend_map[key]["tickets"] += 1
    trend = [
        {**row, "revenue": round(row["revenue"], 2), "energy": round(row["energy"], 1)}
        for row in trend_map.values()
    ]

    community_rows = []
    all_communities = {
        c.id: c
        for c in db.query(Community)
        .filter(Community.tenant_id == user.tenant_id, Community.id.in_(community_ids))
        .all()
    }
    for cid, community in all_communities.items():
        c_piles = [p for p in piles if p.community_id == cid]
        c_connectors = [c for c in connectors if c.pile_id in {p.id for p in c_piles}]
        c_orders = [o for o in orders if o.community_id == cid]
        c_tickets = [t for t in tickets if t.community_id == cid]
        community_rows.append(
            {
                "id": cid,
                "name": community.name,
                "pile_count": len(c_piles),
                "availability": ratio(sum(1 for p in c_piles if p.online and p.status == "online"), len(c_piles)),
                "utilization": ratio(sum(1 for c in c_connectors if c.status == "charging"), len(c_connectors)),
                "revenue": money(sum(o.amount for o in c_orders if o.status == "completed")),
                "order_count": len(c_orders),
                "energy_kwh": round(sum(o.energy_kwh for o in c_orders), 1),
                "fault_rate": ratio(sum(1 for p in c_piles if p.status == "fault"), len(c_piles)),
                "pending_tickets": sum(1 for t in c_tickets if t.status not in {"closed", "cancelled"}),
            }
        )
    community_rows.sort(key=lambda item: item["revenue"], reverse=True)

    recent_orders_query = db.query(Order).filter(
        Order.tenant_id == user.tenant_id, Order.community_id.in_(community_ids)
    )
    recent_tickets_query = db.query(Ticket).filter(
        Ticket.tenant_id == user.tenant_id, Ticket.community_id.in_(community_ids)
    )
    if user.role == "resident":
        recent_orders_query = recent_orders_query.filter(Order.user_id == user.id)
        recent_tickets_query = recent_tickets_query.filter(Ticket.reporter_id == user.id)
    recent_orders = (
        recent_orders_query.order_by(Order.created_at.desc()).limit(6).all() if community_ids else []
    )
    recent_tickets = (
        recent_tickets_query.order_by(Ticket.created_at.desc()).limit(6).all() if community_ids else []
    )

    pending_approvals = (
        db.query(Approval)
        .filter(
            Approval.tenant_id == user.tenant_id,
            Approval.community_id.in_(community_ids),
            Approval.status == "pending",
        )
        .count()
        if community_ids and user.role in {"admin", "finance", "operator"}
        else 0
    )

    reservation_query = db.query(Reservation).filter(
        Reservation.tenant_id == user.tenant_id,
        Reservation.community_id.in_(community_ids),
        Reservation.status == "active",
        Reservation.starts_at >= now - timedelta(hours=1),
    )
    if user.role == "resident":
        reservation_query = reservation_query.filter(Reservation.user_id == user.id)
    active_reservations = reservation_query.count() if community_ids else 0

    fault_events = (
        db.query(DeviceEvent)
        .filter(
            DeviceEvent.tenant_id == user.tenant_id,
            DeviceEvent.pile_id.in_(pile_ids),
            DeviceEvent.occurred_at >= start,
            DeviceEvent.severity.in_(["warning", "critical", "fatal"]),
        )
        .order_by(DeviceEvent.occurred_at.desc())
        .limit(500)
        .all()
        if pile_ids
        else []
    )
    fault_counter: Counter[tuple[str, str]] = Counter()
    last_fault_time: dict[str, datetime] = {}
    pile_by_id = {p.id: p for p in piles}
    for event in fault_events:
        pile = pile_by_id.get(event.pile_id)
        if not pile:
            continue
        fault_counter[(pile.code, event.event_type)] += 1
        last_fault_time[pile.code] = max(last_fault_time.get(pile.code, event.occurred_at), event.occurred_at)
    top_faults = [
        {
            "pile_code": code,
            "event_type": event_type,
            "count": count,
            "last_at": iso(last_fault_time.get(code)),
        }
        for (code, event_type), count in fault_counter.most_common(5)
    ]

    alerts: list[dict[str, Any]] = []
    p1_tickets = [t for t in tickets if t.priority == "P1" and t.status not in {"closed", "cancelled"}]
    if p1_tickets:
        alerts.append(
            {
                "level": "critical",
                "title": f"{len(p1_tickets)} 张 P1 工单未闭环",
                "detail": "P1 故障需在 1 小时内响应，请立即处理。",
                "link": "#/tickets?priority=P1",
            }
        )
    if overdue_tickets:
        alerts.append(
            {
                "level": "warning",
                "title": f"{overdue_tickets} 张工单 SLA 已超时",
                "detail": "建议检查分派与备件情况，必要时升级处理。",
                "link": "#/tickets",
            }
        )
    if pending_approvals and user.role in {"admin", "finance", "operator"}:
        alerts.append(
            {
                "level": "info",
                "title": f"{pending_approvals} 条高风险审批待决策",
                "detail": "停机、退款、调价等动作在审批通过前不会执行。",
                "link": "#/approvals",
            }
        )
    if offline_piles:
        alerts.append(
            {
                "level": "warning",
                "title": f"{offline_piles} 台设备离线",
                "detail": "请检查网络与心跳，超过 30 分钟将自动生成工单。",
                "link": "#/devices?status=offline",
            }
        )

    cards = metric_cards(
        availability=availability,
        utilization=utilization,
        mttr_hours=mttr_hours,
        revenue=revenue,
        refund=refund,
        reservation_success=reservation_success,
        fault_rate=fault_rate,
        pending_tickets=pending_tickets,
        online_piles=online_piles,
        total_piles=total_piles,
    )

    return {
        "scope": {
            "communities": community_rows,
            "community_id": community_id,
            "days": days,
            "from": iso(start),
            "to": iso(end),
        },
        "summary": {
            "total_piles": total_piles,
            "online_piles": online_piles,
            "fault_piles": fault_piles,
            "offline_piles": offline_piles,
            "maintenance_piles": maintenance_piles,
            "total_connectors": len(connectors),
            "charging_connectors": charging_connectors,
            "availability": availability,
            "utilization": utilization,
            "fault_rate": fault_rate,
            "revenue": revenue,
            "refund": refund,
            "energy_kwh": energy,
            "mttr_hours": mttr_hours,
            "reservation_success": reservation_success,
            "pending_tickets": pending_tickets,
            "overdue_tickets": overdue_tickets,
            "pending_approvals": pending_approvals,
            "active_reservations": active_reservations,
            "order_count": len(orders),
            "completed_orders": completed_orders,
            "avg_order_amount": avg_order_amount,
        },
        "cards": cards,
        "trend": trend,
        "communities": community_rows,
        "pile_status": [
            {"key": "online", "label": "在线", "value": online_piles, "color": "#10b981"},
            {"key": "fault", "label": "故障", "value": fault_piles, "color": "#f43f5e"},
            {"key": "offline", "label": "离线", "value": offline_piles, "color": "#94a3b8"},
            {"key": "maintenance", "label": "维护", "value": maintenance_piles, "color": "#f59e0b"},
        ],
        "top_faults": top_faults,
        "alerts": alerts,
        "recent_orders": [order_public(o) for o in recent_orders],
        "recent_tickets": [ticket_public(t) for t in recent_tickets],
        "updated_at": iso(now),
    }


def report_overview(
    db: Session, user: User, *, days: int = 30, community_id: Optional[int] = None
) -> dict[str, Any]:
    data = dashboard(db, user, days=days, community_id=community_id)
    summary = data["summary"]
    orders = _orders_in_range(
        db, user, scoped_community_ids(db, user, community_id), *date_range(days)
    )
    status_counter: Counter[str] = Counter(order.status for order in orders)
    payment_counter: Counter[str] = Counter(order.payment_method for order in orders if order.status == "completed")
    total_amount = sum(order.amount for order in orders if order.status == "completed") or 1
    return {
        "summary": {
            **summary,
            "avg_order_amount": round(total_amount / max(1, status_counter.get("completed", 0)), 2),
            "completed_orders": status_counter.get("completed", 0),
        },
        "order_status": [{"key": key, "value": value} for key, value in status_counter.most_common()],
        "payment_methods": [{"key": key, "value": value} for key, value in payment_counter.most_common()],
        "trend": data["trend"],
        "communities": data["communities"],
        "updated_at": data["updated_at"],
    }
