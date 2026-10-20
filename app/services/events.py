"""设备事件接入、幂等去重、状态机与故障工单升级。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.auth import community_ids_for
from app.errors import bad_request, forbidden, not_found
from app.models import Connector, DeviceEvent, Order, Pile, Ticket, User
from app.services.audit import record_audit
from app.services.tickets import create_ticket
from app.utils import parse_datetime, utcnow

ALLOWED_EVENT_TYPES = {
    "heartbeat",
    "power",
    "current",
    "temperature",
    "offline",
    "online",
    "interrupted",
    "fault",
    "recovered",
}

TICKET_EVENT_TYPES = {"offline", "fault", "temperature", "interrupted"}


def _open_ticket(db: Session, pile_id: int) -> Optional[Ticket]:
    return (
        db.query(Ticket)
        .filter(
            Ticket.pile_id == pile_id,
            Ticket.status.notin_(["closed", "cancelled"]),
        )
        .order_by(Ticket.created_at.desc())
        .first()
    )


def _priority_for(event_type: str, severity: str, payload: dict[str, Any]) -> str:
    if severity in {"critical", "fatal"}:
        return "P1"
    if event_type == "temperature":
        temp = float(payload.get("temperature_c") or payload.get("value") or 0)
        return "P1" if temp >= 75 else "P2"
    if event_type == "offline":
        return "P2"
    if event_type == "interrupted":
        return "P2"
    return "P2" if event_type == "fault" else "P3"


def _ensure_pile_access(user: User, pile: Pile) -> None:
    if pile.tenant_id != user.tenant_id:
        raise not_found("设备不存在")
    scope = community_ids_for(user)
    if scope is not None and pile.community_id not in scope:
        raise forbidden("无权接入该社区设备事件", "COMMUNITY_FORBIDDEN")


def process_event(
    db: Session,
    user: Optional[User],
    payload: dict[str, Any],
    *,
    tenant_id: Optional[int] = None,
    trace_id: Optional[str] = None,
    ip: Optional[str] = None,
) -> dict[str, Any]:
    event_no = str(payload.get("event_no") or "").strip()
    if not event_no:
        raise bad_request("缺少 event_no", "EVENT_NO_REQUIRED")
    if len(event_no) > 80:
        raise bad_request("event_no 过长", "EVENT_NO_INVALID")

    pile_id = payload.get("pile_id")
    pile_code = payload.get("pile_code")
    if not pile_id and not pile_code:
        raise bad_request("缺少 pile_id 或 pile_code", "PILE_REQUIRED")

    event_type = str(payload.get("event_type") or "").strip()
    if event_type not in ALLOWED_EVENT_TYPES:
        raise bad_request(f"不支持的事件类型：{event_type}", "EVENT_TYPE_INVALID")

    tenant = tenant_id or (user.tenant_id if user else 0)
    if not tenant:
        raise bad_request("无法确定租户", "TENANT_REQUIRED")

    # 幂等：同一租户内 event_no 唯一
    existing = (
        db.query(DeviceEvent)
        .filter(DeviceEvent.tenant_id == tenant, DeviceEvent.event_no == event_no)
        .first()
    )
    if existing:
        return {
            "duplicate": True,
            "event_id": existing.id,
            "event_no": existing.event_no,
            "ticket_id": existing.ticket_id,
            "message": "事件编号已处理，已忽略重复投递",
        }

    if pile_id:
        pile = db.get(Pile, int(pile_id))
    else:
        pile = (
            db.query(Pile)
            .filter(Pile.tenant_id == tenant, Pile.code == str(pile_code))
            .first()
        )
    if not pile or pile.tenant_id != tenant:
        raise not_found("设备不存在", "PILE_NOT_FOUND")
    if user:
        _ensure_pile_access(user, pile)

    connector: Optional[Connector] = None
    connector_id = payload.get("connector_id")
    if connector_id:
        connector = db.get(Connector, int(connector_id))
        if not connector or connector.pile_id != pile.id:
            raise bad_request("枪口不属于该设备", "CONNECTOR_MISMATCH")

    occurred_at = parse_datetime(payload.get("occurred_at")) or utcnow()
    severity = str(payload.get("severity") or "info")
    event_payload = payload.get("payload") or {}
    if not isinstance(event_payload, dict):
        event_payload = {"value": event_payload}

    event = DeviceEvent(
        tenant_id=tenant,
        event_no=event_no,
        pile_id=pile.id,
        connector_id=connector.id if connector else None,
        event_type=event_type,
        severity=severity,
        payload=event_payload,
        occurred_at=occurred_at,
    )
    db.add(event)
    db.flush()

    now = utcnow()
    ticket: Optional[Ticket] = None

    if event_type in {"heartbeat", "power", "current", "online", "recovered"}:
        pile.last_heartbeat_at = occurred_at if occurred_at > (pile.last_heartbeat_at or occurred_at) else pile.last_heartbeat_at
        if event_type in {"heartbeat", "online", "recovered"}:
            pile.online = True
            if pile.status == "offline":
                pile.status = "online"
            if event_type == "recovered":
                pile.status = "online"
                for item in pile.connectors:
                    if item.status in {"offline", "fault"}:
                        item.status = "idle"
            if event_type in {"heartbeat", "online"}:
                for item in pile.connectors:
                    if item.status == "offline":
                        item.status = "idle"
        if event_type == "power":
            pile.current_power_kw = float(event_payload.get("power_kw") or 0)
            if connector:
                connector.status = "charging" if pile.current_power_kw > 0.2 else connector.status
        if event_type == "current":
            pile.current_power_kw = round(
                float(event_payload.get("current_a") or 0) * 220 / 1000, 2
            )
    elif event_type == "temperature":
        temperature = float(event_payload.get("temperature_c") or event_payload.get("value") or 0)
        pile.temperature_c = temperature
        if temperature >= 75:
            pile.status = "fault"
            pile.online = True
            for item in pile.connectors:
                if item.status in {"idle", "charging", "reserved"}:
                    item.status = "fault"
            severity = "critical"
    elif event_type == "fault":
        pile.status = "fault"
        pile.online = True
        for item in pile.connectors:
            if item.status in {"idle", "charging", "reserved"}:
                item.status = "fault"
    elif event_type == "offline":
        pile.online = False
        pile.status = "offline"
        pile.current_power_kw = 0
        for item in pile.connectors:
            item.status = "offline"
    elif event_type == "interrupted":
        if connector:
            active_order = (
                db.query(Order)
                .filter(
                    Order.connector_id == connector.id,
                    Order.status == "charging",
                )
                .order_by(Order.starts_at.desc())
                .first()
            )
            if active_order:
                active_order.status = "abnormal"
                active_order.ended_at = now

    # 故障类事件：创建或升级工单
    if event_type in TICKET_EVENT_TYPES or (event_type == "temperature" and severity == "critical"):
        open_ticket = _open_ticket(db, pile.id)
        if open_ticket:
            open_ticket.escalation_count += 1
            priority = _priority_for(event_type, severity, event_payload)
            if priority == "P1" and open_ticket.priority != "P1":
                open_ticket.priority = "P1"
                open_ticket.sla_due_at = now + timedelta(hours=1)
                open_ticket.status = "pending" if open_ticket.status == "closed" else open_ticket.status
            ticket = open_ticket
            record_audit(
                db,
                action="ticket.escalated",
                user=user,
                tenant_id=tenant,
                resource_type="ticket",
                resource_id=open_ticket.ticket_no,
                detail={"event_no": event_no, "event_type": event_type, "severity": severity},
                trace_id=trace_id,
                ip=ip,
            )
        else:
            priority = _priority_for(event_type, severity, event_payload)
            title_map = {
                "offline": "设备离线",
                "fault": "设备故障告警",
                "temperature": "设备温度异常",
                "interrupted": "充电过程中断",
            }
            ticket = create_ticket(
                db,
                tenant_id=tenant,
                community_id=pile.community_id,
                pile=pile,
                title=f"{pile.code} {title_map.get(event_type, '设备异常')}",
                description=(
                    f"设备 {pile.name} 上报 {event_type} 事件，严重级别 {severity}。"
                    f"事件编号 {event_no}，请尽快排查。"
                ),
                priority=priority,
                source="device",
                trace_id=trace_id,
                ip=ip,
            )
            ticket.status = "pending"
        event.ticket_id = ticket.id

    event.processed_at = now
    record_audit(
        db,
        action="device_event.received",
        user=user,
        tenant_id=tenant,
        resource_type="device_event",
        resource_id=event_no,
        detail={
            "pile": pile.code,
            "type": event_type,
            "severity": severity,
            "ticket_id": ticket.ticket_no if ticket else None,
        },
        trace_id=trace_id,
        ip=ip,
    )

    return {
        "duplicate": False,
        "event_id": event.id,
        "event_no": event.event_no,
        "pile_id": pile.id,
        "pile_status": pile.status,
        "ticket_id": ticket.id if ticket else None,
        "ticket_no": ticket.ticket_no if ticket else None,
        "priority": ticket.priority if ticket else None,
        "message": "事件已受理",
    }
