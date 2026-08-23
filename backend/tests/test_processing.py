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


def test_validation_marks_explicit_numeric_date_with_wrong_weekday_as_conflict():
    candidate = CandidateEvent(
        title="No lecture - Friday schedule",
        event_type="class",
        event_date=date(2025, 11, 27),
        source_quote="27-Nov Wednesday No Lecture, Friday Schedule",
        source_page=4,
        confidence="high",
        year_was_explicit=False,
    )
    pages = [
        {
            "page": 4,
            "text": "27-Nov Wednesday No Lecture, Friday Schedule",
            "ocr": False,
        }
    ]

    warning_codes, reason = validate_candidate(
        candidate,
        pages,
        semester_start=date(2025, 8, 25),
        semester_end=date(2025, 12, 20),
    )

    assert "DATE_CONFLICT" in warning_codes
    assert reason == processing.SYLLABUS_TYPO_WARNING


def test_validation_uses_cited_page_context_when_source_quote_omits_date_and_weekday():
    candidate = CandidateEvent(
        title="No lecture - Friday schedule",
        event_type="class",
        event_date=date(2025, 11, 27),
        source_quote="No Lecture, Friday Schedule",
        source_page=4,
        confidence="high",
        year_was_explicit=False,
    )
    pages = [
        {
            "page": 4,
            "text": "27-Nov Wednesday No Lecture, Friday Schedule",
            "ocr": False,
        }
    ]

    warning_codes, reason = validate_candidate(
        candidate,
        pages,
        semester_start=date(2025, 8, 25),
        semester_end=date(2025, 12, 20),
    )

    assert "DATE_CONFLICT" in warning_codes
    assert reason == processing.SYLLABUS_TYPO_WARNING


def test_explicit_date_normalization_uses_nearest_preceding_context_row_when_quote_omits_date():
    candidate = CandidateEvent(
        title="No lecture - Friday schedule",
        event_type="class",
        event_date=date(2025, 11, 26),
        source_quote="No Lecture, Friday Schedule",
        source_page=4,
        confidence="high",
        year_was_explicit=False,
    )
    extraction = SyllabusExtraction(
        course_code="CS-UY 1114",
        course_name="Introduction to Programming and Problem Solving",
        events=[candidate],
    )
    pages = [
        {
            "page": 4,
            "text": (
                "26-Nov Wednesday Review session.\n"
                "27-Nov Thursday No Lecture, Friday Schedule.\n"
                "28-Nov Friday Make-up session."
            ),
            "ocr": False,
        }
    ]

    normalized = processing._normalize_explicit_source_event_dates(
        extraction,
        semester_start=date(2025, 8, 25),
        semester_end=date(2025, 12, 20),
        pages=pages,
    )
    warning_codes, _ = validate_candidate(
        normalized.events[0],
        pages,
        semester_start=date(2025, 8, 25),
        semester_end=date(2025, 12, 20),
    )

    assert normalized.events[0].event_date == date(2025, 11, 27)
    assert "DATE_CONFLICT" not in warning_codes


def test_explicit_date_normalization_uses_candidate_matching_occurrence_for_repeated_quote():
    candidate = CandidateEvent(
        title="No lecture - Friday schedule",
        event_type="class",
        event_date=date(2025, 11, 27),
        source_quote="No Lecture, Friday Schedule",
        source_page=4,
        confidence="high",
        year_was_explicit=False,
    )
    extraction = SyllabusExtraction(
        course_code="CS-UY 1114",
        course_name="Introduction to Programming and Problem Solving",
        events=[candidate],
    )
    pages = [
        {
            "page": 4,
            "text": (
                "26-Nov Wednesday No Lecture, Friday Schedule.\n"
                "Course policies and reminders.\n"
                "27-Nov Thursday No Lecture, Friday Schedule."
            ),
            "ocr": False,
        }
    ]

    normalized = processing._normalize_explicit_source_event_dates(
        extraction,
        semester_start=date(2025, 8, 25),
        semester_end=date(2025, 12, 20),
        pages=pages,
    )
    warning_codes, _ = validate_candidate(
        normalized.events[0],
        pages,
        semester_start=date(2025, 8, 25),
        semester_end=date(2025, 12, 20),
    )

    assert normalized.events[0].event_date == date(2025, 11, 27)
    assert "DATE_CONFLICT" not in warning_codes


def test_explicit_date_normalization_keeps_model_date_when_repeated_quote_matches_no_candidate_date(
):
    candidate = CandidateEvent(
        title="No lecture - Friday schedule",
        event_type="class",
        event_date=date(2025, 11, 28),
        source_quote="No Lecture, Friday Schedule",
        source_page=4,
        confidence="high",
        year_was_explicit=False,
    )
    extraction = SyllabusExtraction(
        course_code="CS-UY 1114",
        course_name="Introduction to Programming and Problem Solving",
        events=[candidate],
    )
    pages = [
        {
            "page": 4,
            "text": (
                "26-Nov Wednesday No Lecture, Friday Schedule.\n"
                "Course policies and reminders.\n"
                "27-Nov Thursday No Lecture, Friday Schedule."
            ),
            "ocr": False,
        }
    ]

    normalized = processing._normalize_explicit_source_event_dates(
        extraction,
        semester_start=date(2025, 8, 25),
        semester_end=date(2025, 12, 20),
        pages=pages,
    )

    assert normalized.events[0].event_date == date(2025, 11, 28)


def test_explicit_date_normalization_allows_repeated_quote_when_all_occurrences_share_one_pair():
    candidate = CandidateEvent(
        title="No lecture - Friday schedule",
        event_type="class",
        event_date=date(2025, 11, 26),
        source_quote="No Lecture, Friday Schedule",
        source_page=4,
        confidence="high",
        year_was_explicit=False,
    )
    extraction = SyllabusExtraction(
        course_code="CS-UY 1114",
        course_name="Introduction to Programming and Problem Solving",
        events=[candidate],
    )
    pages = [
        {
            "page": 4,
            "text": (
                "27-Nov Thursday No Lecture, Friday Schedule.\n"
                "Repeated summary line.\n"
                "27-Nov Thursday No Lecture, Friday Schedule."
            ),
            "ocr": False,
        }
    ]

    normalized = processing._normalize_explicit_source_event_dates(
        extraction,
        semester_start=date(2025, 8, 25),
        semester_end=date(2025, 12, 20),
        pages=pages,
    )

    assert normalized.events[0].event_date == date(2025, 11, 27)


@pytest.mark.parametrize(
    ("source_quote", "event_date"),
    [
        ("27-Nov Thursday No Lecture, Friday Schedule", date(2025, 11, 27)),
        ("Wednesday No Lecture, Friday Schedule", date(2025, 11, 27)),
    ],
)
def test_validation_does_not_invent_weekday_conflicts_without_a_real_mismatch(
    source_quote: str,
    event_date: date,
):
    candidate = CandidateEvent(
        title="No lecture - Friday schedule",
        event_type="class",
        event_date=event_date,
        source_quote=source_quote,
        source_page=4,
        confidence="high",
        year_was_explicit=False,
    )
    pages = [{"page": 4, "text": source_quote, "ocr": False}]

    warning_codes, _ = validate_candidate(
        candidate,
        pages,
        semester_start=date(2025, 8, 25),
        semester_end=date(2025, 12, 20),
    )

    assert "DATE_CONFLICT" not in warning_codes


def test_explicit_date_normalization_does_not_use_the_first_of_multiple_dates():
    source_quote = (
        "27-Nov Wednesday No Lecture, Friday Schedule. "
        "28-Nov Friday Make-up session."
    )
    candidate = CandidateEvent(
        title="Make-up session",
        event_type="class",
        event_date=date(2025, 11, 28),
        source_quote=source_quote,
        source_page=4,
        confidence="high",
        year_was_explicit=False,
    )
    extraction = SyllabusExtraction(
        course_code="CS-UY 1114",
        course_name="Introduction to Programming and Problem Solving",
        events=[candidate],
    )

    normalized = processing._normalize_explicit_source_event_dates(
        extraction,
        semester_start=date(2025, 8, 25),
        semester_end=date(2025, 12, 20),
    )
    warning_codes, _ = validate_candidate(
        normalized.events[0],
        [{"page": 4, "text": source_quote, "ocr": False}],
        semester_start=date(2025, 8, 25),
        semester_end=date(2025, 12, 20),
    )

    assert normalized.events[0].event_date == date(2025, 11, 28)
    assert "DATE_CONFLICT" not in warning_codes


