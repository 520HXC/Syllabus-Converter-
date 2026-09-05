from datetime import time

from app.processing import CandidateEvent, SyllabusExtraction, SyllabusRepair, _merge_extractions


def event(title, *, date="2026-03-29", end="23:59"):
    return CandidateEvent(
        title=title,
        event_type="assignment",
        event_date=date,
        end_time=end,
        source_quote=f"{title} due March 29.",
        source_page=1,
        confidence="high",
        year_was_explicit=True,
        extraction_model="primary",
    )


def test_repair_ignores_already_validated_primary_instead_of_duplicating_or_overwriting():
    homework = event("Homework 8 due")
    midterm = event("Midterm Exam", end="03:30")
    primary = SyllabusExtraction(course_name="Brooklyn", events=[homework, midterm])
    extra_homework = event("Homework 8", end="11:59").model_copy(
        update={"extraction_model": "repair"}
    )
    fixed_midterm = event("Midterm Exam", end="15:30").model_copy(
        update={"extraction_model": "repair"}
    )
    repair = SyllabusRepair(events=[extra_homework, fixed_midterm])
    merged = _merge_extractions(primary, repair, {1}, set())
    assert len(merged.events) == 2
    assert merged.events[0] == homework
    assert merged.events[1].end_time == time(15, 30)
    assert merged.events[1].extraction_model == "repair"


def test_context_aliases_use_existing_canonical_identity_for_protected_events():
    primary = SyllabusExtraction(course_name="Regression", events=[event("Quick Checks deadline")])
    merged = _merge_extractions(
        primary, SyllabusRepair(events=[event("Weekly quick checks")]), set(), set()
    )
    assert merged.events == primary.events


def test_distinct_items_on_same_date_and_same_title_on_different_date_remain():
    homework = event("Homework 8 due")
    quiz = event("Quiz 8")
    later_homework = event("Homework 8", date="2026-04-12")
    primary = SyllabusExtraction(course_name="Regression", events=[homework])
    merged = _merge_extractions(
        primary, SyllabusRepair(events=[quiz, later_homework]), set(), set()
    )
    assert merged.events == [homework, quiz, later_homework]


def test_filtered_unrelated_only_repair_preserves_unresolved_target():
    homework = event("Homework 8 due")
    target = event("Midterm Exam", end="03:30")
    primary = SyllabusExtraction(course_name="Regression", events=[homework, target])
    merged = _merge_extractions(primary, SyllabusRepair(events=[event("Homework 8")]), {1}, set())
    assert merged.events == [homework, target]


def test_same_saved_repair_is_idempotent_after_target_becomes_validated():
    homework = event("Homework 8 due")
    midterm = event("Midterm Exam", end="03:30")
    repair = SyllabusRepair(events=[event("Homework 8"), event("Midterm Exam", end="15:30")])
    primary = SyllabusExtraction(course_name="Regression", events=[homework, midterm])
    first = _merge_extractions(primary, repair, {1}, set())
    second = _merge_extractions(first, repair, set(), set())
    assert second.events == first.events


def test_partial_repair_preserves_each_flagged_item_it_did_not_return():
    first = event("Quiz 1", end="11:59")
    second = event("Quiz 2", end="11:59")
    repaired_first = event("Quiz 1", end="23:59")
    primary = SyllabusExtraction(course_name="Regression", events=[first, second])
    merged = _merge_extractions(primary, SyllabusRepair(events=[repaired_first]), {0, 1}, set())
    assert len(merged.events) == 2
    assert repaired_first in merged.events
    assert second in merged.events


def test_repair_can_correct_date_when_canonical_target_title_is_unique():
    target = event("Midterm Exam", date="2026-03-28", end="03:30")
    repaired = event("Midterm Exam", date="2026-03-29", end="15:30")
    primary = SyllabusExtraction(course_name="Regression", events=[target])
    merged = _merge_extractions(primary, SyllabusRepair(events=[repaired]), {0}, set())
    assert merged.events == [repaired]


def test_repair_with_ambiguous_target_keeps_all_original_candidates_for_review():
    first = event("Homework", date="2026-03-28")
    second = event("Homework", date="2026-04-04")
    repair = event("Homework", date="2026-04-11")
    primary = SyllabusExtraction(course_name="Regression", events=[first, second])
    merged = _merge_extractions(primary, SyllabusRepair(events=[repair]), {0, 1}, set())
    assert first in merged.events and second in merged.events and repair in merged.events


def test_missing_addition_does_not_delete_an_unrelated_flagged_item():
    unresolved = event("Midterm Exam", end="03:30")
    missing = event("Project presentation")
    primary = SyllabusExtraction(course_name="Regression", events=[unresolved])
    merged = _merge_extractions(primary, SyllabusRepair(events=[missing]), {0}, set())
    assert unresolved in merged.events
    assert missing in merged.events
