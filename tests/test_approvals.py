from __future__ import annotations

from tests.conftest import auth_header


def _pile_by_code(client, headers, code: str) -> dict:
    items = client.get("/api/piles?page_size=100", headers=headers).json()["items"]
    return next(item for item in items if item["code"] == code)


def test_stop_pile_approval_flow(client, sessions):
    ops_headers = auth_header(sessions["ops"])
    finance_headers = auth_header(sessions["finance"])
    pile = _pile_by_code(client, ops_headers, "YQ-A-03")

    created = client.post(
        "/api/approvals",
        headers=ops_headers,
        json={
            "type": "stop_pile",
            "target_id": str(pile["id"]),
            "reason": "自动化测试：设备温度持续偏高，申请临时停机检查。",
            "payload": {"pile_id": pile["id"], "action": "maintenance"},
        },
    )
    assert created.status_code == 201, created.text
    approval = created.json()
    assert approval["status"] == "pending"
    assert approval["type"] == "stop_pile"

    duplicate = client.post(
        "/api/approvals",
        headers=ops_headers,
        json={
            "type": "stop_pile",
            "target_id": str(pile["id"]),
            "reason": "重复申请应被合并。",
            "payload": {"pile_id": pile["id"], "action": "maintenance"},
        },
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == approval["id"]
    assert duplicate.json()["created"] is False

    decided = client.post(
        f"/api/approvals/{approval['id']}/decide",
        headers=finance_headers,
        json={"decision": "approve", "comment": "测试审批通过"},
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"

    again = client.post(
        f"/api/approvals/{approval['id']}/decide",
        headers=finance_headers,
        json={"decision": "reject"},
    )
    assert again.status_code == 409
    assert again.json()["code"] == "APPROVAL_ALREADY_DECIDED"

    executed = client.post(f"/api/approvals/{approval['id']}/execute", headers=finance_headers)
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "executed"
    assert executed.json()["execution_result"]["result"] == "success"

    after = client.get(f"/api/piles/{pile['id']}", headers=ops_headers).json()
    assert after["status"] == "maintenance"
    assert all(connector["status"] == "offline" for connector in after["connectors"])

    repeat_execute = client.post(f"/api/approvals/{approval['id']}/execute", headers=finance_headers)
    assert repeat_execute.status_code == 200
    assert repeat_execute.json()["status"] == "executed"


def test_seeded_refund_approval_execution(client, sessions):
    finance_headers = auth_header(sessions["finance"])
    approvals = client.get("/api/approvals?type=refund&status=pending", headers=finance_headers).json()["items"]
    assert approvals
    approval = approvals[0]
    order = client.get(f"/api/orders?keyword={approval['target_id']}", headers=auth_header(sessions["admin"])).json()["items"][0]
    before_refund = order["refund_amount"]

    decided = client.post(
        f"/api/approvals/{approval['id']}/decide",
        headers=finance_headers,
        json={"decision": "approve", "comment": "测试退款通过"},
    )
    assert decided.status_code == 200
    executed = client.post(f"/api/approvals/{approval['id']}/execute", headers=finance_headers)
    assert executed.status_code == 200, executed.text
    assert executed.json()["execution_result"]["refund_amount"] == approval["amount"]

    after = client.get(f"/api/orders/{order['id']}", headers=auth_header(sessions["admin"])).json()
    assert after["refund_amount"] == round(before_refund + approval["amount"], 2)


def test_refund_approval_amount_validation(client, sessions):
    ops_headers = auth_header(sessions["ops"])
    orders = client.get("/api/orders?status=completed&page_size=5", headers=ops_headers).json()["items"]
    order = orders[0]
    amount = round(order["amount"] * 0.3, 2)
    created = client.post(
        "/api/approvals",
        headers=ops_headers,
        json={
            "type": "refund",
            "target_id": order["order_no"],
            "reason": "自动化测试：充电中断，申请部分退款。",
            "payload": {"order_no": order["order_no"], "amount": amount},
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["amount"] == amount

    too_much = client.post(
        "/api/approvals",
        headers=ops_headers,
        json={
            "type": "refund",
            "target_id": order["order_no"],
            "reason": "超额退款测试",
            "payload": {"order_no": order["order_no"], "amount": order["amount"] + 100},
        },
    )
    assert too_much.status_code == 400
    assert too_much.json()["code"] == "REFUND_AMOUNT_EXCEEDED"


def test_approval_permissions(client, sessions):
    resident_headers = auth_header(sessions["resident"])
    ops_headers = auth_header(sessions["ops"])
    pile = _pile_by_code(client, auth_header(sessions["admin"]), "YQ-D-04")
    forbidden = client.post(
        "/api/approvals",
        headers=resident_headers,
        json={
            "type": "stop_pile",
            "target_id": str(pile["id"]),
            "reason": "居民尝试停机",
            "payload": {"pile_id": pile["id"]},
        },
    )
    assert forbidden.status_code == 403

    created = client.post(
        "/api/approvals",
        headers=ops_headers,
        json={
            "type": "stop_pile",
            "target_id": str(pile["id"]),
            "reason": "权限测试：运营发起停机审批。",
            "payload": {"pile_id": pile["id"]},
        },
    )
    assert created.status_code == 201
    # 运营角色不能审批
    decide = client.post(
        f"/api/approvals/{created.json()['id']}/decide",
        headers=ops_headers,
        json={"decision": "approve"},
    )
    assert decide.status_code == 403


def test_operator_approval_scope(client, sessions):
    ops_headers = auth_header(sessions["ops"])
    mx_pile = _pile_by_code(client, auth_header(sessions["admin"]), "MX-A-01")
    response = client.post(
        "/api/approvals",
        headers=ops_headers,
        json={
            "type": "stop_pile",
            "target_id": str(mx_pile["id"]),
            "reason": "越权社区测试申请",
            "payload": {"pile_id": mx_pile["id"]},
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == "COMMUNITY_FORBIDDEN"
