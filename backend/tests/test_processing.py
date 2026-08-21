from __future__ import annotations

from datetime import date, time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pymupdf
import pytest

import app.processing as processing
from app.api import safe_filename
from app.config import Settings
from app.models import (
    JobStatus,
    ProcessingJob,
    RecurringEventSeries,
    ReviewStatus,
    Semester,
    SyllabusDocument,
)
from app.processing import (
    CandidateEvent,
    RecurringRule,
    ScheduleAnchor,
    SyllabusExtraction,
    detect_date_conflict,
    expand_recurring_rules,
    extract_locally,
    extract_pdf_pages,
    extract_with_openai,
    process_job,
    validate_candidate,
)

from .conftest import USER_A


def make_pdf(text: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    if text:
        page.insert_textbox(pymupdf.Rect(72, 72, 520, 760), text)
    content = document.tobytes()
    document.close()
    return content


def test_extract_pdf_pages_uses_embedded_text_without_ocr(monkeypatch):
    def unexpected_ocr(*args, **kwargs):
        raise AssertionError("OCR should not run for a text PDF")

    monkeypatch.setattr("app.processing.ocr_pdf_page", unexpected_ocr)
    content = make_pdf("Embedded syllabus text " * 10)

    pages, used_ocr = extract_pdf_pages(content, min_text_characters=80)

    assert used_ocr is False
    assert pages[0]["page"] == 1
    assert "Embedded syllabus text" in pages[0]["text"]


def test_extract_pdf_pages_runs_ocr_for_a_low_text_page(monkeypatch):
    callback_calls: list[int] = []
    monkeypatch.setattr(
        "app.processing.ocr_pdf_page",
        lambda content, page_number, settings: "Scanned final exam December 12, 2026",
    )

    pages, used_ocr = extract_pdf_pages(
        make_pdf(""),
        min_text_characters=80,
        on_ocr_start=lambda page_number: callback_calls.append(page_number),
    )

    assert used_ocr is True
    assert callback_calls == [1]
    assert pages == [{"page": 1, "text": "Scanned final exam December 12, 2026", "ocr": True}]


def test_extract_pdf_pages_rejects_documents_over_the_page_limit():
    document = pymupdf.open()
    for _ in range(3):
        page = document.new_page()
        page.insert_text((72, 72), "Syllabus text " * 20)
    content = document.tobytes()
    document.close()

    settings = Settings(
        _env_file=None, app_env="test", auth_mode="dev", max_pdf_pages=2
    )

    with pytest.raises(ValueError, match="more than 2 pages"):
        extract_pdf_pages(content, min_text_characters=80, settings=settings)


def test_extract_pdf_pages_limits_ocr_work(monkeypatch):
    document = pymupdf.open()
    document.new_page()
    document.new_page()
    content = document.tobytes()
    document.close()
    monkeypatch.setattr(
        "app.processing.ocr_pdf_page",
        lambda content, page_number, settings: f"OCR page {page_number}",
    )
    settings = Settings(
        _env_file=None, app_env="test", auth_mode="dev", max_ocr_pages=1
    )

    with pytest.raises(ValueError, match="OCR is limited to 1 page"):
        extract_pdf_pages(content, min_text_characters=80, settings=settings)


def test_extract_pdf_pages_rejects_excessive_extracted_text():
    content = make_pdf("Long syllabus text " * 30)
    settings = Settings(
        _env_file=None,
        app_env="test",
        auth_mode="dev",
        max_extracted_text_characters=100,
    )

    with pytest.raises(ValueError, match="more than 100 characters"):
        extract_pdf_pages(content, min_text_characters=1, settings=settings)


def test_validation_keeps_deterministic_warning_codes():
    candidate = CandidateEvent(
        title="Final exam",
        event_type="exam",
        event_date=date(2027, 1, 8),
        start_time=None,
        end_time=None,
        is_all_day=True,
        source_quote="Final exam is scheduled in January",
        source_page=2,
        confidence="low",
        year_was_explicit=False,
        uncertainty_reason="The year is not stated.",
    )
    pages = [{"page": 1, "text": "Nothing about the final is on this page.", "ocr": False}]

    warning_codes, reason = validate_candidate(
        candidate,
        pages,
        semester_start=date(2026, 8, 24),
        semester_end=date(2026, 12, 18),
    )

    assert warning_codes == [
        "OUTSIDE_SEMESTER",
        "YEAR_NOT_EXPLICIT",
        "SOURCE_PAGE_MISSING",
        "LOW_CONFIDENCE",
    ]
    assert "outside the semester" in reason


def test_validation_marks_an_undated_event_for_review():
    candidate = CandidateEvent(
        title="Final exam",
        event_type="exam",
        event_date=None,
        source_quote="Final exam as scheduled by Registrar",
        source_page=1,
        confidence="low",
        year_was_explicit=False,
        uncertainty_reason="The registrar has not published the date.",
    )
    pages = [
        {
            "page": 1,
            "text": "Final exam as scheduled by Registrar",
            "ocr": False,
        }
    ]

    warning_codes, reason = validate_candidate(
        candidate,
        pages,
        semester_start=date(2025, 9, 2),
        semester_end=date(2025, 12, 20),
    )

    assert "DATE_MISSING" in warning_codes
    assert "The event does not have a confirmed date." in reason


def test_unknown_recurring_series_reference_becomes_a_standalone_event():
    candidate = CandidateEvent(
        title="Lab make-up submission deadline",
        event_type="deadline",
        event_date=None,
        source_quote="until 11:59pm on the Sunday that follows the lab",
        source_page=2,
        confidence="high",
        year_was_explicit=False,
        recurring_series_id=uuid4(),
    )

    assert processing.resolve_recurring_series_id(candidate, set()) is None


def test_known_recurring_series_reference_is_preserved():
    series_id = uuid4()
    candidate = CandidateEvent(
        title="Weekly quiz",
        event_type="quiz",
        event_date=date(2026, 9, 18),
        source_quote="Quiz every Friday",
        source_page=2,
        confidence="high",
        year_was_explicit=True,
        recurring_series_id=series_id,
    )

    assert processing.resolve_recurring_series_id(candidate, {series_id}) == series_id


def test_openai_extraction_defaults_to_luna_and_excludes_routine_classes(monkeypatch):
    captured: dict = {}
    output = SyllabusExtraction(
        course_code="CS-UY 1114",
        course_name="Introduction to Programming and Problem Solving",
        instructor="Salim Arfaoui; Peter DePasquale",
        events=[
            CandidateEvent(
                title="Final exam",
                event_type="exam",
                event_date=None,
                source_quote="Final exam as scheduled by Registrar",
                source_page=1,
                confidence="low",
                year_was_explicit=False,
                uncertainty_reason="The registrar has not published the date.",
            )
        ],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_parsed=output)

    class FakeOpenAI:
        def __init__(self, api_key):
            assert api_key == "test-key"
            self.responses = FakeResponses()

    monkeypatch.setattr("app.processing.OpenAI", FakeOpenAI)
    settings = Settings(
        _env_file=None,
        app_env="test",
        auth_mode="dev",
        openai_api_key="test-key",
    )

    result = extract_with_openai(
        [{"page": 1, "text": "Final exam as scheduled by Registrar", "ocr": False}],
        settings,
    )

    assert captured["model"] == "gpt-5.6-luna"
    assert "Do not include routine class meetings" in captured["instructions"]
    assert result.events[0].event_date is None


def test_process_job_repairs_only_retryable_luna_warnings_with_single_terra_call(
    app_client, monkeypatch
):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)
    calls: list[str] = []

    with app.state.session_factory() as session:
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
            filename="cs101.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/cs101.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        storage_key = document.storage_key

    file_path = storage_path / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(
        make_pdf(
            "CS 101 Midterm exam October 14, 2026. "
            "Final exam December 16, 2026 as scheduled by Registrar. " * 4
        )
    )

    luna_output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Introduction to Computer Science",
        instructor=None,
        events=[
            CandidateEvent(
                title="Midterm exam",
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
            ),
            CandidateEvent(
                title="Final exam",
                event_type="exam",
                event_date=date(2026, 12, 16),
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Registrar will announce the final exam later",
                source_page=1,
                confidence="low",
                year_was_explicit=True,
                uncertainty_reason="The source wording is tentative.",
            ),
        ],
    )
    terra_output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Introduction to Computer Science",
        instructor=None,
        events=[
            CandidateEvent(
                title="Final exam",
                event_type="exam",
                event_date=date(2026, 12, 16),
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Final exam December 16, 2026 as scheduled by Registrar",
                source_page=1,
                confidence="high",
                year_was_explicit=True,
                uncertainty_reason=None,
            )
        ],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            calls.append(kwargs["model"])
            if kwargs["model"] == "gpt-5.6-luna":
                return SimpleNamespace(output_parsed=luna_output)
            return SimpleNamespace(output_parsed=terra_output)

    class FakeOpenAI:
        def __init__(self, api_key):
            assert api_key == "test-key"
            self.responses = FakeResponses()

    monkeypatch.setattr("app.processing.OpenAI", FakeOpenAI)
    settings = app.state.settings.model_copy(
        update={
            "extraction_mode": "openai",
            "openai_api_key": "test-key",
            "openai_model": "gpt-5.6-luna",
            "openai_fallback_model": "gpt-5.6-terra",
        }
    )

    process_job(str(job_id), settings=settings, session_factory=app.state.session_factory)

    with app.state.session_factory() as session:
        persisted = session.get(ProcessingJob, job_id)
        assert persisted.status == JobStatus.NEEDS_REVIEW, persisted.error_message
        assert persisted.primary_model == "gpt-5.6-luna"
        assert persisted.fallback_model == "gpt-5.6-terra"
        assert persisted.fallback_used is True
        assert persisted.fallback_reason_codes == ["LOW_CONFIDENCE", "SOURCE_MISMATCH"]
        events = sorted(persisted.document.semester.events, key=lambda item: item.title)
        assert [event.title for event in events] == ["Final exam", "Midterm exam"]
        assert {event.title: event.extraction_model for event in events} == {
            "Final exam": "gpt-5.6-terra",
            "Midterm exam": "gpt-5.6-luna",
        }
        assert next(event for event in events if event.title == "Final exam").warning_codes == []

    assert calls == ["gpt-5.6-luna", "gpt-5.6-terra"]


