from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .config import Settings
from .models import JobStatus, ProcessingJob, ProcessingQuota, SyllabusDocument

ACTIVE_JOB_STATUSES = (
    JobStatus.QUEUED, JobStatus.EXTRACTING_TEXT, JobStatus.RUNNING_OCR,
    JobStatus.EXTRACTING_EVENTS, JobStatus.VALIDATING,
)


def lock_admission(db: Session) -> None:
    """Serialize admission across API processes until their transaction commits.

    The permanent row also serializes requests straddling a UTC day boundary.
    Unlike process locks this works across API replicas and survives restarts.
    """
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
    db.execute(insert(ProcessingQuota).values(key="admission", value=0).on_conflict_do_nothing())
    db.execute(update(ProcessingQuota).where(ProcessingQuota.key == "admission").values(value=0))


def reserve_processing(
    db: Session, user_id: UUID, settings: Settings, *, jobs: int, storage_bytes: int = 0,
) -> None:
    """Caller must hold lock_admission and commit reservations with the job writes."""
    today = datetime.now(UTC).date().isoformat()
    for key, maximum in (
        (f"global:{today}", settings.max_global_jobs_per_day),
        (f"user:{user_id}:{today}", settings.max_user_jobs_per_day),
    ):
        counter = db.get(ProcessingQuota, key)
        used = counter.value if counter else 0
        if used + jobs > maximum:
            raise HTTPException(429, "Daily processing limit reached. Try again tomorrow.")
        if counter is None:
            db.add(ProcessingQuota(key=key, value=jobs))
        else:
            counter.value += jobs

    for owner, active_limit, storage_limit in (
        (None, settings.max_global_active_jobs, settings.max_global_storage_bytes),
        (user_id, settings.max_user_active_jobs, settings.max_user_storage_bytes),
    ):
        active_query = select(func.count()).select_from(ProcessingJob).where(
            ProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
        )
        storage_query = select(func.coalesce(func.sum(SyllabusDocument.size_bytes), 0))
        if owner is not None:
            active_query = active_query.where(ProcessingJob.user_id == owner)
            storage_query = storage_query.where(SyllabusDocument.user_id == owner)
        if db.scalar(active_query) + jobs > active_limit:
            raise HTTPException(429, "Processing queue limit reached. Wait for current jobs.")
        if storage_bytes and db.scalar(storage_query) + storage_bytes > storage_limit:
            raise HTTPException(429, "Upload storage limit reached. Remove an old semester first.")
