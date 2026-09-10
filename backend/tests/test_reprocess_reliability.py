from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pymupdf
from sqlalchemy import func, select

from app.models import (
    ConfidenceLevel,
    Course,
    ExtractedEvent,
    JobStatus,
    ProcessingJob,
    Semester,
    SyllabusDocument,
)
from app.processing import CandidateEvent, SyllabusExtraction

from .conftest import USER_A, auth_headers


def make_pdf(text: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_textbox(pymupdf.Rect(72, 72, 520, 760), text)
    content = document.tobytes()
    document.close()
    return content


def write_pdf(app, storage_key: str, content: bytes) -> None:
    upload_root = Path(app.state.settings.local_storage_path)
    path = upload_root / storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def seed_reprocess_failure_case(app) -> tuple[UUID, UUID, UUID]:
    completed_at = datetime(2026, 8, 25, tzinfo=UTC)
    session_factory = app.state.session_factory
    with session_factory() as session:
        semester = Semester(
            user_id=USER_A,
            name="Fall 2026",
            start_date=date(2026, 8, 24),
            end_date=date(2026, 12, 18),
            timezone="America/New_York",
            review_completed_at=completed_at,
        )
        session.add(semester)
        session.flush()
        document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="cs101.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/doc-1/cs101.pdf",
        )
        course = Course(
            user_id=USER_A,
            semester_id=semester.id,
            document_id=document.id,
            code="CS 101",
            name="Introduction to Computer Science",
            color="#0D9488",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.COMPLETED,
            stage_detail="Review completed",
            completed_at=completed_at,
        )
        session.add_all([course, job])
        session.flush()
        session.add(
            ExtractedEvent(
                user_id=USER_A,
                semester_id=semester.id,
                course_id=course.id,
                document_id=document.id,
                title="Manual final project",
                event_type="assignment",
                event_date=date(2026, 12, 12),
                timezone="America/New_York",
                is_all_day=True,
                source_quote="Final project originally due December 12, 2026",
                source_page=2,
                confidence=ConfidenceLevel.HIGH,
                warning_codes=[],
                review_status="ignored",
            )
        )
        session.commit()
        return semester.id, job.id, document.storage_key


def seed_reprocess_success_case(app) -> tuple[UUID, UUID, str, UUID]:
    session_factory = app.state.session_factory
    with session_factory() as session:
        semester = Semester(
            user_id=USER_A,
            name="Fall 2026",
            start_date=date(2026, 8, 24),
            end_date=date(2026, 12, 18),
            timezone="America/New_York",
            review_completed_at=datetime(2026, 8, 25, tzinfo=UTC),
        )
        session.add(semester)
        session.flush()

        target_document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="cs101.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/doc-1/cs101.pdf",
        )
        sibling_document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="math201.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/doc-2/math201.pdf",
        )
        session.add_all([target_document, sibling_document])
        session.flush()

        target_course = Course(
            user_id=USER_A,
            semester_id=semester.id,
            document_id=target_document.id,
            code="CS 101",
            name="Introduction to Computer Science",
            color="#0D9488",
        )
        sibling_course = Course(
            user_id=USER_A,
            semester_id=semester.id,
            document_id=sibling_document.id,
            code="MATH 201",
            name="Discrete Math",
            color="#2563EB",
        )
        target_job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=target_document,
            status=JobStatus.COMPLETED,
            completed_at=datetime(2026, 8, 25, tzinfo=UTC),
        )
        sibling_job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=sibling_document,
            status=JobStatus.COMPLETED,
            completed_at=datetime(2026, 8, 25, tzinfo=UTC),
        )
        session.add_all([target_course, sibling_course, target_job, sibling_job])
        session.flush()
        session.add_all(
            [
                ExtractedEvent(
                    user_id=USER_A,
                    semester_id=semester.id,
                    course_id=target_course.id,
                    document_id=target_document.id,
                    title="Old midterm",
                    event_type="exam",
                    event_date=date(2026, 10, 10),
                    timezone="America/New_York",
                    is_all_day=True,
                    source_quote="Old midterm October 10, 2026",
                    source_page=1,
                    confidence=ConfidenceLevel.HIGH,
                    warning_codes=[],
                    review_status="confirmed",
                ),
                ExtractedEvent(
                    user_id=USER_A,
                    semester_id=semester.id,
                    course_id=sibling_course.id,
                    document_id=sibling_document.id,
                    title="Keep this quiz",
                    event_type="quiz",
                    event_date=date(2026, 9, 15),
                    timezone="America/New_York",
                    is_all_day=True,
                    source_quote="Quiz 1 September 15, 2026",
                    source_page=1,
                    confidence=ConfidenceLevel.HIGH,
                    warning_codes=[],
                    review_status="confirmed",
                ),
            ]
        )
        session.commit()
        return semester.id, target_job.id, target_document.storage_key, sibling_document.id