def test_process_job_skips_terra_when_warnings_are_not_retryable(app_client, monkeypatch):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)
    calls: list[str] = []

    with app.state.session_factory() as session:
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
            filename="cs101.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/cs101.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        storage_key = document.storage_key

    file_path = storage_path / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(make_pdf("Final exam as scheduled by Registrar. " * 8))

    output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Introduction to Computer Science",
        instructor=None,
        events=[
            CandidateEvent(
                title="Final exam",
                event_type="exam",
                event_date=None,
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Final exam as scheduled by Registrar",
                source_page=1,
                confidence="medium",
                year_was_explicit=False,
                uncertainty_reason="The registrar has not published the date.",
            )
        ],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            calls.append(kwargs["model"])
            return SimpleNamespace(output_parsed=output)

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("app.processing.OpenAI", FakeOpenAI)
    settings = app.state.settings.model_copy(
        update={
            "extraction_mode": "openai",
            "openai_api_key": "test-key",
            "openai_model": "gpt-5.6-luna",
            "openai_fallback_model": "gpt-5.6-terra",
        }
    )

    process_job(str(job_id), settings=settings, session_factory=app.state.session_factory)

    with app.state.session_factory() as session:
        persisted = session.get(ProcessingJob, job_id)
        assert persisted.status == JobStatus.NEEDS_REVIEW, persisted.error_message
        assert persisted.primary_model == "gpt-5.6-luna"
        assert persisted.fallback_used is False
        assert persisted.fallback_reason_codes == []
        event = persisted.document.semester.events[0]
        assert event.extraction_model == "gpt-5.6-luna"
        assert event.warning_codes == ["DATE_MISSING", "YEAR_NOT_EXPLICIT", "MODEL_UNCERTAINTY"]

    assert calls == ["gpt-5.6-luna"]


def test_date_missing_alone_does_not_trigger_terra_retry(app_client, monkeypatch):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)
    calls: list[str] = []

    with app.state.session_factory() as session:
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
            filename="cs101.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/cs101.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        storage_key = document.storage_key

    file_path = storage_path / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(make_pdf("Final exam as scheduled by Registrar. " * 8))

    output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Introduction to Computer Science",
        instructor=None,
        events=[
            CandidateEvent(
                title="Final exam",
                event_type="exam",
                event_date=None,
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Final exam as scheduled by Registrar",
                source_page=1,
                confidence="medium",
                year_was_explicit=True,
                uncertainty_reason=None,
            )
        ],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            calls.append(kwargs["model"])
            return SimpleNamespace(output_parsed=output)

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("app.processing.OpenAI", FakeOpenAI)
    settings = app.state.settings.model_copy(
        update={
            "extraction_mode": "openai",
            "openai_api_key": "test-key",
            "openai_model": "gpt-5.6-luna",
            "openai_fallback_model": "gpt-5.6-terra",
        }
    )

    process_job(str(job_id), settings=settings, session_factory=app.state.session_factory)

    with app.state.session_factory() as session:
        persisted = session.get(ProcessingJob, job_id)
        assert persisted.status == JobStatus.NEEDS_REVIEW, persisted.error_message
        assert persisted.fallback_used is False
        assert persisted.fallback_reason_codes == []
        event = persisted.document.semester.events[0]
        assert event.warning_codes == ["DATE_MISSING"]

    assert calls == ["gpt-5.6-luna"]


def test_process_job_marks_terra_retry_failed_and_keeps_luna_events(app_client, monkeypatch):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)

    with app.state.session_factory() as session:
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
            filename="cs101.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/cs101.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        storage_key = document.storage_key

    file_path = storage_path / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(
        make_pdf("CS 101 Midterm exam October 14, 2026. Final exam December 16, 2026. " * 4)
    )

    luna_output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Introduction to Computer Science",
        instructor=None,
        events=[
            CandidateEvent(
                title="Final exam",
                event_type="exam",
                event_date=date(2026, 12, 16),
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Unmatched final exam quote",
                source_page=1,
                confidence="low",
                year_was_explicit=True,
                uncertainty_reason="Tentative date wording.",
            )
        ],
    )

    class FakeResponses:
        def __init__(self):
            self.calls = 0

        def parse(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(output_parsed=luna_output)
            return SimpleNamespace(output_parsed=None)

    fake_responses = FakeResponses()

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = fake_responses

    monkeypatch.setattr("app.processing.OpenAI", FakeOpenAI)
    settings = app.state.settings.model_copy(
        update={
            "extraction_mode": "openai",
            "openai_api_key": "test-key",
            "openai_model": "gpt-5.6-luna",
            "openai_fallback_model": "gpt-5.6-terra",
        }
    )

    process_job(str(job_id), settings=settings, session_factory=app.state.session_factory)

    with app.state.session_factory() as session:
        persisted = session.get(ProcessingJob, job_id)
        assert persisted.status == JobStatus.NEEDS_REVIEW, persisted.error_message
        assert persisted.fallback_used is True
        assert persisted.fallback_reason_codes == [
            "LOW_CONFIDENCE",
            "SOURCE_MISMATCH",
            "TERRA_RETRY_FAILED",
        ]
        event = persisted.document.semester.events[0]
        assert event.extraction_model == "gpt-5.6-luna"
        assert event.warning_codes == ["SOURCE_MISMATCH", "LOW_CONFIDENCE", "TERRA_RETRY_FAILED"]


def test_process_job_does_not_fallback_on_luna_operational_failure(app_client, monkeypatch):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)
    calls: list[str] = []

    with app.state.session_factory() as session:
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
            filename="cs101.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/cs101.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        storage_key = document.storage_key

    file_path = storage_path / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(make_pdf("Course text " * 40))

    class FakeResponses:
        def parse(self, **kwargs):
            calls.append(kwargs["model"])
            raise TimeoutError("Luna timed out")

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("app.processing.OpenAI", FakeOpenAI)
    settings = app.state.settings.model_copy(
        update={
            "extraction_mode": "openai",
            "openai_api_key": "test-key",
            "openai_model": "gpt-5.6-luna",
            "openai_fallback_model": "gpt-5.6-terra",
        }
    )

    process_job(str(job_id), settings=settings, session_factory=app.state.session_factory)

    with app.state.session_factory() as session:
        persisted = session.get(ProcessingJob, job_id)
        assert persisted.status == JobStatus.FAILED
        assert persisted.error_message == "Luna timed out"
        assert persisted.fallback_used is False

    assert calls == ["gpt-5.6-luna"]


