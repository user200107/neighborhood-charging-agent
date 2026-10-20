"""SQLAlchemy ORM 模型。

所有业务表均带 tenant_id，服务端查询强制附加租户与社区范围条件。
金额使用 Float 保存（演示/运营精度到分），生产可平滑切换 Numeric(12, 2)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.utils import utcnow


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


user_communities = Table(
    "user_communities",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("community_id", ForeignKey("communities.id", ondelete="CASCADE"), primary_key=True),
)


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    contact_name: Mapped[Optional[str]] = mapped_column(String(60))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(30))


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "username", name="uq_user_tenant_username"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    username: Mapped[str] = mapped_column(String(60), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(60), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(30))
    email: Mapped[Optional[str]] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    tenant: Mapped[Tenant] = relationship()
    communities: Mapped[List["Community"]] = relationship(
        secondary=user_communities, back_populates="members", lazy="selectin"
    )


class Community(Base, TimestampMixin):
    __tablename__ = "communities"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_community_tenant_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    city: Mapped[str] = mapped_column(String(60), default="杭州", nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    contact_name: Mapped[Optional[str]] = mapped_column(String(60))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(30))

    members: Mapped[List[User]] = relationship(
        secondary=user_communities, back_populates="communities"
    )
    zones: Mapped[List["Zone"]] = relationship(
        back_populates="community", cascade="all, delete-orphan", lazy="selectin"
    )
    piles: Mapped[List["Pile"]] = relationship(back_populates="community", lazy="selectin")


class Zone(Base, TimestampMixin):
    __tablename__ = "zones"
    __table_args__ = (UniqueConstraint("community_id", "code", name="uq_zone_community_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    community_id: Mapped[int] = mapped_column(
        ForeignKey("communities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))

    community: Mapped[Community] = relationship(back_populates="zones")


class Pile(Base, TimestampMixin):
    __tablename__ = "piles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_pile_tenant_code"),
        Index("ix_pile_scope", "tenant_id", "community_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    community_id: Mapped[int] = mapped_column(
        ForeignKey("communities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    zone_id: Mapped[Optional[int]] = mapped_column(ForeignKey("zones.id", ondelete="SET NULL"))
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(60), default="AC-7kW", nullable=False)
    vendor: Mapped[str] = mapped_column(String(60), default="邻里能源", nullable=False)
    rated_power_kw: Mapped[float] = mapped_column(Float, default=7.0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="online", nullable=False)
    online: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    current_power_kw: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    temperature_c: Mapped[float] = mapped_column(Float, default=26.0, nullable=False)
    signal_strength: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    firmware: Mapped[str] = mapped_column(String(30), default="v2.3.1", nullable=False)
    installed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    notes: Mapped[Optional[str]] = mapped_column(String(255))

    community: Mapped[Community] = relationship(back_populates="piles")
    zone: Mapped[Optional[Zone]] = relationship()
    connectors: Mapped[List["Connector"]] = relationship(
        back_populates="pile", cascade="all, delete-orphan", lazy="selectin"
    )


class Connector(Base, TimestampMixin):
    __tablename__ = "connectors"
    __table_args__ = (UniqueConstraint("pile_id", "code", name="uq_connector_pile_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    pile_id: Mapped[int] = mapped_column(
        ForeignKey("piles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    gun_type: Mapped[str] = mapped_column(String(20), default="GBT_AC", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="idle", nullable=False)
    power_kw: Mapped[float] = mapped_column(Float, default=7.0, nullable=False)
    price_per_kwh: Mapped[float] = mapped_column(Float, default=1.05, nullable=False)
    service_fee: Mapped[float] = mapped_column(Float, default=0.35, nullable=False)
    total_energy_kwh: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    pile: Mapped[Pile] = relationship(back_populates="connectors")


class Reservation(Base, TimestampMixin):
    __tablename__ = "reservations"
    __table_args__ = (Index("ix_reservation_conflict", "connector_id", "status", "starts_at", "ends_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    connector_id: Mapped[int] = mapped_column(ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String(255))

    connector: Mapped[Connector] = relationship()
    user: Mapped[User] = relationship()
    community: Mapped[Community] = relationship()


class Order(Base, TimestampMixin):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "order_no", name="uq_order_tenant_no"),
        Index("ix_order_scope", "tenant_id", "community_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    order_no: Mapped[str] = mapped_column(String(40), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id", ondelete="RESTRICT"), nullable=False, index=True)
    pile_id: Mapped[int] = mapped_column(ForeignKey("piles.id", ondelete="RESTRICT"), nullable=False, index=True)
    connector_id: Mapped[int] = mapped_column(ForeignKey("connectors.id", ondelete="RESTRICT"), nullable=False, index=True)
    reservation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("reservations.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(24), default="reserved", nullable=False, index=True)
    starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    energy_kwh: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    service_fee: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    refund_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(20), default="wechat", nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    cancel_reason: Mapped[Optional[str]] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(20), default="web", nullable=False)

    user: Mapped[User] = relationship()
    community: Mapped[Community] = relationship()
    pile: Mapped[Pile] = relationship()
    connector: Mapped[Connector] = relationship()
    reservation: Mapped[Optional[Reservation]] = relationship()


class DeviceEvent(Base, TimestampMixin):
    __tablename__ = "device_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_no", name="uq_event_tenant_no"),
        Index("ix_event_pile_time", "pile_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    event_no: Mapped[str] = mapped_column(String(80), nullable=False)
    pile_id: Mapped[int] = mapped_column(ForeignKey("piles.id", ondelete="CASCADE"), nullable=False, index=True)
    connector_id: Mapped[Optional[int]] = mapped_column(ForeignKey("connectors.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), default="info", nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    ticket_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tickets.id", ondelete="SET NULL"))

    pile: Mapped[Pile] = relationship()
    ticket: Mapped[Optional["Ticket"]] = relationship()


class Ticket(Base, TimestampMixin):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "ticket_no", name="uq_ticket_tenant_no"),
        Index("ix_ticket_scope", "tenant_id", "community_id", "status", "priority"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    ticket_no: Mapped[str] = mapped_column(String(40), nullable=False)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id", ondelete="CASCADE"), nullable=False, index=True)
    pile_id: Mapped[Optional[int]] = mapped_column(ForeignKey("piles.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(4), default="P3", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    reporter_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assignee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    resolution: Mapped[Optional[str]] = mapped_column(Text)
    heartbeat_checked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    test_order_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    test_order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    sla_due_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    escalation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    community: Mapped[Community] = relationship()
    pile: Mapped[Optional[Pile]] = relationship()
    reporter: Mapped[Optional[User]] = relationship(foreign_keys=[reporter_id])
    assignee: Mapped[Optional[User]] = relationship(foreign_keys=[assignee_id])


class Approval(Base, TimestampMixin):
    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "approval_no", name="uq_approval_tenant_no"),
        Index("ix_approval_scope", "tenant_id", "status", "risk_level"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    approval_no: Mapped[str] = mapped_column(String(40), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(20), default="high", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    community_id: Mapped[Optional[int]] = mapped_column(ForeignKey("communities.id", ondelete="SET NULL"))
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    approver_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    target_type: Mapped[str] = mapped_column(String(30), default="pile", nullable=False)
    target_id: Mapped[str] = mapped_column(String(60), nullable=False)
    target_name: Mapped[Optional[str]] = mapped_column(String(160))
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    impact_scope: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    decision_comment: Mapped[Optional[str]] = mapped_column(String(255))
    execution_result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(20), default="agent", nullable=False)
    trace_id: Mapped[Optional[str]] = mapped_column(String(40), index=True)

    requester: Mapped[User] = relationship(foreign_keys=[requester_id])
    approver: Mapped[Optional[User]] = relationship(foreign_keys=[approver_id])
    community: Mapped[Optional[Community]] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_scope", "tenant_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_name: Mapped[str] = mapped_column(String(60), default="system", nullable=False)
    actor_role: Mapped[str] = mapped_column(String(20), default="system", nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    resource_id: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    ip: Mapped[Optional[str]] = mapped_column(String(60))
    result: Mapped[str] = mapped_column(String(20), default="success", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(60), default="default", nullable=False, index=True)
    input: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), default="read", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="completed", nullable=False)
    answer: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    approval_id: Mapped[Optional[int]] = mapped_column(ForeignKey("approvals.id", ondelete="SET NULL"))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


class AgentMemory(Base, TimestampMixin):
    __tablename__ = "agent_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), default="short", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "endpoint", "key", name="uq_idempotency_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(120), nullable=False)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
