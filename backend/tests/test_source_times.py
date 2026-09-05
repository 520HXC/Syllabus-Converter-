from datetime import date, time

import pytest

from app.models import ConfidenceLevel
from app.processing import (
    CandidateEvent,
    SyllabusExtraction,
    _normalize_explicit_source_event_dates,
    _preview_retryable_codes,
    validate_candidate,
)

START, END = date(2026, 1, 26), date(2026, 5, 26)


def event(quote, *, title="Final Exam", kind="exam", start="02:00", end="04:00"):
    return CandidateEvent(
        title=title,
        event_type=kind,
        event_date="2026-05-17",
        start_time=start,
        end_time=end,
        is_all_day=False,
        source_quote=quote,
        source_page=1,
        confidence=ConfidenceLevel.HIGH,
        year_was_explicit=True,
    )


def normalize(candidate, pages):
    extraction = SyllabusExtraction(course_name="Regression", events=[candidate])
    return _normalize_explicit_source_event_dates(extraction, START, END, pages).events[0]


def test_brooklyn_pm_errors_are_not_accepted_by_validation():
    quote = "Final Exam May 17, 2026 02:00 PM - 04:00 PM."
    candidate = event(quote)
    pages = [{"page": 1, "text": quote}]
    codes, reason = validate_candidate(candidate, pages, START, END)
    assert "TIME_CONFLICT" in codes
    assert "14:00" in reason
    extraction = SyllabusExtraction(course_name="Regression", events=[candidate])
    assert "TIME_CONFLICT" in _preview_retryable_codes(extraction, pages, START, END, {})[0]


def test_brooklyn_exam_pm_is_corrected_with_source_provenance():
    quote = "Midterm Exam: 02:15 PM – 03:30 PM, at the Ingersoll Hall Extension (IA), Room 130"
    candidate = event(quote, title="Midterm Exam", start="02:15", end="03:30")
    corrected = normalize(candidate, [{"page": 1, "text": quote}])
    assert (corrected.start_time, corrected.end_time) == (time(14, 15), time(15, 30))
    assert "02:15 PM" in corrected.derivation_summary
    assert "page 1" in corrected.derivation_summary


def test_brooklyn_global_assignment_deadline_is_scoped_and_crosses_pages():
    policy = "All assignments, excluding the exams, are due at 11:59 PM EST, on Brightspace."
    quote = "Quiz and Homework 3 on Chapter 3 due"
    candidate = event(quote, title="Homework 3", kind="assignment", start=None, end="11:59")
    pages = [{"page": 1, "text": quote}, {"page": 2, "text": policy}]
    corrected = normalize(candidate, pages)
    assert corrected.end_time == time(23, 59)
    assert "page 2" in corrected.derivation_summary
    assert "excluding the exams" in corrected.derivation_summary
    exam = event("Final Exam May 17", start=None, end="11:59")
    assert normalize(exam, [{"page": 1, "text": exam.source_quote}, pages[1]]).end_time == time(
        11, 59
    )


@pytest.mark.parametrize(
    ("source", "start", "end", "expected_start", "expected_end"),
    [
        ("Final Exam: 2–4 PM", "02:00", "04:00", time(14), time(16)),
        ("Final Exam: 12 AM - 2 AM", "12:00", "02:00", time(0), time(2)),
        ("Final Exam: 12 PM - 2 PM", "00:00", "02:00", time(12), time(14)),
        ("Final Exam: 11 AM - 1 PM", "11:00", "01:00", time(11), time(13)),
        ("Final Exam: 14:00 - 16:00", "14:00", "16:00", time(14), time(16)),
        ("Final Exam: 2 p.m. to 4 p.m.", "02:00", "04:00", time(14), time(16)),
    ],
)
def test_clock_formats_preserve_meridiem(source, start, end, expected_start, expected_end):
    candidate = event(source, start=start, end=end)
    pages = [{"page": 1, "text": source}]
    corrected = normalize(candidate, pages)
    assert (corrected.start_time, corrected.end_time) == (expected_start, expected_end)
    assert "TIME_CONFLICT" not in validate_candidate(corrected, pages, START, END)[0]


def test_office_hours_are_not_used_for_an_exam_on_the_same_page():
    source = "Final Exam May 17. Office hours: 2 PM - 4 PM."
    candidate = event("Final Exam May 17", start="02:00", end="04:00")
    corrected = normalize(candidate, [{"page": 1, "text": source}])
    assert corrected == candidate