def test_explicit_date_normalization_prefers_source_quote_date_over_page_context():
    candidate = CandidateEvent(
        title="No lecture - Friday schedule",
        event_type="class",
        event_date=date(2025, 11, 26),
        source_quote="27-Nov Wednesday No Lecture, Friday Schedule",
        source_page=4,
        confidence="high",
        year_was_explicit=False,
    )
    extraction = SyllabusExtraction(
        course_code="CS-UY 1114",
        course_name="Introduction to Programming and Problem Solving",
        events=[candidate],
    )
    pages = [
        {
            "page": 4,
            "text": (
                "26-Nov Wednesday Review session. "
                "27-Nov Wednesday No Lecture, Friday Schedule. "
                "28-Nov Friday Make-up session."
            ),
            "ocr": False,
        }
    ]

    normalized = processing._normalize_explicit_source_event_dates(
        extraction,
        semester_start=date(2025, 8, 25),
        semester_end=date(2025, 12, 20),
        pages=pages,
    )
    warning_codes, warning_reason = validate_candidate(
        normalized.events[0],
        pages,
        semester_start=date(2025, 8, 25),
        semester_end=date(2025, 12, 20),
    )

    assert normalized.events[0].event_date == date(2025, 11, 27)
    assert warning_codes == ["DATE_CONFLICT"]
    assert (
        warning_reason
        == "Syllabus typo. The written date and weekday do not match. The numeric date was kept."
    )


def test_explicit_date_normalization_supports_pipe_separated_source_quote_dates():
    candidate = CandidateEvent(
        title="No lecture - Friday schedule",
        event_type="class",
        event_date=date(2025, 11, 26),
        source_quote="24 | 27-Nov | Wednesday | No Lecture, Friday Schedule",
        source_page=4,
        confidence="high",
        year_was_explicit=False,
    )
    extraction = SyllabusExtraction(
        course_code="CS-UY 1114",
        course_name="Introduction to Programming and Problem Solving",
        events=[candidate],
    )
    pages = [
        {
            "page": 4,
            "text": (
                "22 | 25-Nov | Monday | Review session\n"
                "23 | 26-Nov | Tuesday | Office hours\n"
                "24 | 27-Nov | Wednesday | No Lecture, Friday Schedule\n"
                "25 | 28-Nov | Friday | Make-up session"
            ),
            "ocr": False,
        }
    ]

    normalized = processing._normalize_explicit_source_event_dates(
        extraction,
        semester_start=date(2025, 8, 25),
        semester_end=date(2025, 12, 20),
        pages=pages,
    )
    warning_codes, warning_reason = validate_candidate(
        normalized.events[0],
        pages,
        semester_start=date(2025, 8, 25),
        semester_end=date(2025, 12, 20),
    )

    assert normalized.events[0].event_date == date(2025, 11, 27)
    assert warning_codes == ["DATE_CONFLICT"]
    assert (
        warning_reason
        == "Syllabus typo. The written date and weekday do not match. The numeric date was kept."
    )


def test_explicit_date_normalization_keeps_model_date_when_multiple_quote_pairs_are_ambiguous():
    source_quote = (
        "27-Nov Wednesday No Lecture, Friday Schedule. "
        "28-Nov Friday Make-up session."
    )
    candidate = CandidateEvent(
        title="No lecture - Friday schedule",
        event_type="class",
        event_date=date(2025, 11, 26),
        source_quote=source_quote,
        source_page=4,
        confidence="high",
        year_was_explicit=False,
    )
    extraction = SyllabusExtraction(
        course_code="CS-UY 1114",
        course_name="Introduction to Programming and Problem Solving",
        events=[candidate],
    )

    normalized = processing._normalize_explicit_source_event_dates(
        extraction,
        semester_start=date(2025, 8, 25),
        semester_end=date(2025, 12, 20),
    )

    assert normalized.events[0].event_date == date(2025, 11, 26)


def test_validation_does_not_warn_when_explicit_quote_weekday_matches_real_date():
    candidate = CandidateEvent(
        title="No lecture - Friday schedule",
        event_type="class",
        event_date=date(2025, 11, 27),
        source_quote="27-Nov Thursday No Lecture, Friday Schedule",
        source_page=4,
        confidence="high",
        year_was_explicit=False,
    )
    pages = [
        {
            "page": 4,
            "text": (
                "26-Nov Wednesday Review session. "
                "27-Nov Thursday No Lecture, Friday Schedule. "
                "28-Nov Friday Make-up session."
            ),
            "ocr": False,
        }
    ]

    warning_codes, _ = validate_candidate(
        candidate,
        pages,
        semester_start=date(2025, 8, 25),
        semester_end=date(2025, 12, 20),
    )

    assert "DATE_CONFLICT" not in warning_codes


def test_validation_does_not_warn_when_pipe_separated_quote_weekday_matches_real_date():
    candidate = CandidateEvent(
        title="No lecture - Friday schedule",
        event_type="class",
        event_date=date(2025, 11, 27),
        source_quote="24 | 27-Nov | Thursday | No Lecture, Friday Schedule",
        source_page=4,
        confidence="high",
        year_was_explicit=False,
    )
    pages = [
        {
            "page": 4,
            "text": (
                "22 | 25-Nov | Tuesday | Review session\n"
                "23 | 26-Nov | Wednesday | Office hours\n"
                "24 | 27-Nov | Thursday | No Lecture, Friday Schedule\n"
                "25 | 28-Nov | Friday | Make-up session"
            ),
            "ocr": False,
        }
    ]

    warning_codes, _ = validate_candidate(
        candidate,
        pages,
        semester_start=date(2025, 8, 25),
        semester_end=date(2025, 12, 20),
    )

    assert "DATE_CONFLICT" not in warning_codes


def test_canonicalize_event_identity_normalizes_known_syllabus_items():
    quick_checks = processing._canonicalize_event_identity(
        CandidateEvent(
            title="Quick Checks deadline",
            event_type="deadline",
            event_date=None,
            source_quote="Quick Checks - 8AM the morning of the lecture",
            source_page=2,
            confidence="medium",
            year_was_explicit=True,
        )
    )
    exercise_sets = processing._canonicalize_event_identity(
        CandidateEvent(
            title="Exercise Sets deadline",
            event_type="deadline",
            event_date=None,
            source_quote="Exercise Sets - 8AM the morning after the lecture",
            source_page=2,
            confidence="medium",
            year_was_explicit=True,
        )
    )
    no_lecture = processing._canonicalize_event_identity(
        CandidateEvent(
            title="No lecture / Friday schedule",
            event_type="other",
            event_date=date(2025, 11, 27),
            source_quote="24 | 27-Nov | Wednesday | No Lecture, Friday Schedule",
            source_page=4,
            confidence="medium",
            year_was_explicit=False,
        )
    )

    assert (quick_checks.title, quick_checks.event_type) == ("Quick Checks", "quiz")
    assert (exercise_sets.title, exercise_sets.event_type) == ("Exercise Sets", "assignment")
    assert (no_lecture.title, no_lecture.event_type) == (
        "No lecture / Friday schedule",
        "class",
    )


def test_canonicalize_event_identity_does_not_use_unrelated_source_mentions():
    candidate = CandidateEvent(
        title="Final exam",
        event_type="exam",
        event_date=None,
        source_quote="Unlike Quick Checks, the final exam is scheduled by the Registrar.",
        source_page=1,
        confidence="medium",
        year_was_explicit=True,
    )

    normalized = processing._canonicalize_event_identity(candidate)

    assert normalized.title == "Final exam"
    assert normalized.event_type == "exam"


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


