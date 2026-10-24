from types import SimpleNamespace

import pymupdf
import pytest

from app import processing
from app.errors import PROCESSING_FAILED_MESSAGE
from app.models import JobStatus, ProcessingJob

from .conftest import auth_headers


@pytest.mark.parametrize("malformed", [False, True])
def test_flagged_or_malformed_primary_result_never_calls_a_second_model(
    app_client, monkeypatch, malformed,
):
    client, app = app_client
    semester = client.post(
        "/api/semesters", headers=auth_headers(),
        json={"name": "Fall 2026", "start_date": "2026-08-24",
              "end_date": "2026-12-18", "timezone": "America/New_York"},
    ).json()
    source = "Final exam December 16, 2026. " * 5
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_textbox(pymupdf.Rect(72, 72, 520, 760), source)
        content = document.tobytes()
    response = client.post(
        f"/api/semesters/{semester['id']}/syllabi", headers=auth_headers(),
        files=[("files", ("single-model.pdf", content, "application/pdf"))],
    )
    assert response.status_code == 202
    job_id = response.json()["jobs"][0]["id"]
    calls = []
    output = processing.SyllabusExtraction(
        course_name="Single model regression", events=[processing.CandidateEvent(
            title="Final exam", event_type="exam", event_date="2026-12-16",
            source_quote="A quote that does not appear in the syllabus",
            source_page=1, confidence="low", year_was_explicit=True,
        )],
    )

    class Responses:
        def parse(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_parsed=None if malformed else output)

    class Client:
        def __init__(self, **kwargs):
            self.responses = Responses()

    monkeypatch.setattr(processing, "OpenAI", Client)
    settings = app.state.settings.model_copy(update={
        "extraction_mode": "openai", "openai_api_key": "fake-key",
        "openai_model": "gpt-6.1-sol", "openai_reasoning_effort": "medium",
    })
    processing.process_job(job_id, settings=settings, session_factory=app.state.session_factory)
    assert len(calls) == 1
    assert calls[0]["model"] == "gpt-6.1-sol"
    assert calls[0]["reasoning"] == {"effort": "medium"}
    from uuid import UUID

    with app.state.session_factory() as session:
        job = session.get(ProcessingJob, UUID(job_id))
        assert job.fallback_model is None
        assert job.fallback_used is False
        assert job.fallback_reason_codes == []
        if malformed:
            assert job.status == JobStatus.FAILED
            assert job.error_message == PROCESSING_FAILED_MESSAGE
            assert job.document.semester.events == []
        else:
            assert job.status == JobStatus.NEEDS_REVIEW
            event = job.document.semester.events[0]
            assert event.title == "Final exam"
            assert event.extraction_model == "gpt-6.1-sol"
            assert event.warning_codes == ["SOURCE_MISMATCH", "LOW_CONFIDENCE"]
            assert event.fallback_reason_codes == []


@pytest.mark.parametrize(
    ("source", "expected_title", "missing_anchor"),
    [
        ("Homework is due every Monday.", "Homework", False),
        ("Exercise set is due every Monday.", "Exercise Sets", False),
        ("Monday 7 September 2026 Orientation. Homework is due every Friday.",
         "Homework", False),
        ("Homework is due every Monday starting Monday 7 September 2026.",
         "Homework", False),
        ("Monday 7 September 2026 Orientation. Reflection due two days after lecture.",
         "Reflection", True),
    ],
)
def test_unresolved_exact_schedule_stays_undated_and_keeps_its_warning(
    app_client, monkeypatch, source, expected_title, missing_anchor,
):
    client, app = app_client
    semester = client.post(
        "/api/semesters", headers=auth_headers(),
        json={"name": "Fall 2026", "start_date": "2026-08-24",
              "end_date": "2026-12-18", "timezone": "America/New_York"},
    ).json()
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_textbox(pymupdf.Rect(72, 72, 520, 760), (source + " ") * 4)
        content = document.tobytes()
    response = client.post(
        f"/api/semesters/{semester['id']}/syllabi", headers=auth_headers(),
        files=[("files", ("missing-rule.pdf", content, "application/pdf"))],
    )
    assert response.status_code == 202
    extraction = processing.SyllabusExtraction(course_name="Missing recurrence")
    if missing_anchor:
        extraction.recurring_rules = [processing.RecurringRule(
            title="Reflection", event_type="assignment", rule_kind="relative_to_anchor",
            anchor_title="Lecture", offset_days=2, source_page=1, confidence="high",
            source_quote="Reflection due two days after lecture", expansion_mode="exact",
        )]
    monkeypatch.setattr(processing, "extract_with_openai", lambda pages, settings: extraction)
    settings = app.state.settings.model_copy(update={
        "extraction_mode": "openai", "openai_api_key": "fake-key",
        "openai_model": "gpt-6.1-sol",
    })
    job_id = response.json()["jobs"][0]["id"]
    processing.process_job(job_id, settings=settings, session_factory=app.state.session_factory)
    from uuid import UUID

    with app.state.session_factory() as session:
        job = session.get(ProcessingJob, UUID(job_id))
        assert job.status == JobStatus.NEEDS_REVIEW, job.error_message
        assert len(job.document.semester.events) == 1
        event = job.document.semester.events[0]
        assert event.title == expected_title
        assert event.event_date is None
        assert event.recurring_series_id is None
        assert "DATE_MISSING" in event.warning_codes
        expected_code = "ANCHOR_NOT_FOUND" if missing_anchor else "RECURRING_RULE_MISSING"
        assert expected_code in event.warning_codes
        assert "AMBIGUOUS_RECURRENCE" not in event.warning_codes
        assert event.extraction_model == "gpt-6.1-sol"
        assert event.fallback_reason_codes == []
