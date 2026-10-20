"""审批中心接口。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.orm import Session, joinedload

from app.auth import community_ids_for, ensure_community_access, get_current_user, require_roles
from app.db import get_db
from app.errors import forbidden, not_found
from app.models import Approval, AuditLog, User
from app.schemas import ApprovalCreateRequest, ApprovalDecisionRequest
from app.serializers import approval_public
from app.services.approvals import create_approval_request, decide_approval, execute_approval
from app.services.idempotency import lookup, store
from app.utils import iso, paginate

router = APIRouter(prefix="/api/approvals", tags=["审批"])


@router.get("", summary="审批列表")
def list_approvals(
    status: Optional[str] = None,
    type: Optional[str] = None,
    community_id: Optional[int] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=15, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if user.role == "resident":
        raise forbidden("居民用户无权访问审批中心", "ROLE_FORBIDDEN")
    if community_id is not None:
        ensure_community_access(user, community_id)
    scope = community_ids_for(user)
    query = db.query(Approval).filter(Approval.tenant_id == user.tenant_id)
    if scope is not None:
        query = query.filter(Approval.community_id.in_(scope or [-1]))
    if community_id is not None:
        query = query.filter(Approval.community_id == community_id)
    if status:
        query = query.filter(Approval.status == status)
    if type:
        query = query.filter(Approval.type == type)
    total = query.count()
    approvals = (
        query.options(
            joinedload(Approval.requester),
            joinedload(Approval.approver),
            joinedload(Approval.community),
        )
        .order_by(Approval.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return paginate([approval_public(a) for a in approvals], total, page, page_size)


@router.get("/summary", summary="审批统计")
def approval_summary(
    user: User = Depends(require_roles("operator", "technician", "finance")),
    db: Session = Depends(get_db),
) -> dict:
    scope = community_ids_for(user)
    query = db.query(Approval).filter(Approval.tenant_id == user.tenant_id)
    if scope is not None:
        query = query.filter(Approval.community_id.in_(scope or [-1]))
    approvals = query.all()
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for approval in approvals:
        by_status[approval.status] = by_status.get(approval.status, 0) + 1
        if approval.status == "pending":
            by_type[approval.type] = by_type.get(approval.type, 0) + 1
    return {
        "pending": by_status.get("pending", 0),
        "approved": by_status.get("approved", 0),
        "rejected": by_status.get("rejected", 0),
        "executed": by_status.get("executed", 0),
        "failed": by_status.get("failed", 0),
        "pending_by_type": by_type,
    }


@router.get("/{approval_id}", summary="审批详情")
def get_approval(
    approval_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if user.role == "resident":
        raise forbidden("居民用户无权访问审批中心", "ROLE_FORBIDDEN")
    approval = (
        db.query(Approval)
        .options(
            joinedload(Approval.requester),
            joinedload(Approval.approver),
            joinedload(Approval.community),
        )
        .filter(Approval.id == approval_id, Approval.tenant_id == user.tenant_id)
        .first()
    )
    if not approval:
        raise not_found("审批不存在")
    ensure_community_access(user, approval.community_id)
    timeline = (
        db.query(AuditLog)
        .filter(
            AuditLog.tenant_id == user.tenant_id,
            AuditLog.resource_type == "approval",
            AuditLog.resource_id == approval.approval_no,
        )
        .order_by(AuditLog.created_at.asc())
        .limit(50)
        .all()
    )
    data = approval_public(approval)
    data["timeline"] = [
        {"action": log.action, "at": iso(log.created_at), "actor": log.actor_name, "detail": log.detail}
        for log in timeline
    ]
    data["can_decide"] = user.role in {"admin", "finance"} and approval.status == "pending"
    data["can_execute"] = user.role in {"admin", "finance"} and approval.status == "approved"
    return data


@router.post("", summary="创建审批申请", status_code=201)
def create_approval_endpoint(
    payload: ApprovalCreateRequest,
    request: Request,
    response: Response,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(require_roles("operator", "technician", "finance")),
    db: Session = Depends(get_db),
) -> dict:
    endpoint = "POST /api/approvals"
    body = payload.model_dump(mode="json")
    existing = lookup(db, user, endpoint, idempotency_key, body)
    if existing:
        response.headers["Idempotency-Replayed"] = "true"
        return existing.response

    approval, created = create_approval_request(
        db,
        user,
        action_type=payload.type,
        target_id=payload.target_id,
        reason=payload.reason,
        payload=payload.payload,
        amount=payload.amount,
        source="manual",
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    result = approval_public(approval)
    result["created"] = created
    if idempotency_key:
        store(db, user, endpoint, idempotency_key, body, result, status_code=201)
    db.commit()
    return result


@router.post("/{approval_id}/decide", summary="审批决策")
def decide_approval_endpoint(
    approval_id: int,
    payload: ApprovalDecisionRequest,
    request: Request,
    user: User = Depends(require_roles("finance")),
    db: Session = Depends(get_db),
) -> dict:
    approval = (
        db.query(Approval)
        .options(joinedload(Approval.requester), joinedload(Approval.approver), joinedload(Approval.community))
        .filter(Approval.id == approval_id, Approval.tenant_id == user.tenant_id)
        .first()
    )
    if not approval:
        raise not_found("审批不存在")
    ensure_community_access(user, approval.community_id)
    decide_approval(
        db,
        approval,
        user,
        approve=payload.decision == "approve",
        comment=payload.comment,
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return approval_public(approval)


@router.post("/{approval_id}/execute", summary="执行审批")
def execute_approval_endpoint(
    approval_id: int,
    request: Request,
    user: User = Depends(require_roles("finance")),
    db: Session = Depends(get_db),
) -> dict:
    approval = (
        db.query(Approval)
        .options(joinedload(Approval.requester), joinedload(Approval.approver), joinedload(Approval.community))
        .filter(Approval.id == approval_id, Approval.tenant_id == user.tenant_id)
        .first()
    )
    if not approval:
        raise not_found("审批不存在")
    ensure_community_access(user, approval.community_id)
    execute_approval(
        db,
        approval,
        user,
        trace_id=getattr(request.state, "trace_id", None),
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return approval_public(approval)
