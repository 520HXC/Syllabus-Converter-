from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pymupdf
import pytest
from icalendar import Calendar
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ConfidenceLevel,
    Course,
    ExtractedEvent,
    JobStatus,
    ProcessingJob,
    RecurringEventSeries,
    ReviewStatus,
    Semester,
    SyllabusDocument,
)
from app.processing import CandidateEvent, SyllabusExtraction
from app.storage import StorageError

from .conftest import USER_A, USER_B, auth_headers


def make_pdf(text: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_textbox(pymupdf.Rect(72, 72, 520, 760), text)
    content = document.tobytes()
    document.close()
    return content


def test_event_model_supports_pending_undated_items():
    assert ExtractedEvent.__table__.c.event_date.nullable is True
    assert ReviewStatus.PENDING.value == "pending"


def seed_review_data(app) -> tuple[UUID, UUID, UUID]:
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
        course = Course(
            user_id=USER_A,
            semester_id=semester.id,
            code="CS 101",
            name="Introduction to Computer Science",
            color="#0D9488",
        )
        session.add(course)
        session.flush()
        document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="cs101.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/cs101.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.NEEDS_REVIEW,
        )
        session.add(job)
        confirmed = ExtractedEvent(
            user_id=USER_A,
            semester_id=semester.id,
            course_id=course.id,
            title="Midterm exam",
            event_type="exam",
            event_date=date(2026, 10, 14),
            timezone="America/New_York",
            is_all_day=True,
            source_quote="Midterm exam October 14, 2026",
            source_page=2,
            confidence=ConfidenceLevel.HIGH,
            warning_codes=[],
            extraction_model="gpt-5.6-luna",
            fallback_reason_codes=[],
            review_status=ReviewStatus.CONFIRMED,
        )
        needs_review = ExtractedEvent(
            user_id=USER_A,
            semester_id=semester.id,
            course_id=course.id,
            title="Final project",
            event_type="assignment",
            event_date=date(2026, 12, 10),
            timezone="America/New_York",
            is_all_day=True,
            source_quote="Final project due around December 10",
            source_page=5,
            confidence=ConfidenceLevel.LOW,
            warning_codes=["AMBIGUOUS_DATE"],
            warning_reason="The syllabus says around December 10.",
            extraction_model="gpt-5.6-terra",
            fallback_reason_codes=["LOW_CONFIDENCE", "SOURCE_MISMATCH"],
            review_status=ReviewStatus.NEEDS_REVIEW,
        )
        session.add_all([confirmed, needs_review])
        session.commit()
        return semester.id, confirmed.id, needs_review.id


def seed_course_rule_review_data(app) -> tuple[UUID, UUID, UUID]:
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
        course = Course(
            user_id=USER_A,
            semester_id=semester.id,
            code="CS 101",
            name="Introduction to Computer Science",
            color="#0D9488",
        )
        session.add(course)
        session.flush()
        document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="cs101.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/cs101.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.NEEDS_REVIEW,
        )
        session.add(job)
        confirmed = ExtractedEvent(
            user_id=USER_A,
            semester_id=semester.id,
            course_id=course.id,
            title="Midterm exam",
            event_type="exam",
            event_date=date(2026, 10, 14),
            timezone="America/New_York",
            is_all_day=True,
            source_quote="Midterm exam October 14, 2026",
            source_page=2,
            confidence=ConfidenceLevel.HIGH,
            warning_codes=[],
            extraction_model="gpt-5.6-luna",
            fallback_reason_codes=[],
            review_status=ReviewStatus.CONFIRMED,
        )
        course_rule = ExtractedEvent(
            user_id=USER_A,
            semester_id=semester.id,
            course_id=course.id,
            title="Exercise Sets",
            event_type="assignment",
            event_date=None,
            timezone="America/New_York",
            is_all_day=True,
            source_quote="Exercise Sets due 8AM after the lecture",
            source_page=5,
            confidence=ConfidenceLevel.MEDIUM,
            warning_codes=["AMBIGUOUS_RECURRENCE"],
            warning_reason="The syllabus does not identify every occurrence.",
            extraction_model="gpt-5.6-luna",
            fallback_reason_codes=[],
            review_status=ReviewStatus.NEEDS_REVIEW,
        )
        session.add_all([confirmed, course_rule])
        session.commit()
        return semester.id, confirmed.id, course_rule.id


def seed_legacy_syllabus_typo_review_data(app) -> tuple[UUID, UUID, UUID]:
    session_factory = app.state.session_factory
    with session_factory() as session:
        semester = Semester(
            user_id=USER_A,
            name="Fall 2025",
            start_date=date(2025, 8, 25),
            end_date=date(2025, 12, 20),
            timezone="America/New_York",
        )
        session.add(semester)
        session.flush()
        course = Course(
            user_id=USER_A,
            semester_id=semester.id,
            code="CS-UY 1114",
            name="Introduction to Programming and Problem Solving",
            color="#0D9488",
        )
        session.add(course)
        session.flush()
        document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="Fall_2025_Syllabus.pdf",
            content_type="application/pdf",
            size_bytes=341085,
            storage_key=f"{USER_A}/{semester.id}/Fall_2025_Syllabus.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.NEEDS_REVIEW,
            primary_model="gpt-5.6-luna",
            fallback_model="gpt-5.6-terra",
            fallback_used=True,
            fallback_reason_codes=["DATE_CONFLICT"],
        )
        session.add(job)
        session.flush()
        event = ExtractedEvent(
            user_id=USER_A,
            semester_id=semester.id,
            course_id=course.id,
            document_id=document.id,
            title="No Lecture / Friday schedule",
            event_type="class",
            event_date=date(2025, 11, 27),
            timezone="America/New_York",
            is_all_day=True,
            source_quote="27-Nov Wednesday No Lecture, Friday Schedule",
            source_page=4,
            confidence=ConfidenceLevel.MEDIUM,
            warning_codes=["DATE_CONFLICT", "YEAR_NOT_EXPLICIT", "MODEL_UNCERTAINTY"],
            warning_reason=(
                "The syllabus says Wednesday, but November 27, 2025 is Thursday. "
                "The source does not explicitly state a year. "
                "Terra repaired Date Conflict and shifted the event to November 26."
            ),
            extraction_model="gpt-5.6-terra",
            fallback_reason_codes=["DATE_CONFLICT"],
            derivation_summary="Legacy Terra repair explanation that should not stay visible.",
            review_status=ReviewStatus.NEEDS_REVIEW,
        )
        session.add(event)
        session.commit()
        return semester.id, job.id, event.id


