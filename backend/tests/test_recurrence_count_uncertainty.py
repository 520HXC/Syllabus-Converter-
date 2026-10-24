from datetime import date
from uuid import UUID

import pytest

from app import processing
from app.models import JobStatus, ProcessingJob, RecurringEventSeries

from .conftest import auth_headers

UMD_HOMEWORK_QUOTE = "Homeworks\n10–13 weekly recitation assignments, due every Friday."


def weekly_rule(quote, *, title="Homework", kind="assignment"):
    return processing.RecurringRule(
        title=title, event_type=kind, rule_kind="weekly_fixed", weekday="friday",
        source_quote=quote, source_page=3, confidence="high", expansion_mode="exact",
    )


@pytest.mark.parametrize(
    ("quote", "title", "kind"),
    [
        (UMD_HOMEWORK_QUOTE, "Weekly homework due", "assignment"),
        ("10-13 weekly assignments, due every Friday.", "Homework", "assignment"),
        ("10 to 13 weekly assignments are due every Friday.", "Homework", "assignment"),
        ("About 10 weekly quizzes are due every Friday.", "Quizzes", "quiz"),
        ("Approximately 10 weekly projects are due every Friday.", "Projects", "project"),
    ],
)
def test_uncertain_assessment_count_is_review_only(quote, title, kind):
    rule = weekly_rule(quote, title=title, kind=kind)
    pages = [{"page": 3, "text": quote}]
    extraction = processing.SyllabusExtraction(
        course_name="Count regression", recurring_rules=[rule],
    )
    assert processing._rule_requires_review_only(rule, pages)
    normalized, indexes, _ = processing._normalize_ambiguous_recurring_content(extraction, pages)
    assert normalized.recurring_rules[0].expansion_mode == "review_only"
    assert len(normalized.events) == 1
    assert normalized.events[0].event_date is None
    assert indexes == {0}
    series, events = processing.expand_recurring_rules(
        anchors=[], rules=normalized.recurring_rules, semester_start=date(2026, 1, 26),
        semester_end=date(2026, 5, 19), explicit_events=normalized.events,
        extraction_model="gpt-6.1-sol",
    )
    assert series == events == []


@pytest.mark.parametrize("quote", [
    "Homework is due every Friday from Sep 4, 2026 through Dec 4, 2026.",
    "Homework problems 10–13 are due every Friday.",
    "Homework 10–13 are due every Friday.",
    "Homework is due every Friday at 10:00–13:00.",
    "Homework is due every Friday from September 10–13.",
    "Homework is due every Friday. About 10 weekly quizzes will also occur.",
    "Homework is due every Friday. About 10 lab reports will also be assigned.",
    "Homework is due every Friday. September 10–13 weekly assignments will be introduced.",
])
def test_unrelated_ranges_and_counts_do_not_hide_an_exact_homework_rule(quote):
    rule = weekly_rule(quote)
    pages = [{"page": 3, "text": quote}]
    assert not processing._rule_requires_review_only(rule, pages)
    extraction = processing.SyllabusExtraction(course_name="Exact rule", recurring_rules=[rule])
    normalized, _, _ = processing._normalize_ambiguous_recurring_content(extraction, pages)
    assert normalized.recurring_rules[0].expansion_mode == "exact"
    series, events = processing.expand_recurring_rules(
        anchors=[], rules=normalized.recurring_rules, semester_start=date(2026, 9, 4),
        semester_end=date(2026, 9, 18), explicit_events=[], extraction_model=None,
    )
    assert len(series) == 1
    assert [event.event_date for event in events] == [
        date(2026, 9, 4), date(2026, 9, 11), date(2026, 9, 18),
    ]


def test_uncertain_quiz_count_elsewhere_does_not_change_homework():
    rule = weekly_rule("Homework is due every Friday.")
    pages = [{"page": 3, "text": rule.source_quote + " About 10 weekly quizzes are planned."}]
    assert not processing._rule_requires_review_only(rule, pages)


def test_unmatched_count_quote_is_not_treated_as_grounded_schedule_evidence():
    rule = weekly_rule(UMD_HOMEWORK_QUOTE)
    pages = [{"page": 3, "text": "Homework is due every Friday."}]
    assert not processing._rule_requires_review_only(rule, pages)


def test_umd_captured_homework_rule_persists_once_without_invented_dates(app_client, monkeypatch):
    client, app = app_client
    semester = client.post(
        "/api/semesters", headers=auth_headers(),
        json={"name": "UMD Spring 2026", "start_date": "2026-01-26",
              "end_date": "2026-05-19", "timezone": "America/New_York"},
    ).json()
    response = client.post(
        f"/api/semesters/{semester['id']}/syllabi", headers=auth_headers(),
        files=[("files", ("umd-count.pdf", b"%PDF-1.4 replay fixture", "application/pdf"))],
    )
    assert response.status_code == 202
    # Captured Sol output and its grounded page-3 quote are replayed at the PDF/model boundaries.
    rule = weekly_rule(UMD_HOMEWORK_QUOTE, title="Weekly homework due")
    rule.uncertainty_reason = (
        "The syllabus does not identify the first or last assignment date or any skipped weeks."
    )
    extraction = processing.SyllabusExtraction(
        course_code="ENEE 140", course_name="Introduction to Computer Programming",
        instructor="Tudor Dumitras", recurring_rules=[rule],
    )
    pages = [{"page": 3, "text": UMD_HOMEWORK_QUOTE, "ocr": False}]
    monkeypatch.setattr(processing, "extract_pdf_pages", lambda *args, **kwargs: (pages, False))
    monkeypatch.setattr(processing, "extract_with_openai", lambda *args, **kwargs: extraction)
    settings = app.state.settings.model_copy(update={
        "extraction_mode": "openai", "openai_api_key": "fake-key",
        "openai_model": "gpt-6.1-sol",
    })
    job_id = response.json()["jobs"][0]["id"]
    processing.process_job(job_id, settings=settings, session_factory=app.state.session_factory)
    with app.state.session_factory() as session:
        job = session.get(ProcessingJob, UUID(job_id))
        assert job.status == JobStatus.NEEDS_REVIEW, job.error_message
        assert len(job.document.semester.events) == 1
        event = job.document.semester.events[0]
        assert "homework" in event.title.casefold()
        assert event.event_date is None
        assert event.recurring_series_id is None
        assert "AMBIGUOUS_RECURRENCE" in event.warning_codes
        assert event.source_quote == UMD_HOMEWORK_QUOTE
        assert session.query(RecurringEventSeries).count() == 0


@pytest.mark.parametrize(
    ("quote", "title", "expected_review_only"),
    [
        ("Lab reports\nAbout 10 weekly assignments are due every Friday.",
         "Lab reports", True),
        ("Homework is due every Friday. Lab reports\nAbout 10 weekly assignments are planned.",
         "Homework", False),
        ("Lab reports are due every Friday. About 10 weekly homeworks are planned.",
         "Lab reports", False),
        ("Exercise sets\nAbout 10 weekly assignments are due every Friday.",
         "Exercise sets", True),
    ],
)
def test_generic_assignment_count_follows_its_explicit_subject(
    quote, title, expected_review_only,
):
    rule = weekly_rule(quote, title=title)
    pages = [{"page": 3, "text": quote}]
    assert processing._rule_requires_review_only(rule, pages) is expected_review_only
