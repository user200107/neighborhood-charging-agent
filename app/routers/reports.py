"""报表与导出接口。"""

from __future__ import annotations

import csv
import io
from collections import Counter
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from app.auth import ensure_community_access, require_roles
from app.db import get_db
from app.models import Order, User
from app.services.metrics import dashboard, scoped_community_ids
from app.utils import csv_safe, date_range, utcnow

router = APIRouter(prefix="/api/reports", tags=["报表"])


@router.get("/overview", summary="运营报表")
def report_overview(
    days: int = Query(default=30, ge=1, le=90),
    community_id: Optional[int] = None,
    user: User = Depends(require_roles("operator", "finance")),
    db: Session = Depends(get_db),
) -> dict:
    data = dashboard(db, user, days=days, community_id=community_id)
    community_ids = scoped_community_ids(db, user, community_id)
    start, end = date_range(days)
    orders = (
        db.query(Order)
        .filter(
            Order.tenant_id == user.tenant_id,
            Order.community_id.in_(community_ids),
            Order.created_at >= start,
            Order.created_at <= end,
        )
        .all()
    )
    status_counter = Counter(order.status for order in orders)
    payment_counter = Counter(
        order.payment_method for order in orders if order.status == "completed"
    )
    return {
        "summary": data["summary"],
        "trend": data["trend"],
        "communities": data["communities"],
        "order_status": [{"key": key, "value": value} for key, value in status_counter.most_common()],
        "payment_methods": [{"key": key, "value": value} for key, value in payment_counter.most_common()],
        "updated_at": data["updated_at"],
    }


@router.get("/trend", summary="运营趋势")
def report_trend(
    days: int = Query(default=30, ge=1, le=90),
    community_id: Optional[int] = None,
    user: User = Depends(require_roles("operator", "finance")),
    db: Session = Depends(get_db),
) -> dict:
    data = dashboard(db, user, days=days, community_id=community_id)
    return {"trend": data["trend"], "days": days, "updated_at": data["updated_at"]}


@router.get("/communities", summary="社区对比")
def report_communities(
    days: int = Query(default=30, ge=1, le=90),
    user: User = Depends(require_roles("operator", "finance")),
    db: Session = Depends(get_db),
) -> dict:
    data = dashboard(db, user, days=days)
    return {"items": data["communities"], "updated_at": data["updated_at"]}


@router.get("/orders.csv", summary="导出订单 CSV")
def export_orders(
    days: int = Query(default=30, ge=1, le=90),
    community_id: Optional[int] = None,
    user: User = Depends(require_roles("operator", "finance")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    if community_id is not None:
        ensure_community_access(user, community_id)
    community_ids = scoped_community_ids(db, user, community_id)
    start, end = date_range(days)
    query = (
        db.query(Order)
        .options(joinedload(Order.community), joinedload(Order.pile), joinedload(Order.connector), joinedload(Order.user))
        .filter(
            Order.tenant_id == user.tenant_id,
            Order.community_id.in_(community_ids),
            Order.created_at >= start,
            Order.created_at <= end,
        )
        .order_by(Order.created_at.desc())
        .limit(5000)
    )
    if user.role == "resident":
        query = query.filter(Order.user_id == user.id)
    orders = query.all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["订单号", "社区", "设备", "枪口", "用户", "状态", "开始时间", "结束时间", "电量(kWh)", "金额(元)", "退款(元)"]
    )
    for order in orders:
        writer.writerow(
            [
                csv_safe(order.order_no),
                csv_safe(order.community.name if order.community else ""),
                csv_safe(order.pile.code if order.pile else ""),
                csv_safe(order.connector.code if order.connector else ""),
                csv_safe(order.user.display_name if order.user else ""),
                csv_safe(order.status),
                order.starts_at.isoformat(sep=" ") if order.starts_at else "",
                order.ended_at.isoformat(sep=" ") if order.ended_at else "",
                f"{order.energy_kwh:.2f}",
                f"{order.amount:.2f}",
                f"{order.refund_amount:.2f}",
            ]
        )
    content = "\ufeff" + buffer.getvalue()
    filename = f"orders-{utcnow():%Y%m%d-%H%M}.csv"
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
