from __future__ import annotations

import os
from pathlib import Path

import pytest

# 必须在导入 app 之前设置，确保使用独立测试库。
# 使用项目内固定目录，避免 Windows 沙箱对系统临时目录的访问限制。
_TEST_DIR = Path(__file__).resolve().parent.parent / ".tmp" / "pytest-db"
_TEST_DIR.mkdir(parents=True, exist_ok=True)
for old_db in _TEST_DIR.glob("test.db*"):
    old_db.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_DIR / 'test.db').as_posix()}"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["DEMO_MODE"] = "true"
os.environ["JWT_SECRET"] = "test-only-secret-for-neighbor-charging"
os.environ["APP_ENV"] = "test"
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_MODEL"] = ""
os.environ["ALLOW_SQLITE_FALLBACK"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, drop_all, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_demo_data  # noqa: E402


@pytest.fixture()
def client():
    # 每个用例使用全新的演示库，避免写操作互相污染
    drop_all()
    init_db()
    with SessionLocal() as db:
        seed_demo_data(db)
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient, username: str, password: str = "Demo@2026", tenant_code: str = "NEIGHBOR"):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password, "tenant_code": tenant_code},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def sessions(client: TestClient) -> dict[str, dict]:
    return {role: _login(client, role) for role in ("admin", "ops", "tech", "finance", "resident")}


def auth_header(session: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}