def test_process_job_keeps_numeric_date_and_skips_terra_for_pure_source_weekday_typo(
    app_client, monkeypatch
):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)
    calls: list[str] = []
    page_text = (
        "26-Nov Wednesday Review session.\n"
        "27-Nov Wednesday No Lecture, Friday Schedule.\n"
        "28-Nov Friday Make-up session.\n"
    ) * 4

    with app.state.session_factory() as session:
        semester = Semester(
            user_id=USER_A,
            name="Fall 2025",
            start_date=date(2025, 8, 25),
            end_date=date(2025, 12, 20),
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
    file_path.write_bytes(make_pdf(page_text))

    luna_output = SyllabusExtraction(
        course_code="CS-UY 1114",
        course_name="Introduction to Programming and Problem Solving",
        instructor=None,
        events=[
            CandidateEvent(
                title="No lecture - Friday schedule",
                event_type="class",
                event_date=date(2025, 11, 27),
                source_quote="27-Nov Wednesday No Lecture, Friday Schedule",
                source_page=1,
                confidence="high",
                year_was_explicit=False,
            )
        ],
    )
    terra_output = SyllabusExtraction(
        course_code="CS-UY 1114",
        course_name="Introduction to Programming and Problem Solving",
        instructor=None,
        events=[
            CandidateEvent(
                title="No lecture - Friday schedule",
                event_type="class",
                event_date=date(2025, 11, 26),
                source_quote="27-Nov Wednesday No Lecture, Friday Schedule",
                source_page=1,
                confidence="high",
                year_was_explicit=False,
            )
        ],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            calls.append(kwargs["model"])
            output = luna_output if kwargs["model"] == "gpt-5.6-luna" else terra_output
            return SimpleNamespace(output_parsed=output)

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
        assert persisted.fallback_used is False
        assert persisted.fallback_reason_codes == []
        events = persisted.document.semester.events
        assert len(events) == 1
        event = events[0]
        assert event.event_date == date(2025, 11, 27)
        assert event.extraction_model == "gpt-5.6-luna"
        assert event.warning_codes == ["DATE_CONFLICT"]
        assert (
            event.warning_reason
            == "Syllabus typo. The written date and weekday do not match. "
            "The numeric date was kept."
        )
        assert event.derivation_summary is None

    assert calls == ["gpt-5.6-luna"]


def test_cross_event_date_conflict_stays_retryable_when_source_has_weekday_typo():
    candidate = CandidateEvent(
        title="No lecture - Friday schedule",
        event_type="class",
        event_date=date(2025, 11, 27),
        source_quote="27-Nov Wednesday No Lecture, Friday Schedule",
        source_page=1,
        confidence="high",
        year_was_explicit=False,
    )
    extraction = SyllabusExtraction(
        course_code="CS-UY 1114",
        course_name="Introduction to Programming and Problem Solving",
        events=[candidate],
    )
    pages = [
        {
            "page": 1,
            "text": "27-Nov Wednesday No Lecture, Friday Schedule",
            "ocr": False,
        }
    ]

    retryable_codes, flagged_events, _, _ = processing._preview_retryable_codes(
        extraction,
        pages,
        semester_start=date(2025, 8, 25),
        semester_end=date(2025, 12, 20),
        known_dates_by_title={candidate.title.casefold(): {date(2025, 11, 26)}},
    )

    assert retryable_codes == ["DATE_CONFLICT"]
    assert flagged_events == {0}


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


def test_materializes_missing_ambiguous_recurring_heading_for_review_without_false_positive():
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
            "page": 3,
            "ocr": False,
            "text": (
                'Lab Exams (10%): Periodically, labs may start with a "lab exam". '
                "Lab Policy: Labs may start late. "
                "Exam Policy: Exam dates may change. "
                "Academic dishonesty may include misrepresentation or deception."
            ),
        }
    ]

    completed = processing._materialize_missing_ambiguous_review_events(
        extraction,
        pages,
        extraction_model="gpt-5.6-luna",
    )

    assert len(completed.events) == 1
    event = completed.events[0]
    assert event.title == "Lab Exams"
    assert event.event_type == "exam"
    assert event.event_date is None
    assert event.source_page == 3
    assert event.source_quote == 'Lab Exams (10%): Periodically, labs may start with a "lab exam".'
    assert event.extraction_model == "gpt-5.6-luna"
    assert event.derivation_summary == (
        "Dates were not generated because the syllabus does not identify every occurrence."
    )
    _, ambiguous_indexes, _ = processing._normalize_ambiguous_recurring_content(completed, pages)
    assert ambiguous_indexes == {0}
    assert processing._event_type_for_title("Homework deadline") == "deadline"


def test_materialized_lab_exams_heading_collapses_existing_periodic_alias_on_same_page():
    page_text = (
        'Lab Exams (10%): Periodically, labs may start with a "lab exam". '
        "Lab Policy: Labs may start late."
    )
    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Periodic lab exams",
                event_type="exam",
                event_date=None,
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote='Periodically, labs may start with a "lab exam".',
                source_page=3,
                confidence="medium",
                year_was_explicit=True,
                uncertainty_reason="The syllabus does not identify every lab exam date.",
                extraction_model="gpt-5.6-luna",
                review_status=ReviewStatus.NEEDS_REVIEW,
            )
        ],
        schedule_anchors=[],
        recurring_rules=[],
    )
    pages = [{"page": 3, "ocr": False, "text": page_text}]

    completed = processing._materialize_missing_ambiguous_review_events(
        extraction,
        pages,
        extraction_model="gpt-5.6-luna",
    )
    normalized, ambiguous_indexes, _ = processing._normalize_ambiguous_recurring_content(
        completed,
        pages,
    )

    assert [
        (event.title, event.source_quote, event.review_status)
        for event in normalized.events
    ] == [
        (
            "Lab Exams",
            'Lab Exams (10%): Periodically, labs may start with a "lab exam".',
            ReviewStatus.NEEDS_REVIEW,
        )
    ]
    assert ambiguous_indexes == {0}


def test_materialized_lab_exams_heading_does_not_merge_distinct_page_or_dated_items():
    page_text = (
        'Lab Exams (10%): Periodically, labs may start with a "lab exam". '
        "Lab Policy: Labs may start late."
    )
    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Periodic lab exams",
                event_type="exam",
                event_date=None,
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote='Periodically, labs may start with a "lab exam".',
                source_page=4,
                confidence="medium",
                year_was_explicit=True,
                uncertainty_reason="The syllabus does not identify every lab exam date.",
                extraction_model="gpt-5.6-luna",
                review_status=ReviewStatus.NEEDS_REVIEW,
            ),
            CandidateEvent(
                title="Lab Exams",
                event_type="exam",
                event_date=date(2025, 10, 14),
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Lab Exams October 14, 2025",
                source_page=3,
                confidence="high",
                year_was_explicit=True,
                extraction_model="gpt-5.6-luna",
                review_status=ReviewStatus.NEEDS_REVIEW,
            ),
        ],
        schedule_anchors=[],
        recurring_rules=[],
    )
    pages = [{"page": 3, "ocr": False, "text": page_text}]

    completed = processing._materialize_missing_ambiguous_review_events(
        extraction,
        pages,
        extraction_model="gpt-5.6-luna",
    )
    normalized, ambiguous_indexes, _ = processing._normalize_ambiguous_recurring_content(
        completed,
        pages,
    )

    assert [
        (event.title, event.source_page, event.event_date, event.source_quote)
        for event in normalized.events
    ] == [
        (
            "Lab Exams",
            4,
            None,
            'Periodically, labs may start with a "lab exam".',
        ),
        (
            "Lab Exams",
            3,
            date(2025, 10, 14),
            "Lab Exams October 14, 2025",
        ),
    ]
    assert ambiguous_indexes == {0}


def test_materializes_missing_lab_makeup_deadline_for_review():
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
            "page": 2,
            "ocr": False,
            "text": (
                "Make-Up Policy - Missed labs can be submitted until "
                "11:59pm on the Sunday that follows\n"
                "the lab. Labs can only be made up with an excused absence."
            ),
        }
    ]

    completed = processing._materialize_missing_ambiguous_review_events(
        extraction,
        pages,
        extraction_model="gpt-5.6-luna",
    )

    assert len(completed.events) == 1
    event = completed.events[0]
    assert event.title == "Lab assignment make-up deadline"
    assert event.event_type == "deadline"
    assert event.event_date is None
    assert event.end_time == time(23, 59)
    assert event.source_page == 2
    assert event.source_quote == (
        "Make-Up Policy - Missed labs can be submitted until "
        "11:59pm on the Sunday that follows the lab."
    )
    assert event.extraction_model == "gpt-5.6-luna"
    assert event.derivation_summary == (
        "Dates were not generated because the syllabus does not identify every occurrence."
    )
    normalized, ambiguous_indexes, _ = processing._normalize_ambiguous_recurring_content(
        completed,
        pages,
    )
    assert normalized.events[0].title == "Lab assignment make-up deadline"
    assert ambiguous_indexes == {0}


def test_materializer_reuses_luna_lab_makeup_submission_instead_of_duplicating_it():
    source_quote = (
        "Make-Up Policy - Missed labs can be submitted until "
        "11:59pm on the Sunday that follows the lab."
    )
    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Lab make-up submissions",
                event_type="deadline",
                event_date=None,
                start_time=None,
                end_time=time(23, 59),
                is_all_day=False,
                source_quote=source_quote,
                source_page=2,
                confidence="medium",
                year_was_explicit=True,
                uncertainty_reason=(
                    "The syllabus does not identify the dates of individual labs."
                ),
                extraction_model="gpt-5.6-luna",
            )
        ],
        schedule_anchors=[],
        recurring_rules=[],
    )
    pages = [{"page": 2, "ocr": False, "text": source_quote}]

    completed = processing._materialize_missing_ambiguous_review_events(
        extraction,
        pages,
        extraction_model="gpt-5.6-luna",
    )

    assert len(completed.events) == 1
    event = completed.events[0]
    assert event.title == "Lab assignment make-up deadline"
    assert event.event_type == "deadline"
    assert event.event_date is None
    assert event.end_time == time(23, 59)
    assert event.source_quote == source_quote
    assert event.source_page == 2
    assert event.extraction_model == "gpt-5.6-luna"
    assert event.derivation_summary == (
        "Dates were not generated because the syllabus does not identify every occurrence."
    )


