from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from .auth import CurrentUser, get_current_user
from .config import Settings, get_settings
from .database import get_db
from .ical import build_calendar
from .models import (
    Course,
    ExtractedEvent,
    JobStatus,
    ProcessingJob,
    RecurringEventSeries,
    ReviewStatus,
    Semester,
    SyllabusDocument,
)
from .processing import SYLLABUS_TYPO_WARNING, process_job, source_quote_has_weekday_typo
from .schemas import (
    CourseRead,
    CourseUpdate,
    EventRead,
    EventUpdate,
    JobRead,
    RecurringSeriesRead,
    RecurringSeriesUpdate,
    ReviewCompleteConflict,
    ReviewCompleteResponse,
    ReviewResponse,
    SemesterCreate,
    SemesterRead,
    UploadResponse,
)
from .storage import StorageError, StorageService

router = APIRouter()
DISPATCH_FAILURE_MESSAGE = "Processing could not be started. Please try again."


def cleanup_saved_uploads(
    storage: StorageService,
    storage_keys: list[str],
) -> None:
    if not storage_keys:
        return
    storage.discard_new_uploads(storage_keys)


def safe_filename(filename: str | None) -> str:
    normalized = (filename or "syllabus.pdf").replace("\\", "/")
    basename = PurePosixPath(normalized).name or "syllabus.pdf"
    sanitized = re.sub(r'[\x00-\x1f\x7f"]', "_", basename)
    return sanitized[:255] or "syllabus.pdf"


def is_standalone_course_rule(event: ExtractedEvent) -> bool:
    return (
        "AMBIGUOUS_RECURRENCE" in (event.warning_codes or [])
        and event.recurring_series_id is None
    )


def owned_semester(db: Session, semester_id: UUID, user_id: UUID) -> Semester:
    semester = db.scalar(
        select(Semester).where(Semester.id == semester_id, Semester.user_id == user_id)
    )
    if semester is None:
        raise HTTPException(status_code=404, detail="Semester not found.")
    return semester


def job_read(job: ProcessingJob, *, hide_syllabus_typo_fallback: bool = False) -> JobRead:
    update: dict[str, object] = {"filename": job.document.filename}
    if hide_syllabus_typo_fallback:
        update.update({"fallback_used": False, "fallback_reason_codes": []})
    return JobRead.model_validate(job).model_copy(update=update)


def has_cross_event_date_conflict(
    event: ExtractedEvent,
    comparison_events: list[ExtractedEvent],
) -> bool:
    if event.event_date is None:
        return False
    normalized_title = re.sub(r"\s+", " ", event.title).strip().casefold()
    return any(
        other.id != event.id
        and other.event_date is not None
        and other.event_date != event.event_date
        and re.sub(r"\s+", " ", other.title).strip().casefold() == normalized_title
        for other in comparison_events
    )


def is_pure_syllabus_typo(
    event: ExtractedEvent,
    semester: Semester,
    comparison_events: list[ExtractedEvent] | None = None,
) -> bool:
    warning_codes = set(event.warning_codes or [])
    fallback_codes = set(event.fallback_reason_codes or [])
    semester_events = comparison_events if comparison_events is not None else semester.events
    return bool(
        "DATE_CONFLICT" in warning_codes
        and warning_codes <= {"DATE_CONFLICT", "YEAR_NOT_EXPLICIT", "MODEL_UNCERTAINTY"}
        and fallback_codes <= {"DATE_CONFLICT"}
        and not has_cross_event_date_conflict(event, semester_events)
        and source_quote_has_weekday_typo(
            event.source_quote,
            event.event_date,
            semester.start_date,
            semester.end_date,
        )
    )


def event_read(
    event: ExtractedEvent,
    semester: Semester,
    comparison_events: list[ExtractedEvent] | None = None,
) -> EventRead:
    payload = EventRead.model_validate(event)
    if not is_pure_syllabus_typo(event, semester, comparison_events):
        return payload
    return payload.model_copy(
        update={
            "warning_codes": ["DATE_CONFLICT"],
            "warning_reason": SYLLABUS_TYPO_WARNING,
            "fallback_reason_codes": [],
            "derivation_summary": None,
        }
    )