def seed_recurring_series_data(app) -> tuple[UUID, UUID, UUID]:
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
        document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="cs101.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/cs101.pdf",
        )
        course = Course(
            user_id=USER_A,
            semester_id=semester.id,
            document_id=document.id,
            code="CS 101",
            name="Introduction to Computer Science",
            color="#0D9488",
        )
        session.add_all([document, course])
        session.flush()
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.NEEDS_REVIEW,
            primary_model="gpt-5.6-luna",
            fallback_model="gpt-5.6-terra",
            fallback_used=True,
            fallback_reason_codes=["LOW_CONFIDENCE", "SOURCE_MISMATCH"],
        )
        series = RecurringEventSeries(
            user_id=USER_A,
            semester_id=semester.id,
            course_id=course.id,
            document_id=document.id,
            title="Homework",
            event_type="assignment",
            rule_kind="weekly_fixed",
            rule_summary="Every friday between 2026-09-04 and 2026-12-04",
            source_quote=(
                "Homework due every Friday from Sep 4, 2026 "
                "through Dec 4, 2026 except Nov 27, 2026."
            ),
            source_page=1,
            anchor_sources=[],
            rule_payload={
                "weekday": "friday",
                "boundary_start": "2026-09-04",
                "boundary_end": "2026-12-04",
                "exclusion_dates": ["2026-11-27"],
                "start_time": None,
                "end_time": None,
                "is_all_day": True,
                "anchor_title": None,
                "offset_days": None,
            },
            confidence=ConfidenceLevel.HIGH,
            warning_codes=[],
            warning_reason=None,
            extraction_model="gpt-5.6-luna",
            fallback_reason_codes=[],
        )
        session.add_all([job, series])
        session.flush()
        first_event = ExtractedEvent(
            user_id=USER_A,
            semester_id=semester.id,
            course_id=course.id,
            document_id=document.id,
            recurring_series_id=series.id,
            title="Homework",
            event_type="assignment",
            event_date=date(2026, 9, 4),
            timezone="America/New_York",
            is_all_day=True,
            source_quote=series.source_quote,
            source_page=1,
            confidence=ConfidenceLevel.HIGH,
            warning_codes=[],
            warning_reason=None,
            extraction_model="gpt-5.6-luna",
            fallback_reason_codes=[],
            derivation_summary=series.rule_summary,
            review_status=ReviewStatus.NEEDS_REVIEW,
        )
        second_event = ExtractedEvent(
            user_id=USER_A,
            semester_id=semester.id,
            course_id=course.id,
            document_id=document.id,
            recurring_series_id=series.id,
            title="Homework",
            event_type="assignment",
            event_date=date(2026, 9, 11),
            timezone="America/New_York",
            is_all_day=True,
            source_quote=series.source_quote,
            source_page=1,
            confidence=ConfidenceLevel.HIGH,
            warning_codes=[],
            warning_reason=None,
            extraction_model="gpt-5.6-luna",
            fallback_reason_codes=[],
            derivation_summary=series.rule_summary,
            review_status=ReviewStatus.PENDING,
        )
        session.add_all([first_event, second_event])
        session.commit()
        return semester.id, series.id, job.id


def seed_hidden_blocker_review_data(app) -> tuple[UUID, UUID, UUID]:
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

        first_document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="cs101.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/cs101.pdf",
        )
        second_document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="math201.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/math201.pdf",
        )
        session.add_all([first_document, second_document])
        session.flush()

        first_course = Course(
            user_id=USER_A,
            semester_id=semester.id,
            document_id=first_document.id,
            code="CS 101",
            name="Introduction to Computer Science",
            color="#0D9488",
        )
        second_course = Course(
            user_id=USER_A,
            semester_id=semester.id,
            document_id=second_document.id,
            code="MATH 201",
            name="Discrete Math",
            color="#2563EB",
        )
        session.add_all([first_course, second_course])
        session.flush()

        session.add_all(
            [
                ProcessingJob(
                    user_id=USER_A,
                    semester_id=semester.id,
                    document=first_document,
                    status=JobStatus.NEEDS_REVIEW,
                ),
                ProcessingJob(
                    user_id=USER_A,
                    semester_id=semester.id,
                    document=second_document,
                    status=JobStatus.NEEDS_REVIEW,
                ),
            ]
        )
        blocking_event = ExtractedEvent(
            user_id=USER_A,
            semester_id=semester.id,
            course_id=first_course.id,
            document_id=first_document.id,
            title="Final project",
            event_type="assignment",
            event_date=date(2026, 12, 10),
            timezone="America/New_York",
            is_all_day=True,
            source_quote="Final project due around December 10",
            source_page=5,
            confidence=ConfidenceLevel.LOW,
            warning_codes=["AMBIGUOUS_DATE"],
            warning_reason="The syllabus says around December 10.",
            review_status=ReviewStatus.NEEDS_REVIEW,
        )
        reviewed_event = ExtractedEvent(
            user_id=USER_A,
            semester_id=semester.id,
            course_id=second_course.id,
            document_id=second_document.id,
            title="Quiz 1",
            event_type="quiz",
            event_date=date(2026, 9, 15),
            timezone="America/New_York",
            is_all_day=True,
            source_quote="Quiz 1 takes place on September 15",
            source_page=2,
            confidence=ConfidenceLevel.HIGH,
            warning_codes=[],
            review_status=ReviewStatus.CONFIRMED,
        )
        session.add_all([blocking_event, reviewed_event])
        session.commit()
        return semester.id, blocking_event.id, first_document.id


def seed_reprocess_data(app) -> tuple[UUID, UUID, UUID, str]:
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
        document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="cs101.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/cs101.pdf",
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
            primary_model="gpt-5.6-luna",
            fallback_model="gpt-5.6-terra",
            fallback_used=False,
            fallback_reason_codes=[],
        )
        session.add_all([course, job])
        session.flush()
        event = ExtractedEvent(
            user_id=USER_A,
            semester_id=semester.id,
            course_id=course.id,
            document_id=document.id,
            title="Old midterm",
            event_type="exam",
            event_date=date(2026, 10, 10),
            timezone="America/New_York",
            is_all_day=True,
            source_quote="Old midterm October 10, 2026",
            source_page=1,
            confidence=ConfidenceLevel.HIGH,
            warning_codes=[],
            warning_reason=None,
            extraction_model="gpt-5.6-luna",
            fallback_reason_codes=[],
            review_status=ReviewStatus.CONFIRMED,
        )
        session.add(event)
        session.commit()
        return semester.id, job.id, document.id, document.storage_key


