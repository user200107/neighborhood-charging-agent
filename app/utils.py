"""通用工具函数。"""

from __future__ import annotations

import math
import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

UTC = timezone.utc


def utcnow() -> datetime:
    """返回无时区 UTC 时间（数据库统一按 UTC-naive 存储）。"""
    return datetime.now(UTC).replace(tzinfo=None)


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def iso(value: Optional[datetime | date]) -> Optional[str]:
    """序列化为带 Z 的 ISO-8601，前端可稳定按 UTC 解析。"""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    dt = as_utc(value)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def new_trace_id() -> str:
    return "tr_" + uuid.uuid4().hex[:20]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def gen_order_no(now: Optional[datetime] = None) -> str:
    now = now or utcnow()
    return f"NO{now:%Y%m%d%H%M%S}{secrets.randbelow(9000) + 1000}"


def gen_ticket_no(now: Optional[datetime] = None) -> str:
    now = now or utcnow()
    return f"WO{now:%Y%m%d}{secrets.randbelow(9000) + 1000}"


def gen_approval_no(now: Optional[datetime] = None) -> str:
    now = now or utcnow()
    return f"AP{now:%Y%m%d%H%M%S}{secrets.randbelow(900) + 100}"


def mask_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return phone
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 7:
        return "***"
    return f"{digits[:3]}****{digits[-4:]}"


def mask_name(name: Optional[str]) -> str:
    if not name:
        return "匿名用户"
    if len(name) <= 1:
        return name + "*"
    if len(name) == 2:
        return name[0] + "*"
    return name[0] + "*" * (len(name) - 2) + name[-1]


def money(value: float | int | None) -> float:
    return round(float(value or 0), 2)


def ratio(numerator: float | int, denominator: float | int, digits: int = 1) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator) * 100, digits)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def parse_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo:
            parsed = parsed.astimezone(UTC).replace(tzinfo=None)
        return parsed
    return None


def date_range(days: int, end: Optional[datetime] = None) -> tuple[datetime, datetime]:
    end = end or utcnow()
    start = (end - timedelta(days=max(1, days))).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, end


def human_duration(seconds: float | int | None) -> str:
    if not seconds or seconds < 0:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} 秒"
    if seconds < 3600:
        return f"{seconds // 60} 分钟"
    if seconds < 86400:
        return f"{seconds // 3600} 小时 {seconds % 3600 // 60} 分"
    return f"{seconds // 86400} 天 {seconds % 86400 // 3600} 小时"


def percentile(values: Iterable[float], p: float) -> float:
    data = sorted(values)
    if not data:
        return 0.0
    k = (len(data) - 1) * p
    floor, ceil = math.floor(k), math.ceil(k)
    if floor == ceil:
        return data[int(k)]
    return data[floor] * (ceil - k) + data[ceil] * (k - floor)


def csv_safe(value: Any) -> str:
    text = str(value if value is not None else "")
    if text and text[0] in ("=", "+", "-", "@"):
        text = "'" + text
    return text


def paginate(items: list, total: int, page: int, page_size: int) -> dict:
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size)) if page_size else 1,
    }