def test_process_job_fails_on_terra_repair_operational_failure(app_client, monkeypatch):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)
    calls: list[str] = []

    with app.state.session_factory() as session:
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
            filename="cs101.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/cs101.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        storage_key = document.storage_key

    file_path = storage_path / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(make_pdf("CS 101 Final exam December 16, 2026. " * 8))

    luna_output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Introduction to Computer Science",
        instructor=None,
        events=[
            CandidateEvent(
                title="Final exam",
                event_type="exam",
                event_date=date(2026, 12, 16),
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Unmatched final exam quote",
                source_page=1,
                confidence="low",
                year_was_explicit=True,
                uncertainty_reason="Tentative date wording.",
            )
        ],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            calls.append(kwargs["model"])
            if kwargs["model"] == "gpt-5.6-luna":
                return SimpleNamespace(output_parsed=luna_output)
            raise TimeoutError("Terra timed out")

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("app.processing.OpenAI", FakeOpenAI)
    settings = app.state.settings.model_copy(
        update={
            "extraction_mode": "openai",
            "openai_api_key": "test-key",
            "openai_model": "gpt-5.6-luna",
            "openai_fallback_model": "gpt-5.6-terra",
        }
    )

    process_job(str(job_id), settings=settings, session_factory=app.state.session_factory)

    with app.state.session_factory() as session:
        persisted = session.get(ProcessingJob, job_id)
        assert persisted.status == JobStatus.FAILED
        assert persisted.error_message == "Terra timed out"

    assert calls == ["gpt-5.6-luna", "gpt-5.6-terra"]


def test_process_job_fails_when_both_models_cannot_parse_structured_output(app_client, monkeypatch):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)

    with app.state.session_factory() as session:
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
            filename="cs101.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/cs101.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        storage_key = document.storage_key

    file_path = storage_path / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(make_pdf("Course text " * 40))

    class FakeResponses:
        def parse(self, **kwargs):
            return SimpleNamespace(output_parsed=None)

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("app.processing.OpenAI", FakeOpenAI)
    settings = app.state.settings.model_copy(
        update={
            "extraction_mode": "openai",
            "openai_api_key": "test-key",
            "openai_model": "gpt-5.6-luna",
            "openai_fallback_model": "gpt-5.6-terra",
        }
    )

    process_job(str(job_id), settings=settings, session_factory=app.state.session_factory)

    with app.state.session_factory() as session:
        persisted = session.get(ProcessingJob, job_id)
        assert persisted.status == JobStatus.FAILED
        assert "structured syllabus extraction" in persisted.error_message


def test_expand_recurring_rules_uses_explicit_irregular_anchor_occurrences_for_exact_rules():
    anchor = ScheduleAnchor(
        title="Lecture",
        anchor_type="lecture",
        weekday="tuesday",
        start_time=time(9, 0),
        end_time=time(10, 0),
        boundary_start=date(2025, 9, 1),
        boundary_end=date(2025, 9, 10),
        exclusion_dates=[],
        source_quote="Lecture dates are September 2 and September 5.",
        source_page=1,
        occurrences=[
            {
                "occurrence_date": date(2025, 9, 2),
                "title": "Lecture 1",
                "anchor_type": "lecture",
                "source_quote": "Lecture on September 2",
                "source_page": 1,
            },
            {
                "occurrence_date": date(2025, 9, 5),
                "title": "Lecture 2",
                "anchor_type": "lecture",
                "source_quote": "Lecture on September 5",
                "source_page": 1,
            },
            {
                "occurrence_date": date(2025, 9, 7),
                "title": "Lab make-up",
                "anchor_type": "lab",
                "source_quote": "Lab make-up on September 7",
                "source_page": 1,
            },
        ],
    )
    rule = RecurringRule(
        title="Exercise Set",
        event_type="assignment",
        rule_kind="relative_to_anchor",
        weekday=None,
        start_time=time(8, 0),
        end_time=None,
        is_all_day=False,
        boundary_start=date(2025, 9, 1),
        boundary_end=date(2025, 9, 10),
        exclusion_dates=[],
        source_quote="Exercise Sets at 8AM the morning after lecture.",
        source_page=1,
        confidence="high",
        anchor_title="Lecture",
        offset_days=1,
        uncertainty_reason=None,
        expansion_mode="exact",
    )

    series, derived_events = expand_recurring_rules(
        anchors=[anchor],
        rules=[rule],
        semester_start=date(2025, 9, 1),
        semester_end=date(2025, 9, 30),
        explicit_events=[],
        extraction_model="gpt-5.6-luna",
        max_occurrences=200,
    )

    assert len(series) == 1
    assert [event.event_date for event in derived_events] == [
        date(2025, 9, 3),
        date(2025, 9, 6),
    ]
    assert derived_events[0].start_time == time(8, 0)
    assert series[0].occurrence_count == 2


def test_expand_recurring_rules_skips_review_only_rules():
    review_only_rule = RecurringRule(
        title="Quick Checks",
        event_type="quiz",
        rule_kind="weekly_fixed",
        weekday="friday",
        start_time=time(8, 0),
        end_time=None,
        is_all_day=False,
        boundary_start=date(2025, 9, 1),
        boundary_end=date(2025, 9, 30),
        exclusion_dates=[],
        source_quote="Quick Checks at 8AM with nearly every topic.",
        source_page=1,
        confidence="medium",
        anchor_title=None,
        offset_days=None,
        uncertainty_reason=None,
        expansion_mode="review_only",
    )

    series, derived_events = expand_recurring_rules(
        anchors=[],
        rules=[review_only_rule],
        semester_start=date(2025, 9, 1),
        semester_end=date(2025, 9, 30),
        explicit_events=[],
        extraction_model="gpt-5.6-luna",
        max_occurrences=200,
    )

    assert series == []
    assert derived_events == []


