from __future__ import annotations

import math
import os
import re
import shutil
from collections.abc import Callable, Collection
from datetime import UTC, date, datetime, time
from pathlib import Path
from time import monotonic
from typing import Annotated, Literal
from uuid import UUID, uuid4

import pymupdf
import pytesseract
from dateutil import parser as date_parser
from openai import OpenAI
from pdf2image import convert_from_bytes
from pdf2image.exceptions import PDFInfoNotInstalledError, PDFPopplerTimeoutError
from pydantic import BaseModel, Field, ValidationError, WithJsonSchema
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from .config import Settings, get_settings
from .database import configure_database
from .errors import SafeProcessingError, log_processing_failure
from .event_deduplication import deduplicate_summary_events
from .job_execution import (
    StaleJobExecution,
    claim_job,
    fail_job_execution,
    fence_job_execution,
)
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
from .source_times import clock_conflict, normalize_source_clock
from .storage import StorageService

COURSE_COLORS = ["#0D9488", "#2563EB", "#7C3AED", "#DB2777", "#D97706", "#059669"]
# Constrain the provider schema while retaining Python time parsing for historical
# offset-bearing values, which must still pass source validation before storage.
LocalClock = Annotated[
    time,
    WithJsonSchema({
        "type": "string",
        "pattern": r"^(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d$",
        "description": "Local 24-hour clock HH:MM:SS, without a timezone suffix or offset.",
    }),
]
SYLLABUS_TYPO_WARNING = (
    "Syllabus typo. The written date and weekday do not match. "
    "The numeric date was kept."
)
AMBIGUOUS_RECURRENCE_PATTERN = re.compile(
    r"\b(?:nearly every|usually|periodically)\b",
    re.IGNORECASE,
)
AMBIGUOUS_MODAL_MAY_PATTERN = re.compile(
    r"\bmay\s+(?:occur|be scheduled|start|include|change)\b",
    re.IGNORECASE,
)
AMBIGUOUS_REVIEW_ITEM_PATTERN = re.compile(
    r"\b(?:nearly every|usually|periodically|may\s+(?:occur|be scheduled|start))\b",
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
COURSE_STRUCTURE_PATTERN = re.compile(
    r"\b(?:course structure|this course includes|lecture sections?|lab section)\b",
    re.IGNORECASE,
)
AMBIGUOUS_RECURRING_HEADING_PATTERN = re.compile(
    r"^(?P<title>[A-Za-z][A-Za-z0-9 &/\-]{1,100}?)"
    r"(?:\s*\([^)]*\))?\s*:\s*(?P<body>.+)$",
    re.IGNORECASE,
)
CALENDAR_ITEM_TITLE_PATTERN = re.compile(
    r"\b(?:exams?|quizzes?|quick checks?|exercise sets?|assignments?|homework|projects?|"
    r"presentations?|meetings?|deadlines?|readings?)\b",
    re.IGNORECASE,
)
LAB_MAKEUP_POLICY_PATTERN = re.compile(
    r"(?:\blab(?: assignment)? make-up deadline\s*[-:]\s*"
    r"(?P<titled_time>\d{1,2}:\d{2}\s*(?:am|pm))\s+the sunday "
    r"(?:that\s+)?follow(?:s|ing)\s+"
    r"(?:the\s+)?lab\b)|"
    r"(?:\bmissed labs can be submitted until\s+"
    r"(?P<missed_time>\d{1,2}:\d{2}\s*(?:am|pm))\s+on the sunday that follow(?:s|ing)\s+"
    r"(?:the\s+)?lab\b)",
    re.IGNORECASE,
)
LAB_MAKEUP_TITLE_ALIASES = {
    "lab assignment make up deadline",
    "lab make up submission",
    "lab make up submission deadline",
    "lab make up submissions",
    "lab make up deadline",
    "missed lab make up deadline",
    "missed labs make up deadline",
    "weekly lab assignment make up deadline",
    "weekly lab make up deadline",
}
LAB_EXAM_TITLE_ALIASES = {
    "lab exams",
    "periodic lab exams",
}
REVIEW_ONLY_DERIVATION_SUMMARY = (
    "Dates were not generated because the syllabus does not identify every occurrence."
)
GENERIC_ANCHOR_TYPES = {"lecture", "lab", "discussion", "class", "other"}


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
    start_time: LocalClock | None = None
    end_time: LocalClock | None = None
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
    start_time: LocalClock | None = None
    end_time: LocalClock | None = None
    boundary_start: date | None = None
    boundary_end: date | None = None
    exclusion_dates: list[date] = Field(default_factory=list)
    source_quote: str = Field(min_length=1)
    source_page: int = Field(ge=1)
    derivation_summary: str | None = None
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
    start_time: LocalClock | None = None
    end_time: LocalClock | None = None
    is_all_day: bool = True
    boundary_start: date | None = None
    boundary_end: date | None = None
    exclusion_dates: list[date] = Field(default_factory=list)
    source_quote: str = Field(min_length=1)
    source_page: int = Field(ge=1)
    derivation_summary: str | None = None
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
    command = settings.tesseract_cmd or shutil.which("tesseract")
    if not command:
        locations = (
            ("LOCALAPPDATA", Path("Programs/Tesseract-OCR/tesseract.exe")),
            ("ProgramFiles", Path("Tesseract-OCR/tesseract.exe")),
            ("ProgramFiles(x86)", Path("Tesseract-OCR/tesseract.exe")),
        )
        for variable, relative_path in locations:
            root = os.environ.get(variable)
            if root and (candidate := Path(root) / relative_path).is_file():
                command = str(candidate)
                break
    pytesseract.pytesseract.tesseract_cmd = command or "tesseract"
    try:
        images = convert_from_bytes(
            content,
            first_page=page_number,
            last_page=page_number,
            dpi=220,
            poppler_path=settings.pdf_poppler_path,
            size=settings.max_ocr_dimension_pixels,
            timeout=settings.pdf_render_timeout_seconds,
        )
    except PDFPopplerTimeoutError as error:
        raise SafeProcessingError(
            "OCR page rendering exceeded its time limit. Try a simpler PDF."
        ) from error
    except (PDFInfoNotInstalledError, FileNotFoundError) as error:
        raise SafeProcessingError(
            "OCR could not run because Poppler was not found. "
            "Install Poppler or set PDF_POPPLER_PATH, then retry this file."
        ) from error
    except Exception as error:
        raise SafeProcessingError(
            "OCR could not read this page. Check that the PDF is readable, then retry this file."
        ) from error
    if not images:
        return ""
    try:
        if any(max(image.size) > settings.max_ocr_dimension_pixels for image in images):
            raise SafeProcessingError("OCR page rendering exceeded its image size limit.")
        return pytesseract.image_to_string(
            images[0], timeout=settings.ocr_timeout_seconds
        ).strip()
    except SafeProcessingError:
        raise
    except pytesseract.TesseractNotFoundError as error:
        raise SafeProcessingError(
            "OCR could not run because Tesseract was not found. "
            "Install Tesseract or set TESSERACT_CMD, then retry this file."
        ) from error
    except Exception as error:
        raise SafeProcessingError(
            "OCR could not read this page. Check that the PDF is readable, then retry this file."
        ) from error
    finally:
        for image in images:
            image.close()


def extract_pdf_pages(
    content: bytes,
    min_text_characters: int,
    settings: Settings | None = None,
    on_ocr_start: Callable[[int], None] | None = None,
) -> tuple[list[dict], bool]:
    settings = settings or get_settings()
    deadline = monotonic() + settings.processing_timeout_seconds
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
            if monotonic() >= deadline:
                raise SafeProcessingError(
                    "PDF processing exceeded its time limit. Try a shorter PDF."
                )
            page_number = index + 1
            dimensions = (
                page.rect.width, page.rect.height, page.mediabox.width, page.mediabox.height
            )
            if any(
                not math.isfinite(value) or value <= 0
                or value > settings.max_pdf_page_dimension_points
                for value in dimensions
            ):
                raise ValueError("The PDF page dimensions exceed the supported limit.")
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
            if monotonic() >= deadline:
                raise SafeProcessingError(
                    "PDF processing exceeded its time limit. Try a shorter PDF."
                )
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
    client = OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout_seconds,
        max_retries=0,
    )
    try:
        response = client.responses.parse(
            model=model,
            instructions=instructions,
            input=_pages_for_prompt(pages),
            text_format=text_format,
            store=False,
            max_output_tokens=settings.max_model_output_tokens,
            reasoning={"effort": settings.openai_reasoning_effort},
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
            "Return clock times as local 24-hour HH:MM:SS without Z, UTC conversions, "
            "or timezone offsets. Use separate start_time and end_time fields for ranges. "
            "Use only explicitly stated times or directly applicable assessment deadline "
            "rules. Never infer AM/PM from an ambiguous class schedule or borrow office hours. "
            "Set unknown times to null. Each source_quote must be one short contiguous "
            "verbatim excerpt from its cited page. Never combine separate table rows, "
            "omit intervening text and join the remainder, or append a separate deadline "
            "policy to an assessment quote. A quote may cite just the assessment row; "
            "explain separately located deadline policies in derivation_summary instead. "
            "Keep important items whose date is not published yet and set event_date to null. "
            "Extract schedule_anchors for recurring lectures, labs, or discussions. "
            "When the syllabus lists irregular explicit meeting rows or dates for an anchor, "
            "populate ScheduleOccurrence entries on that anchor with occurrence_date, title, "
            "anchor_type, source_quote, and source_page. "
            "Extract recurring_rules for weekly fixed rules and rules that are relative to "
            "a lecture or lab anchor. Set expansion_mode review_only when recurrence wording "
            "is ambiguous or when a relative phrase like morning of the lecture, morning after "
            "the lecture, or Sunday following the lab does not identify every occurrence. "
            "Otherwise use expansion_mode exact. Use the page markers for source_page. "
            "Copy a short exact source_quote. Do not invent dates. "
            "Return times in 24-hour HH:MM:SS form, preserving source AM/PM. "
            "Times are local to the semester timezone, without UTC offsets. "
            "Put a range's beginning in start_time and its ending in end_time; "
            "never put a range or a timezone suffix in either field. "
            "For example 11:59 PM is 23:59:00, 2-4 PM uses start_time 14:00:00 "
            "and end_time 16:00:00, 12 AM is 00:00:00 and 12 PM is 12:00:00. Include time "
            "in the quoted excerpt when present, without stitching separate passages. "
            "Apply universal assignment deadlines only to their stated "
            "assessment scope and preserve explicit exceptions such as exams. "
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
WEEKDAY_PATTERN = (
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
)
ACTIONABLE_SCHEDULE_PATTERN = re.compile(
    rf"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b|"
    rf"\bfrom\s+{MONTH_PATTERN}\s+\d{{1,2}},?\s+\d{{4}}\b|"
    rf"\bthrough\s+{MONTH_PATTERN}\s+\d{{1,2}},?\s+\d{{4}}\b|"
    r"\bat\s+\d{1,2}(?::\d{2})?\b|"
    r"\bmeets every\b",
    re.IGNORECASE,
)
SECTION_MEETING_TIME_PATTERN = re.compile(
    r"^\s*[A-Z][A-Za-z0-9-]*\s+"
    r"(?:M|T|Tu|W|Th|F|Sa|Su|MW|WF|TR|Mon|Tue|Wed|Thu|Fri|Sat|Sun|M/W|T/Th|Tu/Th)\b"
    r".*?\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\s*[-–]\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
    re.IGNORECASE,
)
STRUCTURAL_CLASS_REFERENCE_PATTERN = re.compile(
    r"\bsee\s+albert\b|\bLB\d+\b",
    re.IGNORECASE,
)
STRUCTURAL_SECTION_DESCRIPTION_PATTERN = re.compile(
    r"\b(?:mandatory\s+)?weekly\s+(?:lab|lecture|discussion|class)\s+sections?\b|"
    r"\b(?:lab|lecture|discussion|class)\s+sections?\b",
    re.IGNORECASE,
)
EXPLICIT_WEEKLY_SOURCE_PATTERN = re.compile(
    rf"\b(?:every|each)\s+(?:{WEEKDAY_PATTERN}|week)\b|\bweekly\b|\bmeets every\b",
    re.IGNORECASE,
)
NON_ACTIONABLE_ASSIGNMENT_DESCRIPTION_PATTERN = re.compile(
    r"\bconducted\s+in\s+a\s+supervised\s+setting\b",
    re.IGNORECASE,
)
EXPLICIT_SOURCE_BOUNDARY_PATTERN = re.compile(
    rf"\bfrom\s+{MONTH_PATTERN}\s+\d{{1,2}},?\s+\d{{4}}\b.*\bthrough\s+{MONTH_PATTERN}\s+\d{{1,2}},?\s+\d{{4}}\b|"
    rf"\bbetween\s+{MONTH_PATTERN}\s+\d{{1,2}},?\s+\d{{4}}\b.*\band\s+{MONTH_PATTERN}\s+\d{{1,2}},?\s+\d{{4}}\b",
    re.IGNORECASE,
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
SOURCE_DATE_WEEKDAY_PATTERNS = (
    re.compile(
        rf"\b(?P<day>\d{{1,2}})[\s|/-]+(?P<month>{MONTH_PATTERN})"
        rf"(?:[\s,|/-]+(?P<year>\d{{4}}))?[\s,|/-]+"
        rf"(?P<weekday>{WEEKDAY_PATTERN})\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?P<month>{MONTH_PATTERN})[\s|/-]+(?P<day>\d{{1,2}})"
        rf"(?:[\s,|/-]+(?P<year>\d{{4}}))?[\s,|/-]+"
        rf"(?P<weekday>{WEEKDAY_PATTERN})\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?P<weekday>{WEEKDAY_PATTERN})[\s,|/-]+(?P<day>\d{{1,2}})"
        rf"[\s|/-]+(?P<month>{MONTH_PATTERN})(?:[\s,|/-]+(?P<year>\d{{4}}))?\b",
        re.IGNORECASE,
    ),
)


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


def _rule_summary(rule: RecurringRule, range_start: date, range_end: date) -> str:
    if rule.rule_kind == "weekly_fixed":
        summary = f"Every {rule.weekday} between {range_start} and {range_end}"
        if rule.boundary_start is None or rule.boundary_end is None:
            summary += " (using semester boundaries where syllabus bounds are missing)"
        return summary
    offset = rule.offset_days or 0
    anchor_title = rule.anchor_title or "anchor"
    return f"{offset} day(s) after {anchor_title}"


def _find_matching_anchors(
    rule: RecurringRule,
    anchors: list[ScheduleAnchor],
) -> list[ScheduleAnchor]:
    if rule.anchor_title is None:
        return []

    normalized_anchor_title = _normalize_title(rule.anchor_title)
    exact_matches = [
        anchor for anchor in anchors if _normalize_title(anchor.title) == normalized_anchor_title
    ]
    if exact_matches:
        return exact_matches

    if normalized_anchor_title in GENERIC_ANCHOR_TYPES:
        generic_matches = [
            anchor for anchor in anchors if anchor.anchor_type == normalized_anchor_title
        ]
        if generic_matches:
            return generic_matches

    return [
        anchor
        for anchor in anchors
        if normalized_anchor_title in _normalize_title(anchor.title)
        or anchor.anchor_type in normalized_anchor_title.split()
    ]


def _requires_exact_anchor(rule: RecurringRule) -> bool:
    return bool(
        rule.rule_kind == "relative_to_anchor"
        and rule.expansion_mode == "exact"
        and rule.anchor_title is not None
        and rule.offset_days is not None
    )


def _validate_rule(
    rule: RecurringRule,
    pages: list[dict],
    anchors: list[ScheduleAnchor],
) -> tuple[list[str], str | None]:
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
    if (
        _requires_exact_anchor(rule)
        and not _rule_requires_review_only(rule, pages)
        and not _find_matching_anchors(rule, anchors)
    ):
        codes.append("ANCHOR_NOT_FOUND")
        reasons.append("The recurring rule refers to a schedule anchor that could not be matched.")
    time_conflicts = [clock_conflict(rule, pages)]
    if rule.rule_kind == "relative_to_anchor" and rule.anchor_title:
        time_conflicts.extend(
            clock_conflict(anchor, pages) for anchor in _find_matching_anchors(rule, anchors)
        )
    if any(time_conflicts):
        codes.append("TIME_CONFLICT")
        reasons.extend(reason for reason in time_conflicts if reason)
    return codes, " ".join(dict.fromkeys(reasons)) or None


def _apply_extraction_model(extraction: SyllabusExtraction, model: str) -> None:
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
        "derivation_summary": rule.derivation_summary,
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


def _event_type_for_title(title: str) -> str:
    normalized = title.casefold()
    if "exam" in normalized:
        return "exam"
    if "quiz" in normalized or "quick check" in normalized:
        return "quiz"
    if "deadline" in normalized:
        return "deadline"
    if any(term in normalized for term in ("assignment", "homework", "exercise set")):
        return "assignment"
    if "project" in normalized:
        return "project"
    if "reading" in normalized:
        return "reading"
    return "other"


def _canonicalize_event_identity(candidate: CandidateEvent) -> CandidateEvent:
    normalized_title = _normalize_phrase(candidate.title)
    title = _display_title(candidate.title)
    event_type = candidate.event_type

    if "quick check" in normalized_title:
        title = "Quick Checks"
        event_type = "quiz"
    elif "exercise set" in normalized_title:
        title = "Exercise Sets"
        event_type = "assignment"
    elif "no lecture" in normalized_title:
        if "friday schedule" in normalized_title:
            title = "No lecture / Friday schedule"
            event_type = "class"

    if title == candidate.title and event_type == candidate.event_type:
        return candidate
    return candidate.model_copy(update={"title": title, "event_type": event_type})


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


def _normalize_phrase(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _title_variants(title: str) -> set[str]:
    display = _display_title(title)
    tokens = [token for token in _normalize_phrase(display).split() if token]
    if not tokens:
        return set()
    singular_tokens = [token[:-1] if token.endswith("s") else token for token in tokens]
    variants = {" ".join(tokens), " ".join(singular_tokens)}
    return {variant for variant in variants if variant}


def _page_sentences(page_text: str) -> list[str]:
    return [
        segment.strip()
        for segment in re.split(r"(?<=[.!?])\s+|\n+", page_text)
        if segment.strip()
    ]


def _segment_with_continuation(segments: list[str], index: int, *, max_parts: int = 3) -> str:
    parts = [segments[index].strip()]
    cursor = index + 1
    while cursor < len(segments) and len(parts) < max_parts:
        previous = parts[-1]
        if previous.endswith((".", "!", "?")):
            break
        next_segment = segments[cursor].strip()
        if not next_segment or next_segment in {"○", "●"}:
            break
        if not re.match(r"^[a-z(]", next_segment):
            break
        parts.append(next_segment)
        cursor += 1
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _related_page_segments(
    *,
    title: str,
    source_page: int,
    source_quote: str,
    pages: list[dict],
) -> list[str]:
    page_text = _page_text(source_page, pages)
    if not page_text:
        return []
    normalized_quote = _normalize_phrase(source_quote)
    title_variants = _title_variants(title)
    segments: list[str] = []
    for sentence in _page_sentences(page_text):
        normalized_sentence = _normalize_phrase(sentence)
        if normalized_quote and normalized_quote in normalized_sentence:
            segments.append(sentence)
            continue
        if any(variant and variant in normalized_sentence for variant in title_variants):
            segments.append(sentence)
    return segments


def _has_relative_review_only_phrase(value: str) -> bool:
    return bool(RELATIVE_REVIEW_ONLY_PATTERN.search(value))


UNCERTAIN_ASSESSMENT_COUNT_PATTERN = re.compile(
    r"(?<![\w:/–—-])"
    r"(?:\d{1,3}\s*(?:[–—-]|\bto\b)\s*\d{1,3}|"
    r"(?:about|around|approximately|roughly|up to|at least)\s+\d{1,3})"
    r"\s+(?:(?:weekly|graded|short|recitation|in-class|online|programming)\s+){0,4}"
    r"(?P<assessment>assignments?|homeworks?|quizzes|quiz|quick\s+checks?|"
    r"exercise\s+sets?|problem\s+sets?|projects?|exams?|tests?|lab\s+reports?)\b",
    re.IGNORECASE,
)


def _has_uncertain_assessment_count(rule: RecurringRule, pages: list[dict]) -> bool:
    quote = rule.source_quote
    if _normalize_evidence(quote) not in _normalize_evidence(_page_text(rule.source_page, pages)):
        return False

    def assignment_subject(value: str) -> str | None:
        subjects = list(re.finditer(
            r"\blab\s+reports?\b|\bhomeworks?\b|\b(?:exercise|problem)\s+sets?\b",
            value, re.IGNORECASE,
        ))
        if not subjects:
            return None
        return "lab_report" if subjects[-1].group().casefold().startswith("lab") else "homework"

    for match in UNCERTAIN_ASSESSMENT_COUNT_PATTERN.finditer(quote):
        # A date, time, location or problem-number range is not an assessment count.
        prefix = quote[:match.start()].rsplit("\n", 1)[-1]
        if re.search(
            r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
            r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
            r"at|hours?|rooms?|problems?|questions?|exercises?)\s*$",
            prefix, re.IGNORECASE,
        ):
            continue
        assessment = _normalize_phrase(match.group("assessment"))
        if re.search(r"\b(?:quiz|quizzes|quick checks?)\b", assessment):
            kind = "quiz"
        elif re.search(r"\bprojects?\b", assessment):
            kind = "project"
        elif re.search(r"\b(?:exams?|tests?)\b", assessment):
            kind = "exam"
        else:
            kind = "assignment"
        if kind == "assignment":
            target_subject = assignment_subject(rule.title)
            counted_subject = assignment_subject(assessment)
            if counted_subject is None:
                # Generic "assignments" inherit the closest explicit subject in
                # the quote, such as UMD's "Homeworks" heading. Different explicit
                # subjects must not borrow each other's approximate counts.
                counted_subject = assignment_subject(quote[:match.start()])
            if counted_subject is not None and counted_subject != target_subject:
                continue
        if kind == rule.event_type:
            return True
    return False


def _rule_requires_review_only(rule: RecurringRule, pages: list[dict]) -> bool:
    related_segments = _related_page_segments(
        title=rule.title,
        source_page=rule.source_page,
        source_quote=rule.source_quote,
        pages=pages,
    )
    has_relative_phrase = _has_relative_review_only_phrase(rule.source_quote) or any(
        _has_relative_review_only_phrase(segment) for segment in related_segments
    )
    if rule.expansion_mode == "review_only":
        return True
    if _has_uncertain_assessment_count(rule, pages):
        return True
    if _is_ambiguous_recurrence_text(rule.source_quote):
        return True
    if rule.rule_kind == "relative_to_anchor" and has_relative_phrase:
        return True
    if has_relative_phrase and any(
        _is_ambiguous_recurrence_text(segment) for segment in related_segments
    ):
        return True
    if rule.rule_kind == "weekly_fixed" and any(
        _is_ambiguous_recurrence_text(segment) for segment in related_segments
    ):
        return True
    return False


def _event_requires_review_only(event: CandidateEvent, pages: list[dict]) -> bool:
    if event.derivation_summary == REVIEW_ONLY_DERIVATION_SUMMARY:
        return True
    if _is_ambiguous_recurrence_text(event.source_quote):
        return True
    related_segments = _related_page_segments(
        title=event.title,
        source_page=event.source_page,
        source_quote=event.source_quote,
        pages=pages,
    )
    has_relative_phrase = _has_relative_review_only_phrase(event.source_quote) or any(
        _has_relative_review_only_phrase(segment) for segment in related_segments
    )
    return bool(
        has_relative_phrase
        and (
            _is_ambiguous_recurrence_text(event.source_quote)
            or any(_is_ambiguous_recurrence_text(segment) for segment in related_segments)
        )
    )


def _is_non_actionable_course_structure_text(value: str) -> bool:
    normalized = re.sub(r"\s+", " ", value).strip()
    return bool(
        normalized
        and COURSE_STRUCTURE_PATTERN.search(normalized)
        and not ACTIONABLE_SCHEDULE_PATTERN.search(normalized)
    )


def _is_non_actionable_course_structure_event(event: CandidateEvent) -> bool:
    return bool(
        event.event_type == "class"
        and event.event_date is None
        and event.start_time is None
        and event.end_time is None
        and _is_non_actionable_course_structure_text(event.source_quote)
    )


def _is_non_actionable_section_meeting_quote(source_quote: str) -> bool:
    has_meeting_shape = bool(
        SECTION_MEETING_TIME_PATTERN.search(source_quote)
        or STRUCTURAL_CLASS_REFERENCE_PATTERN.search(source_quote)
        or STRUCTURAL_SECTION_DESCRIPTION_PATTERN.search(source_quote)
        or re.search(
            r"^\s*(?:lectures?|labs?|class(?:es)?|discussions?)\s*:\s*"
            r"(?:mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|"
            r"fri(?:day)?|sat(?:urday)?|sun(?:day)?|mwf|mw|wf|tr|tu|th|sa|su|[mtwf])\b",
            source_quote,
            re.IGNORECASE,
        )
        or re.search(
            r"\b(?:class|lecture|lab|discussion)\s+schedule(?:\s+and\s+location)?\s*:",
            source_quote,
            re.IGNORECASE,
        )
    )
    has_explicit_weekly = bool(EXPLICIT_WEEKLY_SOURCE_PATTERN.search(source_quote))
    has_explicit_boundary = bool(EXPLICIT_SOURCE_BOUNDARY_PATTERN.search(source_quote))
    return bool(
        has_meeting_shape
        and not (has_explicit_weekly and has_explicit_boundary)
    )


def _is_non_actionable_section_meeting_event(event: CandidateEvent) -> bool:
    return bool(
        event.event_type == "class"
        and event.event_date is None
        and _is_non_actionable_section_meeting_quote(event.source_quote)
    )


def _is_non_actionable_assignment_description_event(event: CandidateEvent) -> bool:
    return bool(
        event.event_type == "assignment"
        and event.event_date is None
        and event.start_time is None
        and event.end_time is None
        and NON_ACTIONABLE_ASSIGNMENT_DESCRIPTION_PATTERN.search(event.source_quote)
    )


def _is_non_actionable_course_structure_rule(rule: RecurringRule) -> bool:
    return bool(
        rule.event_type == "class"
        and rule.start_time is None
        and rule.end_time is None
        and rule.weekday is None
        and rule.boundary_start is None
        and rule.boundary_end is None
        and rule.offset_days is None
        and _is_non_actionable_course_structure_text(rule.source_quote)
    )


def _filter_non_actionable_course_structure_items(
    extraction: SyllabusExtraction,
) -> SyllabusExtraction:
    return SyllabusExtraction(
        course_code=extraction.course_code,
        course_name=extraction.course_name,
        instructor=extraction.instructor,
        events=[
            event.model_copy(deep=True)
            for event in extraction.events
            if not _is_non_actionable_course_structure_event(event)
            and not _is_non_actionable_section_meeting_event(event)
            and not _is_non_actionable_assignment_description_event(event)
        ],
        schedule_anchors=[anchor.model_copy(deep=True) for anchor in extraction.schedule_anchors],
        recurring_rules=[
            rule.model_copy(deep=True)
            for rule in extraction.recurring_rules
            if not _is_non_actionable_course_structure_rule(rule)
            and not _is_non_actionable_section_meeting_rule(rule)
        ],
    )


def _is_non_actionable_section_meeting_rule(rule: RecurringRule) -> bool:
    return bool(
        rule.event_type == "class"
        and rule.rule_kind == "weekly_fixed"
        and _is_non_actionable_section_meeting_quote(rule.source_quote)
    )


def _collapse_lab_makeup_alias_events(
    events: list[CandidateEvent],
) -> tuple[list[CandidateEvent], dict[int, int]]:
    def resolved_deadline_time(candidate: CandidateEvent) -> time | None:
        return candidate.end_time or candidate.start_time

    collapsed_events: list[CandidateEvent] = []
    collapsed_index_map: dict[int, int] = {}
    for original_index, event in enumerate(events):
        normalized_title = _normalize_phrase(event.title)
        if event.event_type != "deadline" or normalized_title not in LAB_MAKEUP_TITLE_ALIASES:
            collapsed_events.append(event)
            collapsed_index_map[original_index] = len(collapsed_events) - 1
            continue
        normalized_quote = _normalize_evidence(event.source_quote)
        matching_index = next(
            (
                index
                for index, existing in enumerate(collapsed_events)
                if existing.event_type == "deadline"
                and existing.source_page == event.source_page
                and _normalize_phrase(existing.title) in LAB_MAKEUP_TITLE_ALIASES
                and (
                    _normalize_evidence(existing.source_quote)
                    and normalized_quote
                    and (
                        _normalize_evidence(existing.source_quote) in normalized_quote
                        or normalized_quote in _normalize_evidence(existing.source_quote)
                    )
                )
            ),
            None,
        )
        if matching_index is None:
            collapsed_events.append(
                event.model_copy(update={"title": "Lab assignment make-up deadline"})
            )
            collapsed_index_map[original_index] = len(collapsed_events) - 1
            continue
        existing = collapsed_events[matching_index]
        existing_quote = _normalize_evidence(existing.source_quote)
        use_new_quote = bool(normalized_quote and len(normalized_quote) > len(existing_quote))
        existing_time = resolved_deadline_time(existing)
        new_time = resolved_deadline_time(event)
        if existing_time == time(23, 59) or new_time == time(23, 59):
            end_time = time(23, 59)
        elif use_new_quote and new_time is not None:
            end_time = new_time
        else:
            end_time = existing_time or new_time
        collapsed_events[matching_index] = existing.model_copy(
            update={
                "title": "Lab assignment make-up deadline",
                "event_date": None,
                "start_time": None,
                "end_time": end_time,
                "is_all_day": False if end_time else existing.is_all_day,
                "source_quote": event.source_quote if use_new_quote else existing.source_quote,
                "source_page": event.source_page if use_new_quote else existing.source_page,
                "confidence": event.confidence if use_new_quote else existing.confidence,
                "year_was_explicit": (
                    event.year_was_explicit if use_new_quote else existing.year_was_explicit
                ),
                "uncertainty_reason": (
                    event.uncertainty_reason if use_new_quote else existing.uncertainty_reason
                ),
                "extraction_model": (
                    event.extraction_model if use_new_quote else existing.extraction_model
                ),
                "derivation_summary": existing.derivation_summary or event.derivation_summary,
                "review_status": ReviewStatus.NEEDS_REVIEW,
            }
        )
        collapsed_index_map[original_index] = matching_index
    return collapsed_events, collapsed_index_map


def _collapse_lab_exam_alias_events(
    events: list[CandidateEvent],
) -> tuple[list[CandidateEvent], dict[int, int]]:
    collapsed_events: list[CandidateEvent] = []
    collapsed_index_map: dict[int, int] = {}
    for original_index, event in enumerate(events):
        normalized_title = _normalize_phrase(event.title)
        if (
            event.event_type != "exam"
            or event.event_date is not None
            or normalized_title not in LAB_EXAM_TITLE_ALIASES
        ):
            collapsed_events.append(event)
            collapsed_index_map[original_index] = len(collapsed_events) - 1
            continue
        normalized_quote = _normalize_evidence(event.source_quote)
        matching_index = next(
            (
                index
                for index, existing in enumerate(collapsed_events)
                if existing.event_type == "exam"
                and existing.event_date is None
                and existing.source_page == event.source_page
                and _normalize_phrase(existing.title) in LAB_EXAM_TITLE_ALIASES
                and (
                    _normalize_evidence(existing.source_quote)
                    and normalized_quote
                    and (
                        _normalize_evidence(existing.source_quote) in normalized_quote
                        or normalized_quote in _normalize_evidence(existing.source_quote)
                    )
                )
            ),
            None,
        )
        if matching_index is None:
            collapsed_events.append(event.model_copy(update={"title": "Lab Exams"}))
            collapsed_index_map[original_index] = len(collapsed_events) - 1
            continue
        existing = collapsed_events[matching_index]
        existing_quote = _normalize_evidence(existing.source_quote)
        use_new_quote = bool(normalized_quote and len(normalized_quote) > len(existing_quote))
        collapsed_events[matching_index] = existing.model_copy(
            update={
                "title": "Lab Exams",
                "source_quote": event.source_quote if use_new_quote else existing.source_quote,
                "source_page": event.source_page if use_new_quote else existing.source_page,
                "confidence": event.confidence if use_new_quote else existing.confidence,
                "year_was_explicit": (
                    event.year_was_explicit if use_new_quote else existing.year_was_explicit
                ),
                "uncertainty_reason": (
                    event.uncertainty_reason if use_new_quote else existing.uncertainty_reason
                ),
                "extraction_model": (
                    event.extraction_model if use_new_quote else existing.extraction_model
                ),
                "derivation_summary": existing.derivation_summary or event.derivation_summary,
                "review_status": ReviewStatus.NEEDS_REVIEW,
            }
        )
        collapsed_index_map[original_index] = matching_index
    return collapsed_events, collapsed_index_map


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
    derivation_summary = REVIEW_ONLY_DERIVATION_SUMMARY

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
    events, collapsed_exam_index_map = _collapse_lab_exam_alias_events(events)
    normalized_event_indexes = {
        collapsed_exam_index_map[index]
        for index in normalized_event_indexes
        if index in collapsed_exam_index_map
    }
    events, collapsed_index_map = _collapse_lab_makeup_alias_events(events)
    normalized_event_indexes = {
        collapsed_index_map[index]
        for index in normalized_event_indexes
        if index in collapsed_index_map
    }

    return (
        SyllabusExtraction(
            course_code=extraction.course_code,
            course_name=extraction.course_name,
            instructor=extraction.instructor,
            events=events,
            schedule_anchors=[
                anchor.model_copy(deep=True) for anchor in extraction.schedule_anchors
            ],
            recurring_rules=rules,
        ),
        normalized_event_indexes,
        ambiguous_reason,
    )


def _detect_missing_recurring_rule(
    extraction: SyllabusExtraction,
    pages: list[dict],
) -> list[str]:
    return [
        item["stable_title"]
        for item in _find_missing_recurring_rule_candidates(extraction, pages)
    ]


def _find_missing_recurring_rule_candidates(
    extraction: SyllabusExtraction,
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


def _matching_lab_makeup_event_indexes(
    events: list[CandidateEvent],
    source_page: int,
    policy_segment: str,
    page_policy_match_count: int,
) -> list[int]:
    normalized_segment = _normalize_evidence(policy_segment)
    matching_indexes: list[int] = []
    for index, event in enumerate(events):
        if (
            event.event_type != "deadline"
            or event.source_page != source_page
            or _normalize_phrase(event.title) not in LAB_MAKEUP_TITLE_ALIASES
        ):
            continue
        normalized_quote = _normalize_evidence(event.source_quote)
        normalized_quote_phrase = _normalize_phrase(event.source_quote)
        quote_matches_segment = bool(
            normalized_quote
            and (
                normalized_quote in normalized_segment
                or normalized_segment in normalized_quote
            )
        )
        alias_only_quote = (
            normalized_quote_phrase in LAB_MAKEUP_TITLE_ALIASES
            and page_policy_match_count == 1
        )
        if quote_matches_segment or alias_only_quote:
            matching_indexes.append(index)
    return matching_indexes


def _materialize_missing_ambiguous_review_events(
    extraction: SyllabusExtraction,
    pages: list[dict],
    *,
    extraction_model: str | None,
) -> SyllabusExtraction:
    events = [event.model_copy(deep=True) for event in extraction.events]
    known_titles = {
        _stable_title_key(item.title)
        for item in [*extraction.events, *extraction.recurring_rules]
    }
    known_title_phrases = {
        _normalize_phrase(item.title) for item in [*extraction.events, *extraction.recurring_rules]
    }
    derivation_summary = REVIEW_ONLY_DERIVATION_SUMMARY

    for page in pages:
        page_policy_match_count = len(list(LAB_MAKEUP_POLICY_PATTERN.finditer(page["text"])))
        segments = _page_sentences(page["text"])
        for index, _ in enumerate(segments):
            segment = _segment_with_continuation(segments, index)
            match = AMBIGUOUS_RECURRING_HEADING_PATTERN.match(segment)
            if match is not None and AMBIGUOUS_REVIEW_ITEM_PATTERN.search(segment) is not None:
                title = _display_title(match.group("title"))
                stable_title = _stable_title_key(title)
                if (
                    stable_title
                    and stable_title not in known_titles
                    and CALENDAR_ITEM_TITLE_PATTERN.search(title) is not None
                ):
                    events.append(
                        CandidateEvent(
                            title=title,
                            event_type=_event_type_for_title(title),
                            event_date=None,
                            start_time=None,
                            end_time=None,
                            is_all_day=True,
                            source_quote=re.sub(r"\s+", " ", segment).strip(),
                            source_page=page["page"],
                            confidence=ConfidenceLevel.MEDIUM,
                            year_was_explicit=True,
                            uncertainty_reason=(
                                "The syllabus describes a recurring item without "
                                "identifying every date."
                            ),
                            extraction_model=extraction_model,
                            derivation_summary=derivation_summary,
                            review_status=ReviewStatus.NEEDS_REVIEW,
                        )
                    )
                    known_titles.add(stable_title)
                    known_title_phrases.add(_normalize_phrase(title))

            deadline_match = LAB_MAKEUP_POLICY_PATTERN.search(segment)
            if deadline_match is None:
                continue
            deadline_time = (
                deadline_match.group("titled_time") or deadline_match.group("missed_time")
            )
            normalized_policy_segment = re.sub(r"\s+", " ", segment).strip()
            parsed_deadline_time = date_parser.parse(deadline_time, fuzzy=True).time()
            existing_indexes = _matching_lab_makeup_event_indexes(
                events,
                page["page"],
                segment,
                page_policy_match_count,
            )
            if existing_indexes:
                canonical_title = _normalize_phrase("Lab assignment make-up deadline")
                survivor_index = next(
                    (
                        index
                        for index in existing_indexes
                        if _normalize_phrase(events[index].title) == canonical_title
                    ),
                    existing_indexes[0],
                )
                existing = events[survivor_index]
                existing_title_is_alias = _normalize_phrase(existing.title) != canonical_title
                normalized_existing_quote = _normalize_evidence(existing.source_quote)
                normalized_existing_phrase = _normalize_phrase(existing.source_quote)
                normalized_segment = _normalize_evidence(segment)
                alias_only_quote = (
                    normalized_existing_phrase in LAB_MAKEUP_TITLE_ALIASES
                    and not (
                        normalized_existing_quote
                        and (
                            normalized_existing_quote in normalized_segment
                            or normalized_segment in normalized_existing_quote
                        )
                    )
                )
                canonical_event = existing.model_copy(
                    update={
                        "title": "Lab assignment make-up deadline",
                        "event_type": "deadline",
                        "event_date": None,
                        "end_time": existing.end_time or parsed_deadline_time,
                        "is_all_day": False,
                        "source_quote": normalized_policy_segment
                        if existing_title_is_alias or alias_only_quote
                        else existing.source_quote,
                        "source_page": page["page"]
                        if existing_title_is_alias or alias_only_quote
                        else existing.source_page,
                        "uncertainty_reason": existing.uncertainty_reason
                        or (
                            "The syllabus describes a recurring item without "
                            "identifying every date."
                        ),
                        "derivation_summary": derivation_summary,
                        "review_status": ReviewStatus.NEEDS_REVIEW,
                    }
                )
                duplicate_indexes = set(existing_indexes)
                events = [
                    canonical_event
                    if index == survivor_index
                    else event
                    for index, event in enumerate(events)
                    if index == survivor_index or index not in duplicate_indexes
                ]
                known_titles.add(_stable_title_key("Lab assignment make-up deadline"))
                known_title_phrases.update(LAB_MAKEUP_TITLE_ALIASES)
                continue
            events.append(
                CandidateEvent(
                    title="Lab assignment make-up deadline",
                    event_type="deadline",
                    event_date=None,
                    start_time=None,
                    end_time=parsed_deadline_time,
                    is_all_day=False,
                    source_quote=normalized_policy_segment,
                    source_page=page["page"],
                    confidence=ConfidenceLevel.MEDIUM,
                    year_was_explicit=True,
                    uncertainty_reason=(
                        "The syllabus describes a recurring item without "
                        "identifying every date."
                    ),
                    extraction_model=extraction_model,
                    derivation_summary=derivation_summary,
                    review_status=ReviewStatus.NEEDS_REVIEW,
                )
            )
            known_titles.add(_stable_title_key("Lab assignment make-up deadline"))
            known_title_phrases.update(LAB_MAKEUP_TITLE_ALIASES)

    has_quiz_assessment = any(
        item.event_type == "quiz"
        or (
            item.event_type != "class"
            and re.search(r"\bquiz(?:zes)?\b", item.title, re.IGNORECASE)
        )
        for item in [*events, *extraction.recurring_rules]
    )
    if not has_quiz_assessment:
        graded_quiz_heading = re.compile(
            r"^[ \t]*quiz(?:zes)?\s*(?:\(\s*)?"
            r"(?P<weight>\d+(?:\.\d+)?)\s*%[ \t]*\)?",
            re.IGNORECASE | re.MULTILINE,
        )
        for page in pages:
            match = next(
                (
                    item for item in graded_quiz_heading.finditer(page["text"])
                    if 0 < float(item.group("weight")) <= 100
                ),
                None,
            )
            if match is None:
                continue
            events.append(
                CandidateEvent(
                    title="Quizzes",
                    event_type="quiz",
                    event_date=None,
                    start_time=None,
                    end_time=None,
                    is_all_day=True,
                    source_quote=re.sub(r"\s+", " ", match.group(0)).strip(),
                    source_page=page["page"],
                    confidence=ConfidenceLevel.MEDIUM,
                    year_was_explicit=False,
                    uncertainty_reason=(
                        "The syllabus lists graded quizzes without individual dates."
                    ),
                    extraction_model=extraction_model,
                    derivation_summary=REVIEW_ONLY_DERIVATION_SUMMARY,
                    review_status=ReviewStatus.NEEDS_REVIEW,
                )
            )
            break

    return extraction.model_copy(update={"events": events})


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
    series_payloads: list[ExpandedRecurringSeries] = []
    derived_events: list[CandidateEvent] = []

    for rule in rules:
        if rule.expansion_mode == "review_only":
            continue
        if _is_non_actionable_section_meeting_rule(rule):
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
            matching_anchors = _find_matching_anchors(rule, anchors)
            if not matching_anchors:
                continue
            anchor_sources = []
            occurrence_dates = []
            exclusions = set(rule.exclusion_dates)
            for anchor in matching_anchors:
                anchor_sources.append(
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
                        "derivation_summary": anchor.derivation_summary,
                        "occurrences": [
                            occurrence.model_dump(mode="json")
                            for occurrence in anchor.occurrences
                        ],
                    }
                )
                for anchor_date in _anchor_occurrences(anchor, semester_start, semester_end):
                    derived_date = anchor_date.fromordinal(
                        anchor_date.toordinal() + rule.offset_days
                    )
                    if range_start <= derived_date <= range_end and derived_date not in exclusions:
                        occurrence_dates.append(derived_date)

        deduped_dates: list[date] = []
        seen_dates: set[date] = set()
        for occurrence_date in sorted(occurrence_dates):
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
        summary = _rule_summary(rule, range_start, range_end)
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


def _find_unresolved_exact_anchor_rules(
    extraction: SyllabusExtraction,
    pages: list[dict],
) -> list[RecurringRule]:
    return [
        rule
        for rule in extraction.recurring_rules
        if _requires_exact_anchor(rule)
        and not _rule_requires_review_only(rule, pages)
        and not _find_matching_anchors(rule, extraction.schedule_anchors)
    ]


def _materialize_unresolved_recurring_review_events(
    extraction: SyllabusExtraction,
    pages: list[dict],
    *,
    extraction_model: str,
) -> tuple[SyllabusExtraction, dict[tuple[str, date | None], str]]:
    """Keep omitted rules and unmatched anchors visible without a second model call."""
    events = [event.model_copy(deep=True) for event in extraction.events]
    unresolved: dict[tuple[str, date | None], str] = {}
    candidates = [
        (
            candidate["title"], "assignment", candidate["source_quote"],
            candidate["source_page"], ConfidenceLevel.MEDIUM, None, None, True,
            "RECURRING_RULE_MISSING",
            "Dates were not generated because the primary extraction "
            "omitted the recurring schedule.",
        )
        for candidate in _find_missing_recurring_rule_candidates(extraction, pages)
    ]
    candidates.extend(
        (
            _display_title(rule.title), rule.event_type, rule.source_quote,
            rule.source_page, _cap_confidence_for_ambiguous_recurrence(rule.confidence),
            rule.start_time, rule.end_time, rule.is_all_day, "ANCHOR_NOT_FOUND",
            "Dates were not generated because the referenced schedule anchor "
            "could not be resolved.",
        )
        for rule in _find_unresolved_exact_anchor_rules(extraction, pages)
    )
    for (title, event_type, quote, page, confidence, start, end, all_day,
         warning_code, reason) in candidates:
        index = next((
            index for index, event in enumerate(events)
            if _stable_title_key(event.title) == _stable_title_key(title)
            and event.event_date is None
        ), None)
        if index is None:
            events.append(CandidateEvent(
                title=title, event_type=event_type, event_date=None,
                start_time=start, end_time=end, is_all_day=all_day,
                source_quote=quote, source_page=page, confidence=confidence,
                year_was_explicit=True, extraction_model=extraction_model,
                derivation_summary=reason, review_status=ReviewStatus.NEEDS_REVIEW,
            ))
            index = len(events) - 1
        else:
            events[index] = events[index].model_copy(update={
                "title": title, "event_date": None, "recurring_series_id": None,
                "source_quote": quote, "source_page": page,
                "extraction_model": extraction_model, "derivation_summary": reason,
                "review_status": ReviewStatus.NEEDS_REVIEW,
            })
        canonical_title = _canonicalize_event_identity(events[index]).title
        unresolved[(_normalize_title(canonical_title), None)] = warning_code
    return extraction.model_copy(update={"events": events}), unresolved


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


def _extract_source_date_weekday_matches(
    source_text: str,
    semester_start: date,
    semester_end: date,
) -> list[tuple[date, str, int, int]]:
    pairs_by_key: dict[tuple[date, str], tuple[date, str, int, int]] = {}
    for pattern in SOURCE_DATE_WEEKDAY_PATTERNS:
        for match in pattern.finditer(source_text):
            explicit_year = match.groupdict().get("year")
            years = (
                [int(explicit_year)]
                if explicit_year
                else list(range(semester_start.year, semester_end.year + 1))
            )
            matching_dates: list[date] = []
            for year in years:
                try:
                    parsed_date = date_parser.parse(
                        f"{match.group('day')} {match.group('month')} {year}",
                        dayfirst=True,
                        fuzzy=False,
                    ).date()
                except (OverflowError, ValueError):
                    continue
                if semester_start <= parsed_date <= semester_end:
                    matching_dates.append(parsed_date)
            matching_dates = list(dict.fromkeys(matching_dates))
            if len(matching_dates) != 1:
                continue
            pair = (matching_dates[0], match.group("weekday").capitalize())
            pairs_by_key.setdefault(pair, (*pair, match.start(), match.end()))
    return sorted(pairs_by_key.values(), key=lambda item: item[2])


def _find_whitespace_tolerant_quote_matches(
    source_quote: str,
    source_text: str,
) -> list[tuple[int, int]]:
    quote_parts = [re.escape(part) for part in re.split(r"\s+", source_quote.strip()) if part]
    if not quote_parts:
        return []
    return [
        (match.start(), match.end())
        for match in re.finditer(r"\s+".join(quote_parts), source_text, re.IGNORECASE)
    ]


def _nearest_preceding_quote_pair(
    source_text: str,
    quote_start: int,
    semester_start: date,
    semester_end: date,
) -> tuple[date, str] | None:
    context_start = max(0, quote_start - 120)
    preceding_context = source_text[context_start:quote_start]
    context_matches = _extract_source_date_weekday_matches(
        preceding_context,
        semester_start,
        semester_end,
    )
    if not context_matches:
        return None
    source_date, source_weekday, _, _ = context_matches[-1]
    return source_date, source_weekday


def _source_numeric_date_and_weekday(
    candidate: CandidateEvent,
    semester_start: date,
    semester_end: date,
    pages: list[dict] | None = None,
) -> tuple[date, str] | None:
    quote_matches = _extract_source_date_weekday_matches(
        candidate.source_quote,
        semester_start,
        semester_end,
    )
    quote_pairs = [
        (source_date, source_weekday)
        for source_date, source_weekday, _, _ in quote_matches
    ]
    if len(quote_pairs) == 1:
        return quote_pairs[0]
    if len(quote_pairs) > 1 and candidate.event_date is not None:
        matching_candidate_pairs = [
            source_pair for source_pair in quote_pairs if source_pair[0] == candidate.event_date
        ]
        if len(matching_candidate_pairs) == 1:
            return matching_candidate_pairs[0]
        return None
    if quote_pairs:
        return None
    if not pages:
        return None
    source_page = next(
        (page for page in pages if page["page"] == candidate.source_page),
        None,
    )
    if source_page is None:
        return None
    quote_matches = _find_whitespace_tolerant_quote_matches(
        candidate.source_quote,
        source_page["text"],
    )
    if not quote_matches:
        return None
    occurrence_pairs = [
        source_pair
        for source_pair in [
            _nearest_preceding_quote_pair(
                source_page["text"],
                quote_start,
                semester_start,
                semester_end,
            )
            for quote_start, _ in quote_matches
        ]
        if source_pair is not None
    ]
    occurrence_pairs = list(dict.fromkeys(occurrence_pairs))
    if not occurrence_pairs:
        return None
    if len(occurrence_pairs) == 1:
        return occurrence_pairs[0]
    if candidate.event_date is None:
        return None
    matching_candidate_pairs = [
        source_pair for source_pair in occurrence_pairs if source_pair[0] == candidate.event_date
    ]
    if len(matching_candidate_pairs) == 1:
        return matching_candidate_pairs[0]
    return None


def _is_source_weekday_typo(
    candidate: CandidateEvent,
    semester_start: date,
    semester_end: date,
    pages: list[dict] | None = None,
) -> bool:
    source_details = _source_numeric_date_and_weekday(
        candidate,
        semester_start,
        semester_end,
        pages,
    )
    if source_details is None:
        return False
    source_date, source_weekday = source_details
    return source_weekday.casefold() != source_date.strftime("%A").casefold()


def source_quote_has_weekday_typo(
    source_quote: str,
    event_date: date | None,
    semester_start: date,
    semester_end: date,
) -> bool:
    matches = _extract_source_date_weekday_matches(
        source_quote,
        semester_start,
        semester_end,
    )
    if event_date is not None:
        matches = [match for match in matches if match[0] == event_date]
    pairs = {(source_date, weekday) for source_date, weekday, _, _ in matches}
    if len(pairs) != 1:
        return False
    source_date, source_weekday = next(iter(pairs))
    return source_weekday.casefold() != source_date.strftime("%A").casefold()


def _normalize_explicit_source_event_dates(
    extraction: SyllabusExtraction,
    semester_start: date,
    semester_end: date,
    pages: list[dict] | None = None,
) -> SyllabusExtraction:
    normalized_events: list[CandidateEvent] = []
    for candidate in extraction.events:
        source_details = _source_numeric_date_and_weekday(
            candidate,
            semester_start,
            semester_end,
            pages,
        )
        if source_details is None:
            normalized_events.append(candidate)
            continue
        source_date, source_weekday = source_details
        update: dict[str, object] = {}
        if candidate.event_date != source_date:
            update["event_date"] = source_date
        if source_weekday.casefold() != source_date.strftime("%A").casefold():
            update["uncertainty_reason"] = None
            update["derivation_summary"] = None
        normalized_events.append(candidate.model_copy(update=update) if update else candidate)
    return extraction.model_copy(
        update={
            "events": [normalize_source_clock(event, pages or []) for event in normalized_events],
            "recurring_rules": [
                normalize_source_clock(rule, pages or []) for rule in extraction.recurring_rules
            ],
            "schedule_anchors": [
                normalize_source_clock(anchor, pages or [])
                for anchor in extraction.schedule_anchors
            ],
        }
    )


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
    source_details = _source_numeric_date_and_weekday(
        candidate,
        semester_start,
        semester_end,
        pages,
    )
    source_weekday_typo = False
    if source_details is not None:
        source_date, source_weekday = source_details
        actual_weekday = source_date.strftime("%A")
        if source_weekday.casefold() != actual_weekday.casefold():
            source_weekday_typo = True
            codes.append("DATE_CONFLICT")
            reasons.append(SYLLABUS_TYPO_WARNING)
    if not candidate.year_was_explicit and not source_weekday_typo:
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

    time_conflict = clock_conflict(candidate, pages)
    if time_conflict:
        codes.append("TIME_CONFLICT")
        reasons.append(time_conflict)

    if candidate.confidence == ConfidenceLevel.LOW:
        codes.append("LOW_CONFIDENCE")
        reasons.append(candidate.uncertainty_reason or "The extraction has low confidence.")
    elif candidate.uncertainty_reason:
        codes.append("MODEL_UNCERTAINTY")
        reasons.append(candidate.uncertainty_reason)
    return codes, " ".join(dict.fromkeys(reasons)) or None


def _update_job(
    session: Session, job: ProcessingJob, status: JobStatus, detail: str,
    *, execution_id: str,
) -> None:
    fence_job_execution(session, job.id, execution_id)
    job.status = status
    job.stage_detail = detail
    job.updated_at = datetime.now(UTC)
    session.commit()


def process_job(
    job_id: str,
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
    execution_id: str | None = None,
) -> None:
    settings = settings or get_settings()
    if session_factory is None:
        _, session_factory = configure_database(settings.database_url)

    job_uuid = UUID(job_id)
    if execution_id is None:
        # Direct/manual callers can adopt the currently queued generation.
        # Celery always supplies its reserved task id, so delayed deliveries
        # never adopt a newer generation.
        with session_factory() as session:
            execution_id = session.scalar(
                select(ProcessingJob.execution_id).where(
                    ProcessingJob.id == job_uuid, ProcessingJob.status == JobStatus.QUEUED,
                )
            ) or str(uuid4())
    claimed = False
    try:
        with session_factory() as session:
            claimed = claim_job(session, job_uuid, execution_id)
            if not claimed:
                return
            job = session.scalar(
                select(ProcessingJob)
                .options(
                    selectinload(ProcessingJob.document).selectinload(SyllabusDocument.semester)
                )
                .where(ProcessingJob.id == job_uuid)
            )
            if job is None:
                return

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
                    execution_id=execution_id,
                ),
            )
            if used_ocr:
                _update_job(
                    session, job, JobStatus.RUNNING_OCR, "OCR completed for scanned pages",
                    execution_id=execution_id,
                )
            job.document.extracted_pages = pages
            job.document.used_ocr = used_ocr
            job.primary_model = (
                settings.openai_model if settings.extraction_mode == "openai" else None
            )
            job.fallback_model = None
            job.fallback_used = False
            job.fallback_reason_codes = []
            _update_job(
                session, job, JobStatus.EXTRACTING_EVENTS, "Extracting course dates",
                execution_id=execution_id,
            )
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

            unresolved_review_codes: dict[tuple[str, date | None], str] = {}
            if settings.extraction_mode == "openai":
                extraction = extract_with_openai(pages, settings)
                _apply_extraction_model(extraction, settings.openai_model)
                extraction = _normalize_explicit_source_event_dates(
                    extraction, job.document.semester.start_date,
                    job.document.semester.end_date, pages,
                )
            else:
                extraction = extract_syllabus(pages, settings)
            materialized_model = (
                settings.openai_model if settings.extraction_mode == "openai" else None
            )
            extraction = _materialize_missing_ambiguous_review_events(
                extraction,
                pages,
                extraction_model=materialized_model,
            )
            extraction = _filter_non_actionable_course_structure_items(extraction)
            extraction, ambiguous_event_indexes, ambiguous_warning_reason = (
                _normalize_ambiguous_recurring_content(extraction, pages)
            )
            deduplicated_events, retained_indexes = deduplicate_summary_events(
                extraction.events, pages
            )
            extraction = extraction.model_copy(update={"events": deduplicated_events})
            ambiguous_event_indexes = {
                retained_indexes[index]
                for index in ambiguous_event_indexes
                if index in retained_indexes
            }
            extraction = _normalize_explicit_source_event_dates(
                extraction,
                job.document.semester.start_date,
                job.document.semester.end_date,
                pages,
            )
            if settings.extraction_mode == "openai":
                # These placeholders represent unresolved schedules, not single dates.
                # Create them after date normalization so nearby dates cannot fill them.
                extraction, unresolved_review_codes = (
                    _materialize_unresolved_recurring_review_events(
                        extraction, pages, extraction_model=settings.openai_model,
                    )
                )
            _update_job(
                session, job, JobStatus.VALIDATING, "Checking dates and source evidence",
                execution_id=execution_id,
            )

            # Keep the ownership row locked through all event/course replacement
            # writes and the final commit. A timeout/retry cannot interleave.
            fence_job_execution(session, job_uuid, execution_id)

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
                warning_codes, warning_reason = _validate_rule(
                    matching_rule,
                    pages,
                    extraction.schedule_anchors,
                )
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
                    fallback_reason_codes=[],
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
                candidate = _canonicalize_event_identity(candidate)
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
                    if "TIME_CONFLICT" in warning_codes:
                        warning_reason = " ".join(dict.fromkeys(
                            part for part in (warning_reason, ambiguous_warning_reason) if part
                        )) or None
                    else:
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
                unresolved_code = unresolved_review_codes.get(
                    (_normalize_title(candidate.title), candidate.event_date)
                )
                if unresolved_code:
                    warning_codes.append(unresolved_code)
                    warning_reason = " ".join(
                        part for part in (warning_reason, candidate.derivation_summary) if part
                    ) or None
                if candidate.recurring_series_id is not None:
                    series_payload = series_map.get(candidate.recurring_series_id)
                    if series_payload is not None:
                        warning_codes = [*series_payload.warning_codes, *warning_codes]
                        warning_reason = " ".join(
                            part
                            for part in [series_payload.warning_reason, warning_reason]
                            if part
                        ) or None
                # TIME_CONFLICT above retains the original offset in its reason.
                # SQL TIME columns discard offsets, so unresolved values must not
                # silently become plausible local clock times during persistence.
                invalid_clock_fields = {
                    field: None
                    for field in ("start_time", "end_time")
                    if getattr(candidate, field) is not None
                    and getattr(candidate, field).tzinfo is not None
                }
                if invalid_clock_fields:
                    candidate = candidate.model_copy(update=invalid_clock_fields)
                    if candidate.start_time is None and candidate.end_time is None:
                        candidate = candidate.model_copy(update={"is_all_day": True})
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
                        fallback_reason_codes=[],
                        derivation_summary=candidate.derivation_summary,
                        review_status=ReviewStatus.NEEDS_REVIEW,
                    )
                )
            job.document.semester.review_completed_at = None
            job.status = JobStatus.NEEDS_REVIEW
            job.stage_detail = "Ready for review"
            job.error_message = None
            job.completed_at = None
            session.commit()
    except StaleJobExecution:
        return
    except Exception as error:
        log_processing_failure(job_id, error)
        if claimed:
            fail_job_execution(session_factory, job_uuid, execution_id, error)
