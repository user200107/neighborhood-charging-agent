"""请求模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginRequest(StrictModel):
    username: str = Field(min_length=2, max_length=60)
    password: str = Field(min_length=6, max_length=128)
    tenant_code: Optional[str] = Field(default="NEIGHBOR", max_length=40)
    remember: bool = False


class RefreshRequest(StrictModel):
    refresh_token: str = Field(min_length=10, max_length=200)


class LogoutRequest(StrictModel):
    refresh_token: Optional[str] = Field(default=None, max_length=200)


class PasswordChangeRequest(StrictModel):
    old_password: str = Field(min_length=6, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class OrderCreateRequest(StrictModel):
    connector_id: int = Field(gt=0)
    mode: Literal["now", "reserved"] = "now"
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    payment_method: Literal["wechat", "alipay", "balance"] = "wechat"
    note: Optional[str] = Field(default=None, max_length=255)


class OrderCancelRequest(StrictModel):
    reason: str = Field(default="用户取消", min_length=2, max_length=255)


class OrderCompleteRequest(StrictModel):
    energy_kwh: Optional[float] = Field(default=None, ge=0, le=200)


class ReservationCreateRequest(StrictModel):
    connector_id: int = Field(gt=0)
    starts_at: datetime
    ends_at: datetime
    note: Optional[str] = Field(default=None, max_length=255)


class TicketCreateRequest(StrictModel):
    community_id: Optional[int] = Field(default=None, gt=0)
    pile_id: Optional[int] = Field(default=None, gt=0)
    title: str = Field(min_length=4, max_length=160)
    description: Optional[str] = Field(default="", max_length=2000)
    priority: Literal["P1", "P2", "P3"] = "P3"
    assignee_id: Optional[int] = Field(default=None, gt=0)


class TicketAssignRequest(StrictModel):
    assignee_id: int = Field(gt=0)


class TicketResolveRequest(StrictModel):
    resolution: str = Field(min_length=5, max_length=2000)


class TicketVerifyRequest(StrictModel):
    test_order_id: int = Field(gt=0)


class ApprovalCreateRequest(StrictModel):
    type: Literal["stop_pile", "refund", "price_change", "bulk_reassign"]
    target_id: str = Field(default="", max_length=120)
    reason: str = Field(min_length=4, max_length=2000)
    amount: float = Field(default=0, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecisionRequest(StrictModel):
    decision: Literal["approve", "reject"]
    comment: str = Field(default="", max_length=255)


class DeviceEventRequest(StrictModel):
    event_no: str = Field(min_length=4, max_length=80)
    pile_id: Optional[int] = Field(default=None, gt=0)
    pile_code: Optional[str] = Field(default=None, max_length=40)
    connector_id: Optional[int] = Field(default=None, gt=0)
    event_type: str = Field(min_length=3, max_length=30)
    severity: Literal["info", "warning", "critical", "fatal"] = "info"
    occurred_at: Optional[datetime] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    tenant_code: Optional[str] = Field(default=None, max_length=40)


class AgentChatRequest(StrictModel):
    message: str = Field(min_length=1, max_length=1000)
    session_id: Optional[str] = Field(default=None, max_length=64)
    community_id: Optional[int] = Field(default=None, gt=0)


class UserCreateRequest(StrictModel):
    username: str = Field(min_length=2, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=60)
    role: Literal["admin", "operator", "technician", "finance", "resident"]
    phone: Optional[str] = Field(default=None, max_length=30)
    email: Optional[str] = Field(default=None, max_length=120)
    community_ids: list[int] = Field(default_factory=list)


class UserUpdateRequest(StrictModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    role: Optional[Literal["admin", "operator", "technician", "finance", "resident"]] = None
    status: Optional[Literal["active", "disabled"]] = None
    phone: Optional[str] = Field(default=None, max_length=30)
    email: Optional[str] = Field(default=None, max_length=120)
    community_ids: Optional[list[int]] = None
