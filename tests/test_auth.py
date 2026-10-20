from __future__ import annotations

from tests.conftest import auth_header


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "sqlite"
    assert response.headers["x-trace-id"].startswith("tr_")


def test_login_and_me(client, sessions):
    session = sessions["admin"]
    assert session["user"]["role"] == "admin"
    assert "audit" in session["menus"]
    assert session["access_token"]
    assert session["refresh_token"]

    response = client.get("/api/auth/me", headers=auth_header(session))
    assert response.status_code == 200
    assert response.json()["user"]["username"] == "admin"
    assert response.json()["tenant"]["code"] == "NEIGHBOR"


def test_login_failure_and_validation(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"
    assert response.json()["trace_id"]

    response = client.post("/api/auth/login", json={"username": "a"})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_refresh_and_logout(client):
    login = client.post(
        "/api/auth/login",
        json={"username": "ops", "password": "Demo@2026"},
    ).json()
    response = client.post("/api/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert response.status_code == 200
    new_token = response.json()["access_token"]
    assert new_token

    old_refresh = client.post("/api/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert old_refresh.status_code == 401

    logout = client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {new_token}"},
        json={"refresh_token": response.json()["refresh_token"]},
    )
    assert logout.status_code == 200

    after = client.post("/api/auth/refresh", json={"refresh_token": response.json()["refresh_token"]})
    assert after.status_code == 401


def test_resident_cannot_access_admin_endpoints(client, sessions):
    headers = auth_header(sessions["resident"])
    for path in ("/api/audit", "/api/approvals", "/api/reports/overview"):
        response = client.get(path, headers=headers)
        assert response.status_code == 403, path
        assert response.json()["code"] in {"FORBIDDEN", "ROLE_FORBIDDEN"}

    response = client.get("/api/users", headers=headers)
    assert response.status_code == 403


def test_operator_can_list_users_but_not_audit(client, sessions):
    assert client.get("/api/users", headers=auth_header(sessions["ops"])).status_code == 200
    assert client.get("/api/audit", headers=auth_header(sessions["ops"])).status_code == 403


def test_token_required(client):
    response = client.get("/api/piles")
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_MISSING"