def test_process_job_normalizes_ambiguous_recurring_candidate_without_duplication(
    app_client, monkeypatch
):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)
    calls: list[str] = []

    with app.state.session_factory() as session:
        semester = Semester(
            user_id=USER_A,
            name="Fall 2025",
            start_date=date(2025, 8, 25),
            end_date=date(2025, 12, 19),
            timezone="America/New_York",
        )
        session.add(semester)
        session.flush()
        document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="fall2025.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/fall2025.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        storage_key = document.storage_key

    file_path = storage_path / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(
        make_pdf("Quick Checks at 8AM the morning of lecture with nearly every topic. " * 4)
    )

    luna_output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Quick Checks",
                event_type="quiz",
                event_date=None,
                start_time=time(8, 0),
                end_time=None,
                is_all_day=False,
                source_quote="Quick Checks at 8AM the morning of lecture with nearly every topic",
                source_page=1,
                confidence="high",
                year_was_explicit=True,
                uncertainty_reason=None,
            )
        ],
        recurring_rules=[
            RecurringRule(
                title="Quick Checks",
                event_type="quiz",
                rule_kind="relative_to_anchor",
                weekday=None,
                start_time=time(8, 0),
                end_time=None,
                is_all_day=False,
                boundary_start=date(2025, 8, 25),
                boundary_end=date(2025, 12, 19),
                exclusion_dates=[],
                source_quote="Quick Checks at 8AM the morning of lecture with nearly every topic",
                source_page=1,
                confidence="high",
                anchor_title="Lecture",
                offset_days=0,
                uncertainty_reason=None,
                expansion_mode="review_only",
            )
        ],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            calls.append(kwargs["model"])
            return SimpleNamespace(output_parsed=luna_output)

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("app.processing.OpenAI", FakeOpenAI)
    settings = app.state.settings.model_copy(
        update={
            "extraction_mode": "openai",
            "openai_api_key": "test-key",
            "openai_model": "gpt-5.6-luna",
            "openai_fallback_model": "gpt-5.6-terra",
        }
    )

    process_job(str(job_id), settings=settings, session_factory=app.state.session_factory)

    with app.state.session_factory() as session:
        persisted = session.get(ProcessingJob, job_id)
        assert persisted.status == JobStatus.NEEDS_REVIEW, persisted.error_message
        assert persisted.fallback_used is False
        events = persisted.document.semester.events
        assert [event.title for event in events] == ["Quick Checks"]
        event = events[0]
        assert event.recurring_series_id is None
        assert event.warning_codes == ["DATE_MISSING", "AMBIGUOUS_RECURRENCE"]
        assert event.warning_reason == (
            "The syllabus uses ambiguous recurrence wording, so exact dates were not generated."
        )
        assert event.derivation_summary == (
            "Dates were not generated because the syllabus does not identify every occurrence."
        )
        assert event.confidence.value == "medium"

    assert calls == ["gpt-5.6-luna"]


def test_process_job_uses_single_terra_call_for_missing_deterministic_recurring_rule(
    app_client, monkeypatch
):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)
    calls: list[str] = []
    terra_instructions: list[str] = []

    with app.state.session_factory() as session:
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
            filename="cs101.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/cs101.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        storage_key = document.storage_key

    file_path = storage_path / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(
        make_pdf("Homework due every Friday from Sep 4, 2026 through Sep 18, 2026. " * 4)
    )

    luna_output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Introduction to Computer Science",
        instructor=None,
        events=[],
        recurring_rules=[],
    )
    terra_output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Introduction to Computer Science",
        instructor=None,
        events=[],
        recurring_rules=[
            RecurringRule(
                title="Homework",
                event_type="assignment",
                rule_kind="weekly_fixed",
                weekday="friday",
                start_time=None,
                end_time=None,
                is_all_day=True,
                boundary_start=date(2026, 9, 4),
                boundary_end=date(2026, 9, 18),
                exclusion_dates=[],
                source_quote="Homework due every Friday from Sep 4, 2026 through Sep 18, 2026",
                source_page=1,
                confidence="high",
                anchor_title=None,
                offset_days=None,
                uncertainty_reason=None,
                expansion_mode="exact",
            )
        ],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            calls.append(kwargs["model"])
            if kwargs["model"] == "gpt-5.6-luna":
                return SimpleNamespace(output_parsed=luna_output)
            terra_instructions.append(kwargs["instructions"])
            return SimpleNamespace(output_parsed=terra_output)

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("app.processing.OpenAI", FakeOpenAI)
    settings = app.state.settings.model_copy(
        update={
            "extraction_mode": "openai",
            "openai_api_key": "test-key",
            "openai_model": "gpt-5.6-luna",
            "openai_fallback_model": "gpt-5.6-terra",
        }
    )

    process_job(str(job_id), settings=settings, session_factory=app.state.session_factory)

    with app.state.session_factory() as session:
        persisted = session.get(ProcessingJob, job_id)
        assert persisted.status == JobStatus.NEEDS_REVIEW, persisted.error_message
        assert persisted.fallback_used is True
        assert persisted.fallback_reason_codes == ["RECURRING_RULE_MISSING"]
        events = sorted(persisted.document.semester.events, key=lambda item: item.event_date)
        assert [event.event_date for event in events] == [
            date(2026, 9, 4),
            date(2026, 9, 11),
            date(2026, 9, 18),
        ]

    assert calls == ["gpt-5.6-luna", "gpt-5.6-terra"]
    assert "recover missing schedule anchors or recurring rules" in terra_instructions[0]


def test_process_job_does_not_trigger_terra_for_ambiguous_recurring_standalone_candidate(
    app_client, monkeypatch
):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)
    calls: list[str] = []

    with app.state.session_factory() as session:
        semester = Semester(
            user_id=USER_A,
            name="Fall 2025",
            start_date=date(2025, 8, 25),
            end_date=date(2025, 12, 19),
            timezone="America/New_York",
        )
        session.add(semester)
        session.flush()
        document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="fall2025.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/fall2025.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        storage_key = document.storage_key

    file_path = storage_path / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(
        make_pdf("Quick Checks at 8AM the morning of lecture with nearly every topic. " * 4)
    )

    luna_output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Quick Checks",
                event_type="quiz",
                event_date=None,
                start_time=time(8, 0),
                end_time=None,
                is_all_day=False,
                source_quote="Quick Checks at 8AM the morning of lecture with nearly every topic",
                source_page=1,
                confidence="medium",
                year_was_explicit=True,
                uncertainty_reason=None,
            )
        ],
        recurring_rules=[],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            calls.append(kwargs["model"])
            return SimpleNamespace(output_parsed=luna_output)

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("app.processing.OpenAI", FakeOpenAI)
    settings = app.state.settings.model_copy(
        update={
            "extraction_mode": "openai",
            "openai_api_key": "test-key",
            "openai_model": "gpt-5.6-luna",
            "openai_fallback_model": "gpt-5.6-terra",
        }
    )

    process_job(str(job_id), settings=settings, session_factory=app.state.session_factory)

    with app.state.session_factory() as session:
        persisted = session.get(ProcessingJob, job_id)
        assert persisted.status == JobStatus.NEEDS_REVIEW, persisted.error_message
        assert persisted.fallback_used is False
        assert persisted.fallback_reason_codes == []
        assert persisted.document.semester.events[0].title == "Quick Checks"

    assert calls == ["gpt-5.6-luna"]


