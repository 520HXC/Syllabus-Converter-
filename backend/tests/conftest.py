from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

USER_A = UUID("11111111-1111-4111-8111-111111111111")
USER_B = UUID("22222222-2222-4222-8222-222222222222")


@pytest.fixture()
def app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "test.db"
    uploads_path = tmp_path / "uploads"

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("PROCESSING_MODE", "manual")
    monkeypatch.setenv("EXTRACTION_MODE", "local")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(uploads_path))
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")

    from app.config import get_settings
    from app.database import reset_database
    from app.main import create_app

    get_settings.cache_clear()
    reset_database()
    app = create_app()

    with TestClient(app) as client:
        yield client, app

    reset_database()
    get_settings.cache_clear()


def auth_headers(user_id: UUID = USER_A) -> dict[str, str]:
    return {"Authorization": f"Bearer {user_id}"}
