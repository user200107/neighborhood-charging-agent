"""轻量 Agent 工作流。

节点与文档保持一致：parse_intent → load_context → check_permission → plan_action
→ risk_gate → request_approval / execute_action → verify_result → write_memory → reflect。
实现不依赖外部图框架，便于在无 LLM Key 的环境下稳定演示；如配置 LLM，可用于润色回答。
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from app.agents.tools import TOOLS, ToolOutcome, get_tool, run_tool
from app.auth import community_ids_for
from app.config import settings
from app.constants import RISK_LABELS
from app.errors import ApiError, forbidden
from app.models import AgentMemory, AgentRun, Approval, Community, Connector, Order, Pile, Ticket, User
from app.serializers import approval_public
from app.services.audit import record_audit
from app.utils import iso, new_trace_id, utcnow

INTENT_LABELS = {
    "greeting": "问候/能力咨询",
    "overview": "运营总览",
    "devices": "设备查询",
    "diagnose": "故障归因",
    "repair": "维修方案",
    "orders": "订单分析",
    "tickets": "工单查询",
    "approvals": "审批查询",
    "availability": "可用性查询",
    "stop_pile": "申请停机",
    "refund": "申请退款",
    "price_change": "申请调价",
    "bulk_reassign": "申请批量改派",
    "create_ticket": "创建工单",
    "explain": "指标解释",
    "unknown": "未识别",
}

_SESSION_LOCK = threading.Lock()
_SESSION_MEMORY: dict[str, tuple[datetime, list[dict[str, Any]]]] = {}
SESSION_TTL_MINUTES = 30


@dataclass
class AgentState:
    db: Session
    user: User
    message: str
    session_id: str
    trace_id: str
    community_id: Optional[int] = None
    intent: str = "unknown"
    entities: dict[str, Any] = field(default_factory=dict)
    plan: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    outcomes: list[ToolOutcome] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    approval: Optional[Approval] = None
    risk_level: str = "read"
    status: str = "completed"
    answer: str = ""
    error: Optional[str] = None
    started_at: float = field(default_factory=time.perf_counter)


def _sanitize_session(value: Optional[str]) -> str:
    if value and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        return value
    return "default"


def _memory_key(user: User, session_id: str) -> str:
    return f"{user.tenant_id}:{user.id}:{session_id}"


def load_session_memory(user: User, session_id: str) -> list[dict[str, Any]]:
    key = _memory_key(user, session_id)
    with _SESSION_LOCK:
        item = _SESSION_MEMORY.get(key)
        if not item:
            return []
        expires, turns = item
        if expires < utcnow():
            _SESSION_MEMORY.pop(key, None)
            return []
        return list(turns)


def append_session_memory(user: User, session_id: str, turn: dict[str, Any]) -> None:
    key = _memory_key(user, session_id)
    with _SESSION_LOCK:
        _, turns = _SESSION_MEMORY.get(key, (utcnow(), []))
        turns = (turns + [turn])[-8:]
        _SESSION_MEMORY[key] = (utcnow() + timedelta(minutes=SESSION_TTL_MINUTES), turns)


def _sanitize_text(text: str) -> str:
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._-]+", r"\1***", text)
    text = re.sub(r"1[3-9]\d{9}", "***", text)
    text = re.sub(r"\b\d{17}[\dXx]\b", "***", text)
    return text[:2000]


def _parse_intent(state: AgentState) -> None:
    text = state.message.strip()
    lowered = text

    if any(keyword in lowered for keyword in ("批量改派", "批量分派", "批量转派")):
        state.intent = "bulk_reassign"
    elif any(keyword in lowered for keyword in ("停机", "关停", "停用")) and not any(
        keyword in lowered for keyword in ("哪些", "查询", "记录", "审批")
    ):
        state.intent = "stop_pile"
    elif "审批" in lowered:
        state.intent = "approvals"
    elif "退款" in lowered and not any(keyword in lowered for keyword in ("退款金额", "退款率", "退款情况", "退款记录")):
        state.intent = "refund"
    elif any(keyword in lowered for keyword in ("调价", "改价", "价格调整")) and not any(
        keyword in lowered for keyword in ("记录", "审批", "历史")
    ):
        state.intent = "price_change"
    elif any(keyword in lowered for keyword in ("建单", "创建工单", "报修", "派单")):
        state.intent = "create_ticket"
    elif any(keyword in lowered for keyword in ("维修方案", "怎么修", "如何修", "维修建议", "检修步骤")):
        state.intent = "repair"
    elif any(keyword in lowered for keyword in ("故障", "诊断", "为什么", "异常", "离线", "告警", "原因")):
        state.intent = "diagnose"
    elif any(keyword in lowered for keyword in ("工单", "积压", "闭环", "派工")):
        state.intent = "tickets"
    elif any(keyword in lowered for keyword in ("空位", "可用", "预约", "附近", "空闲", "充电桩", "枪口")):
        state.intent = "availability"
    elif any(keyword in lowered for keyword in ("订单", "收入", "营收", "客单", "流水")):
        state.intent = "orders"
    elif any(keyword in lowered for keyword in ("指标解释", "什么意思", "口径", "是什么", "含义")):
        state.intent = "explain"
    elif any(
        keyword in lowered
        for keyword in ("运营", "总览", "概览", "可用率", "利用率", "数据", "报表", "情况", "怎么样")
    ):
        state.intent = "overview"
    elif any(keyword in lowered for keyword in ("你好", "您好", "帮助", "能做什么", "功能")):
        state.intent = "greeting"
    else:
        state.intent = "unknown"

    entities: dict[str, Any] = {}

    code_match = re.search(r"\b([A-Za-z]{2,4}-[A-Za-z]-\d{2})\b", text)
    if code_match:
        entities["pile_code"] = code_match.group(1).upper()
    order_match = re.search(r"\b(NO\d{10,})\b", text, re.IGNORECASE)
    if order_match:
        entities["order_no"] = order_match.group(1).upper()
    ticket_match = re.findall(r"\b(WO\d{8,})\b", text, re.IGNORECASE)
    if ticket_match:
        entities["ticket_nos"] = [item.upper() for item in ticket_match]
    amount_match = re.search(r"(\d+(?:\.\d+)?)\s*元", text)
    if amount_match:
        entities["amount"] = float(amount_match.group(1))
    price_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元)?\s*/?\s*度", text)
    if price_match:
        entities["price"] = float(price_match.group(1))
    days_match = re.search(r"(?:近|最近|过去)\s*(\d+)\s*天", text)
    if days_match:
        entities["days"] = max(1, min(int(days_match.group(1)), 30))
    elif "今天" in text or "今日" in text:
        entities["days"] = 1
    elif "本周" in text or "这周" in text:
        entities["days"] = 7
    elif "本月" in text or "这个月" in text:
        entities["days"] = 30

    for priority in ("P1", "P2", "P3"):
        if priority.lower() in text.lower():
            entities["priority"] = priority
            break

    status_map = {
        "故障": "fault",
        "离线": "offline",
        "维护": "maintenance",
        "在线": "online",
        "待处理": "pending",
        "处理中": "processing",
        "待验收": "pending_verification",
        "已关闭": "closed",
    }
    for label, value in status_map.items():
        if label in text:
            entities["status"] = value
            break

    if "服务费" in text:
        fee_match = re.search(r"服务费\s*(\d+(?:\.\d+)?)", text)
        if fee_match:
            entities["service_fee"] = float(fee_match.group(1))
    if "电费" in text or "单价" in text:
        price_match = re.search(r"(?:电费|单价)\s*(\d+(?:\.\d+)?)", text)
        if price_match:
            entities["price"] = float(price_match.group(1))

    state.entities = entities


def _load_context(state: AgentState) -> None:
    scope = community_ids_for(state.user)
    communities = (
        state.db.query(Community)
        .filter(Community.tenant_id == state.user.tenant_id)
        .order_by(Community.name)
        .all()
    )
    allowed = [c for c in communities if scope is None or c.id in scope]
    state.data["communities"] = [{"id": c.id, "name": c.name, "code": c.code} for c in allowed]
    if state.community_id:
        if all(c["id"] != state.community_id for c in state.data["communities"]):
            raise forbidden("无权访问该社区", "COMMUNITY_FORBIDDEN")
    else:
        # 从自然语言中识别社区名称
        for community in allowed:
            if community.name in state.message or community.code.lower() in state.message.lower():
                state.community_id = community.id
                break
    state.data["session_memory"] = load_session_memory(state.user, state.session_id)


def _resolve_connector(state: AgentState) -> Optional[Connector]:
    pile_code = state.entities.get("pile_code")
    if not pile_code:
        return None
    pile = (
        state.db.query(Pile)
        .filter(Pile.tenant_id == state.user.tenant_id, Pile.code == pile_code)
        .first()
    )
    if not pile or not pile.connectors:
        return None
    return pile.connectors[0]


def _plan_action(state: AgentState) -> None:
    entities = state.entities
    intent = state.intent
    days = int(entities.get("days", 7))
    community_id = state.community_id

    if intent == "overview":
        if state.user.role == "resident":
            state.plan = [{"name": "pile_health", "args": {"limit": 10, "community_id": community_id}}]
        else:
            state.plan = [{"name": "operations_overview", "args": {"days": days, "community_id": community_id}}]
    elif intent == "devices":
        args: dict[str, Any] = {"limit": 10, "community_id": community_id}
        if entities.get("status"):
            args["status"] = entities["status"]
        state.plan = [{"name": "pile_health", "args": args}]
    elif intent == "diagnose":
        if entities.get("pile_code"):
            state.plan = [{"name": "diagnose_pile", "args": {"pile_code": entities["pile_code"]}}]
        else:
            state.plan = [
                {"name": "pile_health", "args": {"status": "fault", "limit": 8, "community_id": community_id}},
                {"name": "operations_overview", "args": {"days": 7, "community_id": community_id}},
            ]
    elif intent == "repair":
        if entities.get("pile_code"):
            state.plan = [{"name": "repair_plan", "args": {"pile_code": entities["pile_code"]}}]
        else:
            state.answer = "请提供设备编号（例如 `HP-A-02`），我会结合故障事件生成检修步骤。"
    elif intent == "orders":
        if state.user.role == "resident":
            state.plan = [{"name": "my_orders", "args": {"limit": 8}}]
        else:
            state.plan = [
                {"name": "order_analytics", "args": {"days": days, "community_id": community_id}}
            ]
    elif intent == "tickets":
        args = {"limit": 10, "community_id": community_id}
        if entities.get("priority"):
            args["priority"] = entities["priority"]
        if entities.get("status"):
            args["status"] = entities["status"]
        state.plan = [{"name": "ticket_overview", "args": args}]
    elif intent == "approvals":
        args = {"limit": 8, "community_id": community_id}
        if "待审批" in state.message or "待办" in state.message:
            args["status"] = "pending"
        if "退款" in state.message:
            args["type"] = "refund"
        elif "停机" in state.message:
            args["type"] = "stop_pile"
        elif "调价" in state.message or "改价" in state.message:
            args["type"] = "price_change"
        state.plan = [{"name": "approval_overview", "args": args}]
    elif intent == "availability":
        args = {"limit": 6, "community_id": community_id}
        state.plan = [{"name": "check_availability", "args": args}]
    elif intent == "explain":
        state.plan = [{"name": "metric_glossary", "args": {"term": state.message[:40]}}]
    elif intent == "stop_pile":
        if not entities.get("pile_code"):
            state.answer = "请提供要停机的设备编号（例如 `HP-A-02`），并说明停机原因。"
        else:
            state.plan = [
                {
                    "name": "request_stop_pile",
                    "args": {
                        "pile_code": entities["pile_code"],
                        "reason": state.message[:480],
                    },
                }
            ]
    elif intent == "refund":
        if not entities.get("order_no"):
            state.answer = "请提供需要退款的订单号（例如 `NO202605011234`），并说明退款原因。"
        else:
            args = {"order_no": entities["order_no"], "reason": state.message[:480]}
            if entities.get("amount"):
                args["amount"] = entities["amount"]
            state.plan = [{"name": "request_refund", "args": args}]
    elif intent == "price_change":
        connector = _resolve_connector(state)
        if not connector:
            state.answer = "请提供要调价的设备编号（例如 `YQ-A-01`），并说明目标电费与服务费。"
        elif "price" not in entities:
            state.answer = "请说明目标电费单价（元/度），例如「把 YQ-A-01 的电费调到 1.2 元/度」。"
        else:
            state.plan = [
                {
                    "name": "request_price_change",
                    "args": {
                        "connector_id": connector.id,
                        "price_per_kwh": entities["price"],
                        "service_fee": entities.get("service_fee", connector.service_fee),
                        "reason": state.message[:480],
                    },
                }
            ]
    elif intent == "bulk_reassign":
        state.answer = "批量改派需要明确工单 ID 与接收人，请在「工单」页面多选后发起，或告诉我工单号与维修人员姓名。"
    elif intent == "create_ticket":
        if not entities.get("pile_code"):
            state.answer = "请提供设备编号（例如 `YQ-A-01`）和故障描述，我会创建维修工单。"
        else:
            state.plan = [
                {
                    "name": "create_ticket",
                    "args": {
                        "pile_code": entities["pile_code"],
                        "title": state.message[:120],
                        "description": state.message[:500],
                        "priority": entities.get("priority", "P3"),
                    },
                }
            ]
    elif intent == "greeting":
        state.answer = (
            "我是邻里充电运营助手，可以帮你：\n"
            "• 查看运营总览、设备可用率与故障分布\n"
            "• 结合设备事件诊断故障、生成维修方案\n"
            "• 查询订单收入、工单积压与可用枪口\n"
            "• 发起停机、退款、调价、批量改派等高风险审批（不会直接执行）\n"
            "你还可以直接说「诊断 HP-A-02」或「近 7 天收入情况」。"
        )
    elif intent == "unknown":
        state.answer = (
            "我暂时没理解你的问题。可以试试：\n"
            "• 「近 7 天运营情况怎么样？」\n"
            "• 「诊断 HP-A-02 的故障」\n"
            "• 「查一下云栖花园的空闲充电桩」\n"
            "• 「给 YQ-A-01 创建一张工单」"
        )


def _check_permission(state: AgentState) -> None:
    if not state.plan:
        return
    denied: list[str] = []
    for step in state.plan:
        spec = get_tool(step["name"])
        if not spec:
            raise forbidden(f"工具 {step['name']} 未登记", "TOOL_NOT_ALLOWED")
        if state.user.role not in spec.roles:
            denied.append(spec.label)
    if denied:
        state.status = "rejected"
        state.answer = (
            f"当前角色「{state.user.display_name}」无权执行：{'、'.join(denied)}。"
            "请切换到有权限的运营/财务账号，或提交人工审批。"
        )
        state.plan = []


def _risk_gate(state: AgentState) -> None:
    risks = [get_tool(step["name"]).risk_level for step in state.plan if get_tool(step["name"])]
    if "high_risk" in risks:
        state.risk_level = "high_risk"
    elif "normal_write" in risks:
        state.risk_level = "normal_write"
    else:
        state.risk_level = "read"


def _execute_plan(state: AgentState) -> None:
    for step in state.plan:
        spec = get_tool(step["name"])
        if spec is None:
            continue
        started = time.perf_counter()
        call = {
            "name": spec.name,
            "label": spec.label,
            "risk_level": spec.risk_level,
            "status": "running",
            "args": step["args"],
            "summary": "",
            "duration_ms": 0,
            "at": iso(utcnow()),
        }
        try:
            outcome, params = run_tool(state.db, state.user, spec.name, step["args"])
            elapsed = int((time.perf_counter() - started) * 1000)
            call.update(
                {
                    "status": "success",
                    "summary": outcome.summary,
                    "duration_ms": elapsed,
                    "args": params.model_dump(exclude_none=True),
                }
            )
            state.outcomes.append(outcome)
            state.sources.extend(outcome.sources)
            state.data[spec.name] = outcome.data
            if spec.risk_level == "high_risk" and outcome.data.get("approval"):
                approval_id = outcome.data["approval"]["id"]
                state.approval = state.db.get(Approval, approval_id)
                state.status = "pending_approval"
        except ApiError as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            call.update(
                {
                    "status": "failed",
                    "summary": exc.message,
                    "duration_ms": elapsed,
                    "error_code": exc.code,
                }
            )
            state.status = "failed"
            state.error = exc.message
        except Exception as exc:  # noqa: BLE001 工具异常不暴露堆栈
            elapsed = int((time.perf_counter() - started) * 1000)
            call.update(
                {"status": "failed", "summary": "工具执行异常", "duration_ms": elapsed, "error_code": "TOOL_FAILED"}
            )
            state.status = "failed"
            state.error = "工具执行异常，请稍后重试"
        state.tool_calls.append(call)
        if state.status in {"failed"}:
            break

    # 合并/去重数据来源
    seen = set()
    unique_sources = []
    for source in state.sources:
        key = (source.get("name"), source.get("detail"))
        if key not in seen:
            seen.add(key)
            unique_sources.append(source)
    state.sources = unique_sources


def _verify_result(state: AgentState) -> None:
    if state.status == "pending_approval":
        if not state.approval or state.approval.status != "pending":
            state.status = "failed"
            state.error = "审批创建结果校验失败"
    if state.status == "completed" and not state.outcomes and not state.answer:
        state.status = "failed"
        state.error = "未获得有效数据"


def _reflect(state: AgentState) -> None:
    if state.status == "rejected":
        return
    if state.status == "failed":
        state.answer = f"抱歉，本次查询未能完成：{state.error}。可稍后重试，trace_id：{state.trace_id}"
        return
    if state.status == "pending_approval" and state.approval:
        approval = state.approval
        state.answer = (
            f"【待审批 · 未执行】{state.outcomes[0].summary if state.outcomes else ''}\n"
            f"审批单号：{approval.approval_no}｜类型：{approval.type}｜影响范围：{approval.impact_scope}"
            + (f"｜金额：{approval.amount:.2f} 元" if approval.amount else "")
            + "\n根据安全策略，高风险动作不会由 Agent 直接执行。请财务/管理员在「审批中心」决策后执行，"
            "执行结果将写入审计。"
        )
        return
    if state.answer:
        return
    if state.outcomes:
        state.answer = "\n\n".join(outcome.summary for outcome in state.outcomes)
        if state.intent == "diagnose" and len(state.outcomes) > 1:
            state.answer += "\n\n如需进一步定位，请提供具体设备编号，我可以查看事件时间线并给出维修步骤。"
    else:
        state.answer = "没有查到符合条件的数据。"


def _maybe_llm_polish(state: AgentState) -> None:
    if not settings.llm_enabled or state.status == "pending_approval":
        return
    if not state.outcomes:
        return
    context = {
        "question": state.message,
        "intent": state.intent,
        "tool_results": [
            {"tool": call["name"], "summary": call.get("summary"), "data": state.data.get(call["name"])}
            for call in state.tool_calls
            if call.get("status") == "success"
        ],
    }
    raw = json.dumps(context, ensure_ascii=False, default=str)[:7000]
    prompt = (
        "你是充电运营分析助手。只能依据给定的工具结果回答，不得编造数字或声称执行了写操作。"
        "用简洁中文回答，保留关键数字，200 字以内。\n\n" + raw
    )
    try:
        response = httpx.post(
            settings.llm_endpoint,
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": settings.llm_model,
                "messages": [
                    {"role": "system", "content": "你是严谨的运营数据分析助手。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 400,
            },
            timeout=max(2, settings.agent_timeout_ms / 1000),
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
        if content:
            state.answer = content
            state.data["llm_polished"] = True
    except Exception:  # noqa: BLE001 LLM 不可用时静默回退到模板回答
        return


def _write_memory(state: AgentState) -> None:
    turn = {
        "at": iso(utcnow()),
        "message": _sanitize_text(state.message),
        "intent": state.intent,
        "answer": _sanitize_text(state.answer)[:500],
    }
    append_session_memory(state.user, state.session_id, turn)
    if state.status in {"completed", "pending_approval"} and state.outcomes:
        summary = _sanitize_text(state.outcomes[0].summary)[:500]
        state.db.add(
            AgentMemory(
                tenant_id=state.user.tenant_id,
                user_id=state.user.id,
                kind="long",
                content=summary,
                tags=[state.intent, f"community:{state.community_id or 'all'}"],
                expires_at=utcnow() + timedelta(days=30),
            )
        )


def run_agent(
    db: Session,
    user: User,
    message: str,
    *,
    session_id: Optional[str] = None,
    community_id: Optional[int] = None,
    trace_id: Optional[str] = None,
) -> dict[str, Any]:
    message = (message or "").strip()
    if not message:
        raise ApiError(422, "MESSAGE_REQUIRED", "请输入问题")
    if len(message) > 1000:
        raise ApiError(422, "MESSAGE_TOO_LONG", "问题最多 1000 个字符")

    state = AgentState(
        db=db,
        user=user,
        message=message,
        session_id=_sanitize_session(session_id),
        trace_id=trace_id or new_trace_id(),
        community_id=community_id,
    )

    _parse_intent(state)
    _load_context(state)
    _plan_action(state)
    _risk_gate(state)
    _check_permission(state)
    _execute_plan(state)
    _verify_result(state)
    _reflect(state)
    _maybe_llm_polish(state)
    if state.status == "pending_approval" and state.approval:
        # 高风险回答始终保持“未执行”口径，避免被 LLM 改写
        _reflect(state)
    _write_memory(state)

    latency_ms = int((time.perf_counter() - state.started_at) * 1000)
    run = AgentRun(
        trace_id=state.trace_id,
        tenant_id=user.tenant_id,
        user_id=user.id,
        session_id=state.session_id,
        input=message,
        intent=state.intent,
        risk_level=state.risk_level,
        status=state.status,
        answer=state.answer,
        tool_calls=state.tool_calls,
        sources=state.sources,
        approval_id=state.approval.id if state.approval else None,
        latency_ms=latency_ms,
    )
    db.add(run)
    record_audit(
        db,
        action="agent.chat",
        user=user,
        resource_type="agent_run",
        resource_id=state.trace_id,
        detail={
            "intent": state.intent,
            "risk_level": state.risk_level,
            "status": state.status,
            "tools": [call["name"] for call in state.tool_calls],
            "approval_id": state.approval.id if state.approval else None,
        },
        trace_id=state.trace_id,
    )
    db.flush()

    return {
        "trace_id": state.trace_id,
        "session_id": state.session_id,
        "intent": state.intent,
        "intent_label": INTENT_LABELS.get(state.intent, state.intent),
        "risk_level": state.risk_level,
        "risk_label": RISK_LABELS.get(state.risk_level, state.risk_level),
        "status": state.status,
        "answer": state.answer,
        "sources": state.sources,
        "tool_calls": state.tool_calls,
        "approval": approval_public(state.approval) if state.approval else None,
        "data": state.data,
        "latency_ms": latency_ms,
        "created_at": iso(run.created_at),
    }
