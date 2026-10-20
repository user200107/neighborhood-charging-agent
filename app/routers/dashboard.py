"""运营总览接口。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import User
from app.services.metrics import dashboard

router = APIRouter(prefix="/api/dashboard", tags=["运营总览"])


@router.get("", summary="运营指标总览")
def get_dashboard(
    days: int = Query(default=7, ge=1, le=90),
    community_id: Optional[int] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return dashboard(db, user, days=days, community_id=community_id)