def test_broad_quote_selects_only_this_assessments_times():
    source = "Midterm Exam: 1 PM - 2 PM. Final Exam: 2 PM - 4 PM. Office hours: 6 PM - 7 PM."
    candidate = event(source, start="02:00", end="04:00")
    corrected = normalize(candidate, [{"page": 1, "text": source}])
    assert (corrected.start_time, corrected.end_time) == (time(14), time(16))


def test_conflicting_alternative_times_are_not_guessed():
    source = "Final Exam: 2 PM - 4 PM or 6 PM - 8 PM depending on section."
    candidate = event(source)
    pages = [{"page": 1, "text": source}]
    assert normalize(candidate, pages) == candidate
    assert "TIME_CONFLICT" in validate_candidate(candidate, pages, START, END)[0]


def test_non_meridiem_difference_goes_to_review_without_overwrite():
    source = "Final Exam: 2 PM - 4 PM."
    candidate = event(source, start="03:00", end="05:00")
    pages = [{"page": 1, "text": source}]
    assert normalize(candidate, pages) == candidate
    assert "TIME_CONFLICT" in validate_candidate(candidate, pages, START, END)[0]


def test_model_fabricated_quote_cannot_change_times():
    candidate = event("Final Exam: 2 PM - 4 PM.")
    corrected = normalize(
        candidate, [{"page": 1, "text": "Final Exam May 17. Office hours: 2 PM - 4 PM."}]
    )
    assert corrected == candidate


def test_specific_due_time_overrides_general_deadline():
    source = "Homework 3 is due at 6 PM. All assignments are due at 11:59 PM."
    candidate = event(
        "Homework 3 is due at 6 PM.", title="Homework 3", kind="assignment", start=None, end="06:00"
    )
    corrected = normalize(candidate, [{"page": 1, "text": source}])
    assert corrected.end_time == time(18)


def test_brooklyn_combined_quiz_homework_row_inherits_applicable_policy():
    quote = "Quiz and Homework 3 on Chapter 3 due"
    candidate = event(quote, title="Quiz 3", kind="quiz", start=None, end="11:59")
    pages = [
        {"page": 1, "text": quote},
        {"page": 2, "text": "All assignments, excluding the exams, are due at 11:59 PM EST."},
    ]
    assert normalize(candidate, pages).end_time == time(23, 59)


def test_unmarked_12_hour_clock_does_not_override_an_afternoon_value():
    quote = "Final Exam: 2:00 - 4:00."
    candidate = event(quote, start="14:00", end="16:00")
    assert normalize(candidate, [{"page": 1, "text": quote}]) == candidate


def test_conflicting_universal_deadlines_need_review():
    quote = "Homework 3 due May 17."
    source = quote + " All assignments are due at 11:59 PM. All assignments are due at 6 PM."
    candidate = event(quote, title="Homework 3", kind="assignment", start=None, end="11:59")
    pages = [{"page": 1, "text": source}]
    assert normalize(candidate, pages) == candidate
    assert "TIME_CONFLICT" in validate_candidate(candidate, pages, START, END)[0]


def test_shared_pm_crossing_noon_is_ambiguous_and_not_forced_to_night():
    quote = "Final Exam: 11-1 PM."
    candidate = event(quote, start="11:00", end="13:00")
    pages = [{"page": 1, "text": quote}]
    assert normalize(candidate, pages) == candidate
    assert "TIME_CONFLICT" in validate_candidate(candidate, pages, START, END)[0]


def test_policy_with_unhandled_exception_is_not_applied_blindly():
    quote = "Homework 3 due May 17."
    policy = (
        "All assignments are due at 11:59 PM except Homework 3, whose deadline is announced later."
    )
    candidate = event(quote, title="Homework 3", kind="assignment", start=None, end="11:59")
    pages = [{"page": 1, "text": quote + " " + policy}]
    assert normalize(candidate, pages) == candidate


def test_exam_does_not_borrow_time_from_next_sentence_about_lectures():
    source = "Final Exam date will be announced. Lectures meet 2 PM - 4 PM."
    candidate = event(source)
    pages = [{"page": 1, "text": source}]
    assert normalize(candidate, pages) == candidate
    assert "TIME_CONFLICT" in validate_candidate(candidate, pages, START, END)[0]


def test_exam_does_not_borrow_time_across_a_semicolon():
    source = "Final Exam date will be announced; lectures meet 2 PM - 4 PM."
    candidate = event(source)
    pages = [{"page": 1, "text": source}]
    assert normalize(candidate, pages) == candidate


