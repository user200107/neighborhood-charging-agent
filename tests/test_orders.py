from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from tests.conftest import auth_header


def _available(client, headers, community_id: int = 1, limit: int = 5, starts=None, ends=None):
    params = f"community_id={community_id}&limit={limit}"
    if starts:
        params += f"&starts_at={starts.isoformat()}"
    if ends:
        params += f"&ends_at={ends.isoformat()}"
    response = client.get(f"/api/availability?{params}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_create_order_is_idempotent(client, sessions):
    headers = auth_header(sessions["resident"])
    connector = _available(client, headers)[0]
    key = f"test-{uuid.uuid4().hex}"
    payload = {"connector_id": connector["id"], "mode": "now", "payment_method": "wechat"}

    first = client.post("/api/orders", headers={**headers, "Idempotency-Key": key}, json=payload)
    assert first.status_code == 201, first.text
    order = first.json()
    assert order["status"] == "charging"
    assert order["connector_id"] == connector["id"]

    second = client.post("/api/orders", headers={**headers, "Idempotency-Key": key}, json=payload)
    assert second.status_code == 201
    assert second.headers.get("idempotency-replayed") == "true"
    assert second.json()["id"] == order["id"]

    other_connector = _available(client, headers)[0]
    conflict = client.post(
        "/api/orders",
        headers={**headers, "Idempotency-Key": key},
        json={"connector_id": other_connector["id"], "mode": "now"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_reservation_conflict_and_cancel(client, sessions):
    resident_headers = auth_header(sessions["resident"])
    resident2_login = client.post(
        "/api/auth/login", json={"username": "resident2", "password": "Demo@2026"}
    ).json()
    resident2_headers = {"Authorization": f"Bearer {resident2_login['access_token']}"}

    connector = _available(client, resident_headers)[0]
    starts = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(microsecond=0)
    ends = starts + timedelta(hours=2)
    payload = {
        "connector_id": connector["id"],
        "starts_at": starts.isoformat(),
        "ends_at": ends.isoformat(),
    }
    first = client.post("/api/reservations", headers=resident_headers, json=payload)
    assert first.status_code == 201, first.text
    reservation_id = first.json()["id"]

    second = client.post("/api/reservations", headers=resident2_headers, json=payload)
    assert second.status_code == 409
    assert second.json()["code"] == "RESERVATION_CONFLICT"

    cancel = client.delete(f"/api/reservations/{reservation_id}", headers=resident_headers)
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    again = client.post("/api/reservations", headers=resident2_headers, json=payload)
    assert again.status_code == 201


def test_order_lifecycle_and_scope(client, sessions):
    headers = auth_header(sessions["resident"])
    starts = (datetime.now(timezone.utc) + timedelta(hours=4)).replace(microsecond=0)
    ends = starts + timedelta(hours=2)
    connector = _available(client, headers, starts=starts, ends=ends)[0]
    created = client.post(
        "/api/orders",
        headers=headers,
        json={
            "connector_id": connector["id"],
            "mode": "reserved",
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
        },
    )
    assert created.status_code == 201, created.text
    order = created.json()
    assert order["status"] == "reserved"

    started = client.post(f"/api/orders/{order['id']}/start", headers=headers)
    assert started.status_code == 200
    assert started.json()["status"] == "charging"

    completed = client.post(f"/api/orders/{order['id']}/complete", headers=headers, json={"energy_kwh": 6.5})
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["energy_kwh"] == 6.5
    assert completed.json()["amount"] > 0

    invalid = client.post(f"/api/orders/{order['id']}/start", headers=headers)
    assert invalid.status_code == 409
    assert invalid.json()["code"] == "ORDER_STATUS_CONFLICT"

    # 居民不能使用未授权社区的枪口
    hp_connector = _available(client, auth_header(sessions["admin"]), community_id=2)[0]
    forbidden = client.post(
        "/api/orders",
        headers=headers,
        json={"connector_id": hp_connector["id"], "mode": "now"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "COMMUNITY_FORBIDDEN"


def test_invalid_order_payload(client, sessions):
    response = client.post(
        "/api/orders",
        headers=auth_header(sessions["resident"]),
        json={"connector_id": 0, "mode": "invalid"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