def test_process_job_merges_multiple_fallback_reasons_into_one_terra_call(
    app_client, monkeypatch
):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)
    calls: list[str] = []

    with app.state.session_factory() as session:
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
            filename="cs101.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/cs101.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        storage_key = document.storage_key

    file_path = storage_path / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(
        make_pdf(
            "Final exam December 16, 2026 as scheduled by Registrar. "
            "Homework due every Friday from Sep 4, 2026 through Sep 18, 2026. " * 4
        )
    )

    luna_output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Introduction to Computer Science",
        instructor=None,
        events=[
            CandidateEvent(
                title="Final exam",
                event_type="exam",
                event_date=date(2026, 12, 16),
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Registrar will announce the final exam later",
                source_page=1,
                confidence="low",
                year_was_explicit=True,
                uncertainty_reason="The source wording is tentative.",
            )
        ],
        recurring_rules=[],
    )
    terra_output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Introduction to Computer Science",
        instructor=None,
        events=[
            CandidateEvent(
                title="Final exam",
                event_type="exam",
                event_date=date(2026, 12, 16),
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Final exam December 16, 2026 as scheduled by Registrar",
                source_page=1,
                confidence="high",
                year_was_explicit=True,
                uncertainty_reason=None,
            )
        ],
        recurring_rules=[
            RecurringRule(
                title="Homework",
                event_type="assignment",
                rule_kind="weekly_fixed",
                weekday="friday",
                start_time=None,
                end_time=None,
                is_all_day=True,
                boundary_start=date(2026, 9, 4),
                boundary_end=date(2026, 9, 18),
                exclusion_dates=[],
                source_quote="Homework due every Friday from Sep 4, 2026 through Sep 18, 2026",
                source_page=1,
                confidence="high",
                anchor_title=None,
                offset_days=None,
                uncertainty_reason=None,
                expansion_mode="exact",
            )
        ],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            calls.append(kwargs["model"])
            if kwargs["model"] == "gpt-5.6-luna":
                return SimpleNamespace(output_parsed=luna_output)
            return SimpleNamespace(output_parsed=terra_output)

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("app.processing.OpenAI", FakeOpenAI)
    settings = app.state.settings.model_copy(
        update={
            "extraction_mode": "openai",
            "openai_api_key": "test-key",
            "openai_model": "gpt-5.6-luna",
            "openai_fallback_model": "gpt-5.6-terra",
        }
    )

    process_job(str(job_id), settings=settings, session_factory=app.state.session_factory)

    with app.state.session_factory() as session:
        persisted = session.get(ProcessingJob, job_id)
        assert persisted.status == JobStatus.NEEDS_REVIEW, persisted.error_message
        assert persisted.fallback_used is True
        assert persisted.fallback_reason_codes == [
            "LOW_CONFIDENCE",
            "SOURCE_MISMATCH",
            "RECURRING_RULE_MISSING",
        ]

    assert calls == ["gpt-5.6-luna", "gpt-5.6-terra"]


def test_openai_extraction_instructions_request_schedule_occurrences_and_review_only_rules(
    monkeypatch,
):
    captured: dict = {}
    output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[],
        schedule_anchors=[],
        recurring_rules=[],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_parsed=output)

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("app.processing.OpenAI", FakeOpenAI)
    settings = Settings(
        _env_file=None,
        app_env="test",
        auth_mode="dev",
        openai_api_key="test-key",
    )

    extract_with_openai([{"page": 1, "text": "Course text", "ocr": False}], settings)

    assert "ScheduleOccurrence" in captured["instructions"]
    assert "expansion_mode review_only" in captured["instructions"]


def test_merge_extractions_preserves_unrelated_luna_anchors_when_terra_returns_partial_repair():
    primary = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[],
        schedule_anchors=[
            ScheduleAnchor(
                title="Lecture",
                anchor_type="lecture",
                weekday="monday",
                start_time=time(9, 0),
                end_time=time(10, 0),
                boundary_start=date(2025, 8, 25),
                boundary_end=date(2025, 12, 19),
                exclusion_dates=[],
                source_quote="Lecture every Monday",
                source_page=1,
            ),
            ScheduleAnchor(
                title="Lab",
                anchor_type="lab",
                weekday="wednesday",
                start_time=time(13, 0),
                end_time=time(15, 0),
                boundary_start=date(2025, 8, 27),
                boundary_end=date(2025, 12, 17),
                exclusion_dates=[],
                source_quote="Lab every Wednesday",
                source_page=2,
            ),
        ],
        recurring_rules=[],
    )
    repair = processing.SyllabusRepair(
        schedule_anchors=[
            ScheduleAnchor(
                title="Lecture",
                anchor_type="lecture",
                weekday="tuesday",
                start_time=time(9, 30),
                end_time=time(10, 30),
                boundary_start=date(2025, 8, 26),
                boundary_end=date(2025, 12, 16),
                exclusion_dates=[],
                source_quote="Lecture every Tuesday",
                source_page=3,
            )
        ]
    )

    merged = processing._merge_extractions(primary, repair, set(), set())

    assert len(merged.schedule_anchors) == 2
    assert {anchor.title for anchor in merged.schedule_anchors} == {"Lecture", "Lab"}
    lecture = next(anchor for anchor in merged.schedule_anchors if anchor.title == "Lecture")
    lab = next(anchor for anchor in merged.schedule_anchors if anchor.title == "Lab")
    assert lecture.weekday == "tuesday"
    assert lecture.source_page == 3
    assert lab.weekday == "wednesday"
    assert lab.source_page == 2


def test_detect_missing_recurring_rule_normalizes_titles_for_is_due_and_are_due_each():
    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[],
        schedule_anchors=[],
        recurring_rules=[],
    )
    pages = [
        {
            "page": 1,
            "ocr": False,
            "text": "Homework is due every Friday. Exercise Sets are due each week.",
        }
    ]

    missing_titles = processing._detect_missing_recurring_rule(extraction, pages)

    assert missing_titles == ["homework", "exercise sets"]


def test_may_month_in_exact_recurrence_is_not_treated_as_ambiguous():
    assert (
        processing._is_ambiguous_recurrence_text("Homework is due every Friday in May 2027.")
        is False
    )


def test_process_job_uses_page_context_for_actual_quick_and_exercise_quotes(
    app_client, monkeypatch
):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)
    calls: list[str] = []

    with app.state.session_factory() as session:
        semester = Semester(
            user_id=USER_A,
            name="Fall 2025",
            start_date=date(2025, 8, 25),
            end_date=date(2025, 12, 19),
            timezone="America/New_York",
        )
        session.add(semester)
        session.flush()
        document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="fall2025.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/fall2025.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        storage_key = document.storage_key

    file_path = storage_path / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(
        make_pdf(
            "Quick Checks - 8AM the morning of the lecture. "
            "Exercise Sets - 8AM the morning after the lecture. "
            "Nearly every topic includes a quick check and an exercise set."
        )
    )

    luna_output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[],
        recurring_rules=[
            RecurringRule(
                title="Quick Checks due",
                event_type="quiz",
                rule_kind="relative_to_anchor",
                weekday=None,
                start_time=time(8, 0),
                end_time=None,
                is_all_day=False,
                boundary_start=date(2025, 8, 25),
                boundary_end=date(2025, 12, 19),
                exclusion_dates=[],
                source_quote="Quick Checks - 8AM the morning of the lecture",
                source_page=1,
                confidence="high",
                anchor_title="Lecture",
                offset_days=0,
                uncertainty_reason=None,
                extraction_model="gpt-5.6-luna",
            ),
            RecurringRule(
                title="Exercise Sets",
                event_type="assignment",
                rule_kind="relative_to_anchor",
                weekday=None,
                start_time=time(8, 0),
                end_time=None,
                is_all_day=False,
                boundary_start=date(2025, 8, 25),
                boundary_end=date(2025, 12, 19),
                exclusion_dates=[],
                source_quote="Exercise Sets - 8AM the morning after the lecture",
                source_page=1,
                confidence="high",
                anchor_title="Lecture",
                offset_days=1,
                uncertainty_reason=None,
                extraction_model="gpt-5.6-luna",
            ),
        ],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            calls.append(kwargs["model"])
            return SimpleNamespace(output_parsed=luna_output)

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("app.processing.OpenAI", FakeOpenAI)
    settings = app.state.settings.model_copy(
        update={
            "extraction_mode": "openai",
            "openai_api_key": "test-key",
            "openai_model": "gpt-5.6-luna",
            "openai_fallback_model": "gpt-5.6-terra",
        }
    )

    process_job(str(job_id), settings=settings, session_factory=app.state.session_factory)

    with app.state.session_factory() as session:
        persisted = session.get(ProcessingJob, job_id)
        assert persisted.status == JobStatus.NEEDS_REVIEW, persisted.error_message
        events = sorted(persisted.document.semester.events, key=lambda item: item.title)
        assert [event.title for event in events] == ["Exercise Sets", "Quick Checks"]
        assert all(event.event_date is None for event in events)
        assert all(event.recurring_series_id is None for event in events)
        assert all("AMBIGUOUS_RECURRENCE" in event.warning_codes for event in events)
        assert all(event.confidence.value == "medium" for event in events)

    assert calls == ["gpt-5.6-luna"]


