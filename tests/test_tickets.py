from __future__ import annotations

import uuid

from tests.conftest import auth_header


def _create_completed_test_order(client, resident_headers, exclude_piles=None):
    exclude_piles = exclude_piles or set()
    available = client.get(
        "/api/availability?community_id=1&limit=8", headers=resident_headers
    ).json()["items"]
    connector = next(item for item in available if item["pile"]["id"] not in exclude_piles)
    created = client.post(
        "/api/orders",
        headers=resident_headers,
        json={"connector_id": connector["id"], "mode": "now"},
    )
    assert created.status_code == 201, created.text
    order = created.json()
    completed = client.post(
        f"/api/orders/{order['id']}/complete",
        headers=resident_headers,
        json={"energy_kwh": 3.2},
    )
    assert completed.status_code == 200, completed.text
    return connector["pile"]["id"], completed.json()


def _create_ticket(client, ops_headers, pile_id: int):
    response = client.post(
        "/api/tickets",
        headers=ops_headers,
        json={
            "pile_id": pile_id,
            "title": f"联调测试工单 {uuid.uuid4().hex[:6]}",
            "description": "自动化测试创建的工单，用于验证验收与关闭门禁。",
            "priority": "P2",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_ticket_full_workflow(client, sessions):
    resident_headers = auth_header(sessions["resident"])
    ops_headers = auth_header(sessions["ops"])
    tech_headers = auth_header(sessions["tech"])
    pile_id, order = _create_completed_test_order(client, resident_headers)
    ticket = _create_ticket(client, ops_headers, pile_id)

    assignees = client.get("/api/tickets/assignees", headers=ops_headers).json()["items"]
    tech = next(item for item in assignees if item["role"] == "technician")
    assigned = client.post(
        f"/api/tickets/{ticket['id']}/assign",
        headers=ops_headers,
        json={"assignee_id": tech["id"]},
    )
    assert assigned.status_code == 200
    assert assigned.json()["status"] == "assigned"

    accepted = client.post(f"/api/tickets/{ticket['id']}/accept", headers=tech_headers)
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"

    started = client.post(f"/api/tickets/{ticket['id']}/start", headers=tech_headers)
    assert started.status_code == 200
    assert started.json()["status"] == "processing"

    resolved = client.post(
        f"/api/tickets/{ticket['id']}/resolve",
        headers=tech_headers,
        json={"resolution": "已检查枪口锁止机构并更换磨损部件，设备自检正常。"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "pending_verification"

    # 未验收不能关闭
    blocked = client.post(f"/api/tickets/{ticket['id']}/close", headers=ops_headers)
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "TICKET_ACCEPTANCE_REQUIRED"

    verified = client.post(
        f"/api/tickets/{ticket['id']}/verify",
        headers=tech_headers,
        json={"test_order_id": order["id"]},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["heartbeat_checked"] is True
    assert verified.json()["test_order_verified"] is True

    closed = client.post(f"/api/tickets/{ticket['id']}/close", headers=ops_headers)
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"
    assert closed.json()["closed_at"]

    detail = client.get(f"/api/tickets/{ticket['id']}", headers=ops_headers)
    assert detail.status_code == 200
    actions = [row["action"] for row in detail.json()["timeline"]]
    assert "ticket.created" in actions
    assert "ticket.verified" in actions
    assert "ticket.closed" in actions


def test_ticket_verify_rejects_order_from_other_pile(client, sessions):
    resident_headers = auth_header(sessions["resident"])
    ops_headers = auth_header(sessions["ops"])
    tech_headers = auth_header(sessions["tech"])
    pile_id, _ = _create_completed_test_order(client, resident_headers)
    ticket = _create_ticket(client, ops_headers, pile_id)
    client.post(f"/api/tickets/{ticket['id']}/accept", headers=tech_headers)

    other_pile, other_order = _create_completed_test_order(
        client, resident_headers, exclude_piles={pile_id}
    )
    assert other_pile != pile_id
    response = client.post(
        f"/api/tickets/{ticket['id']}/verify",
        headers=tech_headers,
        json={"test_order_id": other_order["id"]},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "TEST_ORDER_PILE_MISMATCH"


def test_resident_can_report_but_not_process(client, sessions):
    resident_headers = auth_header(sessions["resident"])
    piles = client.get("/api/piles?page_size=5", headers=resident_headers).json()["items"]
    created = client.post(
        "/api/tickets",
        headers=resident_headers,
        json={
            "pile_id": piles[0]["id"],
            "title": "居民投诉：夜间充电噪音较大",
            "description": "希望安排检查散热风扇。",
        },
    )
    assert created.status_code == 201
    assert created.json()["source"] == "complaint"
    assert created.json()["priority"] == "P3"

    forbidden = client.post(f"/api/tickets/{created.json()['id']}/accept", headers=resident_headers)
    assert forbidden.status_code == 403


def test_invalid_ticket_transition(client, sessions):
    ops_headers = auth_header(sessions["ops"])
    piles = client.get("/api/piles?page_size=5", headers=ops_headers).json()["items"]
    ticket = _create_ticket(client, ops_headers, piles[0]["id"])
    response = client.post(f"/api/tickets/{ticket['id']}/resolve", headers=ops_headers, json={"resolution": "直接回填测试"})
    assert response.status_code == 409
    assert response.json()["code"] == "TICKET_STATUS_CONFLICT"
