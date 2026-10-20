"""演示模式心跳模拟。

生产环境由真实设备网关上报心跳；演示模式用后台线程保持在线设备心跳新鲜，
避免长时间打开页面后「待验收」因心跳过期而无法通过。
"""

from __future__ import annotations

import logging
import threading

from app.db import SessionLocal
from app.models import Pile
from app.utils import utcnow

logger = logging.getLogger("charging.simulator")


class DemoHeartbeatSimulator:
    def __init__(self, interval_seconds: int = 45) -> None:
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="demo-heartbeat", daemon=True)
        self._thread.start()
        logger.info("demo heartbeat simulator started (interval=%ss)", self.interval_seconds)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                now = utcnow()
                with SessionLocal() as db:
                    piles = (
                        db.query(Pile)
                        .filter(Pile.online.is_(True), Pile.status.in_(["online", "fault"]))
                        .all()
                    )
                    for pile in piles:
                        pile.last_heartbeat_at = now
                    db.commit()
            except Exception:  # noqa: BLE001
                logger.exception("demo heartbeat update failed")


simulator = DemoHeartbeatSimulator()
