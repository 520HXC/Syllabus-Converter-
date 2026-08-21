from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import ConfidenceLevel, JobStatus, ReviewStatus


class SemesterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    start_date: date
    end_date: date
    timezone: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_dates_and_timezone(self):
        if self.end_date < self.start_date:
            raise ValueError("Semester end date must be on or after the start date.")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Use a valid IANA timezone.") from error
        return self


class SemesterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    start_date: date
    end_date: date
    timezone: str
    review_completed_at: datetime | None
    course_count: int = 0
    document_count: int = 0
    event_count: int = 0
    needs_review_count: int = 0


class CourseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID | None
    code: str | None
    name: str
    instructor: str | None
    color: str


class CourseUpdate(BaseModel):
    code: str | None = Field(default=None, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    instructor: str | None = Field(default=None, max_length=160)
    color: str = Field(default=None, pattern=r"^#[0-9A-F]{6}$")


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    size_bytes: int
    used_ocr: bool


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    status: JobStatus
    stage_detail: str | None
    error_message: str | None
    attempts: int
    filename: str | None = None
    primary_model: str | None = None
    fallback_model: str | None = None
    fallback_used: bool = False
    fallback_reason_codes: list[str] = Field(default_factory=list)


class UploadResponse(BaseModel):
    jobs: list[JobRead]


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    semester_id: UUID
    course_id: UUID
    document_id: UUID | None
    recurring_series_id: UUID | None
    title: str
    event_type: str
    event_date: date | None
    start_time: time | None
    end_time: time | None
    timezone: str
    is_all_day: bool
    source_quote: str
    source_page: int
    confidence: ConfidenceLevel
    warning_codes: list[str]
    warning_reason: str | None
    extraction_model: str | None
    fallback_reason_codes: list[str]
    derivation_summary: str | None
    review_status: ReviewStatus


class RecurringSeriesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    semester_id: UUID
    course_id: UUID
    document_id: UUID | None
    title: str
    event_type: str
    rule_kind: str
    rule_summary: str
    source_quote: str
    source_page: int
    anchor_sources: list[dict]
    rule_payload: dict
    confidence: ConfidenceLevel
    warning_codes: list[str]
    warning_reason: str | None
    extraction_model: str | None
    fallback_reason_codes: list[str]
    occurrence_count: int
    review_status: str = Field(validation_alias="computed_review_status")


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    event_type: str | None = Field(default=None, min_length=1, max_length=40)
    event_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    is_all_day: bool | None = None
    review_status: ReviewStatus | None = None


class RecurringSeriesUpdate(BaseModel):
    review_status: ReviewStatus


class ReviewResponse(BaseModel):
    semester: SemesterRead
    courses: list[CourseRead]
    documents: list[DocumentRead]
    events: list[EventRead]
    recurring_series: list[RecurringSeriesRead]


class ReviewCompleteResponse(BaseModel):
    review_completed_at: datetime


class ReviewCompleteConflict(BaseModel):
    detail: str
    blocking_event_ids: list[UUID]
    blocking_document_ids: list[UUID]
    blocking_count: int