def seed_failed_retry_case(app) -> tuple[UUID, UUID]:
    session_factory = app.state.session_factory
    with session_factory() as session:
        semester = Semester(
            user_id=USER_A,
            name="Fall 2026",
            start_date=date(2026, 8, 24),
            end_date=date(2026, 12, 18),
            timezone="America/New_York",
        )
        session.add(semester)
        session.flush()
        document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="failed.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/doc-1/failed.pdf",
        )
        course = Course(
            user_id=USER_A,
            semester_id=semester.id,
            document_id=document.id,
            code="CS 101",
            name="Introduction to Computer Science",
            color="#0D9488",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.FAILED,
            stage_detail="Processing failed",
            error_message="boom",
        )
        session.add_all([course, job])
        session.flush()
        session.add(
            ExtractedEvent(
                user_id=USER_A,
                semester_id=semester.id,
                course_id=course.id,
                document_id=document.id,
                title="Failed job event",
                event_type="exam",
                event_date=date(2026, 10, 10),
                timezone="America/New_York",
                is_all_day=True,
                source_quote="Failed job event October 10, 2026",
                source_page=1,
                confidence=ConfidenceLevel.HIGH,
                warning_codes=[],
                review_status="needs_review",
            )
        )
        session.commit()
        return semester.id, job.id


def test_reprocess_failure_preserves_manual_review_data_and_completion(
    app_client,
    monkeypatch,
):
    client, app = app_client
    semester_id, job_id, storage_key = seed_reprocess_failure_case(app)
    write_pdf(app, storage_key, make_pdf("CS 101 Midterm exam October 14, 2026. " * 8))

    monkeypatch.setattr(
        "app.processing.extract_syllabus",
        lambda pages, settings: SyllabusExtraction(
            course_code="CS 101",
            course_name="Introduction to Computer Science",
            instructor="Dr. Rivera",
            events=[
                CandidateEvent(
                    title="Replacement event",
                    event_type="exam",
                    event_date=date(2026, 10, 14),
                    start_time=None,
                    end_time=None,
                    is_all_day=True,
                    source_quote="Midterm exam October 14, 2026",
                    source_page=1,
                    confidence="high",
                    year_was_explicit=True,
                    uncertainty_reason=None,
                )
            ],
        ),
    )
    monkeypatch.setattr(
        "app.processing.expand_recurring_rules",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("series exploded")),
    )

    response = client.post(f"/api/jobs/{job_id}/reprocess", headers=auth_headers())

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    with app.state.session_factory() as session:
        semester = session.get(Semester, semester_id)
        job = session.get(ProcessingJob, job_id)
        events = session.scalars(
            select(ExtractedEvent).where(ExtractedEvent.document_id == job.document_id)
        ).all()
        assert semester.review_completed_at == datetime(2026, 8, 25)
        assert job.completed_at == datetime(2026, 8, 25)
        assert [(event.title, event.event_date, event.review_status.value) for event in events] == [
            ("Manual final project", date(2026, 12, 12), "ignored")
        ]


def test_reprocess_success_replaces_only_target_document_data(app_client, monkeypatch):
    client, app = app_client
    semester_id, job_id, storage_key, sibling_document_id = seed_reprocess_success_case(app)
    write_pdf(app, storage_key, make_pdf("CS 101 Midterm exam October 14, 2026. " * 8))

    monkeypatch.setattr(
        "app.processing.extract_syllabus",
        lambda pages, settings: SyllabusExtraction(
            course_code="CS 101",
            course_name="Introduction to Computer Science",
            instructor="Dr. Rivera",
            events=[
                CandidateEvent(
                    title="New midterm",
                    event_type="exam",
                    event_date=date(2026, 10, 14),
                    start_time=None,
                    end_time=None,
                    is_all_day=True,
                    source_quote="Midterm exam October 14, 2026",
                    source_page=1,
                    confidence="high",
                    year_was_explicit=True,
                    uncertainty_reason=None,
                )
            ],
        ),
    )

    response = client.post(f"/api/jobs/{job_id}/reprocess", headers=auth_headers())

    assert response.status_code == 200
    assert response.json()["status"] == "needs_review"
    with app.state.session_factory() as session:
        semester = session.get(Semester, semester_id)
        job = session.get(ProcessingJob, job_id)
        events = session.scalars(
            select(ExtractedEvent).where(ExtractedEvent.semester_id == semester_id)
        ).all()
        sibling_events = [
            event.title for event in events if event.document_id == sibling_document_id
        ]
        target_events = [event.title for event in events if event.document_id == job.document_id]
        assert semester.review_completed_at is None
        assert job.completed_at is None
        assert job.status == JobStatus.NEEDS_REVIEW
        assert target_events == ["New midterm"]
        assert sibling_events == ["Keep this quiz"]
        target_event = next(event for event in events if event.title == "New midterm")
        sibling_event = next(event for event in events if event.title == "Keep this quiz")
        assert target_event.review_status.value == "needs_review"
        assert sibling_event.review_status.value == "confirmed"


