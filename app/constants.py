"""领域常量与状态机定义。"""

from __future__ import annotations

from typing import Dict, FrozenSet

ROLES = ("admin", "operator", "technician", "finance", "resident")

ROLE_LABELS: Dict[str, str] = {
    "admin": "系统管理员",
    "operator": "运营人员",
    "technician": "维修人员",
    "finance": "财务/审批",
    "resident": "居民用户",
}

# 可访问运营工作台的角色
STAFF_ROLES = ("admin", "operator", "technician", "finance")

PILE_STATUSES = ("online", "offline", "fault", "maintenance")
CONNECTOR_STATUSES = ("idle", "charging", "reserved", "fault", "offline")
ORDER_STATUSES = (
    "pending_payment",
    "reserved",
    "charging",
    "completed",
    "cancelled",
    "abnormal",
)
TICKET_STATUSES = (
    "pending",
    "assigned",
    "accepted",
    "processing",
    "pending_verification",
    "closed",
    "cancelled",
)
APPROVAL_STATUSES = ("pending", "approved", "rejected", "executing", "executed", "failed")
PRIORITIES = ("P1", "P2", "P3")

# 订单状态机
ORDER_TRANSITIONS: Dict[str, FrozenSet[str]] = {
    "pending_payment": frozenset({"reserved", "cancelled", "abnormal"}),
    "reserved": frozenset({"charging", "cancelled", "abnormal"}),
    "charging": frozenset({"completed", "abnormal", "cancelled"}),
    "completed": frozenset({"abnormal"}),
    "cancelled": frozenset(),
    "abnormal": frozenset({"completed", "cancelled"}),
}

# 工单状态机
TICKET_TRANSITIONS: Dict[str, FrozenSet[str]] = {
    "pending": frozenset({"assigned", "cancelled"}),
    "assigned": frozenset({"accepted", "cancelled"}),
    "accepted": frozenset({"processing", "pending_verification", "cancelled"}),
    "processing": frozenset({"pending_verification", "cancelled"}),
    "pending_verification": frozenset({"closed", "processing"}),
    "closed": frozenset(),
    "cancelled": frozenset(),
}

# 高风险动作：只能创建审批，不得直接执行
HIGH_RISK_ACTIONS = frozenset({"stop_pile", "refund", "price_change", "bulk_reassign"})

APPROVAL_TYPE_LABELS = {
    "stop_pile": "设备停机",
    "refund": "订单退款",
    "price_change": "计费调价",
    "bulk_reassign": "批量改派",
}

RISK_LABELS = {
    "read": "只读",
    "normal_write": "普通写",
    "high_risk": "高风险",
    "high": "高风险",
    "medium": "中风险",
    "low": "低风险",
}

SLA_HOURS = {"P1": 1, "P2": 4, "P3": 24}

# 前端菜单权限：后端 /auth/me 返回，仅改善体验，服务端仍独立鉴权
MENU_PERMISSIONS: Dict[str, tuple] = {
    "dashboard": ("admin", "operator", "technician", "finance"),
    "devices": ("admin", "operator", "technician", "finance", "resident"),
    "orders": ("admin", "operator", "technician", "finance", "resident"),
    "tickets": ("admin", "operator", "technician", "finance", "resident"),
    "approvals": ("admin", "finance", "operator"),
    "agent": ("admin", "operator", "technician", "finance", "resident"),
    "reports": ("admin", "operator", "finance"),
    "audit": ("admin",),
}
