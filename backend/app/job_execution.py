from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, update
from sqlalchemy.orm import Session, sessionmaker

from .errors import public_error_message
from .models import JobStatus, ProcessingJob

ACTIVE_JOB_STATUSES = (
    JobStatus.EXTRACTING_TEXT,
    JobStatus.RUNNING_OCR,
    JobStatus.EXTRACTING_EVENTS,
    JobStatus.VALIDATING,
)


class StaleJobExecution(RuntimeError):
    """The attempt lost ownership and must discard all pending changes."""


def fence_job_execution(session: Session, job_id: UUID, execution_id: str) -> None:
    """Lock the active attempt before flushing any result or stage changes."""
    with session.no_autoflush:
        result = session.execute(
            update(ProcessingJob)
            .where(
                ProcessingJob.id == job_id,
                ProcessingJob.execution_id == execution_id,
                ProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
            )
            .values(updated_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
    if result.rowcount != 1:
        session.rollback()
        raise StaleJobExecution("Processing attempt no longer owns this job.")


def claim_job(session: Session, job_id: UUID, execution_id: str) -> bool:
    """One conditional write wins even across worker processes or API replicas."""
    result = session.execute(
        update(ProcessingJob)
        .where(
            ProcessingJob.id == job_id,
            ProcessingJob.status == JobStatus.QUEUED,
            or_(ProcessingJob.execution_id == execution_id, ProcessingJob.execution_id.is_(None)),
        )
        .values(
            status=JobStatus.EXTRACTING_TEXT,
            stage_detail="Reading text from the PDF",
            error_message=None,
            execution_id=execution_id,
            attempts=ProcessingJob.attempts + 1,
            updated_at=datetime.now(UTC),
        )
    )
    session.commit()
    return result.rowcount == 1


def fail_job_execution(
    session_factory: sessionmaker[Session],
    job_id: UUID,
    execution_id: str,
    error: BaseException | str,
) -> None:
    # A late timeout from an old task must not overwrite a new attempt or a
    # completed review. No document/course/event rows are modified on failure.
    with session_factory() as session:
        session.execute(
            update(ProcessingJob)
            .where(
                ProcessingJob.id == job_id,
                ProcessingJob.execution_id == execution_id,
                ProcessingJob.status.in_((JobStatus.QUEUED, *ACTIVE_JOB_STATUSES)),
            )
            .values(
                status=JobStatus.FAILED,
                stage_detail="Processing failed",
                error_message=public_error_message(error),
                updated_at=datetime.now(UTC),
            )
        )
        session.commit()
