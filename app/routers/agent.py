"""Agent 工作台接口。"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agents.graph import run_agent
from app.auth import get_current_user
from app.db import get_db
from app.errors import ApiError
from app.models import AgentRun, User
from app.schemas import AgentChatRequest
from app.serializers import agent_run_public

router = APIRouter(prefix="/api/agent", tags=["Agent 工作台"])


@router.post("/chat", summary="Agent 对话")
def chat(
    payload: AgentChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        result = run_agent(
            db,
            user,
            payload.message,
            session_id=payload.session_id,
            community_id=payload.community_id,
            trace_id=getattr(request.state, "trace_id", None),
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


@router.post("/chat/stream", summary="Agent 对话（SSE）")
def chat_stream(
    payload: AgentChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    def event_stream():
        meta = {"type": "start", "session_id": payload.session_id or "default"}
        yield f"event: start\ndata: {json.dumps(meta, ensure_ascii=False)}\n\n"
        try:
            result = run_agent(
                db,
                user,
                payload.message,
                session_id=payload.session_id,
                community_id=payload.community_id,
                trace_id=getattr(request.state, "trace_id", None),
            )
            db.commit()
            yield f"event: result\ndata: {json.dumps(result, ensure_ascii=False, default=str)}\n\n"
        except ApiError as exc:
            db.rollback()
            error = {"type": "error", "code": exc.code, "message": exc.message}
            yield f"event: error\ndata: {json.dumps(error, ensure_ascii=False)}\n\n"
        except Exception:  # noqa: BLE001
            db.rollback()
            error = {"type": "error", "code": "AGENT_FAILED", "message": "Agent 执行失败"}
            yield f"event: error\ndata: {json.dumps(error, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/runs", summary="Agent 运行记录")
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    session_id: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(AgentRun).filter(
        AgentRun.tenant_id == user.tenant_id, AgentRun.user_id == user.id
    )
    if session_id:
        query = query.filter(AgentRun.session_id == session_id)
    runs = query.order_by(AgentRun.created_at.desc()).limit(limit).all()
    return {"items": [agent_run_public(run) for run in runs]}


@router.get("/suggestions", summary="Agent 推荐问题")
def suggestions(user: User = Depends(get_current_user)) -> dict:
    common = [
        "近 7 天运营情况怎么样？",
        "当前有哪些设备故障？",
        "查一下云栖花园的空闲充电桩",
        "可用率和利用率是怎么计算的？",
    ]
    by_role = {
        "admin": [
            "诊断 HP-A-02 的故障原因",
            "近 30 天收入和退款情况",
            "把 YQ-A-01 停机检修",
            "生成 HP-A-02 的维修方案",
        ],
        "operator": [
            "诊断 HP-A-02 的故障原因",
            "P1 工单现在有几张？",
            "把 YQ-A-01 停机检修",
            "近 30 天收入情况",
        ],
        "technician": [
            "诊断 HP-A-02 的故障原因",
            "生成 HP-A-02 的维修方案",
            "当前待处理工单有哪些？",
            "给 YQ-A-01 创建一张 P2 工单",
        ],
        "finance": [
            "近 30 天收入和退款情况",
            "待审批的退款申请有哪些？",
            "把 HP-A-01 的电费调到 1.2 元/度",
            "设备可用率现在是多少？",
        ],
        "resident": [
            "附近有空闲充电桩吗？",
            "我的订单和消费情况",
            "预约成功率是什么意思？",
            "设备可用率是多少？",
        ],
    }
    return {"items": by_role.get(user.role, common)}
