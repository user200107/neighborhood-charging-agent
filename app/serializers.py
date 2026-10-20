"""领域对象序列化。

统一输出带 Z 的 ISO 时间、脱敏手机号与前端可直接展示的派生字段。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.constants import ROLE_LABELS, RISK_LABELS, SLA_HOURS
from app.models import (
    AgentRun,
    Approval,
    AuditLog,
    Community,
    Connector,
    DeviceEvent,
    Order,
    Pile,
    Ticket,
    User,
    Zone,
)
from app.utils import human_duration, iso, mask_phone, money, utcnow


def user_public(user: User, *, include_phone: bool = False) -> dict[str, Any]:
    data = {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "role_label": ROLE_LABELS.get(user.role, user.role),
        "status": user.status,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "phone": mask_phone(user.phone) if include_phone else None,
        "communities": [
            {"id": c.id, "name": c.name, "code": c.code}
            for c in sorted(user.communities, key=lambda item: item.name)
        ],
        "last_login_at": iso(user.last_login_at),
        "created_at": iso(user.created_at),
    }
    return data


def user_brief(user: Optional[User]) -> Optional[dict[str, Any]]:
    if not user:
        return None
    return {
        "id": user.id,
        "display_name": user.display_name,
        "role": user.role,
        "role_label": ROLE_LABELS.get(user.role, user.role),
    }


def community_public(community: Community) -> dict[str, Any]:
    return {
        "id": community.id,
        "code": community.code,
        "name": community.name,
        "city": community.city,
        "address": community.address,
        "status": community.status,
        "contact_name": community.contact_name,
        "contact_phone": mask_phone(community.contact_phone),
        "zone_count": len(community.zones or []),
        "pile_count": len(community.piles or []),
    }


def zone_public(zone: Zone) -> dict[str, Any]:
    return {
        "id": zone.id,
        "community_id": zone.community_id,
        "code": zone.code,
        "name": zone.name,
        "description": zone.description,
    }


def connector_public(connector: Connector) -> dict[str, Any]:
    return {
        "id": connector.id,
        "pile_id": connector.pile_id,
        "code": connector.code,
        "gun_type": connector.gun_type,
        "status": connector.status,
        "power_kw": connector.power_kw,
        "price_per_kwh": round(connector.price_per_kwh, 2),
        "service_fee": round(connector.service_fee, 2),
        "total_energy_kwh": round(connector.total_energy_kwh, 1),
        "available": connector.status == "idle",
    }


def pile_public(pile: Pile, *, include_connectors: bool = True) -> dict[str, Any]:
    connectors = pile.connectors or []
    data = {
        "id": pile.id,
        "community_id": pile.community_id,
        "community_name": pile.community.name if pile.community else None,
        "zone_id": pile.zone_id,
        "zone_name": pile.zone.name if pile.zone else "未分区",
        "code": pile.code,
        "name": pile.name,
        "model": pile.model,
        "vendor": pile.vendor,
        "rated_power_kw": pile.rated_power_kw,
        "status": pile.status,
        "online": pile.online,
        "last_heartbeat_at": iso(pile.last_heartbeat_at),
        "heartbeat_age_seconds": (
            int((utcnow() - pile.last_heartbeat_at).total_seconds()) if pile.last_heartbeat_at else None
        ),
        "current_power_kw": round(pile.current_power_kw, 1),
        "temperature_c": round(pile.temperature_c, 1),
        "signal_strength": pile.signal_strength,
        "firmware": pile.firmware,
        "notes": pile.notes,
        "connector_count": len(connectors),
        "available_count": sum(1 for c in connectors if c.status == "idle"),
        "charging_count": sum(1 for c in connectors if c.status == "charging"),
    }
    if include_connectors:
        data["connectors"] = [connector_public(c) for c in connectors]
    return data


def order_public(order: Order, *, include_user: bool = True) -> dict[str, Any]:
    duration = None
    if order.starts_at:
        end = order.ended_at or utcnow()
        duration = max(0, int((end - order.starts_at).total_seconds()))
    return {
        "id": order.id,
        "order_no": order.order_no,
        "community_id": order.community_id,
        "community_name": order.community.name if order.community else None,
        "pile_id": order.pile_id,
        "pile_code": order.pile.code if order.pile else None,
        "pile_name": order.pile.name if order.pile else None,
        "connector_id": order.connector_id,
        "connector_code": order.connector.code if order.connector else None,
        "user_id": order.user_id,
        "user_name": order.user.display_name if include_user and order.user else None,
        "status": order.status,
        "starts_at": iso(order.starts_at),
        "ended_at": iso(order.ended_at),
        "duration_seconds": duration,
        "duration_text": human_duration(duration),
        "energy_kwh": round(order.energy_kwh, 2),
        "unit_price": round(order.unit_price, 2),
        "service_fee": round(order.service_fee, 2),
        "amount": money(order.amount),
        "refund_amount": money(order.refund_amount),
        "payment_method": order.payment_method,
        "source": order.source,
        "cancel_reason": order.cancel_reason,
        "created_at": iso(order.created_at),
        "updated_at": iso(order.updated_at),
    }


def ticket_public(ticket: Ticket) -> dict[str, Any]:
    now = utcnow()
    age = int((now - ticket.created_at).total_seconds()) if ticket.created_at else 0
    overdue = bool(
        ticket.sla_due_at
        and ticket.status not in {"closed", "cancelled"}
        and ticket.sla_due_at < now
    )
    return {
        "id": ticket.id,
        "ticket_no": ticket.ticket_no,
        "community_id": ticket.community_id,
        "community_name": ticket.community.name if ticket.community else None,
        "pile_id": ticket.pile_id,
        "pile_code": ticket.pile.code if ticket.pile else None,
        "pile_name": ticket.pile.name if ticket.pile else None,
        "title": ticket.title,
        "description": ticket.description,
        "priority": ticket.priority,
        "status": ticket.status,
        "source": ticket.source,
        "reporter": user_brief(ticket.reporter),
        "assignee": user_brief(ticket.assignee),
        "assignee_id": ticket.assignee_id,
        "resolution": ticket.resolution,
        "heartbeat_checked": ticket.heartbeat_checked,
        "test_order_verified": ticket.test_order_verified,
        "test_order_id": ticket.test_order_id,
        "sla_due_at": iso(ticket.sla_due_at),
        "sla_overdue": overdue,
        "escalation_count": ticket.escalation_count,
        "age_seconds": age,
        "age_text": "刚刚" if age < 60 else human_duration(age),
        "accepted_at": iso(ticket.accepted_at),
        "started_at": iso(ticket.started_at),
        "resolved_at": iso(ticket.resolved_at),
        "closed_at": iso(ticket.closed_at),
        "created_at": iso(ticket.created_at),
        "updated_at": iso(ticket.updated_at),
        "sla_hours": SLA_HOURS.get(ticket.priority),
    }


def approval_public(approval: Approval) -> dict[str, Any]:
    from app.constants import APPROVAL_TYPE_LABELS

    return {
        "id": approval.id,
        "approval_no": approval.approval_no,
        "type": approval.type,
        "type_label": APPROVAL_TYPE_LABELS.get(approval.type, approval.type),
        "risk_level": approval.risk_level,
        "risk_label": RISK_LABELS.get(approval.risk_level, approval.risk_level),
        "status": approval.status,
        "community_id": approval.community_id,
        "community_name": approval.community.name if approval.community else None,
        "requester": user_brief(approval.requester),
        "approver": user_brief(approval.approver),
        "target_type": approval.target_type,
        "target_id": approval.target_id,
        "target_name": approval.target_name,
        "amount": money(approval.amount),
        "impact_scope": approval.impact_scope,
        "reason": approval.reason,
        "payload": approval.payload or {},
        "decision_comment": approval.decision_comment,
        "execution_result": approval.execution_result,
        "decided_at": iso(approval.decided_at),
        "executed_at": iso(approval.executed_at),
        "created_at": iso(approval.created_at),
        "updated_at": iso(approval.updated_at),
        "trace_id": approval.trace_id,
        "source": approval.source,
    }


def event_public(event: DeviceEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_no": event.event_no,
        "pile_id": event.pile_id,
        "pile_code": event.pile.code if event.pile else None,
        "connector_id": event.connector_id,
        "event_type": event.event_type,
        "severity": event.severity,
        "payload": event.payload or {},
        "occurred_at": iso(event.occurred_at),
        "processed_at": iso(event.processed_at),
        "ticket_id": event.ticket_id,
    }


def audit_public(log: AuditLog) -> dict[str, Any]:
    return {
        "id": log.id,
        "trace_id": log.trace_id,
        "actor_id": log.actor_id,
        "actor_name": log.actor_name,
        "actor_role": log.actor_role,
        "action": log.action,
        "resource_type": log.resource_type,
        "resource_id": log.resource_id,
        "detail": log.detail or {},
        "ip": log.ip,
        "result": log.result,
        "created_at": iso(log.created_at),
    }


def agent_run_public(run: AgentRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "trace_id": run.trace_id,
        "session_id": run.session_id,
        "input": run.input,
        "intent": run.intent,
        "risk_level": run.risk_level,
        "status": run.status,
        "answer": run.answer,
        "tool_calls": run.tool_calls or [],
        "sources": run.sources or [],
        "approval_id": run.approval_id,
        "latency_ms": run.latency_ms,
        "created_at": iso(run.created_at),
    }


def metric_cards(
    *,
    availability: float,
    utilization: float,
    mttr_hours: float,
    revenue: float,
    refund: float,
    reservation_success: float,
    fault_rate: float,
    pending_tickets: int,
    online_piles: int,
    total_piles: int,
) -> list[dict[str, Any]]:
    return [
        {
            "key": "availability",
            "label": "设备可用率",
            "value": availability,
            "unit": "%",
            "hint": f"{online_piles}/{total_piles} 台在线",
            "tone": "emerald" if availability >= 90 else "amber",
        },
        {
            "key": "utilization",
            "label": "实时利用率",
            "value": utilization,
            "unit": "%",
            "hint": "充电中枪口 / 全部枪口",
            "tone": "teal",
        },
        {
            "key": "revenue",
            "label": "周期收入",
            "value": revenue,
            "unit": "元",
            "hint": f"退款 {refund:.2f} 元",
            "tone": "indigo",
        },
        {
            "key": "mttr",
            "label": "平均修复时长",
            "value": mttr_hours,
            "unit": "小时",
            "hint": f"{pending_tickets} 张工单待处理",
            "tone": "sky",
        },
        {
            "key": "fault_rate",
            "label": "设备故障率",
            "value": fault_rate,
            "unit": "%",
            "hint": "当前故障桩 / 全部桩",
            "tone": "rose" if fault_rate > 5 else "slate",
        },
        {
            "key": "reservation_success",
            "label": "预约成功率",
            "value": reservation_success,
            "unit": "%",
            "hint": "完成 + 进行中 / 全部预约",
            "tone": "violet",
        },
    ]
