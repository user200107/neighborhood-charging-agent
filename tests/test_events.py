from __future__ import annotations

import uuid

from tests.conftest import auth_header


def _pile_by_code(client, headers, code: str) -> dict:
    items = client.get("/api/piles?page_size=100", headers=headers).json()["items"]
    return next(item for item in items if item["code"] == code)


def test_device_event_dedup_and_ticket_creation(client, sessions):
    headers = auth_header(sessions["ops"])
    pile = _pile_by_code(client, headers, "HP-D-04")
    event_no = f"TEST-EVT-{uuid.uuid4().hex[:10]}"
    payload = {
        "event_no": event_no,
        "pile_id": pile["id"],
        "event_type": "fault",
        "severity": "critical",
        "payload": {"fault_code": "E-TEST", "message": "自动化测试故障"},
    }
    first = client.post("/api/device-events", headers=headers, json=payload)
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["duplicate"] is False
    assert data["ticket_id"]
    assert data["priority"] == "P1"

    second = client.post("/api/device-events", headers=headers, json=payload)
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["ticket_id"] == data["ticket_id"]

    tickets = client.get(f"/api/tickets?keyword=HP-D-04&page_size=20", headers=headers).json()["items"]
    matching = [ticket for ticket in tickets if ticket["id"] == data["ticket_id"]]
    assert len(matching) == 1
    assert matching[0]["status"] == "pending"

    recovered = client.post(
        "/api/device-events",
        headers=headers,
        json={
            "event_no": f"TEST-RECOVER-{uuid.uuid4().hex[:10]}",
            "pile_id": pile["id"],
            "event_type": "recovered",
            "severity": "info",
            "payload": {"message": "测试恢复"},
        },
    )
    assert recovered.status_code == 200
    after = client.get(f"/api/piles/{pile['id']}", headers=headers).json()
    assert after["status"] == "online"


def test_device_event_validation_and_permissions(client, sessions):
    headers = auth_header(sessions["ops"])
    pile = _pile_by_code(client, headers, "YQ-D-04")
    bad = client.post(
        "/api/device-events",
        headers=headers,
        json={"event_no": "TEST-BAD-TYPE", "pile_id": pile["id"], "event_type": "unknown"},
    )
    assert bad.status_code == 400
    assert bad.json()["code"] == "EVENT_TYPE_INVALID"

    resident = client.post(
        "/api/device-events",
        headers=auth_header(sessions["resident"]),
        json={
            "event_no": f"TEST-RES-{uuid.uuid4().hex[:8]}",
            "pile_id": pile["id"],
            "event_type": "heartbeat",
        },
    )
    assert resident.status_code == 403


def test_heartbeat_updates_pile(client, sessions):
    headers = auth_header(sessions["ops"])
    pile = _pile_by_code(client, headers, "YQ-D-04")
    response = client.post(
        "/api/device-events",
        headers=headers,
        json={
            "event_no": f"TEST-HB-{uuid.uuid4().hex[:8]}",
            "pile_id": pile["id"],
            "event_type": "heartbeat",
            "severity": "info",
            "payload": {"online": True, "signal": 4},
        },
    )
    assert response.status_code == 200
    detail = client.get(f"/api/piles/{pile['id']}", headers=headers).json()
    assert detail["online"] is True
    assert detail["last_heartbeat_at"]
