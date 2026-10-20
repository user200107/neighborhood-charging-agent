from __future__ import annotations

from tests.conftest import auth_header


def test_community_scope_for_operator(client, sessions):
    headers = auth_header(sessions["ops"])
    response = client.get("/api/piles?page_size=100", headers=headers)
    assert response.status_code == 200
    communities = {item["community_name"] for item in response.json()["items"]}
    assert "梅溪里" not in communities
    assert {"云栖花园", "湖畔新城", "科创家园"} <= communities

    forbidden = client.get("/api/piles?community_id=4", headers=headers)
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "COMMUNITY_FORBIDDEN"


def test_resident_only_sees_home_community(client, sessions):
    headers = auth_header(sessions["resident"])
    response = client.get("/api/piles?page_size=100", headers=headers)
    assert response.status_code == 200
    communities = {item["community_name"] for item in response.json()["items"]}
    assert communities == {"云栖花园"}


def test_tenant_isolation(client, sessions):
    other_login = client.post(
        "/api/auth/login",
        json={"username": "otheradmin", "password": "Demo@2026", "tenant_code": "OTHER"},
    )
    assert other_login.status_code == 200, other_login.text
    other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}

    other_piles = client.get("/api/piles", headers=other_headers).json()["items"]
    assert [pile["code"] for pile in other_piles] == ["OT-A-01"]

    admin_piles = client.get("/api/piles?page_size=100", headers=auth_header(sessions["admin"])).json()["items"]
    assert "OT-A-01" not in {pile["code"] for pile in admin_piles}

    foreign_id = other_piles[0]["id"]
    response = client.get(f"/api/piles/{foreign_id}", headers=auth_header(sessions["admin"]))
    assert response.status_code == 404


def test_resident_cannot_read_other_user_order(client, sessions):
    admin_headers = auth_header(sessions["admin"])
    orders = client.get("/api/orders?page_size=20", headers=admin_headers).json()["items"]
    foreign = next(order for order in orders if order["user_id"] != sessions["resident"]["user"]["id"])
    response = client.get(f"/api/orders/{foreign['id']}", headers=auth_header(sessions["resident"]))
    assert response.status_code == 403
    assert response.json()["code"] == "ORDER_FORBIDDEN"


def test_other_tenant_cannot_inject_device_event(client, sessions):
    other_login = client.post(
        "/api/auth/login",
        json={"username": "otheradmin", "password": "Demo@2026", "tenant_code": "OTHER"},
    ).json()
    foreign_pile = client.get(
        "/api/piles",
        headers={"Authorization": f"Bearer {other_login['access_token']}"},
    ).json()["items"][0]
    response = client.post(
        "/api/device-events",
        headers={"Authorization": f"Bearer {sessions['admin']['access_token']}"},
        json={
            "event_no": "TEST-CROSS-TENANT",
            "pile_id": foreign_pile["id"],
            "event_type": "heartbeat",
            "payload": {"online": True},
        },
    )
    assert response.status_code == 404