def test_process_job_materializes_review_only_rule_without_existing_event(
    app_client, monkeypatch
):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)

    with app.state.session_factory() as session:
        semester = Semester(
            user_id=USER_A,
            name="Fall 2025",
            start_date=date(2025, 8, 25),
            end_date=date(2025, 12, 19),
            timezone="America/New_York",
        )
        session.add(semester)
        session.flush()
        document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="fall2025.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/fall2025.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        storage_key = document.storage_key

    file_path = storage_path / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(
        make_pdf(
            "Quick Checks - 8AM the morning of the lecture. "
            "Nearly every topic includes a quick check."
        )
    )

    luna_output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[],
        recurring_rules=[
            RecurringRule(
                title="Quick Checks",
                event_type="quiz",
                rule_kind="relative_to_anchor",
                weekday=None,
                start_time=time(8, 0),
                end_time=None,
                is_all_day=False,
                boundary_start=date(2025, 8, 25),
                boundary_end=date(2025, 12, 19),
                exclusion_dates=[],
                source_quote="Quick Checks - 8AM the morning of the lecture",
                source_page=1,
                confidence="high",
                anchor_title="Lecture",
                offset_days=0,
                uncertainty_reason=None,
                extraction_model="gpt-5.6-luna",
            )
        ],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            return SimpleNamespace(output_parsed=luna_output)

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("app.processing.OpenAI", FakeOpenAI)
    settings = app.state.settings.model_copy(
        update={
            "extraction_mode": "openai",
            "openai_api_key": "test-key",
            "openai_model": "gpt-5.6-luna",
            "openai_fallback_model": "gpt-5.6-terra",
        }
    )

    process_job(str(job_id), settings=settings, session_factory=app.state.session_factory)

    with app.state.session_factory() as session:
        persisted = session.get(ProcessingJob, job_id)
        events = persisted.document.semester.events
        assert len(events) == 1
        event = events[0]
        assert event.title == "Quick Checks"
        assert event.event_date is None
        assert event.source_quote == "Quick Checks - 8AM the morning of the lecture"
        assert event.source_page == 1
        assert event.start_time == time(8, 0)
        assert event.extraction_model == "gpt-5.6-luna"
        assert event.derivation_summary == (
            "Dates were not generated because the syllabus does not identify every occurrence."
        )
        assert "AMBIGUOUS_RECURRENCE" in event.warning_codes


def test_process_job_only_marks_related_relative_no_date_event_as_ambiguous(
    app_client, monkeypatch
):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)

    with app.state.session_factory() as session:
        semester = Semester(
            user_id=USER_A,
            name="Fall 2025",
            start_date=date(2025, 8, 25),
            end_date=date(2025, 12, 19),
            timezone="America/New_York",
        )
        session.add(semester)
        session.flush()
        document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="fall2025.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/fall2025.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        storage_key = document.storage_key

    file_path = storage_path / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(
        make_pdf(
            "Quick Checks - 8AM the morning of the lecture. "
            "Final exam as scheduled by Registrar. " * 4
        )
    )

    luna_output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Final exam",
                event_type="exam",
                event_date=None,
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Final exam as scheduled by Registrar",
                source_page=1,
                confidence="medium",
                year_was_explicit=True,
                uncertainty_reason=None,
            )
        ],
        recurring_rules=[
            RecurringRule(
                title="Quick Checks",
                event_type="quiz",
                rule_kind="relative_to_anchor",
                weekday=None,
                start_time=time(8, 0),
                end_time=None,
                is_all_day=False,
                boundary_start=date(2025, 8, 25),
                boundary_end=date(2025, 12, 19),
                exclusion_dates=[],
                source_quote="Quick Checks - 8AM the morning of the lecture",
                source_page=1,
                confidence="high",
                anchor_title="Lecture",
                offset_days=0,
                uncertainty_reason=None,
            )
        ],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            return SimpleNamespace(output_parsed=luna_output)

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("app.processing.OpenAI", FakeOpenAI)
    settings = app.state.settings.model_copy(
        update={
            "extraction_mode": "openai",
            "openai_api_key": "test-key",
            "openai_model": "gpt-5.6-luna",
            "openai_fallback_model": "gpt-5.6-terra",
        }
    )

    process_job(str(job_id), settings=settings, session_factory=app.state.session_factory)

    with app.state.session_factory() as session:
        persisted = session.get(ProcessingJob, job_id)
        events = sorted(persisted.document.semester.events, key=lambda item: item.title)
        assert [event.title for event in events] == ["Final exam", "Quick Checks"]
        final_exam = next(event for event in events if event.title == "Final exam")
        quick_checks = next(event for event in events if event.title == "Quick Checks")
        assert "AMBIGUOUS_RECURRENCE" not in final_exam.warning_codes
        assert "AMBIGUOUS_RECURRENCE" in quick_checks.warning_codes


def test_expand_recurring_rules_keeps_unrelated_exact_weekly_rule_even_when_page_has_relative_text(
):
    homework_rule = RecurringRule(
        title="Homework",
        event_type="assignment",
        rule_kind="weekly_fixed",
        weekday="friday",
        start_time=None,
        end_time=None,
        is_all_day=True,
        boundary_start=date(2026, 9, 4),
        boundary_end=date(2026, 9, 18),
        exclusion_dates=[],
        source_quote="Homework is due every Friday from Sep 4, 2026 through Sep 18, 2026",
        source_page=1,
        confidence="high",
        anchor_title=None,
        offset_days=None,
        uncertainty_reason=None,
        extraction_model="gpt-5.6-luna",
    )

    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[],
        schedule_anchors=[],
        recurring_rules=[homework_rule],
    )
    pages = [
        {
            "page": 1,
            "ocr": False,
            "text": (
                "Quick Checks - 8AM the morning of the lecture. "
                "Nearly every topic includes a quick check. "
                "Homework is due every Friday from Sep 4, 2026 through Sep 18, 2026."
            ),
        }
    ]

    normalized, _, _ = processing._normalize_ambiguous_recurring_content(extraction, pages)
    series, derived_events = expand_recurring_rules(
        anchors=[],
        rules=normalized.recurring_rules,
        semester_start=date(2026, 9, 1),
        semester_end=date(2026, 9, 30),
        explicit_events=[],
        extraction_model="gpt-5.6-luna",
        max_occurrences=200,
    )

    assert normalized.recurring_rules[0].expansion_mode == "exact"
    assert len(series) == 1
    assert [event.event_date for event in derived_events] == [
        date(2026, 9, 4),
        date(2026, 9, 11),
        date(2026, 9, 18),
    ]


