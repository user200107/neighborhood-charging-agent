"""写接口幂等辅助。

同一租户/用户/接口/Key 的重复请求返回首次结果；相同 Key 不同请求体返回 409。
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.errors import conflict
from app.models import IdempotencyRecord, User
from app.utils import utcnow

TTL_HOURS = 24


def fingerprint(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def lookup(
    db: Session,
    user: User,
    endpoint: str,
    key: Optional[str],
    payload: Any,
) -> Optional[IdempotencyRecord]:
    if not key:
        return None
    key = key.strip()[:120]
    record = (
        db.query(IdempotencyRecord)
        .filter(
            IdempotencyRecord.tenant_id == user.tenant_id,
            IdempotencyRecord.user_id == user.id,
            IdempotencyRecord.endpoint == endpoint,
            IdempotencyRecord.key == key,
        )
        .first()
    )
    if not record:
        return None
    if record.expires_at and record.expires_at < utcnow():
        db.delete(record)
        db.flush()
        return None
    if record.request_hash != fingerprint(payload):
        raise conflict("该 Idempotency-Key 已用于不同的请求内容", "IDEMPOTENCY_KEY_REUSED")
    return record


def store(
    db: Session,
    user: User,
    endpoint: str,
    key: Optional[str],
    payload: Any,
    response: dict[str, Any],
    status_code: int = 200,
) -> None:
    if not key:
        return
    key = key.strip()[:120]
    db.add(
        IdempotencyRecord(
            tenant_id=user.tenant_id,
            user_id=user.id,
            endpoint=endpoint,
            key=key,
            request_hash=fingerprint(payload),
            status_code=status_code,
            response=response,
            expires_at=utcnow() + timedelta(hours=TTL_HOURS),
        )
    )
    try:
        db.flush()
    except Exception:  # noqa: BLE001 唯一键竞争时由事务回滚，调用方按首次结果处理
        db.rollback()
        raise