def test_course_details_can_be_corrected_during_review(app_client):
    client, app = app_client
    semester_id, _, _ = seed_review_data(app)
    review = client.get(f"/api/semesters/{semester_id}/review", headers=auth_headers()).json()
    course_id = review["courses"][0]["id"]

    response = client.patch(
        f"/api/courses/{course_id}",
        headers=auth_headers(),
        json={"code": "CSCI 101", "name": "Foundations of Computing", "instructor": "Dr. Rivera"},
    )

    assert response.status_code == 200
    assert response.json()["code"] == "CSCI 101"
    assert response.json()["name"] == "Foundations of Computing"
    assert response.json()["instructor"] == "Dr. Rivera"


def test_course_name_update_rejects_explicit_null(app_client):
    client, app = app_client
    semester_id, _, _ = seed_review_data(app)
    review = client.get(f"/api/semesters/{semester_id}/review", headers=auth_headers()).json()
    course_id = review["courses"][0]["id"]

    response = client.patch(
        f"/api/courses/{course_id}",
        headers=auth_headers(),
        json={"name": None},
    )

    assert response.status_code == 422


def test_course_code_and_instructor_can_be_cleared(app_client):
    client, app = app_client
    semester_id, _, _ = seed_review_data(app)
    review = client.get(f"/api/semesters/{semester_id}/review", headers=auth_headers()).json()
    course = review["courses"][0]

    response = client.patch(
        f"/api/courses/{course['id']}",
        headers=auth_headers(),
        json={"code": None, "instructor": None},
    )

    assert response.status_code == 200
    assert response.json()["code"] is None
    assert response.json()["instructor"] is None
    assert response.json()["name"] == course["name"]


def test_course_color_can_be_corrected_during_review_and_persists(app_client):
    client, app = app_client
    semester_id, _, _ = seed_review_data(app)
    review = client.get(f"/api/semesters/{semester_id}/review", headers=auth_headers()).json()
    course = review["courses"][0]

    response = client.patch(
        f"/api/courses/{course['id']}",
        headers=auth_headers(),
        json={"color": "#2563EB"},
    )

    assert response.status_code == 200
    assert response.json()["color"] == "#2563EB"
    assert response.json()["code"] == course["code"]
    assert response.json()["name"] == course["name"]
    assert response.json()["instructor"] == course["instructor"]

    refreshed_review = client.get(
        f"/api/semesters/{semester_id}/review",
        headers=auth_headers(),
    )

    assert refreshed_review.status_code == 200
    assert refreshed_review.json()["courses"][0]["color"] == "#2563EB"


def test_course_color_accepts_lowercase_hex_and_persists(app_client):
    client, app = app_client
    semester_id, _, _ = seed_review_data(app)
    review = client.get(f"/api/semesters/{semester_id}/review", headers=auth_headers()).json()
    course_id = review["courses"][0]["id"]

    response = client.patch(
        f"/api/courses/{course_id}",
        headers=auth_headers(),
        json={"color": "#0d9488"},
    )

    assert response.status_code == 200
    assert response.json()["color"] == "#0d9488"

    refreshed_review = client.get(
        f"/api/semesters/{semester_id}/review",
        headers=auth_headers(),
    )

    assert refreshed_review.status_code == 200
    assert refreshed_review.json()["courses"][0]["color"] == "#0d9488"


@pytest.mark.parametrize(
    "payload",
    [
        {"color": None},
        {"color": "2563EB"},
        {"color": "#12345"},
        {"color": "#1234567"},
        {"color": "#12FG56"},
    ],
)
def test_course_color_update_rejects_null_and_invalid_values(app_client, payload):
    client, app = app_client
    semester_id, _, _ = seed_review_data(app)
    review = client.get(f"/api/semesters/{semester_id}/review", headers=auth_headers()).json()
    course_id = review["courses"][0]["id"]

    response = client.patch(
        f"/api/courses/{course_id}",
        headers=auth_headers(),
        json=payload,
    )

    assert response.status_code == 422


def test_other_user_cannot_patch_course(app_client):
    client, app = app_client
    semester_id, _, _ = seed_review_data(app)
    review = client.get(f"/api/semesters/{semester_id}/review", headers=auth_headers()).json()
    course_id = review["courses"][0]["id"]

    response = client.patch(
        f"/api/courses/{course_id}",
        headers=auth_headers(USER_B),
        json={"color": "#2563EB"},
    )

    assert response.status_code == 404


def test_review_exposes_evidence_and_allows_confirm_or_ignore(app_client):
    client, app = app_client
    semester_id, _, event_id = seed_review_data(app)

    review = client.get(
        f"/api/semesters/{semester_id}/review",
        headers=auth_headers(),
    )

    assert review.status_code == 200
    event = next(item for item in review.json()["events"] if item["id"] == str(event_id))
    assert event["source_page"] == 5
    assert event["source_quote"] == "Final project due around December 10"
    assert event["warning_codes"] == ["AMBIGUOUS_DATE"]
    assert event["warning_reason"] == "The syllabus says around December 10."

    update = client.patch(
        f"/api/extracted-events/{event_id}",
        headers=auth_headers(),
        json={"event_date": "2026-12-11", "review_status": "confirmed"},
    )

    assert update.status_code == 200
    assert update.json()["event_date"] == "2026-12-11"
    assert update.json()["review_status"] == "confirmed"


def test_review_sanitizes_legacy_syllabus_typo_without_reprocessing(app_client):
    client, app = app_client
    semester_id, _, event_id = seed_legacy_syllabus_typo_review_data(app)

    review = client.get(
        f"/api/semesters/{semester_id}/review",
        headers=auth_headers(),
    )

    assert review.status_code == 200
    event = next(item for item in review.json()["events"] if item["id"] == str(event_id))
    assert event["extraction_model"] == "gpt-5.6-terra"
    assert event["warning_codes"] == ["DATE_CONFLICT"]
    assert (
        event["warning_reason"]
        == "Syllabus typo. The written date and weekday do not match. The numeric date was kept."
    )
    assert event["fallback_reason_codes"] == []
    assert event["derivation_summary"] is None


