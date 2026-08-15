from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_name: str = "Syllabus Calendar API"
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./syllabus_calendar.db"
    auth_mode: str = "supabase"
    processing_mode: str = "eager"
    extraction_mode: str = "local"
    cors_origins: str = "http://localhost:5173"

    supabase_url: str | None = None
    supabase_public_key: str | None = None
    supabase_service_role_key: str | None = None
    supabase_storage_bucket: str = "syllabi"
    storage_mode: str = "local"
    local_storage_path: Path = Path(".data/uploads")

    redis_url: str = "redis://localhost:6379/0"
    celery_task_always_eager: bool = False

    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6-luna"
    openai_fallback_model: str = "gpt-5.6-terra"

    max_upload_files: int = 10
    max_upload_bytes: int = 20 * 1024 * 1024
    max_pdf_pages: int = 200
    max_ocr_pages: int = 50
    max_extracted_text_characters: int = 500_000
    min_text_characters_per_page: int = 80
    tesseract_cmd: str | None = None
    pdf_poppler_path: str | None = None

    jwt_audience: str = "authenticated"
    jwt_algorithms: list[str] = Field(default_factory=lambda: ["ES256", "RS256"])

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_security_configuration(self):
        if self.extraction_mode == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when EXTRACTION_MODE=openai.")
        if self.auth_mode == "dev" and self.app_env not in {"development", "test"}:
            raise ValueError(
                "AUTH_MODE=dev is only allowed when APP_ENV is development or test."
            )
        if self.auth_mode == "supabase" and not self.supabase_url:
            raise ValueError("SUPABASE_URL is required when AUTH_MODE=supabase.")
        if self.app_env == "production":
            if self.auth_mode == "dev":
                raise ValueError("AUTH_MODE=dev is not allowed when APP_ENV=production.")
            if self.storage_mode != "supabase":
                raise ValueError("STORAGE_MODE=supabase is required when APP_ENV=production.")
            if not self.supabase_url:
                raise ValueError("SUPABASE_URL is required when APP_ENV=production.")
            if not self.supabase_service_role_key:
                raise ValueError(
                    "SUPABASE_SERVICE_ROLE_KEY is required when APP_ENV=production."
                )
            if "*" in self.cors_origin_list:
                raise ValueError("Production configuration cannot use wildcard CORS origins.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