def test_retry_and_reprocess_reject_active_job_without_duplicate_work(app_client):
    client, app = app_client
    semester_id, job_id = seed_failed_retry_case(app)

    first_retry = client.post(f"/api/jobs/{job_id}/retry", headers=auth_headers())
    second_retry = client.post(f"/api/jobs/{job_id}/retry", headers=auth_headers())
    reprocess = client.post(f"/api/jobs/{job_id}/reprocess", headers=auth_headers())

    assert first_retry.status_code == 200
    assert first_retry.json()["status"] == "queued"
    assert second_retry.status_code == 409
    assert second_retry.json()["detail"] == "Only failed jobs can be retried."
    assert reprocess.status_code == 409
    assert reprocess.json()["detail"] == "Only completed or reviewable jobs can be reprocessed."

    with app.state.session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(ProcessingJob).where(
                ProcessingJob.semester_id == semester_id
            )
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(SyllabusDocument).where(
                SyllabusDocument.semester_id == semester_id
            )
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(ExtractedEvent).where(
                ExtractedEvent.semester_id == semester_id
            )
        ) == 1


def test_reprocess_dispatch_failure_preserves_previous_completion_and_review_data(
    app_client,
    monkeypatch,
):
    client, app = app_client
    semester_id, job_id, storage_key = seed_reprocess_failure_case(app)
    app.state.settings.processing_mode = "worker"
    write_pdf(app, storage_key, make_pdf("CS 101 Midterm exam October 14, 2026. " * 8))

    def fail_dispatch(job_id, settings, **kwargs):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr("app.api.dispatch_job", fail_dispatch)

    response = client.post(f"/api/jobs/{job_id}/reprocess", headers=auth_headers())

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert (
        response.json()["error_message"]
        == "Processing could not be started. Please try again."
    )
    with app.state.session_factory() as session:
        semester = session.get(Semester, semester_id)
        job = session.get(ProcessingJob, job_id)
        events = session.scalars(
            select(ExtractedEvent).where(ExtractedEvent.document_id == job.document_id)
        ).all()
        assert semester.review_completed_at == datetime(2026, 8, 25)
        assert job.completed_at == datetime(2026, 8, 25)
        assert job.stage_detail == "Dispatch failed"
        assert job.error_message == "Processing could not be started. Please try again."
        assert [(event.title, event.event_date, event.review_status.value) for event in events] == [
            ("Manual final project", date(2026, 12, 12), "ignored")
        ]


def test_retry_dispatch_failure_preserves_previous_completion_after_failed_rerun(
    app_client,
    monkeypatch,
):
    client, app = app_client
    semester_id, job_id, storage_key = seed_reprocess_failure_case(app)
    app.state.settings.processing_mode = "worker"
    write_pdf(app, storage_key, make_pdf("CS 101 Midterm exam October 14, 2026. " * 8))

    with app.state.session_factory() as session:
        job = session.get(ProcessingJob, job_id)
        job.status = JobStatus.FAILED
        job.stage_detail = "Processing failed"
        job.error_message = "earlier rerun failed"
        session.commit()

    def fail_dispatch(job_id, settings, **kwargs):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr("app.api.dispatch_job", fail_dispatch)

    response = client.post(f"/api/jobs/{job_id}/retry", headers=auth_headers())

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert (
        response.json()["error_message"]
        == "Processing could not be started. Please try again."
    )
    with app.state.session_factory() as session:
        semester = session.get(Semester, semester_id)
        job = session.get(ProcessingJob, job_id)
        events = session.scalars(
            select(ExtractedEvent).where(ExtractedEvent.document_id == job.document_id)
        ).all()
        assert semester.review_completed_at == datetime(2026, 8, 25)
        assert job.completed_at == datetime(2026, 8, 25)
        assert job.stage_detail == "Dispatch failed"
        assert job.error_message == "Processing could not be started. Please try again."
        assert [(event.title, event.event_date, event.review_status.value) for event in events] == [
            ("Manual final project", date(2026, 12, 12), "ignored")
        ]
