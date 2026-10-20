"""演示数据。

仅在数据库为空时写入，使用固定随机种子，保证每次初始化结果可复现。
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.auth import hash_password
from app.constants import SLA_HOURS
from app.models import (
    AgentMemory,
    Approval,
    AuditLog,
    Community,
    Connector,
    DeviceEvent,
    Order,
    Pile,
    Reservation,
    Tenant,
    Ticket,
    User,
    Zone,
)
from app.utils import gen_approval_no, gen_order_no, gen_ticket_no, utcnow

DEMO_PASSWORD = "Demo@2026"

COMMUNITIES = [
    ("YQ", "云栖花园", "杭州市西湖区", "云栖路 88 号", "A 区", "B 区", "地下车库"),
    ("HP", "湖畔新城", "杭州市滨江区", "湖畔大道 16 号", "一期", "二期", "地下车库"),
    ("KC", "科创家园", "杭州市余杭区", "文一西路 998 号", "研发区", "生活区", "地下车库"),
    ("MX", "梅溪里", "杭州市拱墅区", "梅溪路 23 号", "南区", "北区", "地面车场"),
]

USERS = [
    ("admin", "周明", "admin", "13800001234", "admin@demo.local"),
    ("ops", "林晓", "operator", "13800002345", "ops@demo.local"),
    ("tech", "陈工", "technician", "13800003456", "tech@demo.local"),
    ("finance", "赵敏", "finance", "13800004567", "finance@demo.local"),
    ("resident", "王悦", "resident", "13800005678", "resident@demo.local"),
    ("resident2", "李然", "resident", "13800006789", "resident2@demo.local"),
]


def _tenant_exists(db: Session) -> bool:
    return db.query(Tenant.id).first() is not None


def _make_connectors(db: Session, pile: Pile, count: int, rng: random.Random) -> list[Connector]:
    connectors: list[Connector] = []
    is_dc = pile.rated_power_kw >= 30
    for idx in range(count):
        connector = Connector(
            tenant_id=pile.tenant_id,
            pile_id=pile.id,
            code=f"{idx + 1:02d}",
            gun_type="GBT_DC" if is_dc else "GBT_AC",
            power_kw=pile.rated_power_kw,
            price_per_kwh=round(rng.uniform(0.92, 1.28) + (0.25 if is_dc else 0), 2),
            service_fee=round(rng.uniform(0.25, 0.55), 2),
            total_energy_kwh=round(rng.uniform(320, 4200), 1),
        )
        db.add(connector)
        connectors.append(connector)
    db.flush()
    return connectors


def seed_demo_data(db: Session) -> bool:
    if _tenant_exists(db):
        return False

    rng = random.Random(20260501)
    now = utcnow()
    local_now = now + timedelta(hours=8)  # 演示数据按 Asia/Shanghai 生成营业时段

    tenant = Tenant(
        code="NEIGHBOR",
        name="邻里充电（演示租户）",
        status="active",
        contact_name="运营中心",
        contact_phone="0571-88886666",
    )
    db.add(tenant)
    db.flush()

    # ===== 社区与区域 =====
    communities: list[Community] = []
    zones_by_community: dict[int, list[Zone]] = {}
    for code, name, city, address, *zone_names in COMMUNITIES:
        community = Community(
            tenant_id=tenant.id,
            code=code,
            name=name,
            city=city,
            address=address,
            status="active",
            contact_name=f"{name}物业",
            contact_phone=f"0571-88{rng.randint(100000, 999999)}",
        )
        db.add(community)
        db.flush()
        communities.append(community)
        zones = []
        for zidx, zname in enumerate(zone_names):
            zone = Zone(
                tenant_id=tenant.id,
                community_id=community.id,
                code=f"{code}-Z{zidx + 1}",
                name=zname,
                description=f"{name}{zname}充电区域",
            )
            db.add(zone)
            zones.append(zone)
        db.flush()
        zones_by_community[community.id] = zones

    # ===== 用户 =====
    password_hash = hash_password(DEMO_PASSWORD)
    users: dict[str, User] = {}
    for username, display, role, phone, email in USERS:
        user = User(
            tenant_id=tenant.id,
            username=username,
            password_hash=password_hash,
            display_name=display,
            role=role,
            phone=phone,
            email=email,
            status="active",
        )
        db.add(user)
        users[username] = user
    db.flush()

    # 社区范围授权
    scope_map = {
        "admin": communities,
        "ops": [communities[0], communities[1], communities[2]],
        "tech": [communities[0], communities[1]],
        "finance": communities,
        "resident": [communities[0]],
        "resident2": [communities[0], communities[1]],
    }
    for username, scoped in scope_map.items():
        users[username].communities = list(scoped)

    # ===== 充电桩与枪口 =====
    piles: list[Pile] = []
    connectors_by_pile: dict[int, list[Connector]] = {}
    pile_counter = 0
    for c_index, community in enumerate(communities):
        zones = zones_by_community[community.id]
        for idx in range(4):
            pile_counter += 1
            zone = zones[idx % len(zones)]
            is_dc = idx == 3
            power = 60.0 if is_dc else (11.0 if idx % 2 else 7.0)
            code = f"{community.code}-{'D' if is_dc else 'A'}-{idx + 1:02d}"
            status = "online"
            if community.code == "HP" and idx == 1:
                status = "fault"
            elif community.code == "KC" and idx == 1:
                status = "offline"
            elif community.code == "MX" and idx == 0:
                status = "maintenance"
            online = status == "online"
            pile = Pile(
                tenant_id=tenant.id,
                community_id=community.id,
                zone_id=zone.id,
                code=code,
                name=f"{community.name} {zone.name} {idx + 1:02d} 号桩",
                model="DC-60kW" if is_dc else ("AC-11kW" if power == 11 else "AC-7kW"),
                vendor="邻里能源" if idx % 3 else "星云智充",
                rated_power_kw=power,
                status=status,
                online=online,
                last_heartbeat_at=now - timedelta(minutes=(3 if online else rng.randint(35, 180))),
                current_power_kw=0.0,
                temperature_c=round(28 + rng.uniform(0, 18) + (8 if status == "fault" else 0), 1),
                signal_strength=rng.randint(1, 5),
                firmware=f"v2.{rng.randint(2, 4)}.{rng.randint(0, 6)}",
                installed_at=now - timedelta(days=rng.randint(120, 800)),
                notes="高温告警，待维修" if status == "fault" else None,
            )
            db.add(pile)
            db.flush()
            connectors = _make_connectors(db, pile, 2, rng)
            piles.append(pile)
            connectors_by_pile[pile.id] = connectors

    # 构造实时占用状态
    charging_connectors = [connectors_by_pile[p.id][0] for p in piles if p.status == "online"][:5]
    for index, connector in enumerate(charging_connectors):
        connector.status = "charging"
        connector.pile.current_power_kw = connector.power_kw * rng.uniform(0.55, 0.95)
    reserved_connectors = [connectors_by_pile[p.id][1] for p in piles if p.status == "online"][:2]
    for connector in reserved_connectors:
        connector.status = "reserved"
    for pile in piles:
        if pile.status == "fault":
            for connector in connectors_by_pile[pile.id]:
                connector.status = "fault"
        elif pile.status == "offline":
            for connector in connectors_by_pile[pile.id]:
                connector.status = "offline"
        elif pile.status == "maintenance":
            for connector in connectors_by_pile[pile.id]:
                connector.status = "offline"
    db.flush()

    # ===== 历史订单 =====
    orders: list[Order] = []
    residents = [users["resident"], users["resident2"]]
    for index in range(180):
        community = communities[rng.choices(range(len(communities)), weights=[34, 30, 22, 14])[0]]
        community_piles = [p for p in piles if p.community_id == community.id]
        pile = rng.choice(community_piles)
        connector = rng.choice(connectors_by_pile[pile.id])
        user = rng.choice(residents)
        day_offset = rng.randint(0, 29)
        max_hour = local_now.hour if day_offset == 0 else 21
        if max_hour < 8:
            day_offset = max(1, day_offset)
            max_hour = 21
        local_start = (local_now - timedelta(days=day_offset)).replace(
            hour=rng.randint(7, max(7, min(21, max_hour))),
            minute=rng.choice([0, 10, 15, 20, 30, 40, 45]),
            second=0,
            microsecond=0,
        )
        start = local_start - timedelta(hours=8)
        duration_minutes = rng.randint(35, 190)
        energy = round(connector.power_kw * duration_minutes / 60 * rng.uniform(0.55, 0.92), 2)
        amount = round(energy * (connector.price_per_kwh + connector.service_fee), 2)

        if day_offset == 0 and index % 11 == 0:
            status = "charging"
            start = now - timedelta(minutes=rng.randint(12, 75))
            energy = round(connector.power_kw * (now - start).total_seconds() / 3600 * 0.7, 2)
            amount = round(energy * (connector.price_per_kwh + connector.service_fee), 2)
        elif day_offset == 0 and index % 13 == 0:
            status = "reserved"
            start = now + timedelta(hours=rng.randint(2, 20))
        elif day_offset == 0 and index % 17 == 0:
            status = "pending_payment"
            start = now + timedelta(minutes=20)
        else:
            bucket = rng.random()
            if bucket < 0.80:
                status = "completed"
            elif bucket < 0.90:
                status = "cancelled"
            elif bucket < 0.95:
                status = "abnormal"
            else:
                status = "completed"

        ended = None
        refund = 0.0
        if status == "completed":
            ended = start + timedelta(minutes=duration_minutes)
            if rng.random() < 0.06:
                refund = round(amount * rng.uniform(0.1, 0.5), 2)
        elif status == "cancelled":
            energy = 0.0
            amount = 0.0
            ended = start + timedelta(minutes=rng.randint(2, 20))
        elif status == "abnormal":
            ended = start + timedelta(minutes=duration_minutes)
            refund = round(amount * rng.uniform(0.2, 0.7), 2)
        if status in {"reserved", "pending_payment"}:
            energy = 0.0
            amount = 0.0

        # 已发生订单必须落在当前时间之前
        if status in {"completed", "cancelled", "abnormal"} and start > now - timedelta(minutes=30):
            start = now - timedelta(minutes=rng.randint(45, 420))
            if ended:
                ended = start + timedelta(minutes=duration_minutes)
        created_at = start - timedelta(minutes=rng.randint(1, 30))
        if status in {"reserved", "pending_payment", "charging"}:
            created_at = now - timedelta(minutes=rng.randint(3, 90))
        if created_at > now:
            created_at = now - timedelta(minutes=5)

        order = Order(
            tenant_id=tenant.id,
            order_no=f"NO{start:%Y%m%d}{index:04d}",
            user_id=user.id,
            community_id=community.id,
            pile_id=pile.id,
            connector_id=connector.id,
            status=status,
            starts_at=start,
            ended_at=ended,
            energy_kwh=energy,
            unit_price=connector.price_per_kwh,
            service_fee=connector.service_fee,
            amount=amount,
            refund_amount=refund,
            payment_method=rng.choice(["wechat", "alipay", "balance"]),
            idempotency_key=f"seed-order-{index}",
            source=rng.choice(["web", "app", "agent"]),
            created_at=created_at,
        )
        db.add(order)
        orders.append(order)
    db.flush()

    # ===== 预约 =====
    for index in range(10):
        community = communities[index % len(communities)]
        pile = next(p for p in piles if p.community_id == community.id and p.status == "online")
        connector = connectors_by_pile[pile.id][0]
        starts = (now + timedelta(days=rng.randint(0, 2))).replace(
            hour=rng.randint(8, 20), minute=rng.choice([0, 30]), second=0, microsecond=0
        )
        reservation = Reservation(
            tenant_id=tenant.id,
            community_id=community.id,
            user_id=rng.choice(residents).id,
            connector_id=connector.id,
            starts_at=starts,
            ends_at=starts + timedelta(hours=2),
            status="active",
            note="演示预约",
        )
        db.add(reservation)
    db.flush()

    # ===== 工单 =====
    tech = users["tech"]
    ops = users["ops"]
    fault_pile = next(p for p in piles if p.status == "fault")
    offline_pile = next(p for p in piles if p.status == "offline")
    online_piles = [p for p in piles if p.status == "online"]
    ticket_specs = [
        ("P1", "processing", fault_pile, "充电模块过温，设备自动降功率", "device", 3, True, True),
        ("P2", "pending", offline_pile, "设备连续离线超过 30 分钟", "device", 2, False, False),
        ("P2", "assigned", online_piles[1], "枪口锁止异常，用户无法拔枪", "manual", 6, False, False),
        ("P2", "pending_verification", online_piles[2], "刷卡模块偶发识别失败", "manual", 28, True, False),
        ("P3", "accepted", online_piles[3], "屏幕亮度偏暗", "complaint", 40, False, False),
        ("P3", "closed", online_piles[4], "充电枪线外皮磨损", "manual", 120, True, True),
        ("P2", "closed", online_piles[5], "通信模块断连，已更换 4G 模块", "device", 168, True, True),
        ("P3", "closed", online_piles[6], "桩体标识脱落，已补贴", "complaint", 240, True, True),
        ("P1", "closed", online_piles[7], "急停按钮误触发，已复位并测试", "device", 360, True, True),
    ]
    tickets: list[Ticket] = []
    for idx, (priority, status, pile, title, source, hours_ago, heartbeat, verified) in enumerate(ticket_specs):
        created = now - timedelta(hours=hours_ago)
        ticket = Ticket(
            tenant_id=tenant.id,
            ticket_no=f"WO{created:%Y%m%d}{idx + 1:03d}",
            community_id=pile.community_id,
            pile_id=pile.id,
            title=title,
            description=f"{pile.name}：{title}。请按标准作业流程处理并回填结果。",
            priority=priority,
            status=status,
            source=source,
            reporter_id=ops.id if source != "device" else None,
            sla_due_at=created + timedelta(hours=SLA_HOURS[priority]),
            created_at=created,
        )
        if status in {"assigned", "accepted", "processing", "pending_verification", "closed"}:
            ticket.assignee_id = tech.id
        if status in {"accepted", "processing", "pending_verification", "closed"}:
            ticket.accepted_at = created + timedelta(minutes=18)
        if status in {"processing", "pending_verification", "closed"}:
            ticket.started_at = created + timedelta(minutes=35)
        if status == "pending_verification":
            ticket.resolution = "已更换通讯模块并完成上电自检，申请验收。"
            ticket.resolved_at = created + timedelta(hours=2)
            ticket.heartbeat_checked = heartbeat
            ticket.test_order_verified = verified
        if status == "closed":
            ticket.resolution = "故障已排除，设备心跳正常，测试订单充电 8 分钟无异常。"
            ticket.resolved_at = created + timedelta(hours=2)
            ticket.heartbeat_checked = heartbeat
            ticket.test_order_verified = verified
            ticket.test_order_id = orders[idx].id if idx < len(orders) else None
            ticket.closed_at = created + timedelta(hours=3)
            ticket.escalation_count = 0
        db.add(ticket)
        tickets.append(ticket)
    db.flush()

    # ===== 审批 =====
    refund_order = next(o for o in orders if o.status == "completed" and o.amount > 40)
    connector_for_price = connectors_by_pile[online_piles[0].id][0]
    approval_specs = [
        {
            "type": "stop_pile",
            "status": "pending",
            "target_type": "pile",
            "target_id": str(fault_pile.id),
            "target_name": fault_pile.name,
            "impact_scope": "影响 2 个枪口，预计 25 位居民",
            "reason": "充电模块温度持续超过 75℃，存在安全风险，申请临时停机检修。",
            "payload": {"pile_id": fault_pile.id, "action": "maintenance"},
            "amount": 0,
            "source": "agent",
        },
        {
            "type": "refund",
            "status": "pending",
            "target_type": "order",
            "target_id": refund_order.order_no,
            "target_name": refund_order.order_no,
            "impact_scope": f"订单 {refund_order.order_no}，用户 {refund_order.user.display_name}",
            "reason": "充电中断导致电量不足，申请按比例退款。",
            "payload": {
                "order_id": refund_order.id,
                "order_no": refund_order.order_no,
                "amount": round(refund_order.amount * 0.5, 2),
            },
            "amount": round(refund_order.amount * 0.5, 2),
            "source": "agent",
        },
        {
            "type": "price_change",
            "status": "approved",
            "target_type": "connector",
            "target_id": str(connector_for_price.id),
            "target_name": f"{online_piles[0].code} / {connector_for_price.code} 号枪口",
            "impact_scope": "该枪口后续所有订单",
            "reason": "峰谷电价调整，拟将服务费下调 0.05 元/度。",
            "payload": {
                "connector_id": connector_for_price.id,
                "price_per_kwh": connector_for_price.price_per_kwh,
                "service_fee": max(0.1, connector_for_price.service_fee - 0.05),
            },
            "amount": 0,
            "source": "manual",
        },
        {
            "type": "stop_pile",
            "status": "executed",
            "target_type": "pile",
            "target_id": str(next(p for p in piles if p.status == "maintenance").id),
            "target_name": next(p for p in piles if p.status == "maintenance").name,
            "impact_scope": "影响 2 个枪口，已提前公告",
            "reason": "年度预防性维护。",
            "payload": {"pile_id": next(p for p in piles if p.status == "maintenance").id, "action": "maintenance"},
            "amount": 0,
            "source": "manual",
        },
    ]
    def _approval_community(spec: dict) -> int:
        payload = spec["payload"]
        if spec["type"] == "stop_pile":
            pile = db.get(Pile, int(payload["pile_id"]))
            return pile.community_id if pile else communities[0].id
        if spec["type"] == "refund":
            order = (
                db.query(Order)
                .filter(Order.tenant_id == tenant.id, Order.order_no == spec["target_id"])
                .first()
            )
            return order.community_id if order else communities[0].id
        if spec["type"] == "price_change":
            connector = db.get(Connector, int(payload["connector_id"]))
            return connector.pile.community_id if connector else communities[0].id
        return communities[0].id

    for idx, spec in enumerate(approval_specs):
        created = now - timedelta(hours=(2, 5, 30, 96)[idx])
        approval = Approval(
            tenant_id=tenant.id,
            approval_no=gen_approval_no(created),
            type=spec["type"],
            risk_level="high",
            status=spec["status"],
            community_id=_approval_community(spec),
            requester_id=ops.id,
            target_type=spec["target_type"],
            target_id=spec["target_id"],
            target_name=spec["target_name"],
            amount=spec["amount"],
            impact_scope=spec["impact_scope"],
            reason=spec["reason"],
            payload=spec["payload"],
            source=spec["source"],
            created_at=created,
        )
        if spec["status"] in {"approved", "executed"}:
            approval.approver_id = users["finance"].id
            approval.decided_at = created + timedelta(hours=1)
            approval.decision_comment = "影响范围与金额已核实，同意执行。"
        if spec["status"] == "executed":
            approval.executed_at = created + timedelta(hours=2)
            approval.execution_result = {
                "result": "success",
                "message": "设备已进入维护状态，枪口已下线。",
                "executed_by": users["finance"].display_name,
            }
        db.add(approval)
    db.flush()

    # ===== 设备事件 =====
    event_seq = 0
    for pile in piles:
        event_seq += 1
        db.add(
            DeviceEvent(
                tenant_id=tenant.id,
                event_no=f"EVT-{event_seq:06d}",
                pile_id=pile.id,
                connector_id=connectors_by_pile[pile.id][0].id,
                event_type="heartbeat",
                severity="info",
                payload={"online": pile.online, "signal": pile.signal_strength},
                occurred_at=pile.last_heartbeat_at or now,
                processed_at=now,
            )
        )
    fault_ticket = tickets[0]
    for idx in range(6):
        event_seq += 1
        db.add(
            DeviceEvent(
                tenant_id=tenant.id,
                event_no=f"EVT-{event_seq:06d}",
                pile_id=fault_pile.id,
                connector_id=connectors_by_pile[fault_pile.id][0].id,
                event_type=["temperature", "fault", "power", "fault", "offline", "recovered"][idx],
                severity=["warning", "critical", "info", "critical", "critical", "info"][idx],
                payload={
                    "temperature_c": 72 + idx * 2,
                    "threshold_c": 75,
                    "fault_code": "E-OVERHEAT",
                    "message": "充电模块温度过高，已自动降功率",
                },
                occurred_at=now - timedelta(minutes=180 - idx * 22),
                processed_at=now,
                ticket_id=fault_ticket.id,
            )
        )
    for idx in range(40):
        event_seq += 1
        pile = rng.choice(piles)
        db.add(
            DeviceEvent(
                tenant_id=tenant.id,
                event_no=f"EVT-{event_seq:06d}",
                pile_id=pile.id,
                connector_id=connectors_by_pile[pile.id][0].id,
                event_type=rng.choice(["power", "current", "heartbeat", "temperature"]),
                severity="info",
                payload={
                    "power_kw": round(rng.uniform(0, pile.rated_power_kw), 1),
                    "current_a": round(rng.uniform(0, 32), 1),
                    "temperature_c": round(rng.uniform(26, 46), 1),
                },
                occurred_at=now - timedelta(minutes=rng.randint(5, 60 * 24 * 5)),
                processed_at=now,
            )
        )

    # ===== 审计 =====
    audit_specs = [
        ("login", "auth", "admin", "管理员登录成功"),
        ("device_event.received", "device_event", "EVT-000001", "接收到设备心跳事件"),
        ("order.created", "order", orders[0].order_no, "用户创建充电订单"),
        ("ticket.assigned", "ticket", tickets[2].ticket_no, "工单已分派给维修人员"),
        ("approval.created", "approval", "AP-DEMO", "Agent 创建高风险停机审批"),
        ("approval.approved", "approval", "AP-DEMO", "财务审批通过"),
    ]
    for idx, (action, rtype, rid, detail) in enumerate(audit_specs):
        db.add(
            AuditLog(
                tenant_id=tenant.id,
                trace_id=f"tr_seed_{idx:04d}",
                actor_id=users["admin"].id,
                actor_name=users["admin"].display_name,
                actor_role="admin",
                action=action,
                resource_type=rtype,
                resource_id=rid,
                detail={"message": detail},
                ip="127.0.0.1",
                result="success",
                created_at=now - timedelta(hours=idx * 7 + 1),
            )
        )

    # ===== 第二个租户，用于隔离测试 =====
    other_tenant = Tenant(code="OTHER", name="对比运营方", status="active")
    db.add(other_tenant)
    db.flush()
    other_community = Community(
        tenant_id=other_tenant.id,
        code="OT",
        name="对比社区",
        city="杭州市",
        address="对比路 1 号",
    )
    db.add(other_community)
    db.flush()
    other_user = User(
        tenant_id=other_tenant.id,
        username="otheradmin",
        password_hash=password_hash,
        display_name="对比管理员",
        role="admin",
        phone="13900000000",
        status="active",
    )
    db.add(other_user)
    db.flush()
    other_user.communities = [other_community]
    other_pile = Pile(
        tenant_id=other_tenant.id,
        community_id=other_community.id,
        code="OT-A-01",
        name="对比社区 1 号桩",
        rated_power_kw=7,
        status="online",
        online=True,
        last_heartbeat_at=now,
    )
    db.add(other_pile)
    db.flush()
    db.add(
        Connector(
            tenant_id=other_tenant.id,
            pile_id=other_pile.id,
            code="01",
            gun_type="GBT_AC",
            status="idle",
            power_kw=7,
            price_per_kwh=1.0,
            service_fee=0.3,
        )
    )

    db.commit()
    return True
