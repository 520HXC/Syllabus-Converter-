from __future__ import annotations

import re
from collections.abc import Callable, Collection
from datetime import UTC, date, datetime, time
from typing import Literal
from uuid import UUID, uuid4

import pymupdf
import pytesseract
from dateutil import parser as date_parser
from openai import OpenAI
from pdf2image import convert_from_bytes
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from .config import Settings, get_settings
from .database import configure_database
from .models import (
    ConfidenceLevel,
    Course,
    ExtractedEvent,
    JobStatus,
    ProcessingJob,
    RecurringEventSeries,
    ReviewStatus,
    SyllabusDocument,
)
from .storage import StorageService

COURSE_COLORS = ["#0D9488", "#2563EB", "#7C3AED", "#DB2777", "#D97706", "#059669"]
RETRYABLE_TERRA_CODES = {
    "LOW_CONFIDENCE",
    "SOURCE_MISMATCH",
    "SOURCE_PAGE_MISSING",
    "DATE_CONFLICT",
    "RECURRING_RULE_MISSING",
}
RETRYABLE_TERRA_CODE_ORDER = {
    "LOW_CONFIDENCE": 0,
    "SOURCE_MISMATCH": 1,
    "SOURCE_PAGE_MISSING": 2,
    "DATE_CONFLICT": 3,
    "RECURRING_RULE_MISSING": 4,
    "TERRA_RETRY_FAILED": 5,
}
AMBIGUOUS_RECURRENCE_PATTERN = re.compile(
    r"\b(?:nearly every|usually|periodically)\b",
    re.IGNORECASE,
)
AMBIGUOUS_MODAL_MAY_PATTERN = re.compile(
    r"\bmay\s+(?:occur|be scheduled|start|include|change)\b",
    re.IGNORECASE,
)
RELATIVE_REVIEW_ONLY_PATTERN = re.compile(
    r"\b(?:the\s+)?morning\s+(?:of|after)\s+(?:the\s+)?lecture\b|"
    r"\bsunday\s+(?:that\s+)?follow(?:s|ing)\s+(?:the\s+)?lab\b",
    re.IGNORECASE,
)
DETERMINISTIC_RECURRING_RULE_PATTERN = re.compile(
    r"(?P<title>[A-Za-z0-9 &/\-]{1,120}?)\s+"
    r"(?:(?:is|are)\s+)?"
    r"(?P<action>due|scheduled)\s+"
    r"(?P<cue>every\b|each\s+week\b|weekly\b)",
    re.IGNORECASE,
)


def resolve_recurring_series_id(
    candidate: CandidateEvent,
    known_series_ids: Collection[UUID],
) -> UUID | None:
    if candidate.recurring_series_id in known_series_ids:
        return candidate.recurring_series_id
    return None
