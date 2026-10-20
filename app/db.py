"""数据库连接与会话管理。

开发默认 SQLite；生产通过 DATABASE_URL 切换 PostgreSQL / MySQL。
演示模式下若配置的数据库暂不可达，可回退到 SQLite，避免本地演示无法启动。
"""

from __future__ import annotations

import logging
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import DATA_DIR, settings

logger = logging.getLogger("charging.db")


def _build_engine(url: str) -> Engine:
    is_sqlite = url.startswith("sqlite")
    connect_args = {}
    if is_sqlite:
        connect_args = {"check_same_thread": False, "timeout": 30}
    elif url.startswith("postgresql"):
        connect_args = {"connect_timeout": 3}
    elif url.startswith("mysql"):
        connect_args = {"connect_timeout": 3}
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True, future=True)


def _probe(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def _resolve_engine() -> tuple[Engine, bool]:
    configured = settings.effective_database_url
    engine = _build_engine(configured)
    if configured.startswith("sqlite"):
        return engine, True

    try:
        _probe(engine)
        logger.info("database connected: %s", engine.url.get_backend_name())
        return engine, False
    except Exception as exc:  # noqa: BLE001
        engine.dispose()
        if settings.demo_mode and settings.allow_sqlite_fallback:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            fallback_url = f"sqlite:///{(DATA_DIR / 'charging.db').as_posix()}"
            logger.warning(
                "configured database is unreachable (%s); demo fallback to SQLite. "
                "Start MySQL/PostgreSQL or set ALLOW_SQLITE_FALLBACK=false.",
                type(exc).__name__,
            )
            return _build_engine(fallback_url), True
        raise RuntimeError(
            "数据库不可用，请检查 DATABASE_URL / POSTGRES_URL / MYSQL_URL，"
            "或启动 docker compose up -d"
        ) from exc


engine, _is_sqlite = _resolve_engine()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """创建表结构。生产环境应使用迁移工具，此处用于本地/演示启动。"""
    from app import models  # noqa: F401  确保模型注册

    from app.models import Base

    Base.metadata.create_all(bind=engine)


def drop_all() -> None:
    from app import models  # noqa: F401

    from app.models import Base

    Base.metadata.drop_all(bind=engine)


def ping_db() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        logger.exception("database ping failed")
        return False


def database_label() -> str:
    """隐藏凭据后返回数据库类型，供健康检查使用。"""
    return engine.url.get_backend_name()