def test_update_event_response_sanitizes_legacy_syllabus_typo_fields(app_client):
    client, app = app_client
    _, _, event_id = seed_legacy_syllabus_typo_review_data(app)

    response = client.patch(
        f"/api/extracted-events/{event_id}",
        headers=auth_headers(),
        json={"title": "No lecture / Friday schedule"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["extraction_model"] == "gpt-5.6-terra"
    assert payload["warning_codes"] == ["DATE_CONFLICT"]
    assert (
        payload["warning_reason"]
        == "Syllabus typo. The written date and weekday do not match. The numeric date was kept."
    )
    assert payload["fallback_reason_codes"] == []
    assert payload["derivation_summary"] is None


def test_jobs_sanitize_legacy_syllabus_typo_fallback_when_it_is_the_only_reason(app_client):
    client, app = app_client
    semester_id, _, _ = seed_legacy_syllabus_typo_review_data(app)

    response = client.get(
        f"/api/semesters/{semester_id}/jobs",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()[0]["fallback_used"] is False
    assert response.json()[0]["fallback_reason_codes"] == []


def test_legacy_typo_compatibility_keeps_a_real_cross_event_conflict_visible(app_client):
    client, app = app_client
    semester_id, _, event_id = seed_legacy_syllabus_typo_review_data(app)
    with app.state.session_factory() as session:
        original = session.get(ExtractedEvent, event_id)
        assert original is not None
        second_document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester_id,
            filename="registrar-update.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester_id}/registrar-update.pdf",
        )
        session.add(second_document)
        session.flush()
        session.add(
            ExtractedEvent(
                user_id=USER_A,
                semester_id=semester_id,
                course_id=original.course_id,
                document_id=second_document.id,
                title=original.title,
                event_type="class",
                event_date=date(2025, 11, 26),
                timezone="America/New_York",
                is_all_day=True,
                source_quote="Registrar update lists November 26",
                source_page=1,
                confidence=ConfidenceLevel.HIGH,
                warning_codes=[],
                review_status=ReviewStatus.NEEDS_REVIEW,
            )
        )
        session.commit()

    review = client.get(
        f"/api/semesters/{semester_id}/review",
        headers=auth_headers(),
    )
    jobs = client.get(
        f"/api/semesters/{semester_id}/jobs",
        headers=auth_headers(),
    )

    assert review.status_code == 200
    event = next(item for item in review.json()["events"] if item["id"] == str(event_id))
    assert "MODEL_UNCERTAINTY" in event["warning_codes"]
    assert "Terra repaired Date Conflict" in event["warning_reason"]
    assert event["fallback_reason_codes"] == ["DATE_CONFLICT"]
    assert jobs.json()[0]["fallback_used"] is True
    assert jobs.json()[0]["fallback_reason_codes"] == ["DATE_CONFLICT"]


def test_review_exposes_recurring_series_and_model_audit_fields(app_client):
    client, app = app_client
    semester_id, series_id, _ = seed_recurring_series_data(app)

    review = client.get(
        f"/api/semesters/{semester_id}/review",
        headers=auth_headers(),
    )

    assert review.status_code == 200
    payload = review.json()
    series = next(item for item in payload["recurring_series"] if item["id"] == str(series_id))
    event = next(
        item for item in payload["events"] if item["recurring_series_id"] == str(series_id)
    )
    assert series["rule_payload"]["weekday"] == "friday"
    assert series["extraction_model"] == "gpt-5.6-luna"
    assert series["fallback_reason_codes"] == []
    assert series["review_status"] == "needs_review"
    assert event["extraction_model"] == "gpt-5.6-luna"
    assert event["fallback_reason_codes"] == []
    jobs = client.get(f"/api/semesters/{semester_id}/jobs", headers=auth_headers()).json()
    assert jobs[0]["primary_model"] == "gpt-5.6-luna"
    assert jobs[0]["fallback_model"] == "gpt-5.6-terra"
    assert jobs[0]["fallback_used"] is True
    assert jobs[0]["fallback_reason_codes"] == ["LOW_CONFIDENCE", "SOURCE_MISMATCH"]


def test_semester_list_counts_unresolved_recurring_series_once(app_client):
    client, app = app_client
    semester_id, _, _ = seed_recurring_series_data(app)

    response = client.get("/api/semesters", headers=auth_headers())

    assert response.status_code == 200
    semester = next(item for item in response.json() if item["id"] == str(semester_id))
    assert semester["event_count"] == 2
    assert semester["needs_review_count"] == 1


def test_patch_recurring_series_updates_member_review_statuses(app_client):
    client, app = app_client
    _, series_id, _ = seed_recurring_series_data(app)

    response = client.patch(
        f"/api/recurring-series/{series_id}",
        headers=auth_headers(),
        json={"review_status": "confirmed"},
    )

    assert response.status_code == 200
    assert response.json()["review_status"] == "confirmed"
    with app.state.session_factory() as session:
        statuses = [
            event.review_status.value
            for event in session.query(ExtractedEvent)
            .where(ExtractedEvent.recurring_series_id == series_id)
            .all()
        ]
    assert statuses == ["confirmed", "confirmed"]


def test_patch_recurring_series_preserves_ignored_members_until_restore(app_client):
    client, app = app_client
    _, series_id, _ = seed_recurring_series_data(app)
    with app.state.session_factory() as session:
        ignored = (
            session.query(ExtractedEvent)
            .where(ExtractedEvent.recurring_series_id == series_id)
            .order_by(ExtractedEvent.event_date.asc())
            .first()
        )
        ignored.review_status = ReviewStatus.IGNORED
        session.commit()

    pending = client.patch(
        f"/api/recurring-series/{series_id}",
        headers=auth_headers(),
        json={"review_status": "pending"},
    )
    assert pending.status_code == 200
    with app.state.session_factory() as session:
        statuses = [
            event.review_status.value
            for event in session.query(ExtractedEvent)
            .where(ExtractedEvent.recurring_series_id == series_id)
            .order_by(ExtractedEvent.event_date.asc())
            .all()
        ]
    assert statuses == ["ignored", "pending"]

    restored = client.patch(
        f"/api/recurring-series/{series_id}",
        headers=auth_headers(),
        json={"review_status": "needs_review"},
    )
    assert restored.status_code == 200
    with app.state.session_factory() as session:
        statuses = [
            event.review_status.value
            for event in session.query(ExtractedEvent)
            .where(ExtractedEvent.recurring_series_id == series_id)
            .order_by(ExtractedEvent.event_date.asc())
            .all()
        ]
    assert statuses == ["needs_review", "needs_review"]


@pytest.mark.parametrize("next_status", ["confirmed", "pending"])
def test_recurring_series_preserves_removal_committed_after_loading(
    app_client, monkeypatch, next_status,
):
    from sqlalchemy import update
    from sqlalchemy.orm import Session

    client, app = app_client
    _, series_id, _ = seed_recurring_series_data(app)
    original_scalar = Session.scalar
    removed_ids = []

    def load_then_remove(session, statement, *args, **kwargs):
        result = original_scalar(session, statement, *args, **kwargs)
        if isinstance(result, RecurringEventSeries) and not removed_ids:
            removed_ids.append(result.events[0].id)
            # The competing individual request commits after the bulk request
            # loads its snapshot but before it changes the series members.
            with app.state.session_factory() as concurrent:
                concurrent.execute(update(ExtractedEvent).where(
                    ExtractedEvent.id == removed_ids[0],
                ).values(review_status=ReviewStatus.IGNORED))
                concurrent.commit()
        return result

    monkeypatch.setattr(Session, "scalar", load_then_remove)
    response = client.patch(
        f"/api/recurring-series/{series_id}", headers=auth_headers(),
        json={"review_status": next_status},
    )
    assert response.status_code == 200
    assert response.json()["review_status"] == "mixed"
    with app.state.session_factory() as session:
        assert session.get(ExtractedEvent, removed_ids[0]).review_status == ReviewStatus.IGNORED
        statuses = [event.review_status.value for event in session.query(ExtractedEvent)
                    .where(ExtractedEvent.recurring_series_id == series_id).all()]
        assert sorted(statuses) == sorted(["ignored", next_status])


def test_other_user_cannot_patch_recurring_series(app_client):
    client, app = app_client
    _, series_id, _ = seed_recurring_series_data(app)

    response = client.patch(
        f"/api/recurring-series/{series_id}",
        headers=auth_headers(USER_B),
        json={"review_status": "confirmed"},
    )

    assert response.status_code == 404


def test_review_must_resolve_every_event_before_completion(app_client):
    client, app = app_client
    semester_id, _, event_id = seed_review_data(app)

    blocked = client.post(
        f"/api/semesters/{semester_id}/review/complete",
        headers=auth_headers(),
    )
    assert blocked.status_code == 409

    client.patch(
        f"/api/extracted-events/{event_id}",
        headers=auth_headers(),
        json={"review_status": "ignored"},
    )
    completed = client.post(
        f"/api/semesters/{semester_id}/review/complete",
        headers=auth_headers(),
    )

    assert completed.status_code == 200
    assert completed.json()["review_completed_at"] is not None
    jobs = client.get(f"/api/semesters/{semester_id}/jobs", headers=auth_headers()).json()
    assert jobs[0]["status"] == "completed"


def test_reprocess_job_replaces_events_and_resets_review_complete_on_success(
    app_client, monkeypatch
):
    client, app = app_client
    semester_id, job_id, _, storage_key = seed_reprocess_data(app)
    upload_root = Path(app.state.settings.local_storage_path)
    file_path = upload_root / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(make_pdf("CS 101 Midterm exam October 14, 2026. " * 8))

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
        titles = [event.title for event in session.query(ExtractedEvent).all()]
        assert titles == ["New midterm"]
        assert semester.review_completed_at is None


def test_reprocess_job_preserves_an_existing_course_color(app_client, monkeypatch):
    client, app = app_client
    semester_id, job_id, document_id, storage_key = seed_reprocess_data(app)
    upload_root = Path(app.state.settings.local_storage_path)
    file_path = upload_root / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(make_pdf("CS 101 Midterm exam October 14, 2026. " * 8))

    with app.state.session_factory() as session:
        course = session.query(Course).filter(Course.semester_id == semester_id).one()
        course.document_id = document_id
        course.color = "#F97316"
        session.commit()

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
    with app.state.session_factory() as session:
        course = session.query(Course).filter(Course.document_id == document_id).one()
        semester = session.get(Semester, semester_id)
        assert course.color == "#F97316"
        assert semester.review_completed_at is None


def test_reprocess_job_keeps_previous_review_data_when_processing_fails(
    app_client, monkeypatch
):
    client, app = app_client
    semester_id, job_id, _, storage_key = seed_reprocess_data(app)
    upload_root = Path(app.state.settings.local_storage_path)
    file_path = upload_root / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(make_pdf("CS 101 Midterm exam October 14, 2026. " * 8))

    monkeypatch.setattr(
        "app.processing.extract_syllabus",
        lambda pages, settings: (_ for _ in ()).throw(RuntimeError("parse exploded")),
    )

    response = client.post(f"/api/jobs/{job_id}/reprocess", headers=auth_headers())

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    with app.state.session_factory() as session:
        semester = session.get(Semester, semester_id)
        titles = [event.title for event in session.query(ExtractedEvent).all()]
        assert titles == ["Old midterm"]
        assert semester.review_completed_at == datetime(2026, 8, 25)


def test_reprocess_job_keeps_previous_review_data_when_failure_happens_after_delete(
    app_client, monkeypatch
):
    client, app = app_client
    semester_id, job_id, _, storage_key = seed_reprocess_data(app)
    upload_root = Path(app.state.settings.local_storage_path)
    file_path = upload_root / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(make_pdf("CS 101 Midterm exam October 14, 2026. " * 8))

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
    monkeypatch.setattr(
        "app.processing.expand_recurring_rules",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("series exploded")),
    )

    response = client.post(f"/api/jobs/{job_id}/reprocess", headers=auth_headers())

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    with app.state.session_factory() as session:
        semester = session.get(Semester, semester_id)
        titles = [event.title for event in session.query(ExtractedEvent).all()]
        assert titles == ["Old midterm"]
        assert semester.review_completed_at == datetime(2026, 8, 25)


def test_reprocess_rejects_active_or_failed_jobs(app_client):
    client, app = app_client
    _, active_job_id, _, _ = seed_reprocess_data(app)
    with app.state.session_factory() as session:
        active_job = session.get(ProcessingJob, active_job_id)
        active_job.status = JobStatus.EXTRACTING_EVENTS
        failed_document = SyllabusDocument(
            user_id=USER_A,
            semester_id=active_job.semester_id,
            filename="failed.pdf",
            content_type="application/pdf",
            size_bytes=20,
            storage_key=f"{USER_A}/{active_job.semester_id}/failed.pdf",
        )
        failed_job = ProcessingJob(
            user_id=USER_A,
            semester_id=active_job.semester_id,
            document=failed_document,
            status=JobStatus.FAILED,
        )
        session.add(failed_job)
        session.commit()
        failed_job_id = failed_job.id

    active = client.post(f"/api/jobs/{active_job_id}/reprocess", headers=auth_headers())
    failed = client.post(f"/api/jobs/{failed_job_id}/reprocess", headers=auth_headers())

    assert active.status_code == 409
    assert active.json()["detail"] == "Only completed or reviewable jobs can be reprocessed."
    assert failed.status_code == 409
    assert failed.json()["detail"] == "Use retry for failed jobs."


def test_review_completion_returns_blocking_event_and_document_ids(app_client):
    client, app = app_client
    semester_id, blocking_event_id, blocking_document_id = seed_hidden_blocker_review_data(app)

    blocked = client.post(
        f"/api/semesters/{semester_id}/review/complete",
        headers=auth_headers(),
    )

    assert blocked.status_code == 409
    assert blocked.json() == {
        "detail": "Resolve every event before finishing review.",
        "blocking_event_ids": [str(blocking_event_id)],
        "blocking_document_ids": [str(blocking_document_id)],
        "blocking_count": 1,
    }


def test_undated_item_can_stay_pending_but_cannot_be_confirmed(app_client):
    client, app = app_client
    semester_id, confirmed_id, event_id = seed_review_data(app)
    with app.state.session_factory() as session:
        event = session.get(ExtractedEvent, event_id)
        event.event_date = None
        event.warning_codes = ["DATE_MISSING"]
        event.warning_reason = "The event does not have a confirmed date."
        session.commit()

    rejected = client.patch(
        f"/api/extracted-events/{event_id}",
        headers=auth_headers(),
        json={"review_status": "confirmed"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "Add a date before confirming this event."

    pending = client.patch(
        f"/api/extracted-events/{event_id}",
        headers=auth_headers(),
        json={"review_status": "pending"},
    )
    assert pending.status_code == 200
    assert pending.json()["event_date"] is None
    assert pending.json()["review_status"] == "pending"

    completed = client.post(
        f"/api/semesters/{semester_id}/review/complete",
        headers=auth_headers(),
    )
    assert completed.status_code == 200
    events = client.get(
        f"/api/semesters/{semester_id}/events",
        headers=auth_headers(),
    ).json()
    assert [event["id"] for event in events] == [str(confirmed_id)]

    calendar = client.get(
        f"/api/semesters/{semester_id}/calendar.ics",
        headers=auth_headers(),
    )
    assert calendar.status_code == 200
    assert "Midterm exam" in calendar.text
    assert "Final project" not in calendar.text


def test_course_rule_cannot_be_confirmed_as_single_event_and_state_does_not_mutate(
    app_client,
):
    client, app = app_client
    _, _, event_id = seed_course_rule_review_data(app)

    rejected = client.patch(
        f"/api/extracted-events/{event_id}",
        headers=auth_headers(),
        json={
            "title": "Changed title",
            "event_date": "2026-09-11",
            "review_status": "confirmed",
        },
    )

    assert rejected.status_code == 422
    assert (
        rejected.json()["detail"]
        == "Course rules cannot be published as a single calendar event."
    )

    with app.state.session_factory() as session:
        event = session.get(ExtractedEvent, event_id)
        assert event is not None
        assert event.title == "Exercise Sets"
        assert event.event_date is None
        assert event.review_status == ReviewStatus.NEEDS_REVIEW


def test_course_rule_can_be_saved_pending_and_no_longer_blocks_review_completion(
    app_client,
):
    client, app = app_client
    semester_id, confirmed_id, event_id = seed_course_rule_review_data(app)

    pending = client.patch(
        f"/api/extracted-events/{event_id}",
        headers=auth_headers(),
        json={"review_status": "pending"},
    )

    assert pending.status_code == 200
    assert pending.json()["review_status"] == "pending"
    assert pending.json()["event_date"] is None

    completed = client.post(
        f"/api/semesters/{semester_id}/review/complete",
        headers=auth_headers(),
    )

    assert completed.status_code == 200
    events = client.get(
        f"/api/semesters/{semester_id}/events",
        headers=auth_headers(),
    ).json()
    assert [event["id"] for event in events] == [str(confirmed_id)]


def test_legacy_confirmed_course_rule_still_rejects_partial_updates_without_mutation(
    app_client,
):
    client, app = app_client
    _, _, event_id = seed_course_rule_review_data(app)
    with app.state.session_factory() as session:
        event = session.get(ExtractedEvent, event_id)
        event.review_status = ReviewStatus.CONFIRMED
        event.event_date = date(2026, 9, 11)
        session.commit()

    rejected = client.patch(
        f"/api/extracted-events/{event_id}",
        headers=auth_headers(),
        json={"title": "Edited legacy rule"},
    )

    assert rejected.status_code == 422
    assert (
        rejected.json()["detail"]
        == "Course rules cannot be published as a single calendar event."
    )

    with app.state.session_factory() as session:
        event = session.get(ExtractedEvent, event_id)
        assert event is not None
        assert event.title == "Exercise Sets"
        assert event.event_date == date(2026, 9, 11)
        assert event.review_status == ReviewStatus.CONFIRMED


def test_exact_recurring_series_event_can_still_be_confirmed(app_client):
    client, app = app_client
    _, series_id, _ = seed_recurring_series_data(app)
    with app.state.session_factory() as session:
        event_id = session.scalar(
            select(ExtractedEvent.id)
            .where(ExtractedEvent.recurring_series_id == series_id)
            .order_by(ExtractedEvent.event_date.asc())
        )

    confirmed = client.patch(
        f"/api/extracted-events/{event_id}",
        headers=auth_headers(),
        json={"review_status": "confirmed"},
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["review_status"] == "confirmed"
    assert confirmed.json()["recurring_series_id"] == str(series_id)


def test_legacy_confirmed_course_rule_is_excluded_from_confirmed_events_api(app_client):
    client, app = app_client
    semester_id, confirmed_id, event_id = seed_course_rule_review_data(app)
    with app.state.session_factory() as session:
        event = session.get(ExtractedEvent, event_id)
        event.review_status = ReviewStatus.CONFIRMED
        event.event_date = date(2026, 9, 11)
        session.commit()

    events = client.get(
        f"/api/semesters/{semester_id}/events",
        headers=auth_headers(),
    )

    assert events.status_code == 200
    assert [event["id"] for event in events.json()] == [str(confirmed_id)]


def test_legacy_confirmed_course_rule_is_excluded_from_ics_export(app_client):
    client, app = app_client
    semester_id, _, event_id = seed_course_rule_review_data(app)
    with app.state.session_factory() as session:
        event = session.get(ExtractedEvent, event_id)
        event.review_status = ReviewStatus.CONFIRMED
        event.event_date = date(2026, 9, 11)
        session.commit()

    response = client.get(
        f"/api/semesters/{semester_id}/calendar.ics",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    calendar = Calendar.from_ical(response.content)
    calendar_events = [item for item in calendar.walk() if item.name == "VEVENT"]
    assert len(calendar_events) == 1
    assert str(calendar_events[0]["SUMMARY"]) == "CS 101 · Midterm exam"


def test_calendar_and_ics_include_only_confirmed_events(app_client):
    client, app = app_client
    semester_id, confirmed_id, _ = seed_review_data(app)

    events = client.get(
        f"/api/semesters/{semester_id}/events",
        headers=auth_headers(),
    )
    assert events.status_code == 200
    assert [event["id"] for event in events.json()] == [str(confirmed_id)]

    response = client.get(
        f"/api/semesters/{semester_id}/calendar.ics",
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    calendar = Calendar.from_ical(response.content)
    calendar_events = [item for item in calendar.walk() if item.name == "VEVENT"]
    assert len(calendar_events) == 1
    assert str(calendar_events[0]["SUMMARY"]) == "CS 101 · Midterm exam"
    assert calendar_events[0].decoded("DTEND") == date(2026, 10, 14) + timedelta(days=1)


def test_calendar_download_filename_neutralizes_header_metacharacters(app_client):
    client, _ = app_client
    semester = client.post(
        "/api/semesters",
        headers=auth_headers(),
        json={
            "name": 'Fall\"; filename=\"attacker',
            "start_date": "2026-08-24",
            "end_date": "2026-12-18",
            "timezone": "America/New_York",
        },
    )
    semester_id = semester.json()["id"]

    response = client.get(
        f"/api/semesters/{semester_id}/calendar.ics",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="fall-filename-attacker.ics"'
    )


def test_other_user_cannot_access_review_files_events_or_calendar(app_client):
    client, app = app_client
    semester_id, _, event_id = seed_review_data(app)
    own_review = client.get(
        f"/api/semesters/{semester_id}/review",
        headers=auth_headers(),
    ).json()
    document_id = own_review["documents"][0]["id"]

    assert (
        client.get(
            f"/api/semesters/{semester_id}/review",
            headers=auth_headers(USER_B),
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/extracted-events/{event_id}",
            headers=auth_headers(USER_B),
            json={"review_status": "confirmed"},
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/syllabus-documents/{document_id}/file",
            headers=auth_headers(USER_B),
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/semesters/{semester_id}/calendar.ics",
            headers=auth_headers(USER_B),
        ).status_code
        == 404
    )


def seed_delete_semester_data(app) -> tuple[UUID, str, str]:
    session_factory = app.state.session_factory
    with session_factory() as session:
        semester = Semester(
            user_id=USER_A,
            name="Delete Me",
            start_date=date(2026, 8, 24),
            end_date=date(2026, 12, 18),
            timezone="America/New_York",
        )
        session.add(semester)
        session.flush()
        first_key = f"{USER_A}/{semester.id}/doc-1/syllabus-1.pdf"
        second_key = f"{USER_A}/{semester.id}/doc-2/syllabus-2.pdf"
        first_document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="syllabus-1.pdf",
            content_type="application/pdf",
            size_bytes=101,
            storage_key=first_key,
        )
        second_document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="syllabus-2.pdf",
            content_type="application/pdf",
            size_bytes=102,
            storage_key=second_key,
        )
        session.add_all([first_document, second_document])
        session.flush()
        first_course = Course(
            user_id=USER_A,
            semester_id=semester.id,
            document_id=first_document.id,
            code="CS 101",
            name="Introduction to Computer Science",
            color="#0D9488",
        )
        second_course = Course(
            user_id=USER_A,
            semester_id=semester.id,
            document_id=second_document.id,
            code="MATH 201",
            name="Discrete Math",
            color="#2563EB",
        )
        session.add_all([first_course, second_course])
        session.flush()
        session.add_all(
            [
                ProcessingJob(
                    user_id=USER_A,
                    semester_id=semester.id,
                    document=first_document,
                    status=JobStatus.NEEDS_REVIEW,
                ),
                ProcessingJob(
                    user_id=USER_A,
                    semester_id=semester.id,
                    document=second_document,
                    status=JobStatus.COMPLETED,
                ),
                ExtractedEvent(
                    user_id=USER_A,
                    semester_id=semester.id,
                    course_id=first_course.id,
                    document_id=first_document.id,
                    title="First exam",
                    event_type="exam",
                    event_date=date(2026, 9, 15),
                    timezone="America/New_York",
                    is_all_day=True,
                    source_quote="First exam September 15",
                    source_page=2,
                    confidence=ConfidenceLevel.HIGH,
                    warning_codes=[],
                    review_status=ReviewStatus.CONFIRMED,
                ),
                ExtractedEvent(
                    user_id=USER_A,
                    semester_id=semester.id,
                    course_id=second_course.id,
                    document_id=second_document.id,
                    title="Problem set",
                    event_type="assignment",
                    event_date=date(2026, 9, 18),
                    timezone="America/New_York",
                    is_all_day=True,
                    source_quote="Problem set September 18",
                    source_page=4,
                    confidence=ConfidenceLevel.MEDIUM,
                    warning_codes=[],
                    review_status=ReviewStatus.NEEDS_REVIEW,
                ),
            ]
        )
        session.commit()
        return semester.id, first_key, second_key


def write_uploaded_files(app, payloads: dict[str, bytes]) -> None:
    upload_root = Path(app.state.settings.local_storage_path)
    for storage_key, content in payloads.items():
        path = upload_root / storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def test_delete_semester_removes_owned_descendants_and_storage_keys(app_client, monkeypatch):
    client, app = app_client
    semester_id, first_key, second_key = seed_delete_semester_data(app)
    deleted_keys: list[str] = []

    def fake_delete_many(self, storage_keys: list[str]) -> list:
        deleted_keys.extend(storage_keys)
        return []

    monkeypatch.setattr("app.api.StorageService.delete_many", fake_delete_many)

    response = client.delete(f"/api/semesters/{semester_id}", headers=auth_headers())

    assert response.status_code == 204
    assert response.content == b""
    assert deleted_keys == [first_key, second_key]
    with app.state.session_factory() as session:
        assert session.get(Semester, semester_id) is None
        assert session.query(SyllabusDocument).count() == 0
        assert session.query(Course).count() == 0
        assert session.query(ExtractedEvent).count() == 0
        assert session.query(ProcessingJob).count() == 0


def test_delete_semester_returns_404_for_other_user(app_client, monkeypatch):
    client, app = app_client
    semester_id, _, _ = seed_delete_semester_data(app)
    delete_many_calls: list[list[str]] = []

    def fake_delete_many(self, storage_keys: list[str]) -> list:
        delete_many_calls.append(storage_keys)
        return []

    monkeypatch.setattr("app.api.StorageService.delete_many", fake_delete_many)

    response = client.delete(f"/api/semesters/{semester_id}", headers=auth_headers(USER_B))

    assert response.status_code == 404
    assert delete_many_calls == []


def test_delete_semester_preserves_database_when_storage_delete_fails(app_client, monkeypatch):
    client, app = app_client
    semester_id, _, _ = seed_delete_semester_data(app)

    def fail_delete_many(self, storage_keys: list[str]) -> None:
        raise StorageError(f"failed to delete {storage_keys[0]}")

    monkeypatch.setattr("app.api.StorageService.delete_many", fail_delete_many)

    response = client.delete(f"/api/semesters/{semester_id}", headers=auth_headers())

    assert response.status_code == 502
    assert response.json()["detail"].startswith("failed to delete ")

    with app.state.session_factory() as session:
        assert session.get(Semester, semester_id) is not None
        assert session.query(SyllabusDocument).count() == 2
        assert session.query(Course).count() == 2
        assert session.query(ExtractedEvent).count() == 2
        assert session.query(ProcessingJob).count() == 2


def test_delete_semester_restores_deleted_files_when_database_commit_fails(app_client, monkeypatch):
    client, app = app_client
    semester_id, first_key, second_key = seed_delete_semester_data(app)
    first_bytes = b"%PDF-1.4 first"
    second_bytes = b"%PDF-1.4 second"
    write_uploaded_files(
        app,
        {
            first_key: first_bytes,
            second_key: second_bytes,
        },
    )

    def fail_commit(self):
        raise RuntimeError("commit exploded")

    monkeypatch.setattr(Session, "commit", fail_commit)

    response = client.delete(f"/api/semesters/{semester_id}", headers=auth_headers())

    assert response.status_code == 500
    assert response.json()["detail"] == "Semester deletion could not be completed."
    upload_root = Path(app.state.settings.local_storage_path)
    assert (upload_root / first_key).read_bytes() == first_bytes
    assert (upload_root / second_key).read_bytes() == second_bytes
    with app.state.session_factory() as session:
        assert session.get(Semester, semester_id) is not None
        assert session.query(SyllabusDocument).count() == 2
        assert session.query(Course).count() == 2
        assert session.query(ExtractedEvent).count() == 2
        assert session.query(ProcessingJob).count() == 2


def test_delete_semester_reports_restore_failure_after_database_rollback(app_client, monkeypatch):
    client, app = app_client
    semester_id, first_key, second_key = seed_delete_semester_data(app)
    write_uploaded_files(
        app,
        {
            first_key: b"%PDF-1.4 first",
            second_key: b"%PDF-1.4 second",
        },
    )

    def fail_commit(self):
        raise RuntimeError("commit exploded")

    def fail_restore_many(self, backups):
        raise StorageError("could not restore deleted files")

    monkeypatch.setattr(Session, "commit", fail_commit)
    monkeypatch.setattr("app.api.StorageService.restore_many", fail_restore_many)

    response = client.delete(f"/api/semesters/{semester_id}", headers=auth_headers())

    assert response.status_code == 502
    expected_detail = (
        "Semester deletion rolled back, but storage restoration failed. "
        "could not restore deleted files"
    )
    assert response.json()["detail"] == expected_detail
    with app.state.session_factory() as session:
        assert session.get(Semester, semester_id) is not None


def test_calendar_ics_accepts_repeated_course_id_filters(app_client):
    client, app = app_client
    semester_id, _, _ = seed_hidden_blocker_review_data(app)
    review = client.get(f"/api/semesters/{semester_id}/review", headers=auth_headers()).json()
    first_course_id = next(
        course["id"] for course in review["courses"] if course["code"] == "CS 101"
    )
    second_course_id = next(
        course["id"] for course in review["courses"] if course["code"] == "MATH 201"
    )

    all_courses = client.get(
        f"/api/semesters/{semester_id}/calendar.ics",
        headers=auth_headers(),
    )
    first_course_only = client.get(
        f"/api/semesters/{semester_id}/calendar.ics?course_id={first_course_id}",
        headers=auth_headers(),
    )
    second_course_only = client.get(
        f"/api/semesters/{semester_id}/calendar.ics?course_id={second_course_id}",
        headers=auth_headers(),
    )
    repeated_filter = client.get(
        f"/api/semesters/{semester_id}/calendar.ics?course_id={first_course_id}&course_id={second_course_id}",
        headers=auth_headers(),
    )

    def summaries(response):
        calendar = Calendar.from_ical(response.content)
        return [
            str(item["SUMMARY"])
            for item in calendar.walk()
            if item.name == "VEVENT"
        ]

    assert all_courses.status_code == 200
    assert summaries(all_courses) == [summaries(all_courses)[0]]
    assert "MATH 201" in summaries(all_courses)[0]
    assert "Quiz 1" in summaries(all_courses)[0]
    assert summaries(first_course_only) == []
    assert summaries(second_course_only) == [summaries(all_courses)[0]]
    assert summaries(repeated_filter) == [summaries(all_courses)[0]]


@pytest.mark.parametrize(
    ("course_ids", "expected_status"),
    [
        ("?course_id=not-a-uuid", 422),
        ("?course_id=33333333-3333-4333-8333-333333333333", 200),
    ],
)
def test_calendar_ics_filter_validation_and_nonmatching_course_behavior(
    app_client,
    course_ids,
    expected_status,
):
    client, app = app_client
    semester_id, _, _ = seed_review_data(app)

    response = client.get(
        f"/api/semesters/{semester_id}/calendar.ics{course_ids}",
        headers=auth_headers(),
    )

    assert response.status_code == expected_status