def test_materializer_collapses_luna_and_terra_lab_makeup_aliases_from_same_source():
    source_quote = (
        "Missed labs can be submitted until 11:59pm on the Sunday that follows the lab."
    )
    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Lab assignment make-up deadline",
                event_type="deadline",
                event_date=None,
                end_time=time(23, 59),
                is_all_day=False,
                source_quote=source_quote,
                source_page=2,
                confidence="medium",
                year_was_explicit=True,
                extraction_model="gpt-5.6-luna",
            ),
            CandidateEvent(
                title="Missed lab make-up deadline",
                event_type="deadline",
                event_date=None,
                end_time=time(23, 59),
                is_all_day=False,
                source_quote=source_quote,
                source_page=2,
                confidence="medium",
                year_was_explicit=True,
                extraction_model="gpt-5.6-terra",
            ),
        ],
        schedule_anchors=[],
        recurring_rules=[],
    )
    pages = [{"page": 2, "ocr": False, "text": source_quote}]

    completed = processing._materialize_missing_ambiguous_review_events(
        extraction,
        pages,
        extraction_model="gpt-5.6-luna",
    )

    assert len(completed.events) == 1
    event = completed.events[0]
    assert event.title == "Lab assignment make-up deadline"
    assert event.source_quote == source_quote
    assert event.source_page == 2
    assert event.end_time == time(23, 59)
    assert event.extraction_model == "gpt-5.6-luna"


def test_materializer_does_not_collapse_lab_makeup_aliases_from_different_pages():
    source_quote = (
        "Missed labs can be submitted until 11:59pm on the Sunday that follows the lab."
    )
    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Missed lab make-up deadline",
                event_type="deadline",
                event_date=None,
                end_time=time(23, 59),
                is_all_day=False,
                source_quote=source_quote,
                source_page=2,
                confidence="medium",
                year_was_explicit=True,
                extraction_model="gpt-5.6-luna",
            )
        ],
        schedule_anchors=[],
        recurring_rules=[],
    )
    pages = [
        {"page": 2, "ocr": False, "text": "Course logistics only."},
        {"page": 3, "ocr": False, "text": source_quote},
    ]

    completed = processing._materialize_missing_ambiguous_review_events(
        extraction,
        pages,
        extraction_model="gpt-5.6-luna",
    )

    assert [(event.title, event.source_page) for event in completed.events] == [
        ("Missed lab make-up deadline", 2),
        ("Lab assignment make-up deadline", 3),
    ]


def test_materializer_does_not_collapse_distinct_same_page_lab_policy_text():
    existing_quote = (
        "Lab make-up deadline: 11:59pm the Sunday following the lab after approved absences."
    )
    policy_source = (
        "Missed labs can be submitted until 11:59pm on the Sunday that follows the lab."
    )
    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Lab make-up submissions",
                event_type="deadline",
                event_date=None,
                end_time=time(23, 59),
                is_all_day=False,
                source_quote=existing_quote,
                source_page=2,
                confidence="medium",
                year_was_explicit=True,
                extraction_model="gpt-5.6-luna",
            )
        ],
        schedule_anchors=[],
        recurring_rules=[],
    )
    pages = [
        {
            "page": 2,
            "ocr": False,
            "text": policy_source,
        }
    ]

    completed = processing._materialize_missing_ambiguous_review_events(
        extraction,
        pages,
        extraction_model="gpt-5.6-luna",
    )

    assert [(event.title, event.source_quote) for event in completed.events] == [
        ("Lab make-up submissions", existing_quote),
        ("Lab assignment make-up deadline", policy_source),
    ]


def test_materializer_collapses_short_alias_quote_into_same_page_lab_policy():
    policy_source = (
        "Missed labs can be submitted until 11:59pm on the Sunday that follows the lab."
    )
    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Lab make-up submissions",
                event_type="deadline",
                event_date=None,
                end_time=None,
                is_all_day=True,
                source_quote="Lab make-up submissions",
                source_page=2,
                confidence="medium",
                year_was_explicit=True,
                extraction_model="gpt-5.6-luna",
            )
        ],
        schedule_anchors=[],
        recurring_rules=[],
    )
    pages = [
        {
            "page": 2,
            "ocr": False,
            "text": f"Lab policies. {policy_source}",
        }
    ]

    completed = processing._materialize_missing_ambiguous_review_events(
        extraction,
        pages,
        extraction_model="gpt-5.6-luna",
    )

    assert len(completed.events) == 1
    event = completed.events[0]
    assert event.title == "Lab assignment make-up deadline"
    assert event.end_time == time(23, 59)
    assert event.event_date is None
    assert event.source_quote == policy_source
    assert event.source_page == 2


def test_materializer_does_not_collapse_short_alias_when_page_has_multiple_lab_policies():
    first_policy = "Missed labs can be submitted until 11:59pm on the Sunday that follows the lab."
    second_policy = "Lab assignment make-up deadline: 10:00pm the Sunday following the lab."
    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Lab make-up submissions",
                event_type="deadline",
                event_date=None,
                end_time=None,
                is_all_day=True,
                source_quote="Lab make-up submissions",
                source_page=2,
                confidence="medium",
                year_was_explicit=True,
                extraction_model="gpt-5.6-luna",
            )
        ],
        schedule_anchors=[],
        recurring_rules=[],
    )
    pages = [
        {
            "page": 2,
            "ocr": False,
            "text": f"{first_policy} {second_policy}",
        }
    ]

    completed = processing._materialize_missing_ambiguous_review_events(
        extraction,
        pages,
        extraction_model="gpt-5.6-luna",
    )

    assert [(event.title, event.source_quote) for event in completed.events] == [
        ("Lab make-up submissions", "Lab make-up submissions"),
        ("Lab assignment make-up deadline", first_policy),
        ("Lab assignment make-up deadline", second_policy),
    ]


def test_materializer_does_not_merge_an_unrelated_lab_deadline():
    unrelated_source = "Lab project report deadline is November 14 at 11:59pm."
    policy_source = (
        "Missed labs can be submitted until 11:59pm on the Sunday that follows the lab."
    )
    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Lab project report deadline",
                event_type="deadline",
                event_date=date(2025, 11, 14),
                end_time=time(23, 59),
                is_all_day=False,
                source_quote=unrelated_source,
                source_page=2,
                confidence="high",
                year_was_explicit=True,
                extraction_model="gpt-5.6-luna",
            )
        ],
        schedule_anchors=[],
        recurring_rules=[],
    )
    pages = [
        {
            "page": 2,
            "ocr": False,
            "text": f"{unrelated_source} {policy_source}",
        }
    ]

    completed = processing._materialize_missing_ambiguous_review_events(
        extraction,
        pages,
        extraction_model="gpt-5.6-luna",
    )

    assert [event.title for event in completed.events] == [
        "Lab project report deadline",
        "Lab assignment make-up deadline",
    ]


def test_materializer_and_ambiguous_normalization_collapses_dated_policy_alias():
    policy_source = (
        "Missed labs can be submitted until 11:59pm on the Sunday that follows the lab."
    )
    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Lab make-up submission deadline",
                event_type="deadline",
                event_date=date(2025, 9, 7),
                end_time=time(23, 59),
                is_all_day=False,
                source_quote="submitted until 11:59pm on the Sunday that follows the lab",
                source_page=2,
                confidence="medium",
                year_was_explicit=True,
                extraction_model="gpt-5.6-terra",
            )
        ],
        schedule_anchors=[],
        recurring_rules=[],
    )
    pages = [
        {
            "page": 2,
            "ocr": False,
            "text": f"Make-Up Policy. {policy_source}",
        }
    ]

    completed = processing._materialize_missing_ambiguous_review_events(
        extraction,
        pages,
        extraction_model="gpt-5.6-luna",
    )
    normalized, _, _ = processing._normalize_ambiguous_recurring_content(completed, pages)

    assert [(event.title, event.event_date, event.source_quote) for event in normalized.events] == [
        ("Lab assignment make-up deadline", None, policy_source),
    ]


def test_process_job_collapses_lab_makeup_aliases_without_merging_unrelated_lab_deadline(
    app_client, monkeypatch
):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)
    policy_source = (
        "Missed labs can be submitted until 11:59pm on the Sunday that follows the lab."
    )
    unrelated_source = "Lab project report deadline is November 14 at 11:59pm."
    page_text = f"{unrelated_source}\n{policy_source}"

    with app.state.session_factory() as session:
        semester = Semester(
            user_id=USER_A,
            name="Fall 2025",
            start_date=date(2025, 8, 25),
            end_date=date(2025, 12, 20),
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
    file_path.write_bytes(make_pdf(page_text))

    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Lab assignment make-up deadline",
                event_type="deadline",
                event_date=None,
                end_time=time(23, 59),
                is_all_day=False,
                source_quote=policy_source,
                source_page=1,
                confidence="medium",
                year_was_explicit=True,
            ),
            CandidateEvent(
                title="Missed lab make-up deadline",
                event_type="deadline",
                event_date=None,
                end_time=time(23, 59),
                is_all_day=False,
                source_quote=policy_source,
                source_page=1,
                confidence="medium",
                year_was_explicit=True,
            ),
            CandidateEvent(
                title="Lab project report deadline",
                event_type="deadline",
                event_date=date(2025, 11, 14),
                end_time=time(23, 59),
                is_all_day=False,
                source_quote=unrelated_source,
                source_page=1,
                confidence="high",
                year_was_explicit=True,
            ),
        ],
    )

    monkeypatch.setattr(
        "app.processing.extract_syllabus",
        lambda pages, settings: extraction.model_copy(deep=True),
    )

    process_job(str(job_id), session_factory=app.state.session_factory)

    with app.state.session_factory() as session:
        persisted = session.get(ProcessingJob, job_id)
        assert persisted.status == JobStatus.NEEDS_REVIEW, persisted.error_message
        events = sorted(
            persisted.document.semester.events,
            key=lambda item: (item.title, item.event_date or date.min),
        )
        assert [event.title for event in events] == [
            "Lab assignment make-up deadline",
            "Lab project report deadline",
        ]
        assert events[0].event_date is None
        assert events[0].end_time == time(23, 59)
        assert events[0].source_quote == policy_source
        assert events[1].event_date == date(2025, 11, 14)
        assert events[1].source_quote == unrelated_source


