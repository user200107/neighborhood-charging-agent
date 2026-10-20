"""维修工单接口。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session, joinedload

from app.auth import (
    community_ids_for,
    ensure_community_access,
    get_current_user,
    require_roles,
)
from app.db import get_db
from app.errors import forbidden, not_found
from app.models import AuditLog, Community, Pile, Ticket, User
from app.schemas import (
    TicketAssignRequest,
    TicketCreateRequest,
    TicketResolveRequest,
    TicketVerifyRequest,
)
from app.serializers import ticket_public, user_brief
from app.services.audit import record_audit
from app.services.tickets import (
    accept_ticket,
    assign_ticket,
    close_ticket,
    create_ticket,
    resolve_ticket,
    start_ticket,
    verify_ticket,
)
from app.utils import iso, paginate, utcnow

router = APIRouter(prefix="/api/tickets", tags=["工单"])


def _get_ticket(db: Session, user: User, ticket_id: int) -> Ticket:
    ticket = (
        db.query(Ticket)
        .options(
            joinedload(Ticket.community),
            joinedload(Ticket.pile),
            joinedload(Ticket.reporter),
            joinedload(Ticket.assignee),
        )
        .filter(Ticket.id == ticket_id, Ticket.tenant_id == user.tenant_id)
        .first()
    )
    if not ticket:
        raise not_found("工单不存在")
    ensure_community_access(user, ticket.community_id)
    if user.role == "resident" and ticket.reporter_id != user.id:
        raise forbidden("无权查看他人工单")
    return ticket


def _can_operate(user: User) -> bool:
    return user.role in {"admin", "operator", "technician"}


def _ensure_operable(user: User) -> None:
    if not _can_operate(user):
        raise forbidden("当前角色不能处理工单", "ROLE_FORBIDDEN")


@router.get("", summary="工单列表")
def list_tickets(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    community_id: Optional[int] = None,
    assignee_id: Optional[int] = None,
    keyword: Optional[str] = None,
    overdue: Optional[bool] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=15, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if community_id is not None:
        ensure_community_access(user, community_id)
    scope = community_ids_for(user)
    query = db.query(Ticket).filter(Ticket.tenant_id == user.tenant_id)
    if scope is not None:
        query = query.filter(Ticket.community_id.in_(scope or [-1]))
    if community_id is not None:
        query = query.filter(Ticket.community_id == community_id)
    if status:
        query = query.filter(Ticket.status == status)
    if priority:
        query = query.filter(Ticket.priority == priority)
    if assignee_id:
        query = query.filter(Ticket.assignee_id == assignee_id)
    if overdue:
        query = query.filter(
            Ticket.sla_due_at < utcnow(),
            Ticket.status.notin_(["closed", "cancelled"]),
        )
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            (Ticket.ticket_no.ilike(like))
            | (Ticket.title.ilike(like))
            | Ticket.pile.has(Pile.code.ilike(like))
        )
    if user.role == "resident":
        query = query.filter(Ticket.reporter_id == user.id)
    total = query.count()
    tickets = (
        query.options(
            joinedload(Ticket.community),
            joinedload(Ticket.pile),
            joinedload(Ticket.reporter),
            joinedload(Ticket.assignee),
        )
        .order_by(Ticket.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return paginate([ticket_public(t) for t in tickets], total, page, page_size)


@router.get("/assignees", summary="可分派人员")
def list_assignees(
    community_id: Optional[int] = None,
    user: User = Depends(require_roles("operator", "technician", "finance")),
    db: Session = Depends(get_db),
) -> dict:
    if community_id is not None:
        ensure_community_access(user, community_id)
    scope = community_ids_for(user)
    users = (
        db.query(User)
        .filter(
            User.tenant_id == user.tenant_id,
            User.role.in_(["technician", "operator"]),
            User.status == "active",
        )
        .all()
    )
    if scope is not None:
        users = [u for u in users if any(c.id in scope for c in u.communities)]
    counts = {
        uid: db.query(Ticket)
        .filter(
            Ticket.tenant_id == user.tenant_id,
            Ticket.assignee_id == uid,
            Ticket.status.notin_(["closed", "cancelled"]),
        )
        .count()
        for uid in (u.id for u in users)
    }
    return {
        "items": [
            {**user_brief(u), "open_tickets": counts.get(u.id, 0), "communities": [c.name for c in u.communities]}
            for u in users
        ]
    }


@router.get("/{ticket_id}", summary="工单详情")
def get_ticket(
    ticket_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    ticket = _get_ticket(db, user, ticket_id)
    timeline = (
        db.query(AuditLog)
        .filter(
            AuditLog.tenant_id == user.tenant_id,
            AuditLog.resource_type == "ticket",
            AuditLog.resource_id == ticket.ticket_no,
        )
        .order_by(AuditLog.created_at.asc())
        .limit(50)
        .all()
    )
    data = ticket_public(ticket)
    data["timeline"] = [
        {"action": log.action, "at": iso(log.created_at), "actor": log.actor_name, "detail": log.detail}
        for log in timeline
    ]
    return data


@router.post("", summary="创建工单", status_code=201)
def create_ticket_endpoint(
    payload: TicketCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if user.role not in {"admin", "operator", "technician", "resident"}:
        raise forbidden("当前角色不能创建工单", "ROLE_FORBIDDEN")

    pile: Optional[Pile] = None
    if payload.pile_id:
        pile = db.get(Pile, payload.pile_id)
        if not pile or pile.tenant_id != user.tenant_id:
            raise not_found("设备不存在")
        ensure_community_access(user, pile.community_id)
        community_id = pile.community_id
    else:
        if not payload.community_id:
            raise not_found("请选择社区或设备", "COMMUNITY_REQUIRED")
        ensure_community_access(user, payload.community_id)
        community_id = payload.community_id

    source = "complaint" if user.role == "resident" else "manual"
    priority = "P3" if user.role == "resident" else payload.priority
    assignee_id = payload.assignee_id if user.role in {"admin", "operator"} else None
    if assignee_id:
        assignee = db.get(User, assignee_id)
        if not assignee or assignee.tenant_id != user.tenant_id:
            raise not_found("被分派人不存在")
        ensure_community_access(user, community_id)

    ticket = create_ticket(
        db,
        tenant_id=user.tenant_id,
        community_id=community_id,
        pile=pile,
        title=payload.title,
        description=payload.description or "",
        priority=priority,
        source=source,
        reporter=user,
        assignee_id=assignee_id,
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return ticket_public(ticket)


@router.post("/{ticket_id}/assign", summary="分派工单")
def assign_ticket_endpoint(
    ticket_id: int,
    payload: TicketAssignRequest,
    request: Request,
    user: User = Depends(require_roles("operator", "technician")),
    db: Session = Depends(get_db),
) -> dict:
    ticket = _get_ticket(db, user, ticket_id)
    assignee = db.get(User, payload.assignee_id)
    if not assignee or assignee.tenant_id != user.tenant_id:
        raise not_found("被分派人不存在")
    if user.role == "technician" and assignee.id != user.id and ticket.assignee_id != user.id:
        raise forbidden("维修人员只能接取或转派给自己的工单")
    assign_ticket(
        db,
        ticket,
        assignee,
        user,
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return ticket_public(ticket)


@router.post("/{ticket_id}/accept", summary="接单")
def accept_ticket_endpoint(
    ticket_id: int,
    request: Request,
    user: User = Depends(require_roles("operator", "technician")),
    db: Session = Depends(get_db),
) -> dict:
    ticket = _get_ticket(db, user, ticket_id)
    accept_ticket(
        db,
        ticket,
        user,
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return ticket_public(ticket)


@router.post("/{ticket_id}/start", summary="开始处理")
def start_ticket_endpoint(
    ticket_id: int,
    request: Request,
    user: User = Depends(require_roles("operator", "technician")),
    db: Session = Depends(get_db),
) -> dict:
    ticket = _get_ticket(db, user, ticket_id)
    start_ticket(
        db,
        ticket,
        user,
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return ticket_public(ticket)


@router.post("/{ticket_id}/resolve", summary="维修回填")
def resolve_ticket_endpoint(
    ticket_id: int,
    payload: TicketResolveRequest,
    request: Request,
    user: User = Depends(require_roles("operator", "technician")),
    db: Session = Depends(get_db),
) -> dict:
    ticket = _get_ticket(db, user, ticket_id)
    resolve_ticket(
        db,
        ticket,
        user,
        payload.resolution,
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return ticket_public(ticket)


@router.post("/{ticket_id}/verify", summary="测试订单验收")
def verify_ticket_endpoint(
    ticket_id: int,
    payload: TicketVerifyRequest,
    request: Request,
    user: User = Depends(require_roles("operator", "technician")),
    db: Session = Depends(get_db),
) -> dict:
    ticket = _get_ticket(db, user, ticket_id)
    verify_ticket(
        db,
        ticket,
        user,
        payload.test_order_id,
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return ticket_public(ticket)


@router.post("/{ticket_id}/close", summary="关闭工单")
def close_ticket_endpoint(
    ticket_id: int,
    request: Request,
    user: User = Depends(require_roles("operator")),
    db: Session = Depends(get_db),
) -> dict:
    ticket = _get_ticket(db, user, ticket_id)
    close_ticket(
        db,
        ticket,
        user,
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return ticket_public(ticket)


@router.post("/{ticket_id}/cancel", summary="取消工单")
def cancel_ticket_endpoint(
    ticket_id: int,
    request: Request,
    user: User = Depends(require_roles("operator")),
    db: Session = Depends(get_db),
) -> dict:
    ticket = _get_ticket(db, user, ticket_id)
    if ticket.status in {"closed", "cancelled", "pending_verification"}:
        from app.errors import conflict

        raise conflict("当前状态不能取消工单", "TICKET_STATUS_CONFLICT")
    previous = ticket.status
    ticket.status = "cancelled"
    record_audit(
        db,
        action="ticket.cancelled",
        user=user,
        resource_type="ticket",
        resource_id=ticket.ticket_no,
        detail={"previous": previous},
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return ticket_public(ticket)