def homework_rule():
    from app.processing import RecurringRule

    return RecurringRule(
        title="Homework",
        event_type="assignment",
        rule_kind="weekly_fixed",
        weekday="wednesday",
        start_time=None,
        end_time="11:59",
        is_all_day=False,
        source_quote="Homework is due every Wednesday at 11:59 PM.",
        source_page=1,
        confidence=ConfidenceLevel.HIGH,
    )


def test_recurring_homework_pm_is_validated_before_expansion():
    from app.processing import _validate_rule

    rule = homework_rule()
    pages = [{"page": 1, "text": rule.source_quote}]
    assert "TIME_CONFLICT" in _validate_rule(rule, pages, [])[0]
    extraction = SyllabusExtraction(course_name="Regression", recurring_rules=[rule])
    codes, _, indexes, _ = _preview_retryable_codes(extraction, pages, START, END, {})
    assert "TIME_CONFLICT" in codes
    assert indexes == {0}


def test_recurring_homework_pm_is_normalized_in_all_expanded_occurrences():
    from app.processing import expand_recurring_rules

    rule = homework_rule()
    pages = [{"page": 1, "text": rule.source_quote}]
    extraction = SyllabusExtraction(course_name="Regression", recurring_rules=[rule])
    corrected = _normalize_explicit_source_event_dates(extraction, START, END, pages)
    assert corrected.recurring_rules[0].end_time == time(23, 59)
    series, occurrences = expand_recurring_rules(
        anchors=[],
        rules=corrected.recurring_rules,
        semester_start=START,
        semester_end=END,
        explicit_events=[],
        extraction_model=None,
    )
    assert occurrences and all(item.end_time == time(23, 59) for item in occurrences)
    assert "11:59 PM" in series[0].rule_payload["derivation_summary"]


def test_relative_rule_surfaces_its_anchor_time_conflict():
    from app.processing import RecurringRule, ScheduleAnchor, _validate_rule

    anchor = ScheduleAnchor(
        title="Lecture",
        anchor_type="lecture",
        weekday="monday",
        start_time="02:00",
        end_time="04:00",
        source_quote="Lecture meets 2 PM - 4 PM.",
        source_page=1,
    )
    rule = RecurringRule(
        title="Homework",
        event_type="assignment",
        rule_kind="relative_to_anchor",
        anchor_title="Lecture",
        offset_days=1,
        source_quote="Homework is due one day after Lecture.",
        source_page=1,
        confidence=ConfidenceLevel.HIGH,
    )
    pages = [{"page": 1, "text": anchor.source_quote + " " + rule.source_quote}]
    assert "TIME_CONFLICT" in _validate_rule(rule, pages, [anchor])[0]
    extraction = SyllabusExtraction(
        course_name="Regression", recurring_rules=[rule], schedule_anchors=[anchor]
    )
    corrected = _normalize_explicit_source_event_dates(extraction, START, END, pages)
    assert corrected.schedule_anchors[0].start_time == time(14)
    assert (
        "TIME_CONFLICT"
        not in _validate_rule(corrected.recurring_rules[0], pages, corrected.schedule_anchors)[0]
    )


def test_ambiguous_specific_clock_still_blocks_universal_deadline():
    quote = "Homework 3 is due at 12:00."
    source = quote + " All assignments are due at 12 AM."
    candidate = event(quote, title="Homework 3", kind="assignment", start=None, end="12:00")
    pages = [{"page": 1, "text": source}]
    assert normalize(candidate, pages) == candidate
    assert "TIME_CONFLICT" in validate_candidate(candidate, pages, START, END)[0]


@pytest.mark.parametrize("next_item", ["Lectures meet", "Classes start", "Office hours:"])
def test_exam_time_does_not_cross_new_item_on_next_line(next_item):
    source = f"Final Exam date will be announced\n{next_item} 2 PM - 4 PM"
    candidate = event(source)
    pages = [{"page": 1, "text": source}]
    assert normalize(candidate, pages) == candidate
    assert "TIME_CONFLICT" in validate_candidate(candidate, pages, START, END)[0]


def test_exam_clock_on_wrapped_line_still_belongs_to_exam():
    source = "Final Exam\n2 PM - 4 PM"
    candidate = event(source)
    corrected = normalize(candidate, [{"page": 1, "text": source}])
    assert (corrected.start_time, corrected.end_time) == (time(14), time(16))


