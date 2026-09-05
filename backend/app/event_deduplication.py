from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.processing import CandidateEvent

_EXTRA_SUMMARY = re.compile(r"\b(?:(\d+)\s+)?extra\s+credit\s+assignments?\b", re.I)
_ITEM = re.compile(r"\b(quiz|homework)\s*#?\s*(\d+)\b", re.I)
_COMBINED_ITEM = re.compile(r"\bquiz\s+(?:and|&)\s+homework\s*#?\s*(\d+)\b", re.I)
_WEEKLY_TITLE = re.compile(r"(?:weekly\s+)?homework(?:\s+assignments?)?", re.I)
_HOMEWORK = re.compile(r"\bhomework\s*#?\s*(\d+)\b", re.I)
_ADDITIONAL = re.compile(r"\b(?:additional|separate|extra|in addition)\b", re.I)


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _item_references(value: str) -> set[tuple[str, int]]:
    references = {(match[0].lower(), int(match[1])) for match in _ITEM.findall(value)}
    for number in _COMBINED_ITEM.findall(value):
        references.update({("quiz", int(number)), ("homework", int(number))})
    return references


def _matches_summary_heading(header: str, quoted_fragment: str) -> bool:
    source = re.sub(r"\W+", "", _normalized(header))
    quoted = re.sub(r"\W+", "", _normalized(quoted_fragment))
    if quoted in source:
        return True
    # PDF text can drop a ligature character, e.g. final -> fnal. Permit at most
    # two such extraction characters, never a different assignment description.
    comparison = SequenceMatcher(None, source, quoted, autojunk=False)
    edits = sum(
        max(right - left, other_right - other_left)
        for tag, left, right, other_left, other_right in comparison.get_opcodes()
        if tag != "equal"
    )
    return edits <= 2 and comparison.ratio() >= 0.97


def _extra_credit_members(
    summary: CandidateEvent, events: list[CandidateEvent], source_text: str
) -> tuple[list[int], str | None]:
    title_match = _EXTRA_SUMMARY.match(summary.title)
    quote_match = _EXTRA_SUMMARY.search(summary.source_quote)
    if (
        not title_match
        or not quote_match
        or quote_match[1] is None
        or title_match[1] not in (None, quote_match[1])
        or summary.event_type != "assignment"
        or summary.event_date is None
    ):
        return [], None
    suffix = summary.title[title_match.end():]
    if not re.fullmatch(r"(?:\s+due)?(?:\s*\([^)]*\))?\s*[.!:]*", suffix, re.I):
        return [], None
    count = int(quote_match[1])
    if not 1 <= count <= 20:
        return [], None
    lines = [line.strip() for line in source_text.splitlines() if line.strip()]
    header_indexes = [
        index for index, line in enumerate(lines)
        if (header_match := _EXTRA_SUMMARY.match(line))
        and header_match[1] == quote_match[1]
        and re.search(r"\bdue\b", line, re.I)
        and _matches_summary_heading(line, summary.source_quote[quote_match.start():])
    ]
    if len(header_indexes) != 1:
        return [], None

    # Read only the immediate item list below this heading, never other same-day tasks.
    child_lines: list[str] = []
    references: set[tuple[str, int]] = set()
    for line in lines[header_indexes[0] + 1:header_indexes[0] + count + 1]:
        line_references = _item_references(line)
        if not line_references or not re.search(r"\bdue\b", line, re.I):
            break
        references.update(line_references)
        child_lines.append(line)
        if len(references) >= count:
            break
    if len(references) != count:
        return [], None
    member_indexes: list[int] = []
    for kind, number in sorted(references):
        matches = [
            index for index, candidate in enumerate(events)
            if _item_references(candidate.title) == {(kind, number)}
            and candidate.event_type == ("quiz" if kind == "quiz" else "assignment")
            and candidate.source_page == summary.source_page
            and candidate.event_date == summary.event_date
            and (
                summary.start_time is None
                or candidate.start_time is not None
                and summary.start_time.replace(tzinfo=None)
                == candidate.start_time.replace(tzinfo=None)
            )
            and (
                summary.end_time is None
                or candidate.end_time is not None
                and summary.end_time.replace(tzinfo=None) == candidate.end_time.replace(tzinfo=None)
            )
            and any(
                _normalized(line.lstrip("•‹*- ")) in _normalized(candidate.source_quote)
                for line in child_lines
            )
        ]
        if len(matches) != 1:
            return [], None
        member_indexes.extend(matches)
    return member_indexes, lines[header_indexes[0]]


