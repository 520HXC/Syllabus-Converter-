from __future__ import annotations

from datetime import date, time

import pytest

from app.event_deduplication import deduplicate_summary_events
from app.processing import CandidateEvent

EXTRA_HEADER = "2 Extra Credit assignments due (each is worth 2 fnal grade points:)"
EXTRA_CHILDREN = "Quiz and Homework 14 on Chapter 14 due"
WEEKLY_POLICY = "Are assigned on a weekly basis and are due in approximately one week."


def event(title: str, quote: str, *, page: int = 13, dated: bool = True) -> CandidateEvent:
    return CandidateEvent(
        title=title,
        event_type="quiz" if title.startswith("Quiz") else "assignment",
        event_date=date(2026, 5, 17) if dated else None,
        source_quote=quote,
        source_page=page,
        confidence="medium",
        year_was_explicit=True,
    )


def extra_events() -> list[CandidateEvent]:
    return [
        event("2 Extra Credit assignments due (each is worth 2 final grade points)", EXTRA_HEADER),
        event("Homework 14", EXTRA_CHILDREN),
        event("Quiz 14", EXTRA_CHILDREN),
    ]


def extra_pages() -> list[dict]:
    return [{"page": 13, "text": f"05/17 (Su)\n{EXTRA_HEADER}\n‹ {EXTRA_CHILDREN}\nEnd"}]


def weekly_events(count: int = 10) -> list[CandidateEvent]:
    return [event("Weekly Homework", WEEKLY_POLICY, page=4, dated=False)] + [
        event(f"Homework {number}", f"Week {number + 1} — Homework {number}", page=6, dated=False)
        for number in range(1, count + 1)
    ]


def weekly_pages(count: int = 10) -> list[dict]:
    return [
        {"page": 4, "text": f"Homework (10%)\n•\n{WEEKLY_POLICY}\n•\nSubmit via Canvas."},
        {"page": 6, "text": "Course Schedule\n" + "\n".join(
            f"Week {number + 1}\nHomework {number}" for number in range(1, count + 1)
        )},
    ]


def test_source_parent_is_removed_and_extra_credit_is_retained_on_both_children():
    original = extra_events()
    kept, index_map = deduplicate_summary_events(original, extra_pages())
    assert [item.title for item in kept] == ["Homework 14", "Quiz 14"]
    assert index_map == {1: 0, 2: 1}
    assert all("Extra Credit" in item.derivation_summary for item in kept)
    assert all("worth 2" in item.derivation_summary for item in kept)
    assert all(item.derivation_summary is None for item in original)
    assert all(item.source_quote == EXTRA_CHILDREN for item in kept)


@pytest.mark.parametrize("difference", ["missing", "date", "page", "source", "count", "separate"])
def test_extra_credit_parent_is_kept_without_complete_proven_same_group(difference):
    events = extra_events()
    pages = extra_pages()
    if difference == "missing":
        events.pop()
    elif difference == "date":
        events[2] = events[2].model_copy(update={"event_date": date(2026, 5, 18)})
    elif difference == "page":
        events[2] = events[2].model_copy(update={"source_page": 12})
    elif difference == "source":
        pages[0]["text"] = pages[0]["text"].replace(EXTRA_CHILDREN, "Independent bonus essay due")
    elif difference == "count":
        pages[0]["text"] = pages[0]["text"].replace("2 Extra", "3 Extra")
        events[0] = event("3 Extra Credit assignments due", "3 Extra Credit assignments due")
    elif difference == "separate":
        pages[0]["text"] = pages[0]["text"].replace(
            f"{EXTRA_HEADER}\n‹ {EXTRA_CHILDREN}", f"{EXTRA_CHILDREN}\n{EXTRA_HEADER}\nBonus essays"
        )
    kept, index_map = deduplicate_summary_events(events, pages)
    assert kept == events
    assert index_map == dict(enumerate(range(len(events))))


def test_same_day_independent_extra_credit_assignment_is_never_deleted():
    independent = event("Extra Credit Essay due", "An additional Extra Credit Essay is due.")
    events = [*extra_events(), independent]
    kept, _ = deduplicate_summary_events(events, extra_pages())
    assert [item.title for item in kept] == ["Homework 14", "Quiz 14", "Extra Credit Essay due"]


def test_complete_numbered_homework_replaces_generic_policy_without_losing_rule():
    events = weekly_events()
    events[1] = events[1].model_copy(update={"derivation_summary": "Date unresolved."})
    pages = weekly_pages()
    pages[0]["text"] += "\nThere are 10 homework assignments in total."
    kept, index_map = deduplicate_summary_events(events, pages)
    assert [item.title for item in kept] == [f"Homework {number}" for number in range(1, 11)]
    assert all(item.event_date is None for item in kept)
    assert all(WEEKLY_POLICY in item.derivation_summary for item in kept)
    assert kept[0].derivation_summary.startswith("Date unresolved.")
    assert index_map == {number: number - 1 for number in range(1, 11)}


@pytest.mark.parametrize("difference", ["missing", "source", "extra", "dated", "clock", "heading"])
def test_generic_weekly_rule_is_retained_if_coverage_or_policy_is_uncertain(difference):
    events = weekly_events()
    pages = weekly_pages()
    if difference == "missing":
        events.pop()
    elif difference == "source":
        pages[1]["text"] += "\nHomework 11"
    elif difference == "extra":
        quote = "Additional weekly homework is assigned separately from the numbered assignments."
        events[0] = events[0].model_copy(update={"source_quote": quote})
        pages[0]["text"] = f"Homework\n{quote}"
    elif difference == "dated":
        events[0] = events[0].model_copy(update={"event_date": date(2026, 3, 1)})
    elif difference == "clock":
        events[0] = events[0].model_copy(update={"end_time": time(23, 59)})
    elif difference == "heading":
        pages[0]["text"] = pages[0]["text"].replace("Homework (10%)", "Reading responses")
    kept, _ = deduplicate_summary_events(events, pages)
    assert kept == events


