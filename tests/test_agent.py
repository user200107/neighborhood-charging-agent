from __future__ import annotations

from tests.conftest import auth_header


def _chat(client, session, message: str, session_id: str = "test-session") -> dict:
    response = client.post(
        "/api/agent/chat",
        headers=auth_header(session),
        json={"message": message, "session_id": session_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_agent_read_query_returns_trace_and_sources(client, sessions):
    result = _chat(client, sessions["admin"], "近 7 天运营情况怎么样？")
    assert result["intent"] == "overview"
    assert result["status"] == "completed"
    assert result["risk_level"] == "read"
    assert result["trace_id"].startswith("tr_")
    assert result["sources"]
    assert result["tool_calls"][0]["name"] == "operations_overview"
    assert "收入" in result["answer"]
    assert result["latency_ms"] >= 0


def test_agent_diagnosis(client, sessions):
    result = _chat(client, sessions["ops"], "诊断 HP-A-02 的故障")
    assert result["intent"] == "diagnose"
    assert result["status"] == "completed"
    assert result["tool_calls"][0]["name"] == "diagnose_pile"
    assert any(source["name"] == "device_events" for source in result["sources"])
    assert "HP-A-02" in result["answer"]


def test_agent_high_risk_creates_approval_without_execution(client, sessions):
    headers = auth_header(sessions["ops"])
    before = client.get("/api/piles?page_size=100", headers=headers).json()["items"]
    pile_before = next(p for p in before if p["code"] == "YQ-A-01")

    result = _chat(client, sessions["ops"], "把 YQ-A-01 停机检修", session_id="risk-session")
    assert result["intent"] == "stop_pile"
    assert result["risk_level"] == "high_risk"
    assert result["status"] == "pending_approval"
    assert result["approval"]
    assert result["approval"]["status"] == "pending"
    assert result["tool_calls"][0]["name"] == "request_stop_pile"

    pile_after = client.get(f"/api/piles/{pile_before['id']}", headers=headers).json()
    assert pile_after["status"] == pile_before["status"]
    assert pile_after["status"] != "maintenance"

    approval = client.get(f"/api/approvals/{result['approval']['id']}", headers=headers)
    assert approval.status_code == 200
    assert approval.json()["status"] == "pending"


def test_resident_high_risk_is_rejected(client, sessions):
    result = _chat(client, sessions["resident"], "把 YQ-A-01 停机检修", session_id="resident-risk")
    assert result["status"] == "rejected"
    assert result["risk_level"] == "high_risk"
    assert "无权" in result["answer"]
    assert result["approval"] is None


def test_agent_approval_query(client, sessions):
    result = _chat(client, sessions["finance"], "待审批的退款申请有哪些？", session_id="approval-query")
    assert result["intent"] == "approvals"
    assert result["status"] == "completed"
    assert result["tool_calls"][0]["name"] == "approval_overview"
    assert result["data"]["approval_overview"]["total"] >= 1


def test_resident_overview_uses_device_health_without_revenue(client, sessions):
    result = _chat(client, sessions["resident"], "社区设备运行情况怎么样？", session_id="resident-overview")
    assert result["status"] == "completed"
    assert result["tool_calls"][0]["name"] == "pile_health"
    assert "收入" not in result["answer"]


def test_resident_agent_only_own_orders(client, sessions):
    result = _chat(client, sessions["resident"], "我的订单和消费情况", session_id="resident-orders")
    assert result["intent"] == "orders"
    assert result["status"] == "completed"
    assert result["tool_calls"][0]["name"] == "my_orders"
    items = result["data"]["my_orders"]["items"]
    assert all(item["user_id"] == sessions["resident"]["user"]["id"] for item in items)


def test_agent_validation(client, sessions):
    response = client.post(
        "/api/agent/chat",
        headers=auth_header(sessions["admin"]),
        json={"message": ""},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_agent_tool_whitelist_shape(client, sessions):
    result = _chat(client, sessions["admin"], "帮我执行任意 SQL 查询数据库", session_id="unsafe")
    assert result["status"] in {"completed", "rejected"}
    assert all(call["name"] in {
        "operations_overview", "pile_health", "diagnose_pile", "order_analytics", "my_orders",
        "ticket_overview", "approval_overview", "check_availability", "repair_plan", "metric_glossary",
        "request_stop_pile", "request_refund", "request_price_change",
        "request_bulk_reassign", "create_ticket",
    } for call in result["tool_calls"])
