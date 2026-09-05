from datetime import date, time

import pytest

from app.processing import (
    CandidateEvent,
    RecurringRule,
    ScheduleAnchor,
    SyllabusExtraction,
    _filter_non_actionable_course_structure_items,
    _materialize_missing_ambiguous_review_events,
    expand_recurring_rules,
)

CLASS_SCHEDULE = "Class Schedule and Location: MWF, 9:00 AM - 9:50 AM, IST-1017"


def candidate(title, event_type="class", **kwargs):
    return CandidateEvent(
        title=title,
        event_type=event_type,
        source_quote=kwargs.pop("source_quote", title),
        source_page=1,
        confidence="high",
        year_was_explicit=True,
        **kwargs,
    )


def test_mwf_course_schedule_does_not_expand_into_lecture_events():
    anchor = ScheduleAnchor(
        title="EML 4225 lecture",
        weekday="monday",
        start_time=time(9),
        end_time=time(9, 50),
        source_quote=CLASS_SCHEDULE,
        source_page=1,
    )
    rules = [
        RecurringRule(
            title="EML 4225 lecture",
            event_type="class",
            rule_kind="weekly_fixed",
            weekday=weekday,
            start_time=time(9),
            end_time=time(9, 50),
            boundary_start=date(2026, 1, 12),
            boundary_end=date(2026, 4, 27),
            source_quote=CLASS_SCHEDULE,
            source_page=1,
            confidence="high",
        )
        for weekday in ["monday", "wednesday", "friday"]
    ]
    special_events = [
        candidate("First lecture", event_date=date(2026, 1, 12)),
        candidate("Last day of classes", event_date=date(2026, 4, 27)),
        candidate("Final Review", event_date=date(2026, 4, 27)),
    ]
    extraction = SyllabusExtraction(
        course_name="EML 4225",
        events=special_events,
        schedule_anchors=[anchor],
        recurring_rules=rules,
    )

    filtered = _filter_non_actionable_course_structure_items(extraction)
    _, expanded = expand_recurring_rules(
        anchors=filtered.schedule_anchors,
        rules=filtered.recurring_rules,
        semester_start=date(2026, 1, 12),
        semester_end=date(2026, 5, 1),
        explicit_events=filtered.events,
        extraction_model=None,
    )

    assert expanded == []
    assert filtered.recurring_rules == []
    assert filtered.schedule_anchors == [anchor]
    assert [event.title for event in filtered.events] == [
        "First lecture", "Last day of classes", "Final Review"
    ]


@pytest.mark.parametrize("text", [
    "Grade Breakdown\nHomework\n10%\nQuiz\n10%\nProject\n10%",
    "Quiz (10%)\nOnly approved calculators are allowed.\nNo make-up will be offered.",
    "Quizzes (15%)\nNo individual dates are announced.",
])
def test_missing_graded_quiz_category_is_retained_once_without_dates(text):
    pages = [{"page": 3, "text": text}, {"page": 4, "text": "Quiz (10%)"}]
    extraction = SyllabusExtraction(course_name="EML 4225")

    result = _materialize_missing_ambiguous_review_events(
        extraction, pages, extraction_model="test-model"
    )
    again = _materialize_missing_ambiguous_review_events(
        result, pages, extraction_model="test-model"
    )

    assert len(again.events) == 1
    quiz = again.events[0]
    assert quiz.title == "Quizzes"
    assert quiz.event_type == "quiz"
    assert quiz.event_date is None
    assert quiz.start_time is None
    assert quiz.end_time is None
    assert quiz.source_page == 3
    assert quiz.review_status == "needs_review"
    assert quiz.extraction_model == "test-model"
    assert " ".join(quiz.source_quote.split()) in " ".join(text.split())


@pytest.mark.parametrize("title,event_type", [
    ("Quiz 1", "quiz"),
    ("Homework and Quiz 1", "assignment"),
])
def test_quiz_category_does_not_duplicate_an_existing_assessment(title, event_type):
    event = candidate(title, event_type, event_date=date(2026, 2, 9))
    extraction = SyllabusExtraction(course_name="Example", events=[event])
    result = _materialize_missing_ambiguous_review_events(
        extraction, [{"page": 1, "text": "Quiz (10%)"}], extraction_model=None
    )
    assert result.events == [event]


def test_quiz_category_does_not_duplicate_a_recurring_quiz_rule():
    rule = RecurringRule(
        title="Weekly quizzes",
        event_type="quiz",
        rule_kind="weekly_fixed",
        weekday="friday",
        source_quote="Quizzes each Friday",
        source_page=1,
        confidence="high",
    )
    extraction = SyllabusExtraction(course_name="Example", recurring_rules=[rule])
    result = _materialize_missing_ambiguous_review_events(
        extraction, [{"page": 1, "text": "Quiz (10%)"}], extraction_model=None
    )
    assert result.events == []
    assert result.recurring_rules == [rule]


@pytest.mark.parametrize("text", [
    "No make-up options will be provided for quizzes.",
    "No quizzes will be given in this course.",
    "Quiz (0%)\nUngraded practice only.",
    "Quiz review\n10%\nProject\n20%",
])
def test_quiz_policy_or_ungraded_mention_does_not_invent_an_assessment(text):
    result = _materialize_missing_ambiguous_review_events(
        SyllabusExtraction(course_name="Example"),
        [{"page": 1, "text": text}],
        extraction_model=None,
    )
    assert result.events == []


@pytest.mark.parametrize("quote", [
    "Lectures: Tu 3:30 - 4:45 pm, PHY 4221",
    "Labs: Wed/Fri 10 am - 2 pm, AVW 1454/AJC 2132",
])
def test_plural_weekday_meeting_headers_remain_anchors_not_review_items(quote):
    ordinary = candidate("ENEE 140 meeting", source_quote=quote)
    special = candidate(
        "Last lecture", event_date=date(2026, 5, 12), source_quote="Last lecture May 12"
    )
    anchor = ScheduleAnchor(
        title="ENEE 140 meeting", weekday="tuesday", source_quote=quote, source_page=1
    )
    rule = RecurringRule(
        title="ENEE 140 meeting",
        event_type="class",
        rule_kind="weekly_fixed",
        weekday="tuesday",
        source_quote=quote,
        source_page=1,
        confidence="medium",
        expansion_mode="review_only",
    )
    filtered = _filter_non_actionable_course_structure_items(
        SyllabusExtraction(
            course_name="ENEE 140",
            events=[ordinary, special],
            schedule_anchors=[anchor],
            recurring_rules=[rule],
        )
    )
    assert filtered.events == [special]
    assert filtered.recurring_rules == []
    assert filtered.schedule_anchors == [anchor]