WEEKDAY_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class CandidateEvent(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    event_type: Literal[
        "assignment", "exam", "quiz", "project", "reading", "class", "deadline", "other"
    ]
    event_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    is_all_day: bool = True
    source_quote: str = Field(min_length=1)
    source_page: int = Field(ge=1)
    confidence: ConfidenceLevel
    year_was_explicit: bool
    uncertainty_reason: str | None = None
    recurring_series_id: UUID | None = None
    extraction_model: str | None = None
    derivation_summary: str | None = None
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW


class ScheduleOccurrence(BaseModel):
    occurrence_date: date
    title: str = Field(min_length=1, max_length=240)
    anchor_type: Literal["lecture", "lab", "discussion", "class", "other"] = "class"
    source_quote: str = Field(min_length=1)
    source_page: int = Field(ge=1)


class ScheduleAnchor(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    anchor_type: Literal["lecture", "lab", "discussion", "class", "other"] = "class"
    weekday: Literal[
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
    ]
    start_time: time | None = None
    end_time: time | None = None
    boundary_start: date | None = None
    boundary_end: date | None = None
    exclusion_dates: list[date] = Field(default_factory=list)
    source_quote: str = Field(min_length=1)
    source_page: int = Field(ge=1)
    occurrences: list[ScheduleOccurrence] = Field(default_factory=list)


class RecurringRule(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    event_type: Literal[
        "assignment", "exam", "quiz", "project", "reading", "class", "deadline", "other"
    ]
    rule_kind: Literal["weekly_fixed", "relative_to_anchor"]
    weekday: Literal[
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
    ] | None = None
    start_time: time | None = None
    end_time: time | None = None
    is_all_day: bool = True
    boundary_start: date | None = None
    boundary_end: date | None = None
    exclusion_dates: list[date] = Field(default_factory=list)
    source_quote: str = Field(min_length=1)
    source_page: int = Field(ge=1)
    confidence: ConfidenceLevel
    anchor_title: str | None = None
    offset_days: int | None = None
    uncertainty_reason: str | None = None
    extraction_model: str | None = None
    expansion_mode: Literal["exact", "review_only"] = "exact"


class ExpandedRecurringSeries(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    title: str
    event_type: str
    rule_kind: str
    rule_summary: str
    source_quote: str
    source_page: int
    anchor_sources: list[dict] = Field(default_factory=list)
    rule_payload: dict = Field(default_factory=dict)
    confidence: ConfidenceLevel
    warning_codes: list[str] = Field(default_factory=list)
    warning_reason: str | None = None
    extraction_model: str | None = None
    fallback_reason_codes: list[str] = Field(default_factory=list)
    occurrence_count: int


class SyllabusRepair(BaseModel):
    course_code: str | None = None
    course_name: str | None = None
    instructor: str | None = None
    events: list[CandidateEvent] = Field(default_factory=list)
    schedule_anchors: list[ScheduleAnchor] = Field(default_factory=list)
    recurring_rules: list[RecurringRule] = Field(default_factory=list)


class StructuredExtractionError(RuntimeError):
    pass


class SyllabusExtraction(BaseModel):
    course_code: str | None = None
    course_name: str = Field(min_length=1, max_length=200)
    instructor: str | None = None
    events: list[CandidateEvent] = Field(default_factory=list)
    schedule_anchors: list[ScheduleAnchor] = Field(default_factory=list)
    recurring_rules: list[RecurringRule] = Field(default_factory=list)


def ocr_pdf_page(content: bytes, page_number: int, settings: Settings) -> str:
    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    try:
        images = convert_from_bytes(
            content,
            first_page=page_number,
            last_page=page_number,
            dpi=220,
            poppler_path=settings.pdf_poppler_path,
        )
        if not images:
            return ""
        return pytesseract.image_to_string(images[0]).strip()
    except Exception as error:
        raise RuntimeError(
            "OCR could not run. Install Tesseract and Poppler, then retry this file."
        ) from error


def extract_pdf_pages(
    content: bytes,
    min_text_characters: int,
    settings: Settings | None = None,
    on_ocr_start: Callable[[int], None] | None = None,
) -> tuple[list[dict], bool]:
    settings = settings or get_settings()
    pages: list[dict] = []
    used_ocr = False
    try:
        document = pymupdf.open(stream=content, filetype="pdf")
    except Exception as error:
        raise ValueError("The uploaded file could not be opened as a PDF.") from error

    try:
        if document.page_count > settings.max_pdf_pages:
            raise ValueError(
                f"The PDF has more than {settings.max_pdf_pages} pages and cannot be processed."
            )
        ocr_page_count = 0
        extracted_character_count = 0
        for index, page in enumerate(document):
            page_number = index + 1
            embedded_text = page.get_text("text").strip()
            if len(embedded_text) >= min_text_characters:
                page_text = embedded_text
                used_page_ocr = False
            else:
                if ocr_page_count >= settings.max_ocr_pages:
                    page_word = "page" if settings.max_ocr_pages == 1 else "pages"
                    raise ValueError(
                        f"OCR is limited to {settings.max_ocr_pages} {page_word} per PDF."
                    )
                if on_ocr_start:
                    on_ocr_start(page_number)
                page_text = ocr_pdf_page(content, page_number, settings)
                used_page_ocr = True
                used_ocr = True
                ocr_page_count += 1
            extracted_character_count += len(page_text)
            if extracted_character_count > settings.max_extracted_text_characters:
                raise ValueError(
                    "The PDF contains more than "
                    f"{settings.max_extracted_text_characters} characters of extracted text."
                )
            pages.append({"page": page_number, "text": page_text, "ocr": used_page_ocr})
    finally:
        document.close()

    if not any(page["text"].strip() for page in pages):
        raise ValueError("No readable text was found in this PDF.")
    return pages, used_ocr


def _pages_for_prompt(pages: list[dict]) -> str:
    return "\n\n".join(f"[Page {page['page']}]\n{page['text']}" for page in pages)


def _parse_with_openai(
    pages: list[dict],
    settings: Settings,
    *,
    model: str,
    instructions: str,
    text_format: type[BaseModel],
):
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required when EXTRACTION_MODE is openai.")
    client = OpenAI(api_key=settings.openai_api_key)
    try:
        response = client.responses.parse(
            model=model,
            instructions=instructions,
            input=_pages_for_prompt(pages),
            text_format=text_format,
            store=False,
        )
    except ValidationError as error:
        raise StructuredExtractionError(
            "OpenAI did not return a structured syllabus extraction."
        ) from error
    if response.output_parsed is None:
        raise StructuredExtractionError("OpenAI did not return a structured syllabus extraction.")
    return response.output_parsed


def extract_with_openai(
    pages: list[dict],
    settings: Settings,
    *,
    model: str | None = None,
) -> SyllabusExtraction:
    return _parse_with_openai(
        pages,
        settings,
        model=model or settings.openai_model,
        instructions=(
            "Extract the course identity and every assessment, deadline, cancellation, "
            "or other exceptional date that belongs on a student's calendar. "
            "Do not include routine class meetings, lecture topics, office hours, or readings. "
            "Keep important items whose date is not published yet and set event_date to null. "
            "Extract schedule_anchors for recurring lectures, labs, or discussions. "
            "When the syllabus lists irregular explicit meeting rows or dates for an anchor, "
            "populate ScheduleOccurrence entries on that anchor with occurrence_date, title, "
            "anchor_type, source_quote, and source_page. "
            "Extract recurring_rules for weekly fixed rules and rules that are relative to "
            "a lecture or lab anchor. Set expansion_mode review_only when recurrence wording "
            "is ambiguous or when a relative phrase like morning of the lecture, morning after "
            "the lecture, or Sunday following the lab does not identify every occurrence. "
            "Otherwise use expansion_mode exact. Use the page markers for source_page. Copy a short exact "
            "source_quote. Do not invent dates. "
            "Mark whether the source explicitly states the year. "
            "Use low confidence and explain uncertainty whenever wording is tentative "
            "or conflicting."
        ),
        text_format=SyllabusExtraction,
    )


MONTH_PATTERN = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
EVENT_PATTERN = re.compile(
    rf"(?P<title>[^\n.]{{0,100}}?(?:midterm|final|exam|quiz|assignment|project|paper|"
    rf"presentation|homework)[^\n.]{{0,80}}?)\s+(?:is\s+)?(?:due\s+|on\s+|scheduled\s+)?"
    rf"(?P<date>{MONTH_PATTERN}\s+\d{{1,2}}(?:,?\s+\d{{4}})?)",
    re.IGNORECASE,
)
RECURRING_WEEKLY_PATTERN = re.compile(
    rf"(?P<title>[A-Za-z0-9 &/\-]+?)\s+due\s+every\s+"
    rf"(?P<weekday>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
    rf"from\s+(?P<start>{MONTH_PATTERN}\s+\d{{1,2}},\s+\d{{4}})\s+"
    rf"through\s+(?P<end>{MONTH_PATTERN}\s+\d{{1,2}},\s+\d{{4}})"
    rf"(?:\s+except\s+(?P<exceptions>[^.\n]+))?",
    re.IGNORECASE,
)
DATE_TEXT_PATTERN = re.compile(rf"{MONTH_PATTERN}\s+\d{{1,2}},\s+\d{{4}}", re.IGNORECASE)


def extract_locally(pages: list[dict]) -> SyllabusExtraction:
    full_text = "\n".join(page["text"] for page in pages)
    course_match = re.search(r"\b([A-Z]{2,5})\s*[- ]?\s*(\d{2,4}[A-Z]?)\b", full_text)
    course_code = f"{course_match.group(1)} {course_match.group(2)}" if course_match else None
    first_line = next((line.strip() for line in full_text.splitlines() if line.strip()), "Course")
    course_name = first_line[:200]
    instructor_match = re.search(r"(?:Instructor|Professor)\s*[:\-]\s*([^\n]+)", full_text, re.I)
    events: list[CandidateEvent] = []
    recurring_rules: list[RecurringRule] = []

    for page in pages:
        recurring_spans: list[tuple[int, int]] = []
        for match in RECURRING_WEEKLY_PATTERN.finditer(page["text"]):
            recurring_spans.append(match.span())
            title = re.sub(r"\s+", " ", match.group("title")).strip(" :-")
            weekday = match.group("weekday").casefold()
            boundary_start = date_parser.parse(match.group("start"), fuzzy=True).date()
            boundary_end = date_parser.parse(match.group("end"), fuzzy=True).date()
            exceptions_raw = match.group("exceptions") or ""
            exclusion_dates = [
                date_parser.parse(item.group(0), fuzzy=True).date()
                for item in DATE_TEXT_PATTERN.finditer(exceptions_raw)
            ]
            recurring_rules.append(
                RecurringRule(
                    title=title,
                    event_type="assignment",
                    rule_kind="weekly_fixed",
                    weekday=weekday,
                    start_time=None,
                    end_time=None,
                    is_all_day=True,
                    boundary_start=boundary_start,
                    boundary_end=boundary_end,
                    exclusion_dates=exclusion_dates,
                    source_quote=re.sub(r"\s+", " ", match.group(0)).strip(),
                    source_page=page["page"],
                    confidence="medium",
                    uncertainty_reason=None,
                )
            )
        for match in EVENT_PATTERN.finditer(page["text"]):
            if any(start <= match.start() and match.end() <= end for start, end in recurring_spans):
                continue
            date_text = match.group("date")
            explicit_year = bool(re.search(r"\b\d{4}\b", date_text))
            parsed = date_parser.parse(date_text, fuzzy=True).date()
            raw_title = re.sub(r"\s+", " ", match.group("title")).strip(" :-")
            title = raw_title[-120:] or "Syllabus event"
            lowered = title.lower()
            if "quiz" in lowered:
                event_type = "quiz"
            elif any(word in lowered for word in ("exam", "midterm", "final")):
                event_type = "exam"
            elif "project" in lowered:
                event_type = "project"
            else:
                event_type = "assignment"
            source_quote = re.sub(r"\s+", " ", match.group(0)).strip()
            uncertain = bool(
                re.search(r"\b(?:around|tentative|tbd|approximately)\b", source_quote, re.I)
            )
            events.append(
                CandidateEvent(
                    title=title,
                    event_type=event_type,
                    event_date=parsed,
                    is_all_day=True,
                    source_quote=source_quote,
                    source_page=page["page"],
                    confidence="low" if uncertain or not explicit_year else "medium",
                    year_was_explicit=explicit_year,
                    uncertainty_reason="The date wording is tentative." if uncertain else None,
                )
            )

    return SyllabusExtraction(
        course_code=course_code,
        course_name=course_name,
        instructor=instructor_match.group(1).strip()[:160] if instructor_match else None,
        events=events,
        recurring_rules=recurring_rules,
    )


def extract_syllabus(pages: list[dict], settings: Settings) -> SyllabusExtraction:
    if settings.extraction_mode == "openai":
        return extract_with_openai(pages, settings)
    return extract_locally(pages)


def _ordered_unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _ordered_retryable_codes(items: list[str]) -> list[str]:
    return sorted(
        _ordered_unique(items),
        key=lambda item: (RETRYABLE_TERRA_CODE_ORDER.get(item, 99), item),
    )


def _rule_summary(rule: RecurringRule) -> str:
    if rule.rule_kind == "weekly_fixed":
        return f"Every {rule.weekday} between {rule.boundary_start} and {rule.boundary_end}"
    offset = rule.offset_days or 0
    anchor_title = rule.anchor_title or "anchor"
    return f"{offset} day(s) after {anchor_title}"


def _validate_rule(rule: RecurringRule, pages: list[dict]) -> tuple[list[str], str | None]:
    codes: list[str] = []
    reasons: list[str] = []
    source_page = next((page for page in pages if page["page"] == rule.source_page), None)
    if source_page is None:
        codes.append("SOURCE_PAGE_MISSING")
        reasons.append("The cited source page does not exist in the extracted document.")
    elif _normalize_evidence(rule.source_quote) not in _normalize_evidence(source_page["text"]):
        codes.append("SOURCE_MISMATCH")
        reasons.append("The source quote could not be matched to the cited page.")
    if rule.confidence == ConfidenceLevel.LOW:
        codes.append("LOW_CONFIDENCE")
        reasons.append(rule.uncertainty_reason or "The extraction has low confidence.")
    elif rule.uncertainty_reason:
        codes.append("MODEL_UNCERTAINTY")
        reasons.append(rule.uncertainty_reason)
    return codes, " ".join(dict.fromkeys(reasons)) or None


def _apply_extraction_model(extraction: SyllabusExtraction | SyllabusRepair, model: str) -> None:
    for candidate in extraction.events:
        candidate.extraction_model = model
    for rule in extraction.recurring_rules:
        rule.extraction_model = model


def _anchor_occurrences(
    anchor: ScheduleAnchor,
    semester_start: date,
    semester_end: date,
) -> list[date]:
    range_start = max(semester_start, anchor.boundary_start or semester_start)
    range_end = min(semester_end, anchor.boundary_end or semester_end)
    if range_start > range_end:
        return []
    exclusions = set(anchor.exclusion_dates)
    explicit_dates = sorted(
        {
            occurrence.occurrence_date
            for occurrence in anchor.occurrences
            if occurrence.anchor_type == anchor.anchor_type
            and range_start <= occurrence.occurrence_date <= range_end
            and occurrence.occurrence_date not in exclusions
        }
    )
    if explicit_dates:
        return explicit_dates

    range_start = max(semester_start, anchor.boundary_start or semester_start)
    range_end = min(semester_end, anchor.boundary_end or semester_end)
    if range_start > range_end:
        return []
    current = range_start
    while current.weekday() != WEEKDAY_INDEX[anchor.weekday]:
        current = current.fromordinal(current.toordinal() + 1)
    exclusions = set(anchor.exclusion_dates)
    occurrences: list[date] = []
    while current <= range_end:
        if current not in exclusions:
            occurrences.append(current)
        current = current.fromordinal(current.toordinal() + 7)
    return occurrences


def _weekly_occurrences(
    weekday: str,
    range_start: date,
    range_end: date,
    exclusion_dates: list[date],
) -> list[date]:
    if range_start > range_end:
        return []
    current = range_start
    while current.weekday() != WEEKDAY_INDEX[weekday]:
        current = current.fromordinal(current.toordinal() + 1)
    exclusions = set(exclusion_dates)
    occurrences: list[date] = []
    while current <= range_end:
        if current not in exclusions:
            occurrences.append(current)
        current = current.fromordinal(current.toordinal() + 7)
    return occurrences


def _build_rule_payload(rule: RecurringRule) -> dict:
    return {
        "weekday": rule.weekday,
        "boundary_start": rule.boundary_start.isoformat() if rule.boundary_start else None,
        "boundary_end": rule.boundary_end.isoformat() if rule.boundary_end else None,
        "exclusion_dates": [item.isoformat() for item in rule.exclusion_dates],
        "start_time": rule.start_time.isoformat() if rule.start_time else None,
        "end_time": rule.end_time.isoformat() if rule.end_time else None,
        "is_all_day": rule.is_all_day,
        "anchor_title": rule.anchor_title,
        "offset_days": rule.offset_days,
        "expansion_mode": rule.expansion_mode,
    }


def _stable_title_key(value: str) -> str:
    tokens = re.sub(r"\s+", " ", value).strip(" :-").split()
    while tokens and tokens[-1].casefold() in {"is", "are", "due", "scheduled"}:
        tokens.pop()
    return " ".join(tokens).casefold()


def _display_title(value: str) -> str:
    tokens = re.sub(r"\s+", " ", value).strip(" :-").split()
    while tokens and tokens[-1].casefold() in {"is", "are", "due", "scheduled"}:
        tokens.pop()
    return " ".join(tokens).strip() or value.strip()


def _is_ambiguous_recurrence_text(value: str) -> bool:
    return bool(
        AMBIGUOUS_RECURRENCE_PATTERN.search(value)
        or AMBIGUOUS_MODAL_MAY_PATTERN.search(value)
    )


def _cap_confidence_for_ambiguous_recurrence(confidence: ConfidenceLevel) -> ConfidenceLevel:
    if confidence == ConfidenceLevel.HIGH:
        return ConfidenceLevel.MEDIUM
    return confidence


def _page_text(source_page: int, pages: list[dict]) -> str:
    return next((page["text"] for page in pages if page["page"] == source_page), "")


def _rule_requires_review_only(rule: RecurringRule, pages: list[dict]) -> bool:
    page_text = _page_text(rule.source_page, pages)
    has_relative_phrase = bool(
        RELATIVE_REVIEW_ONLY_PATTERN.search(rule.source_quote)
        or RELATIVE_REVIEW_ONLY_PATTERN.search(page_text)
    )
    if rule.expansion_mode == "review_only":
        return True
    if _is_ambiguous_recurrence_text(rule.source_quote):
        return True
    if rule.rule_kind == "relative_to_anchor" and has_relative_phrase:
        return True
    if has_relative_phrase and _is_ambiguous_recurrence_text(page_text):
        return True
    if _is_ambiguous_recurrence_text(page_text) and rule.rule_kind == "weekly_fixed":
        return True
    return False


def _event_requires_review_only(event: CandidateEvent, pages: list[dict]) -> bool:
    page_text = _page_text(event.source_page, pages)
    has_relative_phrase = bool(
        RELATIVE_REVIEW_ONLY_PATTERN.search(event.source_quote)
        or RELATIVE_REVIEW_ONLY_PATTERN.search(page_text)
    )
    return bool(
        _is_ambiguous_recurrence_text(event.source_quote)
        or has_relative_phrase
        or (has_relative_phrase and _is_ambiguous_recurrence_text(page_text))
    )


def _normalize_ambiguous_recurring_content(
    extraction: SyllabusExtraction,
    pages: list[dict],
) -> tuple[SyllabusExtraction, set[int], str]:
    events = [event.model_copy(deep=True) for event in extraction.events]
    rules = [rule.model_copy(deep=True) for rule in extraction.recurring_rules]
    normalized_event_indexes: set[int] = set()
    ambiguous_reason = (
        "The syllabus uses ambiguous recurrence wording, so exact dates were not generated."
    )
    derivation_summary = (
        "Dates were not generated because the syllabus does not identify every occurrence."
    )

    def normalize_event(event: CandidateEvent) -> CandidateEvent:
        return event.model_copy(
            update={
                "title": _display_title(event.title),
                "event_date": None,
                "recurring_series_id": None,
                "confidence": _cap_confidence_for_ambiguous_recurrence(event.confidence),
                "derivation_summary": derivation_summary,
                "review_status": ReviewStatus.NEEDS_REVIEW,
            }
        )

    for rule_index, rule in enumerate(rules):
        if not _rule_requires_review_only(rule, pages):
            continue
        stable_rule_title = _stable_title_key(rule.title)
        rules[rule_index] = rule.model_copy(
            update={
                "title": _display_title(rule.title),
                "expansion_mode": "review_only",
                "confidence": _cap_confidence_for_ambiguous_recurrence(rule.confidence),
            }
        )
        event_index = next(
            (
                index
                for index, event in enumerate(events)
                if _stable_title_key(event.title) == stable_rule_title
            ),
            None,
        )
        if event_index is None:
            events.append(
                CandidateEvent(
                    title=_display_title(rule.title),
                    event_type=rule.event_type,
                    event_date=None,
                    start_time=rule.start_time,
                    end_time=rule.end_time,
                    is_all_day=rule.is_all_day,
                    source_quote=rule.source_quote,
                    source_page=rule.source_page,
                    confidence=_cap_confidence_for_ambiguous_recurrence(rule.confidence),
                    year_was_explicit=True,
                    uncertainty_reason=rule.uncertainty_reason,
                    extraction_model=rule.extraction_model,
                    derivation_summary=derivation_summary,
                    review_status=ReviewStatus.NEEDS_REVIEW,
                )
            )
            normalized_event_indexes.add(len(events) - 1)
        else:
            events[event_index] = normalize_event(events[event_index])
            normalized_event_indexes.add(event_index)

    for index, event in enumerate(events):
        if event.event_date is None and _event_requires_review_only(event, pages):
            events[index] = normalize_event(event)
            normalized_event_indexes.add(index)

    return (
        SyllabusExtraction(
            course_code=extraction.course_code,
            course_name=extraction.course_name,
            instructor=extraction.instructor,
            events=events,
            schedule_anchors=[anchor.model_copy(deep=True) for anchor in extraction.schedule_anchors],
            recurring_rules=rules,
        ),
        normalized_event_indexes,
        ambiguous_reason,
    )


def _detect_missing_recurring_rule(
    extraction: SyllabusExtraction | SyllabusRepair,
    pages: list[dict],
) -> list[str]:
    return [item["stable_title"] for item in _find_missing_recurring_rule_candidates(extraction, pages)]


def _find_missing_recurring_rule_candidates(
    extraction: SyllabusExtraction | SyllabusRepair,
    pages: list[dict],
) -> list[dict]:
    existing_rule_titles = {_stable_title_key(rule.title) for rule in extraction.recurring_rules}
    existing_event_titles = {
        _stable_title_key(event.title)
        for event in extraction.events
        if event.event_date is not None
    }
    missing_candidates: list[dict] = []
    seen_titles: set[str] = set()

    for page in pages:
        for raw_segment in re.split(r"[\n.]+", page["text"]):
            segment = raw_segment.strip()
            if (
                not segment
                or _is_ambiguous_recurrence_text(segment)
                or RELATIVE_REVIEW_ONLY_PATTERN.search(segment)
            ):
                continue
            match = DETERMINISTIC_RECURRING_RULE_PATTERN.search(segment)
            if match is None:
                continue
            title = _display_title(match.group("title"))
            stable_title = _stable_title_key(title)
            if not stable_title:
                continue
            if (
                stable_title in existing_rule_titles
                or stable_title in existing_event_titles
                or stable_title in seen_titles
            ):
                continue
            missing_candidates.append(
                {
                    "title": title,
                    "stable_title": stable_title,
                    "source_quote": re.sub(r"\s+", " ", segment).strip(),
                    "source_page": page["page"],
                }
            )
            seen_titles.add(stable_title)

    return missing_candidates


def expand_recurring_rules(
    *,
    anchors: list[ScheduleAnchor],
    rules: list[RecurringRule],
    semester_start: date,
    semester_end: date,
    explicit_events: list[CandidateEvent],
    extraction_model: str | None,
    max_occurrences: int = 200,
) -> tuple[list[ExpandedRecurringSeries], list[CandidateEvent]]:
    explicit_keys = {
        (_normalize_title(event.title), event.event_date)
        for event in explicit_events
        if event.event_date is not None
    }
    anchor_map = {_normalize_title(anchor.title): anchor for anchor in anchors}
    series_payloads: list[ExpandedRecurringSeries] = []
    derived_events: list[CandidateEvent] = []

    for rule in rules:
        if rule.expansion_mode == "review_only":
            continue
        range_start = max(semester_start, rule.boundary_start or semester_start)
        range_end = min(semester_end, rule.boundary_end or semester_end)
        if range_start > range_end:
            continue
        if rule.rule_kind == "weekly_fixed":
            if rule.weekday is None:
                continue
            occurrence_dates = _weekly_occurrences(
                rule.weekday,
                range_start,
                range_end,
                rule.exclusion_dates,
            )
            anchor_sources: list[dict] = []
        else:
            if rule.anchor_title is None or rule.offset_days is None:
                continue
            anchor = anchor_map.get(_normalize_title(rule.anchor_title))
            if anchor is None:
                continue
            anchor_sources = [
                {
                    "title": anchor.title,
                    "anchor_type": anchor.anchor_type,
                    "weekday": anchor.weekday,
                    "start_time": anchor.start_time.isoformat() if anchor.start_time else None,
                    "end_time": anchor.end_time.isoformat() if anchor.end_time else None,
                    "boundary_start": anchor.boundary_start.isoformat()
                    if anchor.boundary_start
                    else None,
                    "boundary_end": anchor.boundary_end.isoformat()
                    if anchor.boundary_end
                    else None,
                    "exclusion_dates": [item.isoformat() for item in anchor.exclusion_dates],
                    "source_quote": anchor.source_quote,
                    "source_page": anchor.source_page,
                    "occurrences": [
                        occurrence.model_dump(mode="json") for occurrence in anchor.occurrences
                    ],
                }
            ]
            occurrence_dates = []
            exclusions = set(rule.exclusion_dates)
            for anchor_date in _anchor_occurrences(anchor, semester_start, semester_end):
                derived_date = anchor_date.fromordinal(anchor_date.toordinal() + rule.offset_days)
                if range_start <= derived_date <= range_end and derived_date not in exclusions:
                    occurrence_dates.append(derived_date)

        deduped_dates: list[date] = []
        seen_dates: set[date] = set()
        for occurrence_date in occurrence_dates:
            key = (_normalize_title(rule.title), occurrence_date)
            if key in explicit_keys or occurrence_date in seen_dates:
                continue
            seen_dates.add(occurrence_date)
            deduped_dates.append(occurrence_date)
        if not deduped_dates:
            continue
        truncated = False
        if len(deduped_dates) > max_occurrences:
            deduped_dates = deduped_dates[:max_occurrences]
            truncated = True

        series_id = uuid4()
        summary = _rule_summary(rule)
        warning_codes: list[str] = []
        warning_reason: str | None = None
        if truncated:
            warning_codes.append("RECURRING_TRUNCATED")
            warning_reason = (
                f"Only the first {max_occurrences} occurrences "
                "were generated for this recurring rule."
            )
        series_payloads.append(
            ExpandedRecurringSeries(
                id=series_id,
                title=rule.title,
                event_type=rule.event_type,
                rule_kind=rule.rule_kind,
                rule_summary=summary,
                source_quote=rule.source_quote,
                source_page=rule.source_page,
                anchor_sources=anchor_sources,
                rule_payload=_build_rule_payload(rule),
                confidence=rule.confidence,
                warning_codes=warning_codes,
                warning_reason=warning_reason,
                extraction_model=rule.extraction_model or extraction_model,
                occurrence_count=len(deduped_dates),
            )
        )
        for occurrence_date in deduped_dates:
            derived_events.append(
                CandidateEvent(
                    title=rule.title,
                    event_type=rule.event_type,
                    event_date=occurrence_date,
                    start_time=rule.start_time,
                    end_time=rule.end_time,
                    is_all_day=rule.is_all_day,
                    source_quote=rule.source_quote,
                    source_page=rule.source_page,
                    confidence=rule.confidence,
                    year_was_explicit=True,
                    uncertainty_reason=rule.uncertainty_reason,
                    recurring_series_id=series_id,
                    extraction_model=rule.extraction_model or extraction_model,
                    derivation_summary=summary,
                    review_status=ReviewStatus.NEEDS_REVIEW,
                )
            )

    return series_payloads, derived_events


def _preview_retryable_codes(
    extraction: SyllabusExtraction | SyllabusRepair,
    pages: list[dict],
    semester_start: date,
    semester_end: date,
    known_dates_by_title: dict[str, set[date]],
) -> tuple[list[str], set[int], set[int], dict[str, list[str]]]:
    retryable_codes: list[str] = []
    flagged_event_indexes: set[int] = set()
    flagged_reasons: dict[str, list[str]] = {"events": [], "rules": []}
    for index, candidate in enumerate(extraction.events):
        warning_codes, _ = validate_candidate(candidate, pages, semester_start, semester_end)
        if candidate.event_date is not None and detect_date_conflict(
            candidate.title,
            candidate.event_date,
            known_dates_by_title,
        ):
            warning_codes = [*warning_codes, "DATE_CONFLICT"]
        matched_codes = [code for code in warning_codes if code in RETRYABLE_TERRA_CODES]
        if matched_codes:
            flagged_event_indexes.add(index)
            retryable_codes.extend(matched_codes)
            flagged_reasons["events"].append(
                "event["
                f"{index}] title={candidate.title!r} "
                f"codes={_ordered_retryable_codes(matched_codes)}"
            )
    flagged_rule_indexes: set[int] = set()
    for index, rule in enumerate(extraction.recurring_rules):
        warning_codes, _ = _validate_rule(rule, pages)
        matched_codes = [code for code in warning_codes if code in RETRYABLE_TERRA_CODES]
        if matched_codes:
            flagged_rule_indexes.add(index)
            retryable_codes.extend(matched_codes)
            flagged_reasons["rules"].append(
                "rule["
                f"{index}] title={rule.title!r} "
                f"codes={_ordered_retryable_codes(matched_codes)}"
            )
    missing_titles = _detect_missing_recurring_rule(extraction, pages)
    if missing_titles:
        retryable_codes.append("RECURRING_RULE_MISSING")
        flagged_reasons["rules"].append(
            "missing recurring rules for titles="
            f"{missing_titles}"
        )
    return (
        _ordered_retryable_codes(retryable_codes),
        flagged_event_indexes,
        flagged_rule_indexes,
        flagged_reasons,
    )


def _repair_input(
    pages: list[dict],
    primary_extraction: SyllabusExtraction,
    flagged_event_indexes: set[int],
    flagged_rule_indexes: set[int],
    flagged_reasons: dict[str, list[str]],
) -> str:
    repair_context = {
        "luna_extraction": primary_extraction.model_dump(mode="json"),
        "flagged_event_indexes": sorted(flagged_event_indexes),
        "flagged_rule_indexes": sorted(flagged_rule_indexes),
        "flagged_reasons": flagged_reasons,
    }
    return (
        f"[LunaExtraction]\n{repair_context}\n\n"
        f"[FullDocument]\n{_pages_for_prompt(pages)}"
    )


def _parse_repair_with_openai(
    pages: list[dict],
    settings: Settings,
    primary_extraction: SyllabusExtraction,
    retryable_codes: list[str],
    flagged_event_indexes: set[int],
    flagged_rule_indexes: set[int],
    flagged_reasons: dict[str, list[str]],
) -> SyllabusRepair:
    repair_summary = ", ".join(retryable_codes)
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required when EXTRACTION_MODE is openai.")
    client = OpenAI(api_key=settings.openai_api_key)
    try:
        response = client.responses.parse(
            model=settings.openai_fallback_model,
            instructions=(
                "Repair only the extracted items that failed deterministic validation. "
                f"Focus on these warning codes {repair_summary}. "
                "Keep other validated Luna items unchanged. Explicitly recover missing "
                "schedule anchors or recurring rules when the validation notes say they are "
                "missing. Return only repaired events, schedule_anchors, and recurring_rules "
                "that should replace flagged items or add missing recurring data. "
                f"Flagged event indexes {sorted(flagged_event_indexes)}. "
                f"Flagged rule indexes {sorted(flagged_rule_indexes)}. "
                "Validation detail "
                f"events={flagged_reasons['events']} "
                f"rules={flagged_reasons['rules']}."
            ),
            input=_repair_input(
                pages,
                primary_extraction,
                flagged_event_indexes,
                flagged_rule_indexes,
                flagged_reasons,
            ),
            text_format=SyllabusRepair,
            store=False,
        )
    except ValidationError as error:
        raise StructuredExtractionError(
            "OpenAI did not return a structured syllabus extraction."
        ) from error
    if response.output_parsed is None:
        raise StructuredExtractionError("OpenAI did not return a structured syllabus extraction.")
    return response.output_parsed


def _merge_extractions(
    primary: SyllabusExtraction,
    repair: SyllabusRepair,
    flagged_event_indexes: set[int],
    flagged_rule_indexes: set[int],
) -> SyllabusExtraction:
    merged_events = [
        event.model_copy(deep=True)
        for index, event in enumerate(primary.events)
        if index not in flagged_event_indexes
    ]
    if repair.events:
        merged_events.extend(repair.events)
    else:
        merged_events.extend(
            primary.events[index].model_copy(deep=True) for index in sorted(flagged_event_indexes)
        )

    merged_rules = [
        rule.model_copy(deep=True)
        for index, rule in enumerate(primary.recurring_rules)
        if index not in flagged_rule_indexes
    ]
    if repair.recurring_rules:
        merged_rules.extend(repair.recurring_rules)
    else:
        merged_rules.extend(
            primary.recurring_rules[index].model_copy(deep=True)
            for index in sorted(flagged_rule_indexes)
        )

    merged_anchors = [anchor.model_copy(deep=True) for anchor in primary.schedule_anchors]
    anchor_indexes = {
        (_stable_title_key(anchor.title), anchor.anchor_type): index
        for index, anchor in enumerate(merged_anchors)
    }
    for anchor in repair.schedule_anchors:
        key = (_stable_title_key(anchor.title), anchor.anchor_type)
        if key in anchor_indexes:
            merged_anchors[anchor_indexes[key]] = anchor
        else:
            anchor_indexes[key] = len(merged_anchors)
            merged_anchors.append(anchor)
    return SyllabusExtraction(
        course_code=repair.course_code or primary.course_code,
        course_name=repair.course_name or primary.course_name,
        instructor=repair.instructor or primary.instructor,
        events=merged_events,
        schedule_anchors=merged_anchors,
        recurring_rules=merged_rules,
    )


def _extract_with_model_fallback(
    pages: list[dict],
    settings: Settings,
    semester_start: date,
    semester_end: date,
    known_dates_by_title: dict[str, set[date]],
) -> tuple[SyllabusExtraction, bool, list[str], set[tuple[str, date | None]]]:
    try:
        primary = extract_with_openai(pages, settings, model=settings.openai_model)
        _apply_extraction_model(primary, settings.openai_model)
    except StructuredExtractionError:
        fallback = extract_with_openai(pages, settings, model=settings.openai_fallback_model)
        _apply_extraction_model(fallback, settings.openai_fallback_model)
        return fallback, True, ["PRIMARY_PARSE_FAILED"], set()

    (
        retryable_codes,
        flagged_event_indexes,
        flagged_rule_indexes,
        flagged_reasons,
    ) = _preview_retryable_codes(
        primary,
        pages,
        semester_start,
        semester_end,
        known_dates_by_title,
    )
    if not retryable_codes:
        return primary, False, [], set()

    failed_repair_keys = {
        (_normalize_title(primary.events[index].title), primary.events[index].event_date)
        for index in flagged_event_indexes
    }
    try:
        repair = _parse_repair_with_openai(
            pages,
            settings,
            primary,
            retryable_codes,
            flagged_event_indexes,
            flagged_rule_indexes,
            flagged_reasons,
        )
        _apply_extraction_model(repair, settings.openai_fallback_model)
        merged = _merge_extractions(primary, repair, flagged_event_indexes, flagged_rule_indexes)
        unresolved_missing_candidates = _find_missing_recurring_rule_candidates(merged, pages)
        if not unresolved_missing_candidates:
            return merged, True, retryable_codes, set()
        merged_events = [event.model_copy(deep=True) for event in merged.events]
        failed_repair_keys: set[tuple[str, date | None]] = set()
        for candidate in unresolved_missing_candidates:
            event_index = next(
                (
                    index
                    for index, event in enumerate(merged_events)
                    if _stable_title_key(event.title) == candidate["stable_title"]
                    and event.event_date is None
                ),
                None,
            )
            if event_index is None:
                merged_events.append(
                    CandidateEvent(
                        title=candidate["title"],
                        event_type="assignment",
                        event_date=None,
                        start_time=None,
                        end_time=None,
                        is_all_day=True,
                        source_quote=candidate["source_quote"],
                        source_page=candidate["source_page"],
                        confidence="medium",
                        year_was_explicit=True,
                        uncertainty_reason=None,
                        extraction_model=settings.openai_fallback_model,
                        derivation_summary=(
                            "Dates were not generated because the syllabus does not identify every occurrence."
                        ),
                        review_status=ReviewStatus.NEEDS_REVIEW,
                    )
                )
                event_index = len(merged_events) - 1
            else:
                merged_events[event_index] = merged_events[event_index].model_copy(
                    update={
                        "title": candidate["title"],
                        "event_date": None,
                        "source_quote": candidate["source_quote"],
                        "source_page": candidate["source_page"],
                        "extraction_model": settings.openai_fallback_model,
                        "derivation_summary": (
                            "Dates were not generated because the syllabus does not identify every occurrence."
                        ),
                        "review_status": ReviewStatus.NEEDS_REVIEW,
                    }
                )
            failed_repair_keys.add((_normalize_title(merged_events[event_index].title), None))
        return (
            merged.model_copy(update={"events": merged_events}),
            True,
            _ordered_retryable_codes([*retryable_codes, "TERRA_RETRY_FAILED"]),
            failed_repair_keys,
        )
    except StructuredExtractionError:
        return (
            primary,
            True,
            _ordered_retryable_codes([*retryable_codes, "TERRA_RETRY_FAILED"]),
            failed_repair_keys,
        )


def _normalize_evidence(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def detect_date_conflict(
    title: str,
    event_date: date | None,
    known_dates: dict[str, set[date]],
) -> bool:
    if event_date is None:
        return False
    existing_dates = known_dates.get(_normalize_title(title), set())
    return bool(existing_dates and event_date not in existing_dates)


def validate_candidate(
    candidate: CandidateEvent,
    pages: list[dict],
    semester_start: date,
    semester_end: date,
) -> tuple[list[str], str | None]:
    codes: list[str] = []
    reasons: list[str] = []
    if candidate.event_date is None:
        codes.append("DATE_MISSING")
        reasons.append("The event does not have a confirmed date.")
    elif not semester_start <= candidate.event_date <= semester_end:
        codes.append("OUTSIDE_SEMESTER")
        reasons.append("The extracted date is outside the semester range.")
    if not candidate.year_was_explicit:
        codes.append("YEAR_NOT_EXPLICIT")
        reasons.append("The source does not explicitly state a year.")

    source_page = next((page for page in pages if page["page"] == candidate.source_page), None)
    if source_page is None:
        codes.append("SOURCE_PAGE_MISSING")
        reasons.append("The cited source page does not exist in the extracted document.")
    elif _normalize_evidence(candidate.source_quote) not in _normalize_evidence(
        source_page["text"]
    ):
        codes.append("SOURCE_MISMATCH")
        reasons.append("The source quote could not be matched to the cited page.")

    if candidate.confidence == ConfidenceLevel.LOW:
        codes.append("LOW_CONFIDENCE")
        reasons.append(candidate.uncertainty_reason or "The extraction has low confidence.")
    elif candidate.uncertainty_reason:
        codes.append("MODEL_UNCERTAINTY")
        reasons.append(candidate.uncertainty_reason)
    return codes, " ".join(dict.fromkeys(reasons)) or None


def _update_job(session: Session, job: ProcessingJob, status: JobStatus, detail: str) -> None:
    job.status = status
    job.stage_detail = detail
    job.updated_at = datetime.now(UTC)
    session.commit()


def process_job(
    job_id: str,
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> None:
    settings = settings or get_settings()
    if session_factory is None:
        _, session_factory = configure_database(settings.database_url)

    job_uuid = UUID(job_id)
    try:
        with session_factory() as session:
            job = session.scalar(
                select(ProcessingJob)
                .options(
                    selectinload(ProcessingJob.document).selectinload(SyllabusDocument.semester)
                )
                .where(ProcessingJob.id == job_uuid)
            )
            if job is None:
                return
            job.attempts += 1
            _update_job(session, job, JobStatus.EXTRACTING_TEXT, "Reading text from the PDF")

            content = StorageService(settings).read(job.document.storage_key)
            pages, used_ocr = extract_pdf_pages(
                content,
                min_text_characters=settings.min_text_characters_per_page,
                settings=settings,
                on_ocr_start=lambda page_number: _update_job(
                    session,
                    job,
                    JobStatus.RUNNING_OCR,
                    f"Running OCR on page {page_number}",
                ),
            )
            if used_ocr:
                _update_job(session, job, JobStatus.RUNNING_OCR, "OCR completed for scanned pages")
            job.document.extracted_pages = pages
            job.document.used_ocr = used_ocr
            _update_job(session, job, JobStatus.EXTRACTING_EVENTS, "Extracting course dates")
            known_dates_by_title: dict[str, set[date]] = {}
            other_events = session.execute(
                select(ExtractedEvent.title, ExtractedEvent.event_date).where(
                    ExtractedEvent.semester_id == job.semester_id,
                    ExtractedEvent.document_id != job.document_id,
                )
            ).all()
            for existing_title, existing_date in other_events:
                if existing_date is not None:
                    known_dates_by_title.setdefault(_normalize_title(existing_title), set()).add(
                        existing_date
                    )

            if settings.extraction_mode == "openai":
                job.primary_model = settings.openai_model
                job.fallback_model = settings.openai_fallback_model
                extraction, fallback_used, fallback_reason_codes, failed_repair_keys = (
                    _extract_with_model_fallback(
                        pages,
                        settings,
                        job.document.semester.start_date,
                        job.document.semester.end_date,
                        known_dates_by_title,
                    )
                )
            else:
                extraction = extract_syllabus(pages, settings)
                fallback_used = False
                fallback_reason_codes = []
                failed_repair_keys: set[tuple[str, date | None]] = set()
                job.primary_model = None
                job.fallback_model = None

            extraction, ambiguous_event_indexes, ambiguous_warning_reason = (
                _normalize_ambiguous_recurring_content(extraction, pages)
            )
            job.fallback_used = fallback_used
            job.fallback_reason_codes = fallback_reason_codes
            _update_job(session, job, JobStatus.VALIDATING, "Checking dates and source evidence")

            session.execute(
                delete(ExtractedEvent).where(ExtractedEvent.document_id == job.document_id)
            )
            session.execute(
                delete(RecurringEventSeries).where(
                    RecurringEventSeries.document_id == job.document_id
                )
            )
            existing_course = session.scalar(
                select(Course).where(Course.document_id == job.document_id)
            )
            course_count = len(job.document.semester.courses)
            if existing_course is None:
                course = Course(
                    user_id=job.user_id,
                    semester_id=job.semester_id,
                    document_id=job.document_id,
                    color=COURSE_COLORS[course_count % len(COURSE_COLORS)],
                )
                session.add(course)
            else:
                course = existing_course
            course.code = extraction.course_code
            course.name = extraction.course_name
            course.instructor = extraction.instructor
            session.flush()

            expanded_series, derived_candidates = expand_recurring_rules(
                anchors=extraction.schedule_anchors,
                rules=extraction.recurring_rules,
                semester_start=job.document.semester.start_date,
                semester_end=job.document.semester.end_date,
                explicit_events=extraction.events,
                extraction_model=None,
                max_occurrences=200,
            )
            series_map: dict[UUID, ExpandedRecurringSeries] = {}
            for series_payload in expanded_series:
                matching_rule = next(
                    rule
                    for rule in extraction.recurring_rules
                    if rule.title == series_payload.title
                    and rule.rule_kind == series_payload.rule_kind
                )
                warning_codes, warning_reason = _validate_rule(matching_rule, pages)
                series_record = RecurringEventSeries(
                    id=series_payload.id,
                    user_id=job.user_id,
                    semester_id=job.semester_id,
                    course_id=course.id,
                    document_id=job.document_id,
                    title=series_payload.title,
                    event_type=series_payload.event_type,
                    rule_kind=series_payload.rule_kind,
                    rule_summary=series_payload.rule_summary,
                    source_quote=series_payload.source_quote,
                    source_page=series_payload.source_page,
                    anchor_sources=series_payload.anchor_sources,
                    rule_payload=series_payload.rule_payload,
                    confidence=series_payload.confidence,
                    warning_codes=_ordered_unique([*series_payload.warning_codes, *warning_codes]),
                    warning_reason=" ".join(
                        part for part in [series_payload.warning_reason, warning_reason] if part
                    )
                    or None,
                    extraction_model=series_payload.extraction_model,
                    fallback_reason_codes=fallback_reason_codes
                    if series_payload.extraction_model == settings.openai_fallback_model
                    else [],
                )
                session.add(series_record)
                series_map[series_payload.id] = series_payload

            seen: set[tuple[str, date | None]] = set()
            persisted_candidates = [
                (index, candidate, True) for index, candidate in enumerate(extraction.events)
            ] + [
                (None, candidate, False) for candidate in derived_candidates
            ]
            for candidate_index, candidate, is_primary_event in persisted_candidates:
                recurring_series_id = resolve_recurring_series_id(candidate, series_map.keys())
                if candidate.recurring_series_id != recurring_series_id:
                    candidate = candidate.model_copy(
                        update={"recurring_series_id": recurring_series_id}
                    )
                warning_codes, warning_reason = validate_candidate(
                    candidate,
                    pages,
                    job.document.semester.start_date,
                    job.document.semester.end_date,
                )
                normalized_title = _normalize_title(candidate.title)
                if candidate.recurring_series_id is None and detect_date_conflict(
                    candidate.title, candidate.event_date, known_dates_by_title
                ):
                    warning_codes.append("DATE_CONFLICT")
                    warning_reason = " ".join(
                        part
                        for part in [
                            warning_reason,
                            "A similar event has a different date.",
                        ]
                        if part
                    )
                if is_primary_event and candidate_index in ambiguous_event_indexes:
                    warning_codes.append("AMBIGUOUS_RECURRENCE")
                    warning_reason = ambiguous_warning_reason
                duplicate_key = (normalized_title, candidate.event_date)
                if duplicate_key in seen:
                    warning_codes.append("POSSIBLE_DUPLICATE")
                    warning_reason = " ".join(
                        part
                        for part in [warning_reason, "A similar event appears more than once."]
                        if part
                    )
                if duplicate_key[1] is not None:
                    seen.add(duplicate_key)
                failed_key = (_normalize_title(candidate.title), candidate.event_date)
                if failed_key in failed_repair_keys:
                    warning_codes.append("TERRA_RETRY_FAILED")
                    warning_reason = " ".join(
                        part
                        for part in [
                            warning_reason,
                            "Terra retry failed, so the Luna result was kept.",
                        ]
                        if part
                    )
                candidate_fallback_reason_codes = (
                    ["TERRA_RETRY_FAILED"]
                    if failed_key in failed_repair_keys
                    else fallback_reason_codes
                    if candidate.extraction_model == settings.openai_fallback_model
                    else ["TERRA_RETRY_FAILED"]
                    if "TERRA_RETRY_FAILED" in warning_codes
                    else []
                )
                if candidate.recurring_series_id is not None:
                    series_payload = series_map.get(candidate.recurring_series_id)
                    if series_payload is not None:
                        warning_codes = [*series_payload.warning_codes, *warning_codes]
                        warning_reason = " ".join(
                            part
                            for part in [series_payload.warning_reason, warning_reason]
                            if part
                        ) or None
                session.add(
                    ExtractedEvent(
                        user_id=job.user_id,
                        semester_id=job.semester_id,
                        course_id=course.id,
                        document_id=job.document_id,
                        recurring_series_id=candidate.recurring_series_id,
                        title=candidate.title,
                        event_type=candidate.event_type,
                        event_date=candidate.event_date,
                        start_time=candidate.start_time,
                        end_time=candidate.end_time,
                        timezone=job.document.semester.timezone,
                        is_all_day=candidate.is_all_day,
                        source_quote=candidate.source_quote,
                        source_page=candidate.source_page,
                        confidence=candidate.confidence,
                        warning_codes=_ordered_unique(warning_codes),
                        warning_reason=warning_reason,
                        extraction_model=candidate.extraction_model,
                        fallback_reason_codes=candidate_fallback_reason_codes,
                        derivation_summary=candidate.derivation_summary,
                        review_status=ReviewStatus.NEEDS_REVIEW,
                    )
                )
            job.document.semester.review_completed_at = None
            job.status = JobStatus.NEEDS_REVIEW
            job.stage_detail = "Ready for review"
            job.error_message = None
            session.commit()
    except Exception as error:
        with session_factory() as session:
            job = session.get(ProcessingJob, job_uuid)
            if job is not None:
                job.status = JobStatus.FAILED
                job.stage_detail = "Processing failed"
                job.error_message = str(error)[:2000]
                job.updated_at = datetime.now(UTC)
                session.commit()