@pytest.mark.parametrize(
    ("title", "quote", "value", "expected_start", "expected_end"),
    [
        (
            "Midterm Exam",
            "Tuesday, March 10, 3:30 - 4:45 pm",
            "15:30:00-16:45",
            time(15, 30),
            time(16, 45),
        ),
        (
            "Final Exam",
            "Thursday, May 18, 1:30 - 3:30 pm",
            "13:30:00-15:30",
            time(13, 30),
            time(15, 30),
        ),
    ],
)
def test_real_umd_interval_misparsed_as_offset_is_restored_from_adjacent_source_title(
    title,
    quote,
    value,
    expected_start,
    expected_end,
):
    candidate = event(quote, title=title, start=value, end=None)
    source = f"10%\n{title}\n{quote}\n25%\nAnother assessment"
    pages = [{"page": 1, "text": source}]
    assert candidate.start_time.tzinfo is not None
    assert "TIME_CONFLICT" in validate_candidate(candidate, pages, START, END)[0]
    corrected = normalize(candidate, pages)
    assert (corrected.start_time, corrected.end_time) == (expected_start, expected_end)
    assert corrected.start_time.tzinfo is None
    assert "TIME_CONFLICT" not in validate_candidate(corrected, pages, START, END)[0]
    assert quote.split(", ")[-1] in corrected.derivation_summary


def test_unresolved_clock_offset_is_flagged_without_inventing_end_time():
    quote = "Receive permission at least 48 hours before the exam."
    candidate = event(
        quote,
        title="Absence permission deadline",
        kind="deadline",
        start="15:30:00-16:45",
        end=None,
    )
    pages = [{"page": 1, "text": quote}]
    assert "TIME_CONFLICT" in validate_candidate(candidate, pages, START, END)[0]
    assert normalize(candidate, pages) == candidate


def test_single_eight_am_clock_does_not_gain_an_end_time():
    quote = "Final Exam: 8 AM."
    candidate = event(quote, start="08:00", end=None)
    corrected = normalize(candidate, [{"page": 1, "text": quote}])
    assert corrected.start_time == time(8)
    assert corrected.end_time is None


def test_missing_end_is_recovered_only_from_this_events_explicit_interval():
    quote = "Final Exam: 2 PM - 4 PM."
    candidate = event(quote, start="14:00", end=None)
    corrected = normalize(candidate, [{"page": 1, "text": quote}])
    assert corrected.end_time == time(16)


def test_unresolved_offset_cannot_be_silently_saved_as_local_clock(app_client, monkeypatch):
    import pymupdf

    from app.processing import process_job

    from .conftest import auth_headers

    client, app = app_client
    source = (
        "Absence permission deadline is 48 hours before the exam, subject to instructor approval."
    )
    candidate = event(
        source,
        title="Absence permission deadline",
        kind="deadline",
        start="15:30:00-16:45",
        end=None,
    )
    monkeypatch.setattr(
        "app.processing.extract_locally",
        lambda pages: SyllabusExtraction(course_name="Offset regression", events=[candidate]),
    )
    semester = client.post(
        "/api/semesters",
        headers=auth_headers(),
        json={
            "name": "Spring 2026",
            "start_date": START.isoformat(),
            "end_date": END.isoformat(),
            "timezone": "America/New_York",
        },
    ).json()
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 50), source)
        data = pdf.tobytes()
    uploaded = client.post(
        f"/api/semesters/{semester['id']}/syllabi",
        headers=auth_headers(),
        files=[("files", ("offset.pdf", data, "application/pdf"))],
    )
    assert uploaded.status_code == 202
    process_job(
        uploaded.json()["jobs"][0]["id"],
        settings=app.state.settings,
        session_factory=app.state.session_factory,
    )
    review = client.get(f"/api/semesters/{semester['id']}/review", headers=auth_headers()).json()
    assert len(review["events"]) == 1
    saved = review["events"][0]
    assert saved["start_time"] is None
    assert saved["end_time"] is None
    assert "TIME_CONFLICT" in saved["warning_codes"]
    assert "15:30:00-16:45" in saved["warning_reason"]


@pytest.mark.parametrize("title", ["Quiz 2", "Homework 2"])
def test_combined_numbered_source_covers_second_quiz_and_homework(title):
    quote = "Quiz and Homework 1 & 2 on Chapters 1 & 2 due"
    kind = "quiz" if title.startswith("Quiz") else "assignment"
    candidate = event(quote, title=title, kind=kind, start="23:59:00-05:00", end=None)
    pages = [
        {"page": 1, "text": quote},
        {"page": 2, "text": "All assignments, excluding the exams, are due at 11:59 PM EST."},
    ]
    corrected = normalize(candidate, pages)
    assert corrected.start_time == time(23, 59)
    assert corrected.start_time.tzinfo is None
    assert "TIME_CONFLICT" not in validate_candidate(corrected, pages, START, END)[0]
