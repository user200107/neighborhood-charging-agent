"""Agent 工具白名单。

每个工具声明输入模型、角色权限、风险级别与数据来源；模型只能调用此处登记的工具。
高风险工具仅创建审批申请，不产生业务执行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.auth import community_ids_for
from app.constants import APPROVAL_TYPE_LABELS, HIGH_RISK_ACTIONS
from app.errors import ApiError, bad_request, forbidden, not_found
from app.models import Approval, Community, Connector, DeviceEvent, Order, Pile, Ticket, User
from app.serializers import approval_public, order_public, pile_public, ticket_public
from app.services import metrics as metrics_service
from app.services.approvals import create_approval_request
from app.services.orders import has_time_conflict
from app.services.tickets import create_ticket
from app.utils import iso, parse_datetime, utcnow


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OverviewInput(ToolInput):
    days: int = Field(default=7, ge=1, le=30)
    community_id: Optional[int] = None


class PileHealthInput(ToolInput):
    status: Optional[str] = None
    community_id: Optional[int] = None
    limit: int = Field(default=8, ge=1, le=20)


class DiagnoseInput(ToolInput):
    pile_id: Optional[int] = None
    pile_code: Optional[str] = None


class OrderAnalyticsInput(ToolInput):
    days: int = Field(default=7, ge=1, le=30)
    community_id: Optional[int] = None


class MyOrdersInput(ToolInput):
    limit: int = Field(default=8, ge=1, le=20)


class TicketOverviewInput(ToolInput):
    status: Optional[str] = None
    priority: Optional[str] = None
    limit: int = Field(default=8, ge=1, le=20)
    community_id: Optional[int] = None


class ApprovalOverviewInput(ToolInput):
    status: Optional[str] = "pending"
    type: Optional[str] = None
    limit: int = Field(default=8, ge=1, le=20)
    community_id: Optional[int] = None


class AvailabilityInput(ToolInput):
    community_id: Optional[int] = None
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    limit: int = Field(default=6, ge=1, le=20)


class RepairInput(ToolInput):
    pile_id: Optional[int] = None
    pile_code: Optional[str] = None


class StopPileInput(ToolInput):
    pile_id: Optional[int] = None
    pile_code: Optional[str] = None
    reason: str = Field(min_length=4, max_length=500)


class RefundInput(ToolInput):
    order_no: Optional[str] = None
    amount: Optional[float] = Field(default=None, ge=0.01)
    reason: str = Field(min_length=4, max_length=500)


class PriceChangeInput(ToolInput):
    connector_id: Optional[int] = None
    pile_code: Optional[str] = None
    price_per_kwh: float = Field(ge=0, le=10)
    service_fee: float = Field(ge=0, le=10)
    reason: str = Field(min_length=4, max_length=500)


class BulkReassignInput(ToolInput):
    ticket_ids: list[int] = Field(min_length=1, max_length=50)
    assignee_id: int
    reason: str = Field(min_length=4, max_length=500)


class CreateTicketInput(ToolInput):
    pile_id: Optional[int] = None
    pile_code: Optional[str] = None
    title: str = Field(min_length=4, max_length=120)
    description: str = ""
    priority: str = "P3"


class GlossaryInput(ToolInput):
    term: str = ""


@dataclass
class ToolOutcome:
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)


Handler = Callable[[Session, User, BaseModel], ToolOutcome]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    label: str
    description: str
    input_model: type[BaseModel]
    roles: frozenset[str]
    risk_level: str
    handler: Handler
    timeout_ms: int = 3000
    idempotent: bool = True
    audit_fields: tuple[str, ...] = ("name", "risk_level", "status")


def _source(name: str, detail: str, count: Optional[int] = None) -> dict[str, Any]:
    return {"type": "table", "name": name, "detail": detail, "count": count}


def _scope_ids(db: Session, user: User, community_id: Optional[int]) -> list[int]:
    return metrics_service.scoped_community_ids(db, user, community_id)


def _get_pile(db: Session, user: User, pile_id: Optional[int], pile_code: Optional[str]) -> Pile:
    if not pile_id and not pile_code:
        raise bad_request("请提供设备编号或设备 ID", "PILE_REQUIRED")
    query = db.query(Pile).filter(Pile.tenant_id == user.tenant_id)
    scope = community_ids_for(user)
    if scope is not None:
        query = query.filter(Pile.community_id.in_(scope or [-1]))
    if pile_id:
        pile = query.filter(Pile.id == pile_id).first()
    else:
        pile = query.filter(Pile.code == pile_code.strip().upper()).first()
    if not pile:
        raise not_found("未找到匹配的设备", "PILE_NOT_FOUND")
    return pile


def _overview(db: Session, user: User, params: OverviewInput) -> ToolOutcome:
    data = metrics_service.dashboard(db, user, days=params.days, community_id=params.community_id)
    s = data["summary"]
    summary = (
        f"近 {params.days} 天覆盖 {len(data['communities'])} 个社区：收入 {s['revenue']:.2f} 元，"
        f"设备可用率 {s['availability']:.1f}%，实时利用率 {s['utilization']:.1f}%，"
        f"故障率 {s['fault_rate']:.1f}%，待处理工单 {s['pending_tickets']} 张，"
        f"平均修复时长 {s['mttr_hours']:.1f} 小时。"
    )
    return ToolOutcome(
        summary=summary,
        data={
            "summary": s,
            "communities": data["communities"],
            "alerts": data["alerts"],
            "trend": data["trend"],
        },
        sources=[
            _source("orders", f"近 {params.days} 天订单流水", s["order_count"]),
            _source("piles / connectors", "设备在线与占用状态", s["total_piles"]),
            _source("tickets", "工单 SLA 与处理时长", s["pending_tickets"]),
        ],
    )


def _pile_health(db: Session, user: User, params: PileHealthInput) -> ToolOutcome:
    community_ids = _scope_ids(db, user, params.community_id)
    query = db.query(Pile).filter(Pile.tenant_id == user.tenant_id, Pile.community_id.in_(community_ids))
    if params.status:
        query = query.filter(Pile.status == params.status)
    piles = query.order_by(Pile.status.desc(), Pile.code).limit(params.limit).all()
    items = [pile_public(p) for p in piles]
    abnormal = [p for p in piles if p.status in {"fault", "offline", "maintenance"}]
    summary = (
        f"筛选到 {len(items)} 台设备，其中异常 {len(abnormal)} 台："
        + ("、".join(f"{p.code}({p.status})" for p in abnormal) if abnormal else "暂无异常")
        + "。"
    )
    return ToolOutcome(
        summary=summary,
        data={"items": items},
        sources=[_source("piles", "设备状态与心跳", len(items))],
    )


def _diagnose(db: Session, user: User, params: DiagnoseInput) -> ToolOutcome:
    pile = _get_pile(db, user, params.pile_id, params.pile_code)
    events = (
        db.query(DeviceEvent)
        .filter(DeviceEvent.tenant_id == user.tenant_id, DeviceEvent.pile_id == pile.id)
        .order_by(DeviceEvent.occurred_at.desc())
        .limit(20)
        .all()
    )
    open_tickets = (
        db.query(Ticket)
        .filter(Ticket.tenant_id == user.tenant_id, Ticket.pile_id == pile.id)
        .order_by(Ticket.created_at.desc())
        .limit(5)
        .all()
    )
    recent_orders = (
        db.query(Order)
        .filter(Order.tenant_id == user.tenant_id, Order.pile_id == pile.id)
        .order_by(Order.created_at.desc())
        .limit(5)
        .all()
    )
    causes: list[str] = []
    event_types = {e.event_type for e in events}
    if "temperature" in event_types or pile.temperature_c >= 70:
        causes.append("充电模块散热异常（温度偏高，疑似风扇或风道堵塞）")
    if "offline" in event_types or not pile.online:
        causes.append("设备通信中断（4G/以太网模块或弱信号）")
    if "fault" in event_types:
        codes = {
            str((e.payload or {}).get("fault_code"))
            for e in events
            if e.event_type == "fault" and (e.payload or {}).get("fault_code")
        }
        causes.append("设备故障码：" + ("、".join(sorted(codes)) if codes else "未上报具体故障码"))
    if "interrupted" in event_types:
        causes.append("充电过程被中断（枪口锁止、车辆 BMS 或支付链路）")
    if not causes:
        causes.append("暂未发现明确硬件故障，建议结合现场检查与最近一次充电订单判断")

    last_heartbeat = iso(pile.last_heartbeat_at)
    summary = (
        f"设备 {pile.code}（{pile.name}）当前 {pile.status}，温度 {pile.temperature_c:.1f}℃，"
        f"最近心跳 {last_heartbeat or '未知'}。初步归因：{causes[0]}。"
    )
    return ToolOutcome(
        summary=summary,
        data={
            "pile": pile_public(pile),
            "probable_causes": causes,
            "events": [
                {
                    "event_no": e.event_no,
                    "type": e.event_type,
                    "severity": e.severity,
                    "occurred_at": iso(e.occurred_at),
                    "payload": e.payload,
                }
                for e in events[:10]
            ],
            "tickets": [ticket_public(t) for t in open_tickets],
            "recent_orders": [order_public(o) for o in recent_orders],
            "suggested_action": "若温度持续超过 75℃ 或存在 critical 故障，请创建停机审批并安排现场检修。",
        },
        sources=[
            _source("device_events", "最近 20 条设备事件", len(events)),
            _source("tickets", "该设备历史工单", len(open_tickets)),
            _source("orders", "该设备最近订单", len(recent_orders)),
        ],
    )


def _order_analytics(db: Session, user: User, params: OrderAnalyticsInput) -> ToolOutcome:
    community_ids = _scope_ids(db, user, params.community_id)
    start = utcnow() - timedelta(days=params.days)
    orders = (
        db.query(Order)
        .filter(
            Order.tenant_id == user.tenant_id,
            Order.community_id.in_(community_ids),
            Order.created_at >= start,
        )
        .all()
    )
    if user.role == "resident":
        orders = [o for o in orders if o.user_id == user.id]
    completed = [o for o in orders if o.status == "completed"]
    revenue = round(sum(o.amount for o in completed), 2)
    refund = round(sum(o.refund_amount for o in orders), 2)
    energy = round(sum(o.energy_kwh for o in completed), 1)
    by_status: dict[str, int] = {}
    for order in orders:
        by_status[order.status] = by_status.get(order.status, 0) + 1
    avg = round(revenue / len(completed), 2) if completed else 0
    summary = (
        f"近 {params.days} 天共 {len(orders)} 笔订单，完成 {len(completed)} 笔，"
        f"收入 {revenue:.2f} 元，客单价 {avg:.2f} 元，充电量 {energy:.1f} 度，退款 {refund:.2f} 元。"
    )
    return ToolOutcome(
        summary=summary,
        data={
            "revenue": revenue,
            "refund": refund,
            "energy_kwh": energy,
            "order_count": len(orders),
            "completed_count": len(completed),
            "avg_amount": avg,
            "status_breakdown": by_status,
            "recent_orders": [order_public(o) for o in orders[:8]],
        },
        sources=[_source("orders", f"近 {params.days} 天订单", len(orders))],
    )


def _my_orders(db: Session, user: User, params: MyOrdersInput) -> ToolOutcome:
    orders = (
        db.query(Order)
        .filter(Order.tenant_id == user.tenant_id, Order.user_id == user.id)
        .order_by(Order.created_at.desc())
        .limit(params.limit)
        .all()
    )
    if not orders:
        summary = "你还没有充电订单，可以在「充电桩」页面选择空闲枪口开始充电。"
    else:
        current = [o for o in orders if o.status in {"charging", "reserved"}]
        summary = (
            f"你最近有 {len(orders)} 笔订单，其中进行中 {len(current)} 笔；"
            f"累计消费 {sum(o.amount for o in orders):.2f} 元。"
        )
    return ToolOutcome(
        summary=summary,
        data={"items": [order_public(o) for o in orders]},
        sources=[_source("orders", "本人订单", len(orders))],
    )


def _ticket_overview(db: Session, user: User, params: TicketOverviewInput) -> ToolOutcome:
    community_ids = _scope_ids(db, user, params.community_id)
    query = db.query(Ticket).filter(
        Ticket.tenant_id == user.tenant_id, Ticket.community_id.in_(community_ids)
    )
    if params.status:
        query = query.filter(Ticket.status == params.status)
    if params.priority:
        query = query.filter(Ticket.priority == params.priority)
    tickets = query.order_by(Ticket.priority, Ticket.created_at.desc()).limit(params.limit).all()
    open_count = sum(1 for t in tickets if t.status not in {"closed", "cancelled"})
    p1 = sum(1 for t in tickets if t.priority == "P1" and t.status not in {"closed", "cancelled"})
    overdue = sum(
        1 for t in tickets if t.sla_due_at and t.status not in {"closed", "cancelled"} and t.sla_due_at < utcnow()
    )
    summary = (
        f"筛选到 {len(tickets)} 张工单，未闭环 {open_count} 张，其中 P1 {p1} 张，SLA 超时 {overdue} 张。"
    )
    return ToolOutcome(
        summary=summary,
        data={"items": [ticket_public(t) for t in tickets]},
        sources=[_source("tickets", "工单与 SLA", len(tickets))],
    )


def _approval_overview(db: Session, user: User, params: ApprovalOverviewInput) -> ToolOutcome:
    community_ids = _scope_ids(db, user, params.community_id)
    query = db.query(Approval).filter(
        Approval.tenant_id == user.tenant_id,
        Approval.community_id.in_(community_ids),
    )
    if params.status:
        query = query.filter(Approval.status == params.status)
    if params.type:
        query = query.filter(Approval.type == params.type)
    total = query.count()
    approvals = query.order_by(Approval.created_at.desc()).limit(params.limit).all()
    pending = sum(1 for a in approvals if a.status == "pending")
    type_counts: dict[str, int] = {}
    for approval in approvals:
        if approval.status == "pending":
            type_counts[approval.type] = type_counts.get(approval.type, 0) + 1
    distribution = "、".join(
        f"{APPROVAL_TYPE_LABELS.get(key, key)} {value} 条" for key, value in type_counts.items()
    ) or "暂无待审批类型"
    summary = (
        f"筛选到 {total} 条审批记录，当前展示 {len(approvals)} 条，其中待审批 {pending} 条；{distribution}。"
        if approvals
        else "当前没有符合条件的审批记录。"
    )
    return ToolOutcome(
        summary=summary,
        data={"items": [approval_public(a) for a in approvals], "pending": pending, "total": total},
        sources=[_source("approvals", "高风险动作审批记录", total)],
    )


def _availability(db: Session, user: User, params: AvailabilityInput) -> ToolOutcome:
    community_ids = _scope_ids(db, user, params.community_id)
    starts = parse_datetime(params.start_at) or utcnow()
    ends = parse_datetime(params.end_at) or (starts + timedelta(hours=2))
    connectors = (
        db.query(Connector)
        .join(Pile, Connector.pile_id == Pile.id)
        .filter(
            Connector.tenant_id == user.tenant_id,
            Pile.community_id.in_(community_ids),
            Pile.status == "online",
            Connector.status == "idle",
        )
        .limit(80)
        .all()
    )
    available = [
        c for c in connectors if not has_time_conflict(db, c.id, starts, ends)
    ][: params.limit]
    items = []
    for connector in available:
        pile = connector.pile
        items.append(
            {
                "connector_id": connector.id,
                "pile_id": pile.id,
                "pile_code": pile.code,
                "pile_name": pile.name,
                "community_name": pile.community.name if pile.community else None,
                "gun_type": connector.gun_type,
                "power_kw": connector.power_kw,
                "price_per_kwh": connector.price_per_kwh,
                "service_fee": connector.service_fee,
                "starts_at": iso(starts),
                "ends_at": iso(ends),
            }
        )
    summary = (
        f"在 {iso(starts)} 至 {iso(ends)} 时段找到 {len(items)} 个可用枪口。"
        if items
        else "该时段暂未找到可用枪口，请调整时间或社区。"
    )
    return ToolOutcome(
        summary=summary,
        data={"items": items, "starts_at": iso(starts), "ends_at": iso(ends)},
        sources=[_source("connectors / reservations", "可用枪口与时段冲突", len(items))],
    )


def _repair_plan(db: Session, user: User, params: RepairInput) -> ToolOutcome:
    pile = _get_pile(db, user, params.pile_id, params.pile_code)
    events = (
        db.query(DeviceEvent)
        .filter(DeviceEvent.tenant_id == user.tenant_id, DeviceEvent.pile_id == pile.id)
        .order_by(DeviceEvent.occurred_at.desc())
        .limit(10)
        .all()
    )
    fault_code = next(
        ((e.payload or {}).get("fault_code") for e in events if (e.payload or {}).get("fault_code")),
        None,
    )
    steps = [
        "断电挂牌，确认高压与直流母线残余电压已释放。",
        "检查充电模块散热风扇、滤网与风道，清理积尘并测试风量。",
        "读取设备日志与故障码，核对最后一次充电订单的电流曲线。",
        "复测枪口绝缘、接地与锁止机构，确认无机械卡滞。",
        "上电后执行 10 分钟带载测试订单，观察温度与功率是否稳定。",
    ]
    if not pile.online:
        steps.insert(0, "优先排查 4G/以太网通信模块与 SIM 卡状态，确认设备可回连平台。")
    summary = (
        f"针对 {pile.code}（{pile.status}）建议按 {len(steps)} 步检修"
        + (f"，重点核对故障码 {fault_code}" if fault_code else "")
        + "；完成后必须做心跳检查与测试订单验收。"
    )
    return ToolOutcome(
        summary=summary,
        data={"pile": pile_public(pile), "steps": steps, "fault_code": fault_code},
        sources=[_source("device_events", "故障事件与日志", len(events)), _source("piles", "设备档案", 1)],
    )


def _stop_pile(db: Session, user: User, params: StopPileInput) -> ToolOutcome:
    pile = _get_pile(db, user, params.pile_id, params.pile_code)
    approval, created = create_approval_request(
        db,
        user,
        action_type="stop_pile",
        target_id=str(pile.id),
        reason=params.reason,
        payload={"pile_id": pile.id, "action": "maintenance"},
        source="agent",
    )
    summary = (
        f"已创建设备停机审批 {approval.approval_no}（待审批，尚未执行）：{pile.name}。"
        if created
        else f"该设备已有进行中的停机审批 {approval.approval_no}，未重复创建。"
    )
    return ToolOutcome(
        summary=summary,
        data={"approval": approval_public(approval), "created": created},
        sources=[_source("approvals", "高风险动作审批", 1)],
    )


def _refund(db: Session, user: User, params: RefundInput) -> ToolOutcome:
    if not params.order_no:
        raise bad_request("请提供订单号，例如 NO202605011234", "ORDER_NO_REQUIRED")
    approval, created = create_approval_request(
        db,
        user,
        action_type="refund",
        target_id=params.order_no,
        reason=params.reason,
        payload={"order_no": params.order_no, "amount": params.amount},
        source="agent",
    )
    summary = (
        f"已创建退款审批 {approval.approval_no}，金额 {approval.amount:.2f} 元，等待财务审批后执行。"
        if created
        else f"该订单已有进行中的退款审批 {approval.approval_no}，未重复创建。"
    )
    return ToolOutcome(
        summary=summary,
        data={"approval": approval_public(approval), "created": created},
        sources=[_source("approvals", "退款审批", 1), _source("orders", "订单金额校验", 1)],
    )


def _price_change(db: Session, user: User, params: PriceChangeInput) -> ToolOutcome:
    connector: Optional[Connector] = None
    if params.connector_id:
        connector = db.get(Connector, params.connector_id)
    elif params.pile_code:
        pile = _get_pile(db, user, None, params.pile_code)
        connector = pile.connectors[0] if pile.connectors else None
    if not connector or connector.tenant_id != user.tenant_id:
        raise not_found("未找到匹配的枪口", "CONNECTOR_NOT_FOUND")
    approval, created = create_approval_request(
        db,
        user,
        action_type="price_change",
        target_id=str(connector.id),
        reason=params.reason,
        payload={
            "connector_id": connector.id,
            "price_per_kwh": params.price_per_kwh,
            "service_fee": params.service_fee,
        },
        source="agent",
    )
    summary = (
        f"已创建调价审批 {approval.approval_no}，新价格 {params.price_per_kwh:.2f} + "
        f"{params.service_fee:.2f} 元/度，待审批后生效。"
        if created
        else f"该枪口已有进行中的调价审批 {approval.approval_no}。"
    )
    return ToolOutcome(
        summary=summary,
        data={"approval": approval_public(approval), "created": created},
        sources=[_source("approvals", "调价审批", 1), _source("connectors", "计费规则", 1)],
    )


def _bulk_reassign(db: Session, user: User, params: BulkReassignInput) -> ToolOutcome:
    approval, created = create_approval_request(
        db,
        user,
        action_type="bulk_reassign",
        reason=params.reason,
        payload={"ticket_ids": params.ticket_ids, "assignee_id": params.assignee_id},
        source="agent",
    )
    summary = (
        f"已创建批量改派审批 {approval.approval_no}，涉及 {len(params.ticket_ids)} 张工单，待审批后执行。"
        if created
        else f"已有进行中的批量改派审批 {approval.approval_no}。"
    )
    return ToolOutcome(
        summary=summary,
        data={"approval": approval_public(approval), "created": created},
        sources=[_source("approvals", "批量改派审批", 1)],
    )


def _create_ticket(db: Session, user: User, params: CreateTicketInput) -> ToolOutcome:
    pile = _get_pile(db, user, params.pile_id, params.pile_code)
    ticket = create_ticket(
        db,
        tenant_id=user.tenant_id,
        community_id=pile.community_id,
        pile=pile,
        title=params.title,
        description=params.description or "由 Agent 工作台创建，请现场核实。",
        priority=params.priority,
        source="agent",
        reporter=user,
    )
    return ToolOutcome(
        summary=f"已创建工单 {ticket.ticket_no}（{ticket.priority}），可在工单页面继续分派与处理。",
        data={"ticket": ticket_public(ticket)},
        sources=[_source("tickets", "新建工单", 1)],
    )


def _glossary(db: Session, user: User, params: GlossaryInput) -> ToolOutcome:
    glossary = {
        "可用率": "在线且状态正常的设备数 / 设备总数，反映设备是否具备服务能力。",
        "利用率": "正在充电的枪口数 / 全部枪口数，反映实时产能利用情况。",
        "故障率": "当前处于故障状态的设备数 / 设备总数。",
        "MTTR": "平均修复时长：已关闭工单从创建到关闭的平均耗时，P1 目标 ≤ 1 小时。",
        "预约成功率": "完成或进行中的订单 /（完成 + 进行中 + 取消 + 异常）订单。",
        "客单价": "周期内完成订单收入 / 完成订单数。",
    }
    term = params.term.strip()
    if term:
        matched = {k: v for k, v in glossary.items() if term in k or k in term}
        if not matched:
            matched = glossary
    else:
        matched = glossary
    summary = "；".join(f"{k}：{v}" for k, v in matched.items())
    return ToolOutcome(
        summary=summary,
        data={"glossary": matched},
        sources=[_source("metrics", "指标口径说明", len(matched))],
    )


TOOLS: dict[str, ToolSpec] = {
    "operations_overview": ToolSpec(
        name="operations_overview",
        label="运营总览",
        description="查询设备可用率、利用率、收入、工单等核心指标",
        input_model=OverviewInput,
        roles=frozenset({"admin", "operator", "technician", "finance"}),
        risk_level="read",
        handler=_overview,
    ),
    "pile_health": ToolSpec(
        name="pile_health",
        label="设备健康查询",
        description="按状态查询设备在线、故障与枪口占用",
        input_model=PileHealthInput,
        roles=frozenset({"admin", "operator", "technician", "finance", "resident"}),
        risk_level="read",
        handler=_pile_health,
    ),
    "diagnose_pile": ToolSpec(
        name="diagnose_pile",
        label="故障归因",
        description="结合设备事件、工单和订单诊断故障原因",
        input_model=DiagnoseInput,
        roles=frozenset({"admin", "operator", "technician", "finance"}),
        risk_level="read",
        handler=_diagnose,
    ),
    "order_analytics": ToolSpec(
        name="order_analytics",
        label="订单分析",
        description="统计周期订单量、收入、退款与充电量",
        input_model=OrderAnalyticsInput,
        roles=frozenset({"admin", "operator", "finance"}),
        risk_level="read",
        handler=_order_analytics,
    ),
    "my_orders": ToolSpec(
        name="my_orders",
        label="我的订单",
        description="查询本人预约与充电订单",
        input_model=MyOrdersInput,
        roles=frozenset({"resident"}),
        risk_level="read",
        handler=_my_orders,
    ),
    "ticket_overview": ToolSpec(
        name="ticket_overview",
        label="工单概览",
        description="查询工单积压、P1 与 SLA 超时情况",
        input_model=TicketOverviewInput,
        roles=frozenset({"admin", "operator", "technician", "finance"}),
        risk_level="read",
        handler=_ticket_overview,
    ),
    "approval_overview": ToolSpec(
        name="approval_overview",
        label="审批查询",
        description="查询停机、退款、调价、批量改派审批记录与待办",
        input_model=ApprovalOverviewInput,
        roles=frozenset({"admin", "operator", "finance"}),
        risk_level="read",
        handler=_approval_overview,
    ),
    "check_availability": ToolSpec(
        name="check_availability",
        label="可用枪口查询",
        description="查询指定社区和时段的空闲枪口",
        input_model=AvailabilityInput,
        roles=frozenset({"admin", "operator", "technician", "finance", "resident"}),
        risk_level="read",
        handler=_availability,
    ),
    "repair_plan": ToolSpec(
        name="repair_plan",
        label="维修方案",
        description="根据故障事件生成检修步骤",
        input_model=RepairInput,
        roles=frozenset({"admin", "operator", "technician"}),
        risk_level="read",
        handler=_repair_plan,
    ),
    "metric_glossary": ToolSpec(
        name="metric_glossary",
        label="指标解释",
        description="解释运营指标口径",
        input_model=GlossaryInput,
        roles=frozenset({"admin", "operator", "technician", "finance", "resident"}),
        risk_level="read",
        handler=_glossary,
    ),
    "request_stop_pile": ToolSpec(
        name="request_stop_pile",
        label="申请设备停机",
        description="高风险动作：创建设备停机审批，不直接执行",
        input_model=StopPileInput,
        roles=frozenset({"admin", "operator", "technician"}),
        risk_level="high_risk",
        handler=_stop_pile,
    ),
    "request_refund": ToolSpec(
        name="request_refund",
        label="申请订单退款",
        description="高风险动作：创建退款审批，不直接执行",
        input_model=RefundInput,
        roles=frozenset({"admin", "operator", "finance"}),
        risk_level="high_risk",
        handler=_refund,
    ),
    "request_price_change": ToolSpec(
        name="request_price_change",
        label="申请计费调价",
        description="高风险动作：创建调价审批，不直接执行",
        input_model=PriceChangeInput,
        roles=frozenset({"admin", "operator", "finance"}),
        risk_level="high_risk",
        handler=_price_change,
    ),
    "request_bulk_reassign": ToolSpec(
        name="request_bulk_reassign",
        label="申请批量改派",
        description="高风险动作：创建批量改派审批，不直接执行",
        input_model=BulkReassignInput,
        roles=frozenset({"admin", "operator", "finance"}),
        risk_level="high_risk",
        handler=_bulk_reassign,
    ),
    "create_ticket": ToolSpec(
        name="create_ticket",
        label="创建维修工单",
        description="普通写动作：创建工单并写入审计",
        input_model=CreateTicketInput,
        roles=frozenset({"admin", "operator", "technician"}),
        risk_level="normal_write",
        handler=_create_ticket,
        idempotent=False,
    ),
}


def get_tool(name: str) -> Optional[ToolSpec]:
    return TOOLS.get(name)


def validate_args(spec: ToolSpec, args: dict[str, Any]) -> BaseModel:
    try:
        return spec.input_model(**args)
    except ValidationError as exc:
        raise bad_request(
            f"工具 {spec.name} 参数校验失败",
            "TOOL_ARGUMENT_INVALID",
            exc.errors(include_url=False),
        ) from exc


def run_tool(db: Session, user: User, name: str, args: dict[str, Any]) -> tuple[ToolOutcome, BaseModel]:
    spec = TOOLS.get(name)
    if not spec:
        raise forbidden(f"工具 {name} 未登记，禁止调用", "TOOL_NOT_ALLOWED")
    if user.role not in spec.roles:
        raise forbidden("当前角色无权调用该工具", "TOOL_ROLE_FORBIDDEN")
    params = validate_args(spec, args)
    outcome = spec.handler(db, user, params)
    return outcome, params
