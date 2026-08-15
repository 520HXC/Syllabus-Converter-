from __future__ import annotations

from datetime import date
from uuid import uuid4

from app.models import (
    ConfidenceLevel,
    Course,
    ExtractedEvent,
    ReviewStatus,
    Semester,
    SyllabusDocument,
)

from .conftest import USER_B, auth_headers


def test_create_semester_persists_and_is_isolated_by_user(app_client):
    client, _ = app_client
    response = client.post(
        "/api/semesters",
        headers=auth_headers(),
        json={
            "name": "Fall 2026",
            "start_date": "2026-08-24",
            "end_date": "2026-12-18",
            "timezone": "America/New_York",
        },
    )

    assert response.status_code == 201
    semester = response.json()
    assert semester["name"] == "Fall 2026"
    assert semester["timezone"] == "America/New_York"

    own_semesters = client.get("/api/semesters", headers=auth_headers())
    other_semesters = client.get("/api/semesters", headers=auth_headers(USER_B))

    assert [item["id"] for item in own_semesters.json()] == [semester["id"]]
    assert other_semesters.json() == []


def test_create_semester_rejects_an_inverted_date_range(app_client):
    client, _ = app_client

    response = client.post(
        "/api/semesters",
        headers=auth_headers(),
        json={
            "name": "Fall 2026",
            "start_date": "2026-12-18",
            "end_date": "2026-08-24",
            "timezone": "America/New_York",
        },
    )

    assert response.status_code == 422


def test_list_semesters_includes_aggregate_counts(app_client):
    client, app = app_client

    with app.state.session_factory() as session:
        semester = Semester(
            user_id=USER_B,
            name="Spring 2027",
            start_date=date(2027, 1, 11),
            end_date=date(2027, 5, 7),
            timezone="America/New_York",
        )
        session.add(semester)
        session.flush()

        document = SyllabusDocument(
            user_id=USER_B,
            semester_id=semester.id,
            filename="math201.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_B}/{semester.id}/math201.pdf",
        )
        session.add(document)
        session.flush()

        course = Course(
            user_id=USER_B,
            semester_id=semester.id,
            document_id=document.id,
            code="MATH 201",
            name="Discrete Math",
            color="#2563EB",
        )
        session.add(course)
        session.flush()

        session.add_all(
            [
                ExtractedEvent(
                    user_id=USER_B,
                    semester_id=semester.id,
                    course_id=course.id,
                    document_id=document.id,
                    title="Quiz 1",
                    event_type="quiz",
                    event_date=date(2027, 2, 4),
                    timezone="America/New_York",
                    is_all_day=True,
                    source_quote="Quiz 1 takes place on February 4",
                    source_page=2,
                    confidence=ConfidenceLevel.HIGH,
                    warning_codes=[],
                    review_status=ReviewStatus.CONFIRMED,
                ),
                ExtractedEvent(
                    user_id=USER_B,
                    semester_id=semester.id,
                    course_id=course.id,
                    document_id=document.id,
                    title="Project checkpoint",
                    event_type="assignment",
                    event_date=date(2027, 3, 12),
                    timezone="America/New_York",
                    is_all_day=True,
                    source_quote="Project checkpoint due March 12",
                    source_page=6,
                    confidence=ConfidenceLevel.LOW,
                    warning_codes=["AMBIGUOUS_DATE"],
                    warning_reason="The date is only approximate.",
                    review_status=ReviewStatus.NEEDS_REVIEW,
                ),
            ]
        )
        session.commit()

    response = client.get("/api/semesters", headers=auth_headers(USER_B))

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(semester.id),
            "name": "Spring 2027",
            "start_date": "2027-01-11",
            "end_date": "2027-05-07",
            "timezone": "America/New_York",
            "review_completed_at": None,
            "course_count": 1,
            "document_count": 1,
            "event_count": 2,
            "needs_review_count": 1,
        }
    ]


def test_list_semesters_counts_an_orphaned_series_event_as_a_review_decision(app_client):
    client, app = app_client

    with app.state.session_factory() as session:
        semester = Semester(
            user_id=USER_B,
            name="Fall 2027",
            start_date=date(2027, 8, 23),
            end_date=date(2027, 12, 17),
            timezone="America/New_York",
        )
        session.add(semester)
        session.flush()
        course = Course(
            user_id=USER_B,
            semester_id=semester.id,
            code="CS 101",
            name="Intro to CS",
            color="#2563EB",
        )
        session.add(course)
        session.flush()
        session.add(
            ExtractedEvent(
                user_id=USER_B,
                semester_id=semester.id,
                course_id=course.id,
                recurring_series_id=uuid4(),
                title="Lab make-up submission deadline",
                event_type="deadline",
                event_date=None,
                timezone="America/New_York",
                is_all_day=False,
                source_quote="until Sunday after the lab",
                source_page=2,
                confidence=ConfidenceLevel.HIGH,
                warning_codes=["DATE_MISSING"],
                review_status=ReviewStatus.NEEDS_REVIEW,
            )
        )
        session.commit()

    response = client.get("/api/semesters", headers=auth_headers(USER_B))

    assert response.status_code == 200
    assert response.json()[0]["needs_review_count"] == 1
