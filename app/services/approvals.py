"""审批流：申请、决策、执行与回执。

高风险动作只能经由本服务创建审批；执行入口再次校验状态与角色。
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.auth import community_ids_for
from app.constants import APPROVAL_TYPE_LABELS, HIGH_RISK_ACTIONS
from app.errors import bad_request, conflict, forbidden, not_found
from app.models import Approval, Community, Connector, Order, Pile, Ticket, User
from app.services.audit import record_audit
from app.services.tickets import assign_ticket
from app.utils import gen_approval_no, money, utcnow


def _unique_approval_no(db: Session, tenant_id: int) -> str:
    for _ in range(5):
        candidate = gen_approval_no()
        if not (
            db.query(Approval.id)
            .filter(Approval.tenant_id == tenant_id, Approval.approval_no == candidate)
            .first()
        ):
            return candidate
    raise conflict("审批号生成冲突，请重试", "APPROVAL_NO_CONFLICT")


def _check_scope(user: User, community_id: Optional[int]) -> None:
    if community_id is None:
        return
    scope = community_ids_for(user)
    if scope is not None and community_id not in scope:
        raise forbidden("无权操作该社区的数据", "COMMUNITY_FORBIDDEN")


def _target_from_payload(
    db: Session, user: User, action_type: str, target_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    if action_type == "stop_pile":
        pile_id = payload.get("pile_id") or target_id
        if not pile_id:
            raise bad_request("缺少设备 ID", "PILE_REQUIRED")
        try:
            pile = db.get(Pile, int(pile_id))
        except (TypeError, ValueError) as exc:
            raise bad_request("设备 ID 无效", "PILE_ID_INVALID") from exc
        if not pile or pile.tenant_id != user.tenant_id:
            raise not_found("设备不存在", "PILE_NOT_FOUND")
        _check_scope(user, pile.community_id)
        connector_count = len(pile.connectors)
        community = db.get(Community, pile.community_id)
        return {
            "community_id": pile.community_id,
            "target_type": "pile",
            "target_id": str(pile.id),
            "target_name": pile.name,
            "impact_scope": f"{community.name if community else ''} · {connector_count} 个枪口受影响",
            "payload": {**payload, "pile_id": pile.id},
        }
    if action_type == "refund":
        order: Optional[Order] = None
        if payload.get("order_id"):
            order = db.get(Order, int(payload["order_id"]))
        elif payload.get("order_no") or target_id:
            order_no = payload.get("order_no") or target_id
            order = (
                db.query(Order)
                .filter(Order.tenant_id == user.tenant_id, Order.order_no == str(order_no))
                .first()
            )
        if not order or order.tenant_id != user.tenant_id:
            raise not_found("订单不存在", "ORDER_NOT_FOUND")
        remaining = money(order.amount - order.refund_amount)
        amount = money(payload.get("amount") or remaining)
        if amount <= 0:
            raise bad_request("退款金额必须大于 0", "REFUND_AMOUNT_INVALID")
        if amount > remaining:
            raise bad_request("退款金额不能超过订单可退金额", "REFUND_AMOUNT_EXCEEDED")
        _check_scope(user, order.community_id)
        return {
            "community_id": order.community_id,
            "target_type": "order",
            "target_id": order.order_no,
            "target_name": f"{order.order_no} · {order.user.display_name if order.user else ''}",
            "impact_scope": f"订单金额 {order.amount:.2f} 元，可退 {remaining:.2f} 元",
            "payload": {**payload, "order_id": order.id, "order_no": order.order_no, "amount": amount},
            "amount": amount,
        }
    if action_type == "price_change":
        connector_id = payload.get("connector_id") or target_id
        if not connector_id:
            raise bad_request("缺少枪口 ID", "CONNECTOR_REQUIRED")
        try:
            connector = db.get(Connector, int(connector_id))
        except (TypeError, ValueError) as exc:
            raise bad_request("枪口 ID 无效", "CONNECTOR_ID_INVALID") from exc
        if not connector or connector.tenant_id != user.tenant_id:
            raise not_found("枪口不存在", "CONNECTOR_NOT_FOUND")
        pile = db.get(Pile, connector.pile_id)
        if not pile:
            raise not_found("设备不存在", "PILE_NOT_FOUND")
        _check_scope(user, pile.community_id)
        new_price = float(payload.get("price_per_kwh", connector.price_per_kwh))
        new_fee = float(payload.get("service_fee", connector.service_fee))
        if new_price < 0 or new_fee < 0:
            raise bad_request("计费价格不能为负数", "PRICE_INVALID")
        return {
            "community_id": pile.community_id,
            "target_type": "connector",
            "target_id": str(connector.id),
            "target_name": f"{pile.code} / {connector.code} 号枪口",
            "impact_scope": f"该枪口后续订单，当前 {connector.price_per_kwh:.2f} + {connector.service_fee:.2f} 元/度",
            "payload": {
                **payload,
                "connector_id": connector.id,
                "price_per_kwh": new_price,
                "service_fee": new_fee,
            },
        }
    if action_type == "bulk_reassign":
        ticket_ids = payload.get("ticket_ids") or []
        assignee_id = payload.get("assignee_id")
        if not ticket_ids:
            raise bad_request("缺少工单列表", "TICKET_IDS_REQUIRED")
        if not assignee_id:
            raise bad_request("缺少被分派人", "ASSIGNEE_REQUIRED")
        assignee = db.get(User, int(assignee_id))
        if not assignee or assignee.tenant_id != user.tenant_id:
            raise not_found("被分派人不存在", "ASSIGNEE_NOT_FOUND")
        tickets = (
            db.query(Ticket)
            .filter(Ticket.tenant_id == user.tenant_id, Ticket.id.in_(ticket_ids))
            .all()
        )
        if len(tickets) != len(set(ticket_ids)):
            raise not_found("部分工单不存在", "TICKET_NOT_FOUND")
        community_id = tickets[0].community_id
        for ticket in tickets:
            _check_scope(user, ticket.community_id)
        return {
            "community_id": community_id,
            "target_type": "ticket_batch",
            "target_id": ",".join(str(t.id) for t in tickets)[:60],
            "target_name": f"{len(tickets)} 张工单批量改派",
            "impact_scope": f"工单 {len(tickets)} 张 → {assignee.display_name}",
            "payload": {**payload, "ticket_ids": [t.id for t in tickets], "assignee_id": assignee.id},
        }
    raise bad_request("不支持的审批类型", "APPROVAL_TYPE_INVALID")


def create_approval_request(
    db: Session,
    requester: User,
    *,
    action_type: str,
    target_id: str = "",
    reason: str = "",
    payload: Optional[dict[str, Any]] = None,
    amount: float = 0.0,
    source: str = "manual",
    trace_id: Optional[str] = None,
    ip: Optional[str] = None,
) -> tuple[Approval, bool]:
    if action_type not in HIGH_RISK_ACTIONS:
        raise bad_request("该动作不是高风险动作，无需审批", "NOT_HIGH_RISK")
    if requester.role not in {"admin", "operator", "technician", "finance"}:
        raise forbidden("当前角色不能发起高风险动作", "ROLE_FORBIDDEN")
    if len(reason.strip()) < 4:
        raise bad_request("请填写至少 4 个字的业务理由", "REASON_REQUIRED")

    payload = payload or {}
    info = _target_from_payload(db, requester, action_type, target_id, payload)
    target_id_value = info["target_id"]

    existing = (
        db.query(Approval)
        .filter(
            Approval.tenant_id == requester.tenant_id,
            Approval.type == action_type,
            Approval.target_id == target_id_value,
            Approval.status.in_(["pending", "approved", "executing"]),
        )
        .order_by(Approval.created_at.desc())
        .first()
    )
    if existing:
        return existing, False

    approval = Approval(
        tenant_id=requester.tenant_id,
        approval_no=_unique_approval_no(db, requester.tenant_id),
        type=action_type,
        risk_level="high",
        status="pending",
        community_id=info.get("community_id"),
        requester_id=requester.id,
        target_type=info["target_type"],
        target_id=target_id_value,
        target_name=info["target_name"],
        amount=money(info.get("amount", amount)),
        impact_scope=info["impact_scope"],
        reason=reason.strip()[:2000],
        payload=info["payload"],
        source=source,
        trace_id=trace_id,
    )
    db.add(approval)
    db.flush()
    record_audit(
        db,
        action="approval.created",
        user=requester,
        resource_type="approval",
        resource_id=approval.approval_no,
        detail={
            "type": action_type,
            "target": approval.target_name,
            "amount": approval.amount,
            "label": APPROVAL_TYPE_LABELS.get(action_type),
        },
        trace_id=trace_id,
        ip=ip,
    )
    return approval, True


def decide_approval(
    db: Session,
    approval: Approval,
    approver: User,
    *,
    approve: bool,
    comment: str = "",
    trace_id: Optional[str] = None,
    ip: Optional[str] = None,
) -> Approval:
    if approver.role not in {"admin", "finance"}:
        raise forbidden("只有财务或管理员可以审批", "APPROVER_FORBIDDEN")
    if approval.tenant_id != approver.tenant_id:
        raise not_found("审批不存在")
    if approval.status != "pending":
        raise conflict("该审批已处理，禁止重复审批", "APPROVAL_ALREADY_DECIDED", {"status": approval.status})
    if approval.requester_id == approver.id and approver.role != "admin":
        raise forbidden("不能审批自己发起的申请", "SELF_APPROVAL_FORBIDDEN")

    approval.status = "approved" if approve else "rejected"
    approval.approver_id = approver.id
    approval.decided_at = utcnow()
    approval.decision_comment = (comment or "").strip()[:255]
    record_audit(
        db,
        action="approval.approved" if approve else "approval.rejected",
        user=approver,
        resource_type="approval",
        resource_id=approval.approval_no,
        detail={"comment": approval.decision_comment},
        trace_id=trace_id,
        ip=ip,
    )
    return approval


def execute_approval(
    db: Session,
    approval: Approval,
    executor: User,
    *,
    trace_id: Optional[str] = None,
    ip: Optional[str] = None,
) -> Approval:
    if executor.role not in {"admin", "finance"}:
        raise forbidden("只有财务或管理员可以执行审批", "EXECUTOR_FORBIDDEN")
    if approval.tenant_id != executor.tenant_id:
        raise not_found("审批不存在")
    if approval.status == "executed":
        return approval
    if approval.status != "approved":
        raise conflict("只有已通过的审批可以执行", "APPROVAL_NOT_APPROVED")
    if approval.executed_at is not None:
        return approval

    approval.status = "executing"
    db.flush()
    result: dict[str, Any] = {}
    try:
        if approval.type == "stop_pile":
            pile_id = approval.payload.get("pile_id") or approval.target_id
            pile = db.get(Pile, int(pile_id)) if str(pile_id).isdigit() else None
            if not pile or pile.tenant_id != approval.tenant_id:
                raise not_found("设备不存在", "PILE_NOT_FOUND")
            pile.status = "maintenance"
            pile.online = False
            pile.current_power_kw = 0
            for connector in pile.connectors:
                connector.status = "offline"
            result = {
                "result": "success",
                "message": f"{pile.name} 已进入维护状态，枪口已下线。",
                "pile_id": pile.id,
            }
        elif approval.type == "refund":
            order = None
            order_id = approval.payload.get("order_id")
            if order_id:
                order = db.get(Order, int(order_id))
            if order is None:
                order_no = approval.payload.get("order_no") or approval.target_id
                order = (
                    db.query(Order)
                    .filter(
                        Order.tenant_id == approval.tenant_id,
                        Order.order_no == str(order_no),
                    )
                    .first()
                )
            if not order or order.tenant_id != approval.tenant_id:
                raise not_found("订单不存在", "ORDER_NOT_FOUND")
            amount = money(approval.payload.get("amount") or approval.amount)
            remaining = money(order.amount - order.refund_amount)
            if amount <= 0 or amount > remaining:
                raise conflict("退款金额超出可退范围", "REFUND_AMOUNT_EXCEEDED")
            order.refund_amount = money(order.refund_amount + amount)
            result = {
                "result": "success",
                "message": f"订单 {order.order_no} 退款 {amount:.2f} 元已受理。",
                "order_no": order.order_no,
                "refund_amount": amount,
            }
        elif approval.type == "price_change":
            connector_id = approval.payload.get("connector_id") or approval.target_id
            connector = db.get(Connector, int(connector_id)) if str(connector_id).isdigit() else None
            if not connector or connector.tenant_id != approval.tenant_id:
                raise not_found("枪口不存在", "CONNECTOR_NOT_FOUND")
            old_price, old_fee = connector.price_per_kwh, connector.service_fee
            connector.price_per_kwh = float(approval.payload.get("price_per_kwh", old_price))
            connector.service_fee = float(approval.payload.get("service_fee", old_fee))
            result = {
                "result": "success",
                "message": (
                    f"枪口计费已更新为 {connector.price_per_kwh:.2f} + {connector.service_fee:.2f} 元/度。"
                ),
                "connector_id": connector.id,
                "before": {"price_per_kwh": old_price, "service_fee": old_fee},
                "after": {"price_per_kwh": connector.price_per_kwh, "service_fee": connector.service_fee},
            }
        elif approval.type == "bulk_reassign":
            assignee = db.get(User, int(approval.payload.get("assignee_id")))
            if not assignee or assignee.tenant_id != approval.tenant_id:
                raise not_found("被分派人不存在", "ASSIGNEE_NOT_FOUND")
            tickets = (
                db.query(Ticket)
                .filter(
                    Ticket.tenant_id == approval.tenant_id,
                    Ticket.id.in_(approval.payload.get("ticket_ids") or []),
                )
                .all()
            )
            for ticket in tickets:
                assign_ticket(db, ticket, assignee, executor, trace_id=trace_id, ip=ip)
            result = {
                "result": "success",
                "message": f"已批量改派 {len(tickets)} 张工单给 {assignee.display_name}。",
                "count": len(tickets),
            }
        else:
            raise bad_request("未知审批类型", "APPROVAL_TYPE_INVALID")
    except Exception as exc:
        approval.status = "failed"
        approval.execution_result = {"result": "failed", "message": str(exc)}
        record_audit(
            db,
            action="approval.execution_failed",
            user=executor,
            resource_type="approval",
            resource_id=approval.approval_no,
            detail={"error": str(exc)},
            result="failed",
            trace_id=trace_id,
            ip=ip,
        )
        raise

    approval.status = "executed"
    approval.executed_at = utcnow()
    approval.execution_result = {**result, "executed_by": executor.display_name}
    record_audit(
        db,
        action="approval.executed",
        user=executor,
        resource_type="approval",
        resource_id=approval.approval_no,
        detail=approval.execution_result,
        trace_id=trace_id,
        ip=ip,
    )
    return approval