def dispatch_job(job_id: UUID, settings: Settings) -> None:
    if settings.processing_mode == "manual":
        return
    from .worker import process_document_job

    process_document_job.delay(str(job_id))


def mark_job_dispatch_failed(
    db: Session,
    job: ProcessingJob,
    error: Exception,
) -> None:
    job.status = JobStatus.FAILED
    job.stage_detail = "Dispatch failed"
    job.error_message = DISPATCH_FAILURE_MESSAGE
    db.commit()
    db.refresh(job)


def dispatch_or_mark_failed(
    db: Session,
    job: ProcessingJob,
    settings: Settings,
) -> None:
    try:
        dispatch_job(job.id, settings)
    except Exception as error:
        mark_job_dispatch_failed(db, job, error)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/semesters", response_model=SemesterRead, status_code=status.HTTP_201_CREATED)
def create_semester(
    payload: SemesterCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> Semester:
    semester = Semester(user_id=user.id, **payload.model_dump())
    db.add(semester)
    db.commit()
    db.refresh(semester)
    return semester


@router.get("/semesters", response_model=list[SemesterRead])
def list_semesters(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[SemesterRead]:
    course_counts = (
        select(Course.semester_id.label("semester_id"), func.count(Course.id).label("course_count"))
        .where(Course.user_id == user.id)
        .group_by(Course.semester_id)
        .subquery()
    )
    document_counts = (
        select(
            SyllabusDocument.semester_id.label("semester_id"),
            func.count(SyllabusDocument.id).label("document_count"),
        )
        .where(SyllabusDocument.user_id == user.id)
        .group_by(SyllabusDocument.semester_id)
        .subquery()
    )
    event_counts = (
        select(
            ExtractedEvent.semester_id.label("semester_id"),
            func.count(ExtractedEvent.id).label("event_count"),
        )
        .where(ExtractedEvent.user_id == user.id)
        .group_by(ExtractedEvent.semester_id)
        .subquery()
    )
    unresolved_series_counts = (
        select(
            RecurringEventSeries.semester_id.label("semester_id"),
            func.count(RecurringEventSeries.id).label("needs_review_count"),
        )
        .where(
            RecurringEventSeries.user_id == user.id,
            RecurringEventSeries.id.in_(
                select(ExtractedEvent.recurring_series_id).where(
                    ExtractedEvent.user_id == user.id,
                    ExtractedEvent.recurring_series_id.is_not(None),
                    ExtractedEvent.review_status == ReviewStatus.NEEDS_REVIEW,
                )
            ),
        )
        .group_by(RecurringEventSeries.semester_id)
        .subquery()
    )
    standalone_needs_review_counts = (
        select(
            ExtractedEvent.semester_id.label("semester_id"),
            func.count(ExtractedEvent.id).label("needs_review_count"),
        )
        .where(
            ExtractedEvent.user_id == user.id,
            or_(
                ExtractedEvent.recurring_series_id.is_(None),
                ExtractedEvent.recurring_series_id.not_in(
                    select(RecurringEventSeries.id).where(
                        RecurringEventSeries.user_id == user.id
                    )
                ),
            ),
            ExtractedEvent.review_status == ReviewStatus.NEEDS_REVIEW,
        )
        .group_by(ExtractedEvent.semester_id)
        .subquery()
    )
    payload: list[SemesterRead] = []
    rows = db.execute(
        select(
            Semester,
            func.coalesce(course_counts.c.course_count, 0),
            func.coalesce(document_counts.c.document_count, 0),
            func.coalesce(event_counts.c.event_count, 0),
            func.coalesce(unresolved_series_counts.c.needs_review_count, 0)
            + func.coalesce(standalone_needs_review_counts.c.needs_review_count, 0),
        )
        .outerjoin(course_counts, course_counts.c.semester_id == Semester.id)
        .outerjoin(document_counts, document_counts.c.semester_id == Semester.id)
        .outerjoin(event_counts, event_counts.c.semester_id == Semester.id)
        .outerjoin(
            unresolved_series_counts, unresolved_series_counts.c.semester_id == Semester.id
        )
        .outerjoin(
            standalone_needs_review_counts,
            standalone_needs_review_counts.c.semester_id == Semester.id,
        )
        .where(Semester.user_id == user.id)
        .order_by(Semester.created_at.desc())
    ).all()
    for semester, course_count, document_count, event_count, needs_review_count in rows:
        payload.append(
            SemesterRead.model_validate(semester).model_copy(
                update={
                    "course_count": int(course_count),
                    "document_count": int(document_count),
                    "event_count": int(event_count),
                    "needs_review_count": int(needs_review_count),
                }
            )
        )
    return payload


@router.delete("/semesters/{semester_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_semester(
    semester_id: UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> Response:
    semester = owned_semester(db, semester_id, user.id)
    storage_keys = list(
        db.scalars(
            select(SyllabusDocument.storage_key).where(
                SyllabusDocument.semester_id == semester_id,
                SyllabusDocument.user_id == user.id,
            )
        )
    )
    storage = StorageService(settings)
    try:
        backups = storage.delete_many(storage_keys)
    except StorageError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    try:
        db.execute(
            delete(ProcessingJob).where(
                ProcessingJob.semester_id == semester_id,
                ProcessingJob.user_id == user.id,
            )
        )
        db.execute(
            delete(ExtractedEvent).where(
                ExtractedEvent.semester_id == semester_id,
                ExtractedEvent.user_id == user.id,
            )
        )
        db.execute(
            delete(Course).where(
                Course.semester_id == semester_id,
                Course.user_id == user.id,
            )
        )
        db.execute(
            delete(SyllabusDocument).where(
                SyllabusDocument.semester_id == semester_id,
                SyllabusDocument.user_id == user.id,
            )
        )
        db.delete(semester)
        db.commit()
    except Exception as error:
        db.rollback()
        try:
            storage.restore_many(backups)
        except StorageError as restore_error:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Semester deletion rolled back, but storage restoration failed. "
                    f"{restore_error}"
                ),
            ) from restore_error
        finally:
            storage.cleanup_backups(backups)
        raise HTTPException(
            status_code=500,
            detail="Semester deletion could not be completed.",
        ) from error
    storage.cleanup_backups(backups)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/semesters/{semester_id}/syllabi",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_syllabi(
    semester_id: UUID,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    semester = owned_semester(db, semester_id, user.id)
    if len(files) > settings.max_upload_files:
        raise HTTPException(
            status_code=400,
            detail=f"Upload at most {settings.max_upload_files} PDF files at a time.",
        )
    if not files:
        raise HTTPException(status_code=400, detail="Choose at least one PDF file.")

    pending: list[tuple[UploadFile, bytes]] = []
    for uploaded in files:
        filename = safe_filename(uploaded.filename)
        if uploaded.content_type != "application/pdf" or not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=415, detail="Only PDF syllabus files are supported.")
        content = await uploaded.read(settings.max_upload_bytes + 1)
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="Each PDF must be 20 MB or smaller.")
        if not content.startswith(b"%PDF"):
            raise HTTPException(status_code=415, detail="The selected file is not a valid PDF.")
        pending.append((uploaded, content))

    storage = StorageService(settings)
    jobs: list[ProcessingJob] = []
    saved_storage_keys: list[str] = []
    try:
        for uploaded, content in pending:
            filename = safe_filename(uploaded.filename)
            document_id = uuid4()
            storage_key = f"{user.id}/{semester.id}/{document_id}/{filename}"
            saved_storage_keys.append(storage_key)
            storage.save(storage_key, content, "application/pdf")

            document = SyllabusDocument(
                id=document_id,
                user_id=user.id,
                semester_id=semester.id,
                filename=filename,
                content_type="application/pdf",
                size_bytes=len(content),
                storage_key=storage_key,
            )
            job = ProcessingJob(
                user_id=user.id,
                semester_id=semester.id,
                document=document,
                status=JobStatus.QUEUED,
                stage_detail="Waiting to process",
            )
            db.add(job)
            jobs.append(job)
        db.commit()
    except StorageError as error:
        db.rollback()
        try:
            cleanup_saved_uploads(storage, saved_storage_keys)
        except StorageError as cleanup_error:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"{error} Partial upload cleanup failed. "
                    f"{cleanup_error}"
                ),
            ) from cleanup_error
        raise HTTPException(status_code=502, detail=str(error)) from error
    except Exception as error:
        db.rollback()
        try:
            cleanup_saved_uploads(storage, saved_storage_keys)
        except StorageError as cleanup_error:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Upload could not be completed and cleanup failed. "
                    f"{cleanup_error}"
                ),
            ) from cleanup_error
        raise HTTPException(
            status_code=500,
            detail="Upload could not be completed.",
        ) from error
    for job in jobs:
        db.refresh(job)
        dispatch_or_mark_failed(db, job, settings)

    return UploadResponse(jobs=[job_read(job) for job in jobs])


