from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from icalendar import Calendar

from app.ical import build_calendar


def exported_event(**overrides):
    values = {
        "id": "deadline-test",
        "course": SimpleNamespace(code="CS 101", name="Computer Science"),
        "title": "Final project",
        "source_page": 1,
        "source_quote": "Final project due December 10, 2026 at 11:59 PM.",
        "event_date": date(2026, 12, 10),
        "start_time": None,
        "end_time": None,
        "is_all_day": False,
        "timezone": "America/New_York",
    }
    values.update(overrides)
    result = Calendar.from_ical(build_calendar("Test semester", [SimpleNamespace(**values)]))
    return result.walk("VEVENT")[0]


@pytest.mark.parametrize("deadline", [time(23, 59), time.fromisoformat("23:59:00-05:00")])
def test_end_time_only_exports_deadline_in_semester_timezone_without_duration(deadline):
    event = exported_event(end_time=deadline)

    assert event.decoded("DTSTART") == datetime(
        2026, 12, 10, 23, 59, tzinfo=ZoneInfo("America/New_York")
    )
    assert event["DTSTART"].params["TZID"] == "America/New_York"
    assert "DTEND" not in event
    assert "DURATION" not in event


def test_explicit_all_day_ignores_residual_times():
    event = exported_event(is_all_day=True, start_time=time(9), end_time=time(23, 59))

    assert type(event.decoded("DTSTART")) is date
    assert event.decoded("DTSTART") == date(2026, 12, 10)
    assert event.decoded("DTEND") == date(2026, 12, 11)


def test_event_without_times_exports_as_all_day():
    event = exported_event()

    assert type(event.decoded("DTSTART")) is date
    assert event.decoded("DTEND") == date(2026, 12, 11)


@pytest.mark.parametrize(
    ("event_date", "expected_offset"),
    [
        (date(2026, 3, 6), timedelta(hours=-5)),
        (date(2026, 3, 9), timedelta(hours=-4)),
        (date(2026, 10, 30), timedelta(hours=-4)),
        (date(2026, 11, 2), timedelta(hours=-5)),
    ],
)
def test_timed_interval_keeps_wall_clock_and_dst_offset(event_date, expected_offset):
    event = exported_event(event_date=event_date, start_time=time(9), end_time=time(10, 30))

    start = event.decoded("DTSTART")
    end = event.decoded("DTEND")
    assert start.date() == end.date() == event_date
    assert start.time() == time(9)
    assert end.time() == time(10, 30)
    assert start.utcoffset() == end.utcoffset() == expected_offset
    assert end - start == timedelta(minutes=90)
    assert event["DTSTART"].params["TZID"] == "America/New_York"
    assert event["DTEND"].params["TZID"] == "America/New_York"


def test_start_only_does_not_invent_duration():
    event = exported_event(start_time=time(14, 15))

    assert event.decoded("DTSTART").time() == time(14, 15)
    assert "DTEND" not in event
    assert "DURATION" not in event
