from __future__ import annotations

from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, inspect, text

from alembic import command
from app.config import get_settings


def test_alembic_upgrade_and_downgrade_sqlite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    database_path = tmp_path / "migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    try:
        command.upgrade(config, "0003_recurring_model_audit")
        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        legacy_id, owner_id, semester_id, document_id = [uuid4().hex for _ in range(4)]
        now = datetime.now(UTC)
        try:
            metadata = MetaData()
            semesters = Table("semesters", metadata, autoload_with=engine)
            documents = Table("syllabus_documents", metadata, autoload_with=engine)
            jobs = Table("processing_jobs", metadata, autoload_with=engine)
            with engine.begin() as connection:
                connection.execute(semesters.insert().values(
                    id=semester_id, user_id=owner_id, name="Saved semester",
                    start_date=date(2026, 8, 24), end_date=date(2026, 12, 18),
                    timezone="America/New_York", created_at=now, updated_at=now,
                ))
                connection.execute(documents.insert().values(
                    id=document_id, user_id=owner_id, semester_id=semester_id,
                    filename="saved.pdf", content_type="application/pdf", size_bytes=12,
                    storage_key="saved.pdf", extracted_pages=[], used_ocr=False, created_at=now,
                ))
                connection.execute(jobs.insert().values(
                    id=legacy_id, user_id=owner_id, semester_id=semester_id,
                    document_id=document_id, status="NEEDS_REVIEW", attempts=3,
                    created_at=now, updated_at=now,
                ))
        finally:
            engine.dispose()

        command.upgrade(config, "head")
        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        try:
            inspector = inspect(engine)
            columns = {
                column["name"]: column for column in inspector.get_columns("processing_jobs")
            }
            assert columns["execution_id"]["nullable"] is True
            assert "processing_quotas" in inspector.get_table_names()
            with engine.begin() as connection:
                preserved = connection.execute(text(
                    "SELECT status, attempts, execution_id FROM processing_jobs WHERE id = :id"
                ), {"id": legacy_id}).one()
                assert tuple(preserved) == ("NEEDS_REVIEW", 3, None)
                connection.execute(text(
                    "INSERT INTO processing_quotas (key, value) VALUES ('admission', 0)"
                ))
                assert connection.scalar(text(
                    "SELECT value FROM processing_quotas WHERE key = 'admission'"
                )) == 0
        finally:
            engine.dispose()
        command.downgrade(config, "base")
    finally:
        get_settings.cache_clear()


def test_postgres_security_migration_closes_direct_metadata_access(monkeypatch):
    """Compile production SQL without connecting to a database."""
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("EXTRACTION_MODE", "local")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://unused@localhost/unused")
    get_settings.cache_clear()
    output = StringIO()
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(backend / "alembic"))
    try:
        command.upgrade(config, "0003_recurring_model_audit:head", sql=True)
        sql = output.getvalue()
        assert "ALTER TABLE processing_jobs ADD COLUMN execution_id VARCHAR(36)" in sql
        assert "CREATE TABLE processing_quotas" in sql
        assert "ALTER TABLE processing_quotas ENABLE ROW LEVEL SECURITY" in sql
        for table in ("semesters", "syllabus_documents", "processing_jobs", "processing_quotas"):
            assert f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC, anon, authenticated" in sql
            assert f"GRANT ALL ON TABLE public.{table} TO service_role" in sql
        # No schema-wide revocation breaks Auth/profile usage or the backend owner.
        assert "ON ALL TABLES" not in sql
        assert "FROM service_role" not in sql
        assert "FROM postgres" not in sql

        output.seek(0)
        output.truncate()
        command.downgrade(config, "head:0003_recurring_model_audit", sql=True)
        downgrade_sql = output.getvalue()
        assert "DROP TABLE processing_quotas" in downgrade_sql
        assert "DROP COLUMN execution_id" in downgrade_sql
        assert "GRANT" not in downgrade_sql
    finally:
        get_settings.cache_clear()
