from __future__ import annotations

from tests.conftest import auth_header


def test_dashboard_and_reports(client, sessions):
    headers = auth_header(sessions["admin"])
    dashboard = client.get("/api/dashboard?days=30", headers=headers)
    assert dashboard.status_code == 200
    data = dashboard.json()
    assert len(data["cards"]) == 6
    assert data["summary"]["total_piles"] == 16
    assert data["summary"]["revenue"] >= 0
    assert len(data["trend"]) == 30
    assert len(data["communities"]) == 4

    reports = client.get("/api/reports/overview?days=30", headers=headers)
    assert reports.status_code == 200
    body = reports.json()
    assert body["summary"]["completed_orders"] >= 0
    assert body["order_status"]
    assert body["payment_methods"]

    csv_response = client.get("/api/reports/orders.csv?days=30", headers=headers)
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert csv_response.content.startswith("\ufeff".encode("utf-8"))
    assert "订单号" in csv_response.text


def test_community_filter(client, sessions):
    headers = auth_header(sessions["admin"])
    response = client.get("/api/dashboard?days=7&community_id=1", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["scope"]["community_id"] == 1
    assert all(item["id"] == 1 for item in data["communities"])


def test_audit_log(client, sessions):
    headers = auth_header(sessions["admin"])
    response = client.get("/api/audit?page_size=50", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] > 0
    actions = client.get("/api/audit/actions", headers=headers)
    assert actions.status_code == 200
    assert "auth.login" in actions.json()["items"]
