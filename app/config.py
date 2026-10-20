"""应用配置。

配置来源优先级：环境变量 > .env > 默认值。
生产环境应通过部署平台注入密钥，禁止提交 .env。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def _normalize_database_url(url: str) -> str:
    """兼容云平台常见的 postgres:// 连接串，并显式使用 psycopg3 驱动。"""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("mysql://"):
        return "mysql+pymysql://" + url[len("mysql://") :]
    return url


class Settings(BaseSettings):
    app_name: str = "邻里充电 · 运营平台"
    app_env: str = "development"
    debug: bool = True

    # 业务库；为空时使用项目内 SQLite，便于本地零依赖启动
    database_url: str = ""
    # 文档中约定的两个数据库，可按需分别注入；未提供时复用 database_url
    mysql_url: str = ""
    postgres_url: str = ""
    identity_database_url: str = ""
    business_database_url: str = ""

    jwt_secret: str = "dev-only-neighborhood-charging-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 480
    refresh_token_days: int = 7

    device_api_key: str = ""

    demo_mode: bool = True
    seed_demo_data: bool = True
    # 演示环境数据库不可达时回退 SQLite；生产务必设为 false
    allow_sqlite_fallback: bool = True

    cors_origins: str = "*"

    llm_model: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""

    agent_timeout_ms: int = 8000
    login_max_attempts: int = 5
    login_window_seconds: int = 300

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @property
    def effective_database_url(self) -> str:
        """返回实际使用的数据库连接串。

        依次尝试显式业务库、PostgreSQL、MySQL，最后回退到 SQLite。
        """
        for url in (
            self.business_database_url,
            self.database_url,
            self.postgres_url,
            self.mysql_url,
            self.identity_database_url,
        ):
            if url and url.strip():
                return _normalize_database_url(url.strip())

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{(DATA_DIR / 'charging.db').as_posix()}"

    @property
    def cors_origin_list(self) -> List[str]:
        raw = os.getenv("CORS_ORIGINS", self.cors_origins)
        if not raw or raw.strip() == "*":
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key and self.llm_model)

    @property
    def llm_endpoint(self) -> str:
        base = (self.llm_base_url or "https://api.openai.com/v1").rstrip("/")
        return f"{base}/chat/completions"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