@router.get("/semesters/{semester_id}/jobs", response_model=list[JobRead])
def list_jobs(
    semester_id: UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[JobRead]:
    semester = owned_semester(db, semester_id, user.id)
    jobs = db.scalars(
        select(ProcessingJob)
        .options(selectinload(ProcessingJob.document))
        .where(
            ProcessingJob.semester_id == semester_id,
            ProcessingJob.user_id == user.id,
        )
        .order_by(ProcessingJob.created_at.asc())
    ).all()
    events = list(
        db.scalars(
            select(ExtractedEvent).where(
                ExtractedEvent.semester_id == semester_id,
                ExtractedEvent.user_id == user.id,
            )
        )
    )
    events_by_document: dict[UUID, list[ExtractedEvent]] = {}
    for event in events:
        if event.document_id is not None:
            events_by_document.setdefault(event.document_id, []).append(event)

    payloads: list[JobRead] = []
    for job in jobs:
        related_events = events_by_document.get(job.document_id, [])
        fallback_events = [event for event in related_events if event.fallback_reason_codes]
        hide_syllabus_typo_fallback = bool(
            set(job.fallback_reason_codes or []) == {"DATE_CONFLICT"}
            and fallback_events
            and all(
                is_pure_syllabus_typo(event, semester, events)
                for event in fallback_events
            )
        )
        payloads.append(
            job_read(job, hide_syllabus_typo_fallback=hide_syllabus_typo_fallback)
        )
    return payloads


@router.post("/jobs/{job_id}/retry", response_model=JobRead)
def retry_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> JobRead:
    job = db.scalar(
        select(ProcessingJob)
        .options(selectinload(ProcessingJob.document))
        .where(ProcessingJob.id == job_id, ProcessingJob.user_id == user.id)
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found.")
    if job.status != JobStatus.FAILED:
        raise HTTPException(status_code=409, detail="Only failed jobs can be retried.")
    job.status = JobStatus.QUEUED
    job.stage_detail = "Waiting to retry"
    job.error_message = None
    db.commit()
    db.refresh(job)
    dispatch_or_mark_failed(db, job, settings)
    return job_read(job)


@router.post("/jobs/{job_id}/reprocess", response_model=JobRead)
def reprocess_job(
    job_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> JobRead:
    job = db.scalar(
        select(ProcessingJob)
        .options(selectinload(ProcessingJob.document))
        .where(ProcessingJob.id == job_id, ProcessingJob.user_id == user.id)
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found.")
    if job.status not in {JobStatus.NEEDS_REVIEW, JobStatus.COMPLETED}:
        if job.status == JobStatus.FAILED:
            raise HTTPException(status_code=409, detail="Use retry for failed jobs.")
        raise HTTPException(
            status_code=409,
            detail="Only completed or reviewable jobs can be reprocessed.",
        )
    job.status = JobStatus.QUEUED
    job.stage_detail = "Waiting to reprocess"
    job.error_message = None
    job.fallback_used = False
    job.fallback_reason_codes = []
    db.commit()
    db.refresh(job)
    if settings.processing_mode == "manual":
        process_job(
            str(job.id),
            settings=settings,
            session_factory=request.app.state.session_factory,
        )
        with request.app.state.session_factory() as session:
            refreshed = session.scalar(
                select(ProcessingJob)
                .options(selectinload(ProcessingJob.document))
                .where(ProcessingJob.id == job.id, ProcessingJob.user_id == user.id)
            )
            if refreshed is not None:
                return job_read(refreshed)
    else:
        dispatch_or_mark_failed(db, job, settings)
    return job_read(job)


@router.get("/semesters/{semester_id}/review", response_model=ReviewResponse)
def get_review(
    semester_id: UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> ReviewResponse:
    semester = owned_semester(db, semester_id, user.id)
    courses = list(
        db.scalars(
            select(Course)
            .where(Course.semester_id == semester_id, Course.user_id == user.id)
            .order_by(Course.name.asc())
        )
    )
    documents = list(
        db.scalars(
            select(SyllabusDocument)
            .where(
                SyllabusDocument.semester_id == semester_id,
                SyllabusDocument.user_id == user.id,
            )
            .order_by(SyllabusDocument.created_at.asc())
        )
    )
    events = list(
        db.scalars(
            select(ExtractedEvent)
            .where(
                ExtractedEvent.semester_id == semester_id,
                ExtractedEvent.user_id == user.id,
            )
            .order_by(ExtractedEvent.event_date.asc(), ExtractedEvent.title.asc())
        )
    )
    recurring_series = list(
        db.scalars(
            select(RecurringEventSeries)
            .options(selectinload(RecurringEventSeries.events))
            .where(
                RecurringEventSeries.semester_id == semester_id,
                RecurringEventSeries.user_id == user.id,
            )
            .order_by(RecurringEventSeries.title.asc(), RecurringEventSeries.created_at.asc())
        )
    )
    return ReviewResponse(
        semester=semester,
        courses=courses,
        documents=documents,
        events=[event_read(event, semester, events) for event in events],
        recurring_series=recurring_series,
    )


@router.patch("/extracted-events/{event_id}", response_model=EventRead)
def update_event(
    event_id: UUID,
    payload: EventUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> EventRead:
    event = db.scalar(
        select(ExtractedEvent).where(
            ExtractedEvent.id == event_id,
            ExtractedEvent.user_id == user.id,
        )
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Extracted event not found.")
    updates = payload.model_dump(exclude_unset=True)
    next_review_status = updates.get("review_status", event.review_status)
    next_event_date = updates.get("event_date", event.event_date)
    next_is_all_day = updates.get("is_all_day", event.is_all_day)
    next_start_time = updates.get("start_time", event.start_time)
    next_end_time = updates.get("end_time", event.end_time)

    if is_standalone_course_rule(event) and next_review_status == ReviewStatus.CONFIRMED:
        raise HTTPException(
            status_code=422,
            detail="Course rules cannot be published as a single calendar event.",
        )
    if next_review_status == ReviewStatus.CONFIRMED and next_event_date is None:
        raise HTTPException(status_code=422, detail="Add a date before confirming this event.")
    if next_is_all_day:
        next_start_time = None
        next_end_time = None
    if next_start_time and next_end_time and next_end_time <= next_start_time:
        raise HTTPException(status_code=422, detail="End time must be after start time.")

    for field, value in updates.items():
        setattr(event, field, value)
    if event.is_all_day:
        event.start_time = None
        event.end_time = None

    db.commit()
    db.refresh(event)
    return event_read(event, event.semester)


@router.patch("/recurring-series/{series_id}", response_model=RecurringSeriesRead)
def update_recurring_series(
    series_id: UUID,
    payload: RecurringSeriesUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> RecurringEventSeries:
    series = db.scalar(
        select(RecurringEventSeries)
        .options(selectinload(RecurringEventSeries.events))
        .where(RecurringEventSeries.id == series_id, RecurringEventSeries.user_id == user.id)
    )
    if series is None:
        raise HTTPException(status_code=404, detail="Recurring series not found.")
    if payload.review_status == ReviewStatus.CONFIRMED and any(
        event.event_date is None
        for event in series.events
        if event.review_status != ReviewStatus.IGNORED
    ):
        raise HTTPException(status_code=422, detail="Add dates before confirming this series.")
    for event in series.events:
        if (
            payload.review_status in {ReviewStatus.CONFIRMED, ReviewStatus.PENDING}
            and event.review_status == ReviewStatus.IGNORED
        ):
            continue
        event.review_status = payload.review_status
    db.commit()
    db.refresh(series)
    return series


@router.patch("/courses/{course_id}", response_model=CourseRead)
def update_course(
    course_id: UUID,
    payload: CourseUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> Course:
    course = db.scalar(select(Course).where(Course.id == course_id, Course.user_id == user.id))
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(course, field, value)
    db.commit()
    db.refresh(course)
    return course


@router.post(
    "/semesters/{semester_id}/review/complete",
    response_model=ReviewCompleteResponse,
)
def complete_review(
    semester_id: UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> ReviewCompleteResponse:
    semester = owned_semester(db, semester_id, user.id)
    blocking_events = list(
        db.scalars(
            select(ExtractedEvent).where(
                ExtractedEvent.semester_id == semester_id,
                ExtractedEvent.user_id == user.id,
                ExtractedEvent.review_status == ReviewStatus.NEEDS_REVIEW,
            )
            .order_by(
                ExtractedEvent.document_id.asc(),
                ExtractedEvent.event_date.asc(),
                ExtractedEvent.title.asc(),
            )
        )
    )
    if blocking_events:
        payload = ReviewCompleteConflict(
            detail="Resolve every event before finishing review.",
            blocking_event_ids=[event.id for event in blocking_events],
            blocking_document_ids=list(
                dict.fromkeys(
                    event.document_id
                    for event in blocking_events
                    if event.document_id is not None
                )
            ),
            blocking_count=len(blocking_events),
        )
        return JSONResponse(status_code=409, content=payload.model_dump(mode="json"))
    semester.review_completed_at = datetime.now(UTC)
    db.execute(
        update(ProcessingJob)
        .where(
            ProcessingJob.semester_id == semester_id,
            ProcessingJob.user_id == user.id,
            ProcessingJob.status == JobStatus.NEEDS_REVIEW,
        )
        .values(
            status=JobStatus.COMPLETED,
            stage_detail="Review completed",
            completed_at=semester.review_completed_at,
        )
    )
    db.commit()
    db.refresh(semester)
    return ReviewCompleteResponse(review_completed_at=semester.review_completed_at)


@router.get("/semesters/{semester_id}/events", response_model=list[EventRead])
def list_confirmed_events(
    semester_id: UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[EventRead]:
    semester = owned_semester(db, semester_id, user.id)
    events = list(
        db.scalars(
            select(ExtractedEvent)
            .where(
                ExtractedEvent.semester_id == semester_id,
                ExtractedEvent.user_id == user.id,
                ExtractedEvent.review_status == ReviewStatus.CONFIRMED,
                ExtractedEvent.event_date.is_not(None),
            )
            .order_by(ExtractedEvent.event_date.asc(), ExtractedEvent.title.asc())
        )
    )
    return [
        event_read(event, semester)
        for event in events
        if not is_standalone_course_rule(event)
    ]


@router.get("/semesters/{semester_id}/calendar.ics")
def download_calendar(
    semester_id: UUID,
    course_id: list[UUID] | None = Query(default=None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    semester = owned_semester(db, semester_id, user.id)
    query = (
        select(ExtractedEvent)
        .options(selectinload(ExtractedEvent.course))
        .where(
            ExtractedEvent.semester_id == semester_id,
            ExtractedEvent.user_id == user.id,
            ExtractedEvent.review_status == ReviewStatus.CONFIRMED,
            ExtractedEvent.event_date.is_not(None),
        )
        .order_by(ExtractedEvent.event_date.asc())
    )
    if course_id:
        query = query.where(ExtractedEvent.course_id.in_(course_id))
    events = [
        event for event in db.scalars(query) if not is_standalone_course_rule(event)
    ]
    filename = re.sub(r"[^a-z0-9]+", "-", semester.name.lower()).strip("-") or "semester"
    return Response(
        build_calendar(semester.name, events),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}.ics"'},
    )


@router.get("/syllabus-documents/{document_id}/file")
def download_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> Response:
    document = db.scalar(
        select(SyllabusDocument).where(
            SyllabusDocument.id == document_id,
            SyllabusDocument.user_id == user.id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Syllabus not found.")
    try:
        content = StorageService(settings).read(document.storage_key)
    except StorageError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{document.filename}"'},
    )