def test_process_job_collapses_same_policy_terra_lab_alias_with_hallucinated_date(
    app_client, monkeypatch
):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)
    policy_source = (
        "Missed labs can be submitted until 11:59pm on the Sunday that follows the lab."
    )

    with app.state.session_factory() as session:
        semester = Semester(
            user_id=USER_A,
            name="Fall 2025",
            start_date=date(2025, 8, 25),
            end_date=date(2025, 12, 20),
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
            f"Final exam as scheduled by Registrar. Make-Up Policy. {policy_source}"
        )
    )

    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Final exam",
                event_type="exam",
                event_date=None,
                is_all_day=True,
                source_quote="Final exam as scheduled by Registrar",
                source_page=1,
                confidence="low",
                year_was_explicit=True,
                uncertainty_reason="The source wording is tentative.",
                extraction_model="gpt-5.6-luna",
            ),
            CandidateEvent(
                title="Lab assignment make-up deadline",
                event_type="deadline",
                event_date=None,
                end_time=time(23, 59),
                is_all_day=False,
                source_quote=policy_source,
                source_page=1,
                confidence="medium",
                year_was_explicit=True,
                extraction_model="gpt-5.6-luna",
            ),
            CandidateEvent(
                title="Lab make-up submission deadline",
                event_type="deadline",
                event_date=date(2025, 9, 7),
                end_time=time(23, 59),
                is_all_day=False,
                source_quote="submitted until 11:59pm on the Sunday that follows the lab",
                source_page=1,
                confidence="medium",
                year_was_explicit=True,
                extraction_model="gpt-5.6-terra",
            ),
        ],
    )

    monkeypatch.setattr(
        "app.processing._extract_with_model_fallback",
        lambda pages, settings, semester_start, semester_end, known_dates_by_title: (
            extraction.model_copy(deep=True),
            True,
            ["LOW_CONFIDENCE"],
            set(),
        ),
    )
    monkeypatch.setattr(
        "app.processing.extract_pdf_pages",
        lambda content, min_text_characters=80, settings=None, on_ocr_start=None: (
            [
                {
                    "page": 1,
                    "text": (
                        "Final exam as scheduled by Registrar. "
                        f"Make-Up Policy. {policy_source}"
                    ),
                    "ocr": False,
                }
            ],
            False,
        ),
    )
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
        lab_events = [
            event
            for event in persisted.document.semester.events
            if "lab" in event.title.casefold()
        ]
        assert len(lab_events) == 1
        event = lab_events[0]
        assert event.title == "Lab assignment make-up deadline"
        assert event.event_date is None
        assert event.source_quote == policy_source
        assert event.extraction_model == "gpt-5.6-luna"


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
            'Lab Exams (10%): Periodically, labs may start with a "lab exam". '
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
        assert ambiguous_titles == {
            "Exercise Sets",
            "Lab Exams",
            "Lab assignment make-up deadline",
            "Quick Checks",
        }

    assert calls == ["gpt-5.6-luna"]


def test_process_job_filters_non_actionable_course_structure_lab_entry(
    app_client, monkeypatch
):
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
            filename="course-structure.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/course-structure.pdf",
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
            "Course Structure: This course includes twice-weekly lecture sections and one "
            "mandatory weekly lab section. LB1 - LB8 See Albert See Albert. " * 4
        )
    )

    luna_output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Mandatory weekly lab",
                event_type="class",
                event_date=None,
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote=(
                    "Course Structure: This course includes twice-weekly lecture sections and "
                    "one mandatory weekly lab section. LB1 - LB8 See Albert See Albert"
                ),
                source_page=1,
                confidence="medium",
                year_was_explicit=True,
                uncertainty_reason=None,
                extraction_model="gpt-5.6-terra",
            )
        ],
        recurring_rules=[],
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
        assert persisted.status == JobStatus.NEEDS_REVIEW, persisted.error_message
        assert persisted.document.semester.events == []
        series_count = session.query(RecurringEventSeries).filter(
            RecurringEventSeries.document_id == persisted.document.id
        ).count()
        assert series_count == 0