def test_process_job_marks_unresolved_deterministic_rule_after_single_terra_repair(
    app_client, monkeypatch
):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)
    calls: list[str] = []

    with app.state.session_factory() as session:
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
            filename="cs101.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/cs101.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        storage_key = document.storage_key

    file_path = storage_path / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(
        make_pdf(
            "Homework is due every Friday from Sep 4, 2026 through Sep 18, 2026. " * 4
        )
    )

    luna_output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[],
        recurring_rules=[],
    )
    terra_output = processing.SyllabusRepair(
        events=[
            CandidateEvent(
                title="Homework",
                event_type="assignment",
                event_date=None,
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Homework is due every Friday from Sep 4, 2026 through Sep 18, 2026",
                source_page=1,
                confidence="medium",
                year_was_explicit=True,
                uncertainty_reason=None,
            )
        ],
        recurring_rules=[],
        schedule_anchors=[],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            calls.append(kwargs["model"])
            if kwargs["model"] == "gpt-5.6-luna":
                return SimpleNamespace(output_parsed=luna_output)
            return SimpleNamespace(output_parsed=terra_output)

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("app.processing.OpenAI", FakeOpenAI)
    settings = app.state.settings.model_copy(
        update={
            "extraction_mode": "openai",
            "openai_api_key": "test-key",
            "openai_model": "gpt-5.6-luna",
            "openai_fallback_model": "gpt-5.6-terra",
        }
    )

    process_job(str(job_id), settings=settings, session_factory=app.state.session_factory)

    with app.state.session_factory() as session:
        persisted = session.get(ProcessingJob, job_id)
        assert persisted.status == JobStatus.NEEDS_REVIEW, persisted.error_message
        assert persisted.fallback_used is True
        assert persisted.fallback_reason_codes == ["RECURRING_RULE_MISSING", "TERRA_RETRY_FAILED"]
        events = persisted.document.semester.events
        assert len(events) == 1
        event = events[0]
        assert event.title == "Homework"
        assert event.event_date is None
        assert "TERRA_RETRY_FAILED" in event.warning_codes
        assert event.fallback_reason_codes == ["TERRA_RETRY_FAILED"]

    assert calls == ["gpt-5.6-luna", "gpt-5.6-terra"]


def test_process_job_sanitized_fall_2025_policy_creates_four_dated_five_review_only_and_zero_series(
    app_client, monkeypatch
):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)
    calls: list[str] = []

    with app.state.session_factory() as session:
        semester = Semester(
            user_id=USER_A,
            name="Fall 2025",
            start_date=date(2025, 8, 25),
            end_date=date(2025, 12, 19),
            timezone="America/New_York",
        )
        session.add(semester)
        session.flush()
        document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="fall2025.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/fall2025.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        storage_key = document.storage_key

    file_path = storage_path / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(
        make_pdf(
            "Project Proposal September 12, 2025. Midterm 1 October 3, 2025. "
            "Midterm 2 November 7, 2025. Final Presentation December 5, 2025. "
            "Final exam as scheduled by Registrar. "
            "Quick Checks - 8AM the morning of the lecture. "
            "Exercise Sets - 8AM the morning after the lecture. "
            "Nearly every topic includes a quick check and exercise set. "
            "Lab Exams are scheduled periodically. "
            "Lab assignment make-up deadline as scheduled by course staff. "
            "Lab assignment make-up deadline - 11:59PM the Sunday following the lab."
        )
    )

    luna_output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Project Proposal",
                event_type="project",
                event_date=date(2025, 9, 12),
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Project Proposal September 12, 2025",
                source_page=1,
                confidence="high",
                year_was_explicit=True,
                uncertainty_reason=None,
            ),
            CandidateEvent(
                title="Midterm 1",
                event_type="exam",
                event_date=date(2025, 10, 3),
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Midterm 1 October 3, 2025",
                source_page=1,
                confidence="high",
                year_was_explicit=True,
                uncertainty_reason=None,
            ),
            CandidateEvent(
                title="Midterm 2",
                event_type="exam",
                event_date=date(2025, 11, 7),
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Midterm 2 November 7, 2025",
                source_page=1,
                confidence="high",
                year_was_explicit=True,
                uncertainty_reason=None,
            ),
            CandidateEvent(
                title="Final Presentation",
                event_type="project",
                event_date=date(2025, 12, 5),
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Final Presentation December 5, 2025",
                source_page=1,
                confidence="high",
                year_was_explicit=True,
                uncertainty_reason=None,
            ),
            CandidateEvent(
                title="Final exam",
                event_type="exam",
                event_date=None,
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Final exam as scheduled by Registrar",
                source_page=1,
                confidence="medium",
                year_was_explicit=True,
                uncertainty_reason=None,
            ),
            CandidateEvent(
                title="Lab assignment make-up deadline",
                event_type="deadline",
                event_date=None,
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Lab assignment make-up deadline as scheduled by course staff",
                source_page=1,
                confidence="medium",
                year_was_explicit=True,
                uncertainty_reason=None,
            ),
            CandidateEvent(
                title="Lab Exams",
                event_type="exam",
                event_date=None,
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Lab Exams are scheduled periodically",
                source_page=1,
                confidence="medium",
                year_was_explicit=True,
                uncertainty_reason=None,
            ),
        ],
        recurring_rules=[
            RecurringRule(
                title="Quick Checks",
                event_type="quiz",
                rule_kind="relative_to_anchor",
                weekday=None,
                start_time=time(8, 0),
                end_time=None,
                is_all_day=False,
                boundary_start=date(2025, 8, 25),
                boundary_end=date(2025, 12, 19),
                exclusion_dates=[],
                source_quote="Quick Checks - 8AM the morning of the lecture",
                source_page=1,
                confidence="high",
                anchor_title="Lecture",
                offset_days=0,
                uncertainty_reason=None,
            ),
            RecurringRule(
                title="Exercise Sets",
                event_type="assignment",
                rule_kind="relative_to_anchor",
                weekday=None,
                start_time=time(8, 0),
                end_time=None,
                is_all_day=False,
                boundary_start=date(2025, 8, 25),
                boundary_end=date(2025, 12, 19),
                exclusion_dates=[],
                source_quote="Exercise Sets - 8AM the morning after the lecture",
                source_page=1,
                confidence="high",
                anchor_title="Lecture",
                offset_days=1,
                uncertainty_reason=None,
            ),
        ],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            calls.append(kwargs["model"])
            return SimpleNamespace(output_parsed=luna_output)

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("app.processing.OpenAI", FakeOpenAI)
    settings = app.state.settings.model_copy(
        update={
            "extraction_mode": "openai",
            "openai_api_key": "test-key",
            "openai_model": "gpt-5.6-luna",
            "openai_fallback_model": "gpt-5.6-terra",
        }
    )

    process_job(str(job_id), settings=settings, session_factory=app.state.session_factory)

    with app.state.session_factory() as session:
        persisted = session.get(ProcessingJob, job_id)
        assert persisted.status == JobStatus.NEEDS_REVIEW, persisted.error_message
        all_events = sorted(
            persisted.document.semester.events,
            key=lambda item: (item.event_date is None, item.title),
        )
        dated_events = [event for event in all_events if event.event_date is not None]
        review_events = [event for event in all_events if event.event_date is None]
        series_count = session.query(RecurringEventSeries).filter(
            RecurringEventSeries.document_id == persisted.document.id
        ).count()
        assert len(dated_events) == 4
        assert len(review_events) == 5
        assert [event.title for event in dated_events] == [
            "Final Presentation",
            "Midterm 1",
            "Midterm 2",
            "Project Proposal",
        ]
        assert [event.title for event in review_events] == [
            "Exercise Sets",
            "Final exam",
            "Lab Exams",
            "Lab assignment make-up deadline",
            "Quick Checks",
        ]
        assert series_count == 0
        assert all(event.recurring_series_id is None for event in review_events)
        ambiguous_titles = {
            event.title for event in review_events if "AMBIGUOUS_RECURRENCE" in event.warning_codes
        }
        assert ambiguous_titles == {"Exercise Sets", "Quick Checks"}

    assert calls == ["gpt-5.6-luna"]


