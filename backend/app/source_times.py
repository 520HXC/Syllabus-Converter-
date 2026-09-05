"""Conservative clock checks against cited text and explicit assignment-wide policies."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time
from typing import Any

_MERIDIEM = r"[ap]\.?\s*m\.?"
_CLOCK = (
    rf"(?P<{{prefix}}hour>\d{{1,2}})(?::(?P<{{prefix}}minute>[0-5]\d))?"
    rf"\s*(?P<{{prefix}}meridiem>{_MERIDIEM})?"
)
_RANGE = re.compile(
    r"(?<![\d:/])"
    + _CLOCK.replace("{prefix}", "a")
    + r"\s*(?:[-–—]|\bto\b)\s*"
    + _CLOCK.replace("{prefix}", "b")
    + r"(?!\w)",
    re.I,
)
_SINGLE = re.compile(r"(?<![\d:/])" + _CLOCK.replace("{prefix}", "a") + r"(?!\w)", re.I)
_OWNERS = re.compile(
    r"\b(?:office\s+hours?|midterm(?:\s+exam)?|final\s+exam|exam\s+[\divx]+|"
    r"homework\s+\d+|quiz\s+\d+|assignment\s+\d+|project\s+\d+)\b",
    re.I,
)
_POLICY = re.compile(
    r"\bAll\s+(?P<kind>assignments|homework|quizzes|projects)"
    r"(?P<qualifier>\s*,\s*(?:excluding|except)\s+(?:the\s+)?exams\s*,)?"
    r"\s+(?:are\s+)?due\s+(?:at|by)\s+" + _CLOCK.replace("{prefix}", "a"),
    re.I,
)


@dataclass(frozen=True)
class SourceClock:
    start: time
    end: time | None
    quote: str
    page: int
    is_policy: bool = False
    ambiguous: bool = False


def _compact(value: str) -> str:
    value = re.sub(r"\u00ad\s*", "", value)
    return re.sub(r"\s+", " ", value).strip().casefold()


def _clock(match: re.Match, prefix: str, shared_meridiem: str | None = None) -> time | None:
    hour = int(match.group(prefix + "hour"))
    minute = int(match.group(prefix + "minute") or 0)
    meridiem = match.group(prefix + "meridiem") or shared_meridiem
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem.casefold().startswith("p") else 0)
    elif match.group(prefix + "minute") is None:
        return None
    return time(hour, minute) if hour < 24 else None


def _clocks(value: str, page: int) -> list[SourceClock]:
    result: list[SourceClock] = []
    occupied: list[tuple[int, int]] = []
    for match in _RANGE.finditer(value):
        # A colon or meridiem is required so dates such as May 16-26 are not clocks.
        shared = match.group("bmeridiem")
        start = _clock(match, "a", shared)
        end = _clock(match, "b")
        if start is not None and end is not None:
            occupied.append(match.span())
            explicit = bool(
                match.group("ameridiem")
                or shared
                or start.hour == 0
                or end.hour == 0
                or max(start.hour, end.hour) > 12
            )
            ambiguous = not explicit or bool(
                shared and not match.group("ameridiem") and start >= end
            )
            result.append(
                SourceClock(start, end, match.group(0).strip(), page, ambiguous=ambiguous)
            )
    for match in _SINGLE.finditer(value):
        if any(left <= match.start() < right for left, right in occupied):
            continue
        parsed = _clock(match, "a")
        if parsed is not None:
            explicit = bool(match.group("ameridiem") or parsed.hour == 0 or parsed.hour > 12)
            result.append(
                SourceClock(parsed, None, match.group(0).strip(), page, ambiguous=not explicit)
            )
    return result


def _first_statement(value: str) -> str:
    # Keep dotted a.m./p.m. intact while using actual sentence and clause boundaries.
    masked = re.sub(_MERIDIEM, lambda match: match.group(0).replace(".", "_"), value, flags=re.I)
    boundary = re.search(r"[.!?;](?:\s|$)", masked)
    end = boundary.end() if boundary else len(value)
    # PDF wrapping may omit punctuation between unrelated schedule items. A new
    # subject with its own meeting verb is a boundary; a wrapped clock alone is not.
    for item in re.finditer(
        r"\b(?:lectures?|class(?:es)?|office\s+hours?|labs?|discussions?|tutorials?)"
        r"\s*(?:(?:meet|start|begin|occur)(?:s)?\b|:)",
        masked,
        re.I,
    ):
        if item.start() > 0:
            end = min(end, item.start())
            break
    return value[:end]


def _owned_quote(candidate: Any, page_text: str) -> str | None:
    quote = re.sub(r"\s+", " ", candidate.source_quote).strip()
    # Require the cited excerpt to exist. For damaged PDF hyphenation after a time,
    # its complete title-and-clock prefix is enough; never trust ungrounded clocks.
    matches = list(_RANGE.finditer(quote)) + list(_SINGLE.finditer(quote))
    clocks = [match for match in matches if _clock(match, "a", match.groupdict().get("bmeridiem"))]
    if _compact(quote) not in _compact(page_text):
        if not clocks:
            return None
        prefix_end = max(match.end() for match in clocks)
        quote = quote[:prefix_end]
        if _compact(quote) not in _compact(page_text):
            return None
    title = candidate.title.split(":", 1)[0].strip()
    owners = list(_OWNERS.finditer(quote))
    title_owners = list(_OWNERS.finditer(title))
    if title_owners and not owners:
        # Table rows often cite only a date/time while the assessment title is on
        # the immediately preceding line. Require that exact adjacency uniquely.
        identity = title_owners[0].group(0)
        adjacent = re.escape(_compact(identity)) + r"\s*:?\s+" + re.escape(_compact(quote))
        if len(list(re.finditer(adjacent, _compact(page_text)))) == 1:
            quote = identity + ": " + quote
            owners = list(_OWNERS.finditer(quote))
    if title_owners:
        identity = _compact(title_owners[0].group(0))
        matching = [owner for owner in owners if _compact(owner.group(0)) == identity]
        if len(matching) != 1:
            combined = re.search(
                r"\bquiz\s+and\s+homework\s+(\d+)(?:\s*(?:&|and)\s*(\d+))?\b",
                quote,
                re.I,
            )
            if combined and not _clocks(quote, candidate.source_page):
                members = {
                    f"{kind} {number}"
                    for kind in ("quiz", "homework")
                    for number in combined.groups()
                    if number is not None
                }
                if identity in members:
                    return _first_statement(quote)
            return None
        owner = matching[0]
        following = next((item for item in owners if item.start() > owner.start()), None)
        return _first_statement(
            quote[owner.start() : following.start() if following else len(quote)]
        )
    if len(owners) > 1 or any("office" in owner.group(0).casefold() for owner in owners):
        return None
    # An exact event title is necessary for otherwise unrecognized assessment labels.
    if _compact(title) not in _compact(quote):
        return None
    title_start = _compact(quote).find(_compact(title))
    return _first_statement(quote[title_start:])


def source_clocks(candidate: Any, pages: list[dict]) -> list[SourceClock]:
    source_page = next((page for page in pages if page["page"] == candidate.source_page), None)
    if source_page is None:
        return []
    owned = _owned_quote(candidate, source_page["text"])
    if owned is None:
        return []
    direct = _clocks(owned, candidate.source_page)
    if direct:
        return direct
    # Only an explicit universal deadline can be borrowed from another page. Exams,
    # administrative deadlines, and class/office-hour times never inherit this rule.
    if getattr(candidate, "event_type", "class") not in {"assignment", "quiz", "project"}:
        return []
    policies: list[SourceClock] = []
    for page in pages:
        page_text = re.sub(r"\s+", " ", page["text"])
        for match in _POLICY.finditer(page_text):
            tail = re.split(r"[.!?](?:\s|$)", page_text[match.end() :], maxsplit=1)[0]
            if re.search(r"\b(?:except|excluding|unless|other than|if)\b", tail, re.I):
                continue
            kind = match.group("kind").casefold()
            types = {"homework": "assignment", "quizzes": "quiz", "projects": "project"}
            if kind != "assignments" and getattr(candidate, "event_type", "class") != types[kind]:
                continue
            parsed = _clock(match, "a")
            if parsed is not None:
                policies.append(SourceClock(parsed, None, match.group(0), page["page"], True))
    return policies


def _expected_fields(candidate: Any, clock: SourceClock) -> dict[str, time]:
    if clock.end is not None:
        return {"start_time": clock.start, "end_time": clock.end}
    if clock.is_policy or getattr(candidate, "event_type", "class") in {
        "assignment",
        "quiz",
        "project",
        "deadline",
    }:
        field = (
            "start_time"
            if candidate.start_time is not None and candidate.end_time is None
            else "end_time"
        )
    else:
        field = (
            "end_time"
            if candidate.end_time is not None and candidate.start_time is None
            else "start_time"
        )
    return {field: clock.start}


def clock_conflict(candidate: Any, pages: list[dict]) -> str | None:
    offset_fields = [
        f"{field}={getattr(candidate, field).isoformat()}"
        for field in ("start_time", "end_time")
        if getattr(candidate, field) is not None and getattr(candidate, field).tzinfo is not None
    ]
    if offset_fields:
        return (
            "The extracted clock contains an unsupported timezone offset: "
            + ", ".join(offset_fields)
            + ". Confirm a local time in the semester timezone; a range must use separate fields."
        )
    clocks = source_clocks(candidate, pages)
    if not clocks:
        page = next((page for page in pages if page["page"] == candidate.source_page), None)
        owned = _owned_quote(candidate, page["text"]) if page else None
        if (
            owned is not None
            and (candidate.start_time or candidate.end_time)
            and _clocks(candidate.source_quote, candidate.source_page)
            and not _clocks(owned, candidate.source_page)
        ):
            return "The cited time belongs to another statement or item. Confirm this item's time."
        return None
    expectations = [tuple(_expected_fields(candidate, clock).items()) for clock in clocks]
    if any(clock.ambiguous for clock in clocks) or len(set(expectations)) > 1:
        return "The cited text contains multiple possible times. Confirm this event's time."
    mismatches = [
        f"{field} should be {expected.strftime('%H:%M')} from page {clocks[0].page}"
        for field, expected in expectations[0]
        if getattr(candidate, field) is not None and getattr(candidate, field) != expected
    ]
    if mismatches:
        return "The extracted time conflicts with the source clock. " + "; ".join(mismatches) + "."
    return None


def normalize_source_clock(candidate: Any, pages: list[dict]) -> Any:
    clocks = source_clocks(candidate, pages)
    if not clocks:
        return candidate
    expectations = [tuple(_expected_fields(candidate, clock).items()) for clock in clocks]
    if any(clock.ambiguous for clock in clocks) or len(set(expectations)) != 1:
        return candidate
    changes = {}

    def matches_local_clock(current: time | None, expected: time) -> bool:
        return current is not None and (current.hour % 12, current.minute, current.second) == (
            expected.hour % 12,
            expected.minute,
            expected.second,
        )

    grounded_range = clocks[0].end is not None and any(
        matches_local_clock(getattr(candidate, field), expected)
        for field, expected in expectations[0]
    )
    for field, expected in expectations[0]:
        current = getattr(candidate, field)
        # Restore a missing interval endpoint only from this item's explicit source
        # range. Never interpret a malformed UTC offset as the missing endpoint.
        if current is None and grounded_range:
            changes[field] = expected
        elif matches_local_clock(current, expected) and current != expected:
            changes[field] = expected
    if not changes:
        return candidate
    evidence = clocks[0]
    note = f"Time normalized from page {evidence.page}: {evidence.quote}."
    summary = candidate.derivation_summary or ""
    changes["derivation_summary"] = " ".join(part for part in (summary, note) if part)
    if hasattr(candidate, "is_all_day"):
        changes["is_all_day"] = False
    return candidate.model_copy(update=changes)