def test_expand_recurring_rules_keeps_exact_class_rule_with_range_and_time():
    exact_class_rule = RecurringRule(
        title="Lecture",
        event_type="class",
        rule_kind="weekly_fixed",
        weekday="monday",
        start_time=time(10, 0),
        end_time=time(11, 15),
        is_all_day=False,
        boundary_start=date(2026, 9, 7),
        boundary_end=date(2026, 9, 21),
        exclusion_dates=[],
        source_quote="Lecture meets every Monday at 10:00 from Sep 7, 2026 through Sep 21, 2026",
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
        recurring_rules=[exact_class_rule],
    )
    pages = [
        {
            "page": 1,
            "ocr": False,
            "text": (
                "Course Structure: This course includes twice-weekly lecture sections and one "
                "mandatory weekly lab section. "
                "Lecture meets every Monday at 10:00 from Sep 7, 2026 through Sep 21, 2026."
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
    assert [(event.event_date, event.start_time, event.end_time) for event in derived_events] == [
        (date(2026, 9, 7), time(10, 0), time(11, 15)),
        (date(2026, 9, 14), time(10, 0), time(11, 15)),
        (date(2026, 9, 21), time(10, 0), time(11, 15)),
    ]


def test_expand_recurring_rules_skips_section_meeting_line_without_explicit_source_evidence():
    section_rule = RecurringRule(
        title="Weekly Lecture — Monday Sections",
        event_type="class",
        rule_kind="weekly_fixed",
        weekday="monday",
        start_time=time(11, 0),
        end_time=time(12, 20),
        is_all_day=False,
        boundary_start=date(2025, 9, 8),
        boundary_end=date(2025, 12, 8),
        exclusion_dates=[],
        source_quote="ALEC MW 11:00am - 12:20pm",
        source_page=1,
        confidence="high",
        anchor_title=None,
        offset_days=None,
        uncertainty_reason=None,
        extraction_model="gpt-5.6-luna",
    )

    series, derived_events = expand_recurring_rules(
        anchors=[],
        rules=[section_rule],
        semester_start=date(2025, 8, 24),
        semester_end=date(2025, 12, 18),
        explicit_events=[],
        extraction_model="gpt-5.6-luna",
        max_occurrences=200,
    )

    assert series == []
    assert derived_events == []


def test_expand_recurring_rules_skips_structural_lab_reference_without_explicit_source_evidence():
    lab_rule = RecurringRule(
        title="Weekly Labs",
        event_type="class",
        rule_kind="weekly_fixed",
        weekday="wednesday",
        start_time=None,
        end_time=None,
        is_all_day=True,
        boundary_start=date(2025, 9, 3),
        boundary_end=date(2025, 12, 10),
        exclusion_dates=[],
        source_quote="LB1 - LB8 See Albert",
        source_page=2,
        confidence="medium",
        anchor_title=None,
        offset_days=None,
        uncertainty_reason=None,
        extraction_model="gpt-5.6-luna",
    )

    series, derived_events = expand_recurring_rules(
        anchors=[],
        rules=[lab_rule],
        semester_start=date(2025, 8, 24),
        semester_end=date(2025, 12, 18),
        explicit_events=[],
        extraction_model="gpt-5.6-luna",
        max_occurrences=200,
    )

    assert series == []
    assert derived_events == []


def test_expand_recurring_rules_skips_section_meeting_line_with_weekly_language_but_no_range():
    section_rule = RecurringRule(
        title="Weekly Lecture — Monday Sections",
        event_type="class",
        rule_kind="weekly_fixed",
        weekday="monday",
        start_time=time(11, 0),
        end_time=time(12, 20),
        is_all_day=False,
        boundary_start=date(2025, 9, 8),
        boundary_end=date(2025, 12, 8),
        exclusion_dates=[],
        source_quote="ALEC MW 11:00am - 12:20pm every Monday",
        source_page=1,
        confidence="high",
        anchor_title=None,
        offset_days=None,
        uncertainty_reason=None,
        extraction_model="gpt-5.6-luna",
    )

    series, derived_events = expand_recurring_rules(
        anchors=[],
        rules=[section_rule],
        semester_start=date(2025, 8, 24),
        semester_end=date(2025, 12, 18),
        explicit_events=[],
        extraction_model="gpt-5.6-luna",
        max_occurrences=200,
    )

    assert series == []
    assert derived_events == []


def test_expand_recurring_rules_skips_section_meeting_line_with_range_but_no_weekly_language():
    section_rule = RecurringRule(
        title="Weekly Lecture — Monday Sections",
        event_type="class",
        rule_kind="weekly_fixed",
        weekday="monday",
        start_time=time(11, 0),
        end_time=time(12, 20),
        is_all_day=False,
        boundary_start=date(2025, 9, 8),
        boundary_end=date(2025, 12, 8),
        exclusion_dates=[],
        source_quote="ALEC MW 11:00am - 12:20pm from Sep 8, 2025 through Dec 8, 2025",
        source_page=1,
        confidence="high",
        anchor_title=None,
        offset_days=None,
        uncertainty_reason=None,
        extraction_model="gpt-5.6-luna",
    )

    series, derived_events = expand_recurring_rules(
        anchors=[],
        rules=[section_rule],
        semester_start=date(2025, 8, 24),
        semester_end=date(2025, 12, 18),
        explicit_events=[],
        extraction_model="gpt-5.6-luna",
        max_occurrences=200,
    )

    assert series == []
    assert derived_events == []


def test_expand_recurring_rules_matches_generic_anchor_titles_across_sections():
    monday_section = ScheduleAnchor(
        title="ALEC lecture",
        anchor_type="lecture",
        weekday="monday",
        start_time=time(11, 0),
        end_time=time(12, 20),
        boundary_start=date(2025, 9, 3),
        boundary_end=date(2025, 9, 10),
        exclusion_dates=[],
        source_quote="ALEC MW 11:00am - 12:20pm",
        source_page=1,
    )
    wednesday_section = ScheduleAnchor(
        title="ALEC lecture",
        anchor_type="lecture",
        weekday="wednesday",
        start_time=time(11, 0),
        end_time=time(12, 20),
        boundary_start=date(2025, 9, 3),
        boundary_end=date(2025, 9, 10),
        exclusion_dates=[],
        source_quote="ALEC MW 11:00am - 12:20pm",
        source_page=1,
    )
    duplicate_monday_section = ScheduleAnchor(
        title="BLEC lecture",
        anchor_type="lecture",
        weekday="monday",
        start_time=time(11, 0),
        end_time=time(12, 20),
        boundary_start=date(2025, 9, 3),
        boundary_end=date(2025, 9, 10),
        exclusion_dates=[],
        source_quote="BLEC MW 11:00am - 12:20pm",
        source_page=1,
    )
    quick_checks = RecurringRule(
        title="Quick Checks",
        event_type="quiz",
        rule_kind="relative_to_anchor",
        weekday=None,
        start_time=time(8, 0),
        end_time=None,
        is_all_day=False,
        boundary_start=date(2025, 9, 3),
        boundary_end=date(2025, 9, 10),
        exclusion_dates=[],
        source_quote="Quick Checks due at 8AM on lecture day",
        source_page=2,
        confidence="high",
        anchor_title="Lecture",
        offset_days=0,
        uncertainty_reason=None,
    )

    series, derived_events = expand_recurring_rules(
        anchors=[monday_section, wednesday_section, duplicate_monday_section],
        rules=[quick_checks],
        semester_start=date(2025, 8, 24),
        semester_end=date(2025, 12, 18),
        explicit_events=[],
        extraction_model="gpt-5.6-luna",
        max_occurrences=200,
    )

    assert len(series) == 1
    assert [event.event_date for event in derived_events] == [
        date(2025, 9, 3),
        date(2025, 9, 8),
        date(2025, 9, 10),
    ]
    assert len(series[0].anchor_sources) == 3


def test_preview_retryable_codes_flags_exact_relative_rule_without_matching_anchor():
    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Intro to CS",
        instructor=None,
        events=[],
        schedule_anchors=[],
        recurring_rules=[
            RecurringRule(
                title="Lecture reflection",
                event_type="assignment",
                rule_kind="relative_to_anchor",
                weekday=None,
                start_time=None,
                end_time=None,
                is_all_day=True,
                boundary_start=date(2025, 9, 3),
                boundary_end=date(2025, 12, 10),
                exclusion_dates=[],
                source_quote="Reflection due two days after lecture",
                source_page=1,
                confidence="high",
                anchor_title="Lecture",
                offset_days=2,
                uncertainty_reason=None,
                expansion_mode="exact",
            )
        ],
    )

    retryable_codes, _, flagged_rule_indexes, flagged_reasons = processing._preview_retryable_codes(
        extraction,
        pages=[
            {
                "page": 1,
                "ocr": False,
                "text": "Reflection due two days after lecture",
            }
        ],
        semester_start=date(2025, 8, 24),
        semester_end=date(2025, 12, 18),
        known_dates_by_title={},
    )

    assert retryable_codes == ["ANCHOR_NOT_FOUND"]
    assert flagged_rule_indexes == {0}
    assert "ANCHOR_NOT_FOUND" in flagged_reasons["rules"][0]


def test_process_job_review_only_relative_rule_without_anchor_skips_terra(app_client, monkeypatch):
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
            filename="review-only-no-anchor.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/review-only-no-anchor.pdf",
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
            "Nearly every topic includes a quick check. " * 4
        )
    )

    luna_output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Intro to CS",
        instructor=None,
        events=[],
        schedule_anchors=[],
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
        assert persisted.fallback_reason_codes == []
        assert len(persisted.document.semester.events) == 1

    assert calls == ["gpt-5.6-luna"]


def test_process_job_materializes_unresolved_exact_relative_rule_without_anchor(
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
            filename="missing-anchor.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/missing-anchor.pdf",
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
    file_path.write_bytes(make_pdf("Reflection due two days after lecture. " * 4))

    luna_output = SyllabusExtraction(
        course_code="CS 101",
        course_name="Intro to CS",
        instructor=None,
        events=[],
        schedule_anchors=[],
        recurring_rules=[
            RecurringRule(
                title="Lecture reflection",
                event_type="assignment",
                rule_kind="relative_to_anchor",
                weekday=None,
                start_time=None,
                end_time=None,
                is_all_day=True,
                boundary_start=date(2025, 8, 25),
                boundary_end=date(2025, 12, 19),
                exclusion_dates=[],
                source_quote="Reflection due two days after lecture",
                source_page=1,
                confidence="high",
                anchor_title="Lecture",
                offset_days=2,
                uncertainty_reason=None,
                expansion_mode="exact",
            )
        ],
    )
    terra_output = processing.SyllabusRepair(
        course_code="CS 101",
        course_name="Intro to CS",
        instructor=None,
        events=[],
        schedule_anchors=[],
        recurring_rules=[],
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
        assert persisted.fallback_reason_codes == ["ANCHOR_NOT_FOUND", "TERRA_RETRY_FAILED"]
        events = persisted.document.semester.events
        assert len(events) == 1
        event = events[0]
        assert event.title == "Lecture reflection"
        assert event.event_date is None
        assert event.recurring_series_id is None
        assert "TERRA_RETRY_FAILED" in event.warning_codes
        assert event.fallback_reason_codes == ["TERRA_RETRY_FAILED"]

    assert calls == ["gpt-5.6-luna", "gpt-5.6-terra"]


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


def test_filter_non_actionable_course_structure_items_drops_lab_assignment_description():
    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Lab Assignments",
                event_type="assignment",
                event_date=None,
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Weekly lab assignments are conducted in a supervised setting.",
                source_page=2,
                confidence="medium",
                year_was_explicit=True,
            ),
            CandidateEvent(
                title="Homework",
                event_type="assignment",
                event_date=None,
                start_time=None,
                end_time=time(23, 59),
                is_all_day=False,
                source_quote="Homework is due every Friday from Sep 4, 2026 through Sep 18, 2026.",
                source_page=2,
                confidence="medium",
                year_was_explicit=True,
            ),
        ],
        schedule_anchors=[],
        recurring_rules=[],
    )

    filtered = processing._filter_non_actionable_course_structure_items(extraction)

    assert [event.title for event in filtered.events] == ["Homework"]