def _weekly_homework_members(
    summary: CandidateEvent, events: list[CandidateEvent], pages: dict[int, str]
) -> list[int]:
    if (
        not _WEEKLY_TITLE.fullmatch(summary.title.strip())
        or summary.event_type != "assignment"
        or summary.event_date is not None
        or summary.start_time is not None
        or summary.end_time is not None
        or summary.recurring_series_id is not None
        or _ADDITIONAL.search(summary.source_quote)
        or not re.search(r"\b(?:weekly|every week|each week)\b", summary.source_quote, re.I)
    ):
        return []
    quote = _normalized(summary.source_quote)
    page = _normalized(pages.get(summary.source_page, ""))
    quote_start = page.find(quote)
    if quote_start < 0 or not re.search(
        r"\bhomework(?:\s*\([^)]*\))?\s*[•‹*\-]*\s*$", page[:quote_start]
    ):
        return []

    policy_context = page[max(0, quote_start - 100):quote_start + len(quote) + 200]
    if _ADDITIONAL.search(policy_context):
        return []

    # Consecutive published numbers cannot prove the full semester inventory.
    # Require an explicit total before removing an otherwise useful weekly rule.
    full_text = "\n".join(pages.values())
    totals = re.findall(
        r"\b(?:there\s+(?:are|will be)|a total of)\s+(\d+)\s+homework"
        r"(?:\s+assignments)?\b", full_text, re.I,
    )
    if len(set(totals)) != 1:
        return []
    numbers = {
        int(number) for page_text in pages.values() for number in _HOMEWORK.findall(page_text)
    }
    expected_count = int(totals[0])
    if (
        expected_count < 2 or expected_count > 200
        or numbers != set(range(1, expected_count + 1))
    ):
        return []
    if re.search(
        r"\bhomework\b[^.\n]*\b(?:announced|unpublished|later|TBA)\b", full_text, re.I,
    ):
        return []
    members: list[int] = []
    for number in sorted(numbers):
        matches = [
            index for index, candidate in enumerate(events)
            if candidate.event_type == "assignment"
            and _item_references(candidate.title) == {("homework", number)}
            and ("homework", number) in _item_references(candidate.source_quote)
            and ("homework", number) in _item_references(pages.get(candidate.source_page, ""))
        ]
        if len(matches) != 1:
            return []
        members.extend(matches)
    return members


def deduplicate_summary_events(
    events: list[CandidateEvent], pages: list[dict]
) -> tuple[list[CandidateEvent], dict[int, int]]:
    """Collapse proven parent summaries within one course/document extraction.

    The index map contains retained original indexes only, so callers can remap
    per-event validation flags. No inference is made across courses or documents.
    Source quotes and review status are retained, and source policy is copied to
    each concrete item's derivation rather than silently discarded.
    """
    page_text = {page["page"]: page["text"] for page in pages}
    removed: set[int] = set()
    annotations: dict[int, list[str]] = {}
    for index, summary in enumerate(events):
        members, verified_quote = _extra_credit_members(
            summary, events, page_text.get(summary.source_page, "")
        )
        label = "Extra Credit source summary"
        if not members:
            members = _weekly_homework_members(summary, events, page_text)
            label = "Homework policy"
            verified_quote = summary.source_quote
        if not members:
            continue
        removed.add(index)
        note = f"{label} on page {summary.source_page}: {verified_quote}"
        for member in members:
            annotations.setdefault(member, []).append(note)

    kept: list[CandidateEvent] = []
    index_map: dict[int, int] = {}
    for index, candidate in enumerate(events):
        if index in removed:
            continue
        index_map[index] = len(kept)
        notes = [candidate.derivation_summary] if candidate.derivation_summary else []
        for note in annotations.get(index, []):
            if not any(note in existing for existing in notes):
                notes.append(note)
        kept.append(
            candidate.model_copy(update={"derivation_summary": " ".join(notes)})
            if index in annotations else candidate
        )
    return kept, index_map
