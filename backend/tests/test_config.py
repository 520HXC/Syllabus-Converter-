from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "auth_mode": "supabase",
        "processing_mode": "celery",
        "extraction_mode": "local",
        "cors_origins": "https://calendar.example.com",
        "supabase_url": "https://example.supabase.co",
        "supabase_service_role_key": "service-role",
        "storage_mode": "supabase",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_rejects_development_authentication() -> None:
    with pytest.raises(ValidationError, match="AUTH_MODE=dev"):
        production_settings(auth_mode="dev")


def test_authentication_defaults_to_supabase_and_fails_closed_without_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="SUPABASE_URL"):
        Settings(_env_file=None, app_env="development", supabase_url=None)


def test_development_authentication_is_rejected_outside_local_or_test_environments() -> None:
    with pytest.raises(ValidationError, match="development or test"):
        Settings(_env_file=None, app_env="staging", auth_mode="dev")


@pytest.mark.parametrize("app_env", ["development", "test"])
def test_development_authentication_requires_an_explicit_local_environment(
    app_env: str,
) -> None:
    settings = Settings(_env_file=None, app_env=app_env, auth_mode="dev")

    assert settings.auth_mode == "dev"


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("supabase_url", "SUPABASE_URL"),
        ("supabase_service_role_key", "SUPABASE_SERVICE_ROLE_KEY"),
    ],
)
def test_production_requires_backend_supabase_credentials(field: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        production_settings(**{field: None})


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="wildcard CORS"):
        production_settings(cors_origins="*")


def test_openai_extraction_requires_api_key() -> None:
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings(_env_file=None, extraction_mode="openai", openai_api_key=None)