def test_filter_non_actionable_course_structure_items_drops_section_meeting_events_and_rules():
    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Weekly Lecture — DLEC",
                event_type="class",
                event_date=None,
                start_time=time(17, 0),
                end_time=time(18, 20),
                is_all_day=False,
                source_quote="DLEC MW 5:00pm - 6:20pm",
                source_page=1,
                confidence="medium",
                year_was_explicit=True,
            ),
            CandidateEvent(
                title="Lecture",
                event_type="class",
                event_date=None,
                start_time=time(10, 0),
                end_time=time(11, 15),
                is_all_day=False,
                source_quote=(
                    "Lecture meets every Monday at 10:00 from Sep 7, 2026 through Sep 21, 2026"
                ),
                source_page=1,
                confidence="high",
                year_was_explicit=True,
            ),
        ],
        schedule_anchors=[],
        recurring_rules=[
            RecurringRule(
                title="Weekly Lecture — Wednesday Sections",
                event_type="class",
                rule_kind="weekly_fixed",
                weekday="wednesday",
                start_time=time(11, 0),
                end_time=time(12, 20),
                is_all_day=False,
                boundary_start=date(2025, 9, 3),
                boundary_end=date(2025, 12, 10),
                exclusion_dates=[],
                source_quote="BLEC MW 11:00am - 12:20pm",
                source_page=1,
                confidence="medium",
                anchor_title=None,
                offset_days=None,
                uncertainty_reason=None,
            ),
            RecurringRule(
                title="Lecture",
                event_type="class",
                rule_kind="weekly_fixed",
                weekday="monday",
                start_time=time(10, 0),
                end_time=time(11, 15),
                is_all_day=False,
                boundary_start=date(2026, 9, 7),
                boundary_end=date(2026, 9, 21),
                exclusion_dates=[],
                source_quote=(
                    "Lecture meets every Monday at 10:00 from Sep 7, 2026 through Sep 21, 2026"
                ),
                source_page=1,
                confidence="high",
                anchor_title=None,
                offset_days=None,
                uncertainty_reason=None,
            ),
        ],
    )

    filtered = processing._filter_non_actionable_course_structure_items(extraction)

    assert [event.title for event in filtered.events] == ["Lecture"]
    assert [rule.title for rule in filtered.recurring_rules] == ["Lecture"]


def test_filter_non_actionable_course_structure_items_drops_undated_section_description_event():
    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Weekly lab section",
                event_type="class",
                event_date=None,
                start_time=None,
                end_time=None,
                is_all_day=False,
                source_quote="one mandatory weekly lab section",
                source_page=2,
                confidence="medium",
                year_was_explicit=True,
            ),
            CandidateEvent(
                title="Exam 1",
                event_type="exam",
                event_date=date(2025, 10, 21),
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Exam Dates: 21 Oct 2025",
                source_page=2,
                confidence="high",
                year_was_explicit=True,
            ),
        ],
        schedule_anchors=[],
        recurring_rules=[],
    )

    filtered = processing._filter_non_actionable_course_structure_items(extraction)

    assert [event.title for event in filtered.events] == ["Exam 1"]


def test_filter_non_actionable_course_structure_items_drops_section_rule_without_range():
    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[],
        schedule_anchors=[],
        recurring_rules=[
            RecurringRule(
                title="Weekly lab section",
                event_type="class",
                rule_kind="weekly_fixed",
                weekday="wednesday",
                start_time=None,
                end_time=None,
                is_all_day=False,
                boundary_start=None,
                boundary_end=None,
                exclusion_dates=[],
                source_quote="one mandatory weekly lab section",
                source_page=2,
                confidence="medium",
                anchor_title=None,
                offset_days=None,
                uncertainty_reason="The syllabus does not identify every weekly lab date.",
            ),
            RecurringRule(
                title="Lecture",
                event_type="class",
                rule_kind="weekly_fixed",
                weekday="monday",
                start_time=time(10, 0),
                end_time=time(11, 15),
                is_all_day=False,
                boundary_start=date(2026, 9, 7),
                boundary_end=date(2026, 9, 21),
                exclusion_dates=[],
                source_quote=(
                    "Lecture meets every Monday at 10:00 from Sep 7, 2026 through Sep 21, 2026"
                ),
                source_page=1,
                confidence="high",
                anchor_title=None,
                offset_days=None,
                uncertainty_reason=None,
            ),
        ],
    )

    filtered = processing._filter_non_actionable_course_structure_items(extraction)

    assert [rule.title for rule in filtered.recurring_rules] == ["Lecture"]


def test_normalize_ambiguous_recurring_content_collapses_lab_alias_from_review_only_rule():
    policy_quote = "until 11:59pm on the Sunday that follows the lab"
    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Lab assignment make-up deadline",
                event_type="deadline",
                event_date=None,
                start_time=None,
                end_time=time(23, 59),
                is_all_day=False,
                source_quote=policy_quote,
                source_page=2,
                confidence="medium",
                year_was_explicit=True,
                extraction_model="gpt-5.6-luna",
            )
        ],
        schedule_anchors=[],
        recurring_rules=[
            RecurringRule(
                title="Lab Make-Up Submission Deadline",
                event_type="deadline",
                rule_kind="relative_to_anchor",
                weekday=None,
                start_time=None,
                end_time=time(23, 59),
                is_all_day=False,
                boundary_start=None,
                boundary_end=None,
                exclusion_dates=[],
                source_quote=policy_quote,
                source_page=2,
                confidence="medium",
                anchor_title="Lab",
                offset_days=0,
                uncertainty_reason="The syllabus does not identify every lab date.",
                extraction_model="gpt-5.6-terra",
                expansion_mode="review_only",
            )
        ],
    )
    pages = [{"page": 2, "ocr": False, "text": policy_quote}]

    normalized, _, _ = processing._normalize_ambiguous_recurring_content(extraction, pages)

    assert [
        (event.title, event.source_quote, event.source_page) for event in normalized.events
    ] == [("Lab assignment make-up deadline", policy_quote, 2)]


def test_normalize_ambiguous_recurring_content_remaps_indexes_after_lab_alias_collapse():
    policy_quote = "until 11:59pm on the Sunday that follows the lab"
    quick_checks_quote = "Quick Checks - 8AM the morning of the lecture"
    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Lab assignment make-up deadline",
                event_type="deadline",
                event_date=None,
                start_time=None,
                end_time=time(23, 59),
                is_all_day=False,
                source_quote=policy_quote,
                source_page=2,
                confidence="medium",
                year_was_explicit=True,
                extraction_model="gpt-5.6-luna",
            ),
            CandidateEvent(
                title="Quick Checks",
                event_type="quiz",
                event_date=None,
                start_time=time(8, 0),
                end_time=None,
                is_all_day=False,
                source_quote=quick_checks_quote,
                source_page=2,
                confidence="medium",
                year_was_explicit=True,
                extraction_model="gpt-5.6-luna",
            ),
        ],
        schedule_anchors=[],
        recurring_rules=[
            RecurringRule(
                title="Lab Make-Up Submission Deadline",
                event_type="deadline",
                rule_kind="relative_to_anchor",
                weekday=None,
                start_time=None,
                end_time=time(23, 59),
                is_all_day=False,
                boundary_start=None,
                boundary_end=None,
                exclusion_dates=[],
                source_quote=policy_quote,
                source_page=2,
                confidence="medium",
                anchor_title="Lab",
                offset_days=0,
                uncertainty_reason="The syllabus does not identify every lab date.",
                extraction_model="gpt-5.6-terra",
                expansion_mode="review_only",
            )
        ],
    )
    pages = [
        {
            "page": 2,
            "ocr": False,
            "text": (
                f"{policy_quote}. Nearly every topic includes a quick check. "
                f"{quick_checks_quote}."
            ),
        }
    ]

    normalized, ambiguous_indexes, _ = processing._normalize_ambiguous_recurring_content(
        extraction,
        pages,
    )

    assert [event.title for event in normalized.events] == [
        "Lab assignment make-up deadline",
        "Quick Checks",
    ]
    assert ambiguous_indexes == {0, 1}


def test_collapse_lab_makeup_alias_events_canonicalizes_alias_first_time_fields():
    events = [
        CandidateEvent(
            title="Lab Make-Up Submission Deadline",
            event_type="deadline",
            event_date=None,
            start_time=time(23, 59),
            end_time=None,
            is_all_day=False,
            source_quote="until 11:59pm on the Sunday that follows the lab",
            source_page=2,
            confidence="medium",
            year_was_explicit=True,
        ),
        CandidateEvent(
            title="Lab assignment make-up deadline",
            event_type="deadline",
            event_date=None,
            start_time=None,
            end_time=None,
            is_all_day=True,
            source_quote="until 11:59pm on the Sunday that follows the lab",
            source_page=2,
            confidence="medium",
            year_was_explicit=True,
        ),
    ]

    collapsed_events, collapsed_index_map = processing._collapse_lab_makeup_alias_events(events)

    assert collapsed_index_map == {0: 0, 1: 0}
    assert len(collapsed_events) == 1
    event = collapsed_events[0]
    assert event.title == "Lab assignment make-up deadline"
    assert event.start_time is None
    assert event.end_time == time(23, 59)
    assert event.is_all_day is False