def test_undated_categories_without_numbered_items_are_retained():
    events = [
        event("Weekly Homework", WEEKLY_POLICY, page=4, dated=False),
        event("Final Exam", "Comprehensive final exam", page=4, dated=False),
        event("Quiz", "Quizzes count for ten percent", page=4, dated=False),
    ]
    kept, _ = deduplicate_summary_events(events, weekly_pages())
    assert kept == events


def test_deduplication_is_idempotent_and_does_not_duplicate_annotations():
    first, _ = deduplicate_summary_events(extra_events(), extra_pages())
    second, _ = deduplicate_summary_events(first, extra_pages())
    assert second == first


def test_extra_credit_summary_with_conflicting_clock_is_retained_for_review():
    events = extra_events()
    events[0] = events[0].model_copy(update={"end_time": time(23, 59)})
    events[1] = events[1].model_copy(update={"end_time": time(17)})
    kept, _ = deduplicate_summary_events(events, extra_pages())
    assert kept == events


def test_weekly_policy_with_additional_assignments_in_next_sentence_is_preserved():
    events = weekly_events()
    pages = weekly_pages()
    pages[0]["text"] += "\nAdditional homework beyond the numbered schedule may be assigned."
    kept, _ = deduplicate_summary_events(events, pages)
    assert kept == events


def test_weekly_summary_kept_when_later_homework_is_unpublished():
    events = weekly_events(2)
    pages = weekly_pages(2)
    pages[0]["text"] += "\nThere are 2 homework assignments in total."
    pages[1]["text"] += "\nWeeks 3-15 homework details will be announced later."
    kept, index_map = deduplicate_summary_events(events, pages)
    assert [item.title for item in kept] == [item.title for item in events]
    assert index_map == {0: 0, 1: 1, 2: 2}


def test_consecutive_homework_numbers_do_not_prove_complete_inventory():
    events = weekly_events(2)
    pages = weekly_pages(2)
    kept, _ = deduplicate_summary_events(events, pages)
    assert kept[0].title == "Weekly Homework"


def test_extra_credit_combined_cross_page_quotes_still_match_verified_local_list():
    events = extra_events()
    policy = "All assignments, excluding the exams, are due at 11:59 PM EST. "
    events[0] = events[0].model_copy(update={
        "title": "2 Extra Credit assignments",
        "source_quote": policy + EXTRA_HEADER.replace("fnal", "final"),
    })
    for index in (1, 2):
        events[index] = events[index].model_copy(update={
            "source_quote": policy + EXTRA_CHILDREN,
        })
    kept, _ = deduplicate_summary_events(events, extra_pages())
    assert [item.title for item in kept] == ["Homework 14", "Quiz 14"]
    assert all(EXTRA_HEADER in item.derivation_summary for item in kept)
    assert all(policy not in item.derivation_summary for item in kept)


def test_extra_credit_cross_page_quote_does_not_match_unrelated_local_list():
    events = extra_events()
    events[0] = events[0].model_copy(update={"title": "2 Extra Credit assignments"})
    events[1] = events[1].model_copy(update={"source_quote": "Homework 14 unrelated assignment"})
    kept, _ = deduplicate_summary_events(events, extra_pages())
    assert kept == events


def test_extra_credit_same_count_cannot_replace_separate_essay_and_reflection():
    events = extra_events()
    independent = "Separately, 2 Extra Credit assignments are due, an essay and a reflection."
    events[0] = events[0].model_copy(update={
        "title": "2 Extra Credit assignments essays and reflection", "source_quote": independent,
    })
    pages = extra_pages()
    pages[0]["text"] += "\n" + independent
    kept, _ = deduplicate_summary_events(events, pages)
    assert kept == events


def test_extra_credit_generic_title_still_requires_matching_local_heading():
    events = extra_events()
    independent = "Separately, 2 Extra Credit assignments are due, an essay and a reflection."
    events[0] = events[0].model_copy(update={
        "title": "2 Extra Credit assignments", "source_quote": independent,
    })
    pages = extra_pages()
    pages[0]["text"] += "\n" + independent
    kept, _ = deduplicate_summary_events(events, pages)
    assert kept == events


def test_extra_credit_count_can_come_from_verified_source_not_model_title():
    events = extra_events()
    events[0] = events[0].model_copy(update={
        "title": "Extra Credit assignments due",
        "start_time": time.fromisoformat("23:59:00-04:00"),
    })
    for index in (1, 2):
        events[index] = events[index].model_copy(update={"start_time": time(23, 59)})
    kept, _ = deduplicate_summary_events(events, extra_pages())
    assert [item.title for item in kept] == ["Homework 14", "Quiz 14"]


def test_duplicate_summary_clock_offset_cannot_block_same_verified_children():
    events = extra_events()
    events[0] = events[0].model_copy(update={"start_time": time.fromisoformat("23:59:00-05:00")})
    for index in (1, 2):
        events[index] = events[index].model_copy(update={"start_time": time(23, 59)})
    kept, _ = deduplicate_summary_events(events, extra_pages())
    assert [item.title for item in kept] == ["Homework 14", "Quiz 14"]
