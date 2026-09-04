from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event

from .models import ExtractedEvent


def build_calendar(name: str, events: list[ExtractedEvent]) -> bytes:
    calendar = Calendar()
    calendar.add("prodid", "-//Syllabus Calendar//MVP//EN")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("x-wr-calname", name)

    for item in events:
        event = Event()
        course_label = item.course.code or item.course.name
        event.add("summary", f"{course_label} · {item.title}")
        event.add("uid", f"{item.id}@syllabus-calendar.local")
        event.add(
            "description",
            f"Imported from syllabus page {item.source_page}.\n\n{item.source_quote}",
        )
        event_time = item.start_time or item.end_time
        if item.is_all_day or event_time is None:
            event.add("dtstart", item.event_date)
            event.add("dtend", item.event_date + timedelta(days=1))
        else:
            zone = ZoneInfo(item.timezone)
            event.add("dtstart", datetime.combine(item.event_date, event_time, tzinfo=zone))
            if item.start_time is not None and item.end_time is not None:
                event.add("dtend", datetime.combine(item.event_date, item.end_time, tzinfo=zone))
        calendar.add_component(event)

    return calendar.to_ical()
