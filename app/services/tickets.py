"""工单领域服务：创建、流转、验收与关闭。"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.constants import SLA_HOURS, TICKET_TRANSITIONS
from app.errors import bad_request, conflict
from app.models import Order, Pile, Ticket, User
from app.services.audit import record_audit
from app.utils import gen_ticket_no, utcnow

HEARTBEAT_WINDOW_MINUTES = 60


def _unique_ticket_no(db: Session, tenant_id: int) -> str:
    for _ in range(5):
        candidate = gen_ticket_no()
        exists = (
            db.query(Ticket.id)
            .filter(Ticket.tenant_id == tenant_id, Ticket.ticket_no == candidate)
            .first()
        )
        if not exists:
            return candidate
    raise conflict("工单号生成冲突，请重试", "TICKET_NO_CONFLICT")


def create_ticket(
    db: Session,
    *,
    tenant_id: int,
    community_id: int,
    pile: Optional[Pile],
    title: str,
    description: str = "",
    priority: str = "P3",
    source: str = "manual",
    reporter: Optional[User] = None,
    assignee_id: Optional[int] = None,
    trace_id: Optional[str] = None,
    ip: Optional[str] = None,
) -> Ticket:
    priority = priority if priority in SLA_HOURS else "P3"
    now = utcnow()
    ticket = Ticket(
        tenant_id=tenant_id,
        ticket_no=_unique_ticket_no(db, tenant_id),
        community_id=community_id,
        pile_id=pile.id if pile else None,
        title=title[:160],
        description=description,
        priority=priority,
        status="pending",
        source=source,
        reporter_id=reporter.id if reporter else None,
        assignee_id=assignee_id,
        sla_due_at=now + timedelta(hours=SLA_HOURS[priority]),
    )
    db.add(ticket)
    db.flush()
    if assignee_id:
        ticket.status = "assigned"
    record_audit(
        db,
        action="ticket.created",
        user=reporter,
        tenant_id=tenant_id,
        resource_type="ticket",
        resource_id=ticket.ticket_no,
        detail={"priority": priority, "title": title, "source": source},
        trace_id=trace_id,
        ip=ip,
    )
    return ticket


def _transition(ticket: Ticket, target: str, action: str) -> None:
    if target not in TICKET_TRANSITIONS.get(ticket.status, frozenset()):
        raise conflict(
            f"工单当前状态 {ticket.status} 不允许执行 {action}",
            "TICKET_STATUS_CONFLICT",
            {"current": ticket.status, "target": target},
        )
    ticket.status = target


def assign_ticket(
    db: Session,
    ticket: Ticket,
    assignee: User,
    actor: User,
    *,
    trace_id: Optional[str] = None,
    ip: Optional[str] = None,
) -> Ticket:
    if assignee.tenant_id != ticket.tenant_id:
        raise bad_request("不能分派给其他租户的用户", "ASSIGNEE_INVALID")
    if assignee.role not in {"technician", "operator", "admin"}:
        raise bad_request("只能分派给维修或运营人员", "ASSIGNEE_INVALID")
    if ticket.status in {"closed", "cancelled"}:
        raise conflict("已关闭工单不能重新分派", "TICKET_CLOSED")
    if ticket.status == "pending":
        _transition(ticket, "assigned", "assign")
    elif ticket.status in {"assigned", "accepted"}:
        pass
    else:
        raise conflict("当前状态不能改派", "TICKET_STATUS_CONFLICT")
    previous = ticket.assignee_id
    ticket.assignee_id = assignee.id
    record_audit(
        db,
        action="ticket.assigned",
        user=actor,
        resource_type="ticket",
        resource_id=ticket.ticket_no,
        detail={"assignee": assignee.display_name, "previous": previous},
        trace_id=trace_id,
        ip=ip,
    )
    return ticket


def accept_ticket(
    db: Session, ticket: Ticket, actor: User, *, trace_id: Optional[str] = None, ip: Optional[str] = None
) -> Ticket:
    if ticket.assignee_id and ticket.assignee_id != actor.id and actor.role not in {"admin", "operator"}:
        raise conflict("只能接取分派给自己的工单", "TICKET_NOT_ASSIGNED_TO_YOU")
    if ticket.status == "pending":
        ticket.assignee_id = actor.id
        ticket.status = "assigned"
    _transition(ticket, "accepted", "accept")
    ticket.accepted_at = utcnow()
    record_audit(
        db, action="ticket.accepted", user=actor, resource_type="ticket",
        resource_id=ticket.ticket_no, detail={}, trace_id=trace_id, ip=ip,
    )
    return ticket


def start_ticket(
    db: Session, ticket: Ticket, actor: User, *, trace_id: Optional[str] = None, ip: Optional[str] = None
) -> Ticket:
    _transition(ticket, "processing", "start")
    ticket.started_at = utcnow()
    record_audit(
        db, action="ticket.started", user=actor, resource_type="ticket",
        resource_id=ticket.ticket_no, detail={}, trace_id=trace_id, ip=ip,
    )
    return ticket


def resolve_ticket(
    db: Session,
    ticket: Ticket,
    actor: User,
    resolution: str,
    *,
    trace_id: Optional[str] = None,
    ip: Optional[str] = None,
) -> Ticket:
    if len(resolution.strip()) < 5:
        raise bad_request("维修回填至少 5 个字", "RESOLUTION_TOO_SHORT")
    _transition(ticket, "pending_verification", "resolve")
    ticket.resolution = resolution.strip()[:2000]
    ticket.resolved_at = utcnow()
    ticket.heartbeat_checked = False
    ticket.test_order_verified = False
    record_audit(
        db, action="ticket.resolved", user=actor, resource_type="ticket",
        resource_id=ticket.ticket_no, detail={"resolution": ticket.resolution},
        trace_id=trace_id, ip=ip,
    )
    return ticket


def _heartbeat_healthy(pile: Optional[Pile]) -> tuple[bool, str]:
    if pile is None:
        return False, "工单未关联设备"
    if not pile.online:
        return False, "设备当前离线，心跳检查未通过"
    if not pile.last_heartbeat_at:
        return False, "缺少设备心跳记录"
    age = (utcnow() - pile.last_heartbeat_at).total_seconds() / 60
    if age > HEARTBEAT_WINDOW_MINUTES:
        return False, f"最近心跳距今 {age:.0f} 分钟，超过 {HEARTBEAT_WINDOW_MINUTES} 分钟阈值"
    return True, "心跳正常"


def verify_ticket(
    db: Session,
    ticket: Ticket,
    actor: User,
    test_order_id: int,
    *,
    trace_id: Optional[str] = None,
    ip: Optional[str] = None,
) -> Ticket:
    if ticket.status not in {"accepted", "processing", "pending_verification"}:
        raise conflict("当前状态不能提交验收", "TICKET_STATUS_CONFLICT")
    order = db.get(Order, test_order_id)
    if not order or order.tenant_id != ticket.tenant_id:
        raise bad_request("测试订单不存在", "TEST_ORDER_NOT_FOUND")
    if ticket.pile_id and order.pile_id != ticket.pile_id:
        raise bad_request("测试订单必须来自同一台设备", "TEST_ORDER_PILE_MISMATCH")
    if order.status != "completed":
        raise bad_request("测试订单尚未完成", "TEST_ORDER_NOT_COMPLETED")

    healthy, message = _heartbeat_healthy(ticket.pile)
    if not healthy:
        raise conflict(f"验收失败：{message}", "HEARTBEAT_CHECK_FAILED", {"message": message})

    ticket.heartbeat_checked = True
    ticket.test_order_verified = True
    ticket.test_order_id = order.id
    if ticket.status != "pending_verification":
        ticket.status = "pending_verification"
    record_audit(
        db,
        action="ticket.verified",
        user=actor,
        resource_type="ticket",
        resource_id=ticket.ticket_no,
        detail={"test_order_id": order.id, "heartbeat": message},
        trace_id=trace_id,
        ip=ip,
    )
    return ticket


def close_ticket(
    db: Session, ticket: Ticket, actor: User, *, trace_id: Optional[str] = None, ip: Optional[str] = None
) -> Ticket:
    if ticket.status != "pending_verification":
        raise conflict("工单必须先完成维修并进入待验收状态", "TICKET_NOT_VERIFIED")
    if not ticket.heartbeat_checked or not ticket.test_order_verified:
        raise conflict("关闭前必须完成设备心跳检查和测试订单验证", "TICKET_ACCEPTANCE_REQUIRED")

    healthy, message = _heartbeat_healthy(ticket.pile)
    if not healthy:
        raise conflict(f"关闭失败：{message}", "HEARTBEAT_CHECK_FAILED")

    order = db.get(Order, ticket.test_order_id) if ticket.test_order_id else None
    if not order or order.status != "completed":
        raise conflict("测试订单状态异常，无法关闭工单", "TEST_ORDER_INVALID")

    ticket.status = "closed"
    ticket.closed_at = utcnow()

    pile = ticket.pile
    if pile and pile.status == "fault":
        pile.status = "online"
        pile.online = True
        for connector in pile.connectors:
            if connector.status == "fault":
                connector.status = "idle"

    record_audit(
        db,
        action="ticket.closed",
        user=actor,
        resource_type="ticket",
        resource_id=ticket.ticket_no,
        detail={"test_order_id": order.id, "heartbeat": message},
        trace_id=trace_id,
        ip=ip,
    )
    return ticket