def test_expand_recurring_rules_honors_boundaries_exclusions_dedupes_and_caps():
    anchor = ScheduleAnchor(
        title="Lecture",
        anchor_type="lecture",
        weekday="monday",
        start_time=time(9, 0),
        end_time=time(10, 0),
        boundary_start=date(2026, 9, 7),
        boundary_end=date(2026, 9, 28),
        exclusion_dates=[date(2026, 9, 14)],
        source_quote="Lecture meets every Monday",
        source_page=1,
    )
    weekly_quiz = RecurringRule(
        title="Weekly quiz",
        event_type="quiz",
        rule_kind="weekly_fixed",
        weekday="friday",
        start_time=None,
        end_time=None,
        is_all_day=True,
        boundary_start=date(2026, 9, 4),
        boundary_end=date(2026, 9, 18),
        exclusion_dates=[date(2026, 9, 11)],
        source_quote="Weekly quiz every Friday except September 11",
        source_page=2,
        confidence="medium",
        anchor_title=None,
        offset_days=None,
        uncertainty_reason=None,
    )
    lecture_reflection = RecurringRule(
        title="Lecture reflection",
        event_type="assignment",
        rule_kind="relative_to_anchor",
        weekday=None,
        start_time=None,
        end_time=None,
        is_all_day=True,
        boundary_start=date(2026, 9, 7),
        boundary_end=date(2026, 9, 30),
        exclusion_dates=[date(2026, 9, 23)],
        source_quote="Reflection due two days after each lecture",
        source_page=3,
        confidence="high",
        anchor_title="Lecture",
        offset_days=2,
        uncertainty_reason=None,
    )
    explicit_events = [
        CandidateEvent(
            title="Weekly quiz",
            event_type="quiz",
            event_date=date(2026, 9, 4),
            start_time=None,
            end_time=None,
            is_all_day=True,
            source_quote="Weekly quiz Friday September 4",
            source_page=2,
            confidence="high",
            year_was_explicit=True,
            uncertainty_reason=None,
        )
    ]

    series, derived_events = expand_recurring_rules(
        anchors=[anchor],
        rules=[weekly_quiz, lecture_reflection],
        semester_start=date(2026, 9, 1),
        semester_end=date(2026, 9, 30),
        explicit_events=explicit_events,
        extraction_model="gpt-5.6-luna",
        max_occurrences=200,
    )

    assert len(series) == 2
    assert [(event.title, event.event_date) for event in derived_events] == [
        ("Weekly quiz", date(2026, 9, 18)),
        ("Lecture reflection", date(2026, 9, 9)),
        ("Lecture reflection", date(2026, 9, 30)),
    ]
    assert all(event.recurring_series_id is not None for event in derived_events)
    assert all(event.extraction_model == "gpt-5.6-luna" for event in derived_events)
    assert all(event.review_status == ReviewStatus.NEEDS_REVIEW for event in derived_events)
    assert all("DATE_CONFLICT" not in item.warning_codes for item in series)
    assert {item.title: item.occurrence_count for item in series} == {
        "Weekly quiz": 1,
        "Lecture reflection": 2,
    }

    long_rule = RecurringRule(
        title="Homework",
        event_type="assignment",
        rule_kind="weekly_fixed",
        weekday="monday",
        start_time=None,
        end_time=None,
        is_all_day=True,
        boundary_start=date(2026, 1, 5),
        boundary_end=date(2030, 1, 1),
        exclusion_dates=[],
        source_quote="Homework every Monday",
        source_page=5,
        confidence="high",
        anchor_title=None,
        offset_days=None,
        uncertainty_reason=None,
    )

    _, capped_events = expand_recurring_rules(
        anchors=[],
        rules=[long_rule],
        semester_start=date(2026, 1, 1),
        semester_end=date(2030, 1, 1),
        explicit_events=[],
        extraction_model="gpt-5.6-luna",
        max_occurrences=200,
    )

    assert len(capped_events) == 200


def test_date_conflict_detection_compares_normalized_titles():
    known_dates = {"midterm exam": {date(2026, 10, 14)}}

    assert detect_date_conflict("Midterm Exam", date(2026, 10, 15), known_dates) is True
    assert detect_date_conflict("Midterm Exam", date(2026, 10, 14), known_dates) is False
    assert detect_date_conflict("Final exam", date(2026, 10, 15), known_dates) is False
    assert detect_date_conflict("Final exam", None, known_dates) is False


def test_local_extractor_builds_weekly_recurring_rule_from_clear_due_line():
    pages = [
        {
            "page": 1,
            "ocr": False,
            "text": (
                "CS 101 Syllabus\n"
                "Homework due every Friday from Sep 4, 2026 "
                "through Dec 4, 2026 except Nov 27, 2026.\n"
            ),
        }
    ]

    extraction = extract_locally(pages)

    assert extraction.course_name == "CS 101 Syllabus"
    assert extraction.events == []
    assert len(extraction.recurring_rules) == 1
    rule = extraction.recurring_rules[0]
    assert rule.title == "Homework"
    assert rule.rule_kind == "weekly_fixed"
    assert rule.weekday == "friday"
    assert rule.boundary_start == date(2026, 9, 4)
    assert rule.boundary_end == date(2026, 12, 4)
    assert rule.exclusion_dates == [date(2026, 11, 27)]


def test_safe_filename_removes_path_segments_and_header_characters():
    assert safe_filename("../private/syllabus.pdf") == "syllabus.pdf"
    assert safe_filename('..\\private\\my"course.pdf') == "my_course.pdf"


def test_process_job_extracts_and_persists_reviewable_events(app_client, monkeypatch):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)

    with app.state.session_factory() as session:
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
            filename="cs101.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/cs101.pdf",
        )
        job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=document,
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        storage_key = document.storage_key

    file_path = storage_path / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(
        make_pdf("CS 101 Midterm exam October 14, 2026. Course policies and schedule. " * 4)
    )

    monkeypatch.setattr(
        "app.processing.extract_syllabus",
        lambda pages, settings: SyllabusExtraction(
            course_code="CS 101",
            course_name="Introduction to Computer Science",
            instructor=None,
            events=[
                CandidateEvent(
                    title="Midterm exam",
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
                ),
                CandidateEvent(
                    title="Final exam",
                    event_type="exam",
                    event_date=None,
                    source_quote="Final exam as scheduled by Registrar",
                    source_page=1,
                    confidence="low",
                    year_was_explicit=False,
                    uncertainty_reason="The registrar has not published the date.",
                ),
            ],
        ),
    )

    process_job(str(job_id), settings=app.state.settings, session_factory=app.state.session_factory)

    with app.state.session_factory() as session:
        persisted = session.get(ProcessingJob, job_id)
        assert persisted.status == JobStatus.NEEDS_REVIEW, persisted.error_message
        assert persisted.document.used_ocr is False
        assert persisted.document.extracted_pages[0]["page"] == 1
        assert len(persisted.document.semester.events) == 2
        midterm = next(
            event for event in persisted.document.semester.events if event.title == "Midterm exam"
        )
        assert midterm.source_page == 1
        assert midterm.warning_codes == []
        assert midterm.review_status.value == "needs_review"
        final = next(
            event for event in persisted.document.semester.events if event.title == "Final exam"
        )
        assert final.event_date is None
        assert "DATE_MISSING" in final.warning_codes


def test_process_job_contains_failure_to_one_document(app_client, monkeypatch):
    _, app = app_client
    with app.state.session_factory() as session:
        semester = Semester(
            user_id=USER_A,
            name="Fall 2026",
            start_date=date(2026, 8, 24),
            end_date=date(2026, 12, 18),
            timezone="America/New_York",
        )
        session.add(semester)
        session.flush()
        failed_job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=SyllabusDocument(
                user_id=USER_A,
                semester_id=semester.id,
                filename="broken.pdf",
                content_type="application/pdf",
                size_bytes=20,
                storage_key="missing/broken.pdf",
            ),
            status=JobStatus.QUEUED,
        )
        waiting_job = ProcessingJob(
            user_id=USER_A,
            semester_id=semester.id,
            document=SyllabusDocument(
                user_id=USER_A,
                semester_id=semester.id,
                filename="waiting.pdf",
                content_type="application/pdf",
                size_bytes=20,
                storage_key="missing/waiting.pdf",
            ),
            status=JobStatus.QUEUED,
        )
        session.add_all([failed_job, waiting_job])
        session.commit()
        failed_id = failed_job.id
        waiting_id = waiting_job.id

    process_job(
        str(failed_id), settings=app.state.settings, session_factory=app.state.session_factory
    )

    with app.state.session_factory() as session:
        assert session.get(ProcessingJob, failed_id).status == JobStatus.FAILED
        assert session.get(ProcessingJob, waiting_id).status == JobStatus.QUEUED