def test_collapse_lab_makeup_alias_events_prefers_2359_from_longer_alias_quote():
    events = [
        CandidateEvent(
            title="Lab Make-Up Submission Deadline",
            event_type="deadline",
            event_date=None,
            start_time=None,
            end_time=time(22, 0),
            is_all_day=False,
            source_quote="on the Sunday that follows the lab",
            source_page=2,
            confidence="medium",
            year_was_explicit=True,
            extraction_model="gpt-5.6-luna",
        ),
        CandidateEvent(
            title="Lab assignment make-up deadline",
            event_type="deadline",
            event_date=None,
            start_time=None,
            end_time=time(23, 59),
            is_all_day=False,
            source_quote=(
                "Lab assignment make-up deadline until 11:59pm on the Sunday "
                "that follows the lab"
            ),
            source_page=2,
            confidence="medium",
            year_was_explicit=True,
            extraction_model="gpt-5.6-terra",
        ),
    ]

    collapsed_events, collapsed_index_map = processing._collapse_lab_makeup_alias_events(events)

    assert collapsed_index_map == {0: 0, 1: 0}
    assert len(collapsed_events) == 1
    event = collapsed_events[0]
    assert event.title == "Lab assignment make-up deadline"
    assert event.start_time is None
    assert event.end_time == time(23, 59)
    assert event.source_quote == (
        "Lab assignment make-up deadline until 11:59pm on the Sunday "
        "that follows the lab"
    )
    assert event.extraction_model == "gpt-5.6-terra"


def test_collapse_lab_makeup_alias_events_collapses_weekly_alias_title():
    policy_quote = "until 11:59pm on the Sunday that follows the lab"
    events = [
        CandidateEvent(
            title="Weekly lab assignment make-up deadline",
            event_type="deadline",
            event_date=None,
            start_time=None,
            end_time=None,
            is_all_day=True,
            source_quote=policy_quote,
            source_page=2,
            confidence="medium",
            year_was_explicit=True,
        ),
        CandidateEvent(
            title="Lab assignment make-up deadline",
            event_type="deadline",
            event_date=None,
            start_time=None,
            end_time=time(23, 59),
            is_all_day=False,
            source_quote=policy_quote,
            source_page=2,
            confidence="medium",
            year_was_explicit=True,
        ),
    ]

    collapsed_events, collapsed_index_map = processing._collapse_lab_makeup_alias_events(events)

    assert collapsed_index_map == {0: 0, 1: 0}
    assert len(collapsed_events) == 1
    event = collapsed_events[0]
    assert event.title == "Lab assignment make-up deadline"
    assert event.end_time == time(23, 59)


def test_collapse_lab_exam_alias_events_prefers_quote_donor_model_provenance():
    events = [
        CandidateEvent(
            title="Periodic lab exams",
            event_type="exam",
            event_date=None,
            start_time=None,
            end_time=None,
            is_all_day=True,
            source_quote='Periodically, labs may start with a "lab exam".',
            source_page=3,
            confidence="medium",
            year_was_explicit=True,
            extraction_model="gpt-5.6-luna",
        ),
        CandidateEvent(
            title="Lab Exams",
            event_type="exam",
            event_date=None,
            start_time=None,
            end_time=None,
            is_all_day=True,
            source_quote='Lab Exams (10%): Periodically, labs may start with a "lab exam".',
            source_page=3,
            confidence="medium",
            year_was_explicit=True,
            extraction_model="gpt-5.6-terra",
        ),
    ]

    collapsed_events, collapsed_index_map = processing._collapse_lab_exam_alias_events(events)

    assert collapsed_index_map == {0: 0, 1: 0}
    assert len(collapsed_events) == 1
    event = collapsed_events[0]
    assert event.title == "Lab Exams"
    assert event.source_quote == 'Lab Exams (10%): Periodically, labs may start with a "lab exam".'
    assert event.extraction_model == "gpt-5.6-terra"


def test_process_job_attempt6_shapes_drop_section_items_and_keep_shifted_ambiguous_warning(
    app_client, monkeypatch
):
    _, app = app_client
    storage_path = Path(app.state.settings.local_storage_path)

    with app.state.session_factory() as session:
        semester = Semester(
            user_id=USER_A,
            name="Fall 2025",
            start_date=date(2025, 8, 25),
            end_date=date(2025, 12, 20),
            timezone="America/New_York",
        )
        session.add(semester)
        session.flush()
        document = SyllabusDocument(
            user_id=USER_A,
            semester_id=semester.id,
            filename="attempt6.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key=f"{USER_A}/{semester.id}/attempt6.pdf",
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
            "DLEC MW 5:00pm - 6:20pm. BLEC MW 11:00am - 12:20pm. "
            "LB1 - LB8 See Albert. "
            "Weekly lab assignments are conducted in a supervised setting. "
            "Missed labs can be submitted until 11:59pm on the Sunday that follows the lab. "
            "Nearly every topic includes a quick check. "
            "Quick Checks - 8AM the morning of the lecture. "
            "Final exam as scheduled by Registrar."
        )
    )

    extraction = SyllabusExtraction(
        course_code="CS 101",
        course_name="Foundations of Computing",
        instructor=None,
        events=[
            CandidateEvent(
                title="Weekly Lecture — DLEC",
                event_type="class",
                event_date=None,
                start_time=time(17, 0),
                end_time=time(18, 20),
                is_all_day=False,
                source_quote="DLEC MW 5:00pm - 6:20pm",
                source_page=1,
                confidence="medium",
                year_was_explicit=True,
            ),
            CandidateEvent(
                title="Lab Assignments",
                event_type="assignment",
                event_date=None,
                start_time=None,
                end_time=None,
                is_all_day=True,
                source_quote="Weekly lab assignments are conducted in a supervised setting.",
                source_page=1,
                confidence="medium",
                year_was_explicit=True,
            ),
            CandidateEvent(
                title="Lab assignment make-up deadline",
                event_type="deadline",
                event_date=None,
                start_time=None,
                end_time=time(23, 59),
                is_all_day=False,
                source_quote="until 11:59pm on the Sunday that follows the lab",
                source_page=1,
                confidence="medium",
                year_was_explicit=True,
            ),
            CandidateEvent(
                title="Quick Checks",
                event_type="quiz",
                event_date=None,
                start_time=time(8, 0),
                end_time=None,
                is_all_day=False,
                source_quote="Quick Checks - 8AM the morning of the lecture",
                source_page=1,
                confidence="medium",
                year_was_explicit=True,
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
            ),
        ],
        schedule_anchors=[],
        recurring_rules=[
            RecurringRule(
                title="Weekly Lecture — Wednesday Sections",
                event_type="class",
                rule_kind="weekly_fixed",
                weekday="wednesday",
                start_time=time(11, 0),
                end_time=time(12, 20),
                is_all_day=False,
                boundary_start=date(2025, 9, 3),
                boundary_end=date(2025, 12, 10),
                exclusion_dates=[],
                source_quote="BLEC MW 11:00am - 12:20pm",
                source_page=1,
                confidence="medium",
                anchor_title=None,
                offset_days=None,
                uncertainty_reason=None,
            ),
            RecurringRule(
                title="Weekly Labs",
                event_type="class",
                rule_kind="weekly_fixed",
                weekday="wednesday",
                start_time=None,
                end_time=None,
                is_all_day=True,
                boundary_start=date(2025, 9, 3),
                boundary_end=date(2025, 12, 10),
                exclusion_dates=[],
                source_quote="LB1 - LB8 See Albert",
                source_page=1,
                confidence="medium",
                anchor_title=None,
                offset_days=None,
                uncertainty_reason=None,
            ),
            RecurringRule(
                title="Lab Make-Up Submission Deadline",
                event_type="deadline",
                rule_kind="relative_to_anchor",
                weekday=None,
                start_time=None,
                end_time=time(23, 59),
                is_all_day=False,
                boundary_start=None,
                boundary_end=None,
                exclusion_dates=[],
                source_quote="until 11:59pm on the Sunday that follows the lab",
                source_page=1,
                confidence="medium",
                anchor_title="Lab",
                offset_days=0,
                uncertainty_reason="The syllabus does not identify every lab date.",
                expansion_mode="review_only",
            ),
        ],
    )

    monkeypatch.setattr(
        "app.processing.extract_syllabus",
        lambda pages, settings: extraction.model_copy(deep=True),
    )

    process_job(str(job_id), session_factory=app.state.session_factory)

    with app.state.session_factory() as session:
        persisted = session.get(ProcessingJob, job_id)
        assert persisted.status == JobStatus.NEEDS_REVIEW, persisted.error_message
        events = sorted(
            persisted.document.semester.events,
            key=lambda item: item.title,
        )
        assert [event.title for event in events] == [
            "Final exam",
            "Lab assignment make-up deadline",
            "Quick Checks",
        ]
        quick_checks = next(event for event in events if event.title == "Quick Checks")
        assert "AMBIGUOUS_RECURRENCE" in quick_checks.warning_codes
        assert all("section" not in event.title.casefold() for event in events)
        assert all("weekly lecture" not in event.title.casefold() for event in events)
        assert all("weekly labs" not in event.title.casefold() for event in events)
        series_count = session.query(RecurringEventSeries).filter(
            RecurringEventSeries.document_id == persisted.document.id
        ).count()
        assert series_count == 0


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
