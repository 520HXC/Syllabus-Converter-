from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from enum import StrEnum

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, ForeignKey, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class JobStatus(StrEnum):
    QUEUED = "queued"
    EXTRACTING_TEXT = "extracting_text"
    RUNNING_OCR = "running_ocr"
    EXTRACTING_EVENTS = "extracting_events"
    VALIDATING = "validating"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    FAILED = "failed"


class ConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ReviewStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    IGNORED = "ignored"


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class Semester(Base):
    __tablename__ = "semesters"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(120))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String(80))
    review_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    courses: Mapped[list[Course]] = relationship(
        back_populates="semester", cascade="all, delete-orphan"
    )
    documents: Mapped[list[SyllabusDocument]] = relationship(
        back_populates="semester", cascade="all, delete-orphan"
    )
    events: Mapped[list[ExtractedEvent]] = relationship(
        back_populates="semester", cascade="all, delete-orphan"
    )
    recurring_series: Mapped[list[RecurringEventSeries]] = relationship(
        back_populates="semester", cascade="all, delete-orphan"
    )


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    semester_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("syllabus_documents.id", ondelete="SET NULL"), unique=True, index=True
    )
    code: Mapped[str | None] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    instructor: Mapped[str | None] = mapped_column(String(160))
    color: Mapped[str] = mapped_column(String(7), default="#0D9488")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    semester: Mapped[Semester] = relationship(back_populates="courses")
    events: Mapped[list[ExtractedEvent]] = relationship(back_populates="course")
    recurring_series: Mapped[list[RecurringEventSeries]] = relationship(back_populates="course")


class SyllabusDocument(Base):
    __tablename__ = "syllabus_documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    semester_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100), default="application/pdf")
    size_bytes: Mapped[int]
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    extracted_pages: Mapped[list[dict]] = mapped_column(JSON, default=list)
    used_ocr: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    semester: Mapped[Semester] = relationship(back_populates="documents")
    job: Mapped[ProcessingJob] = relationship(
        back_populates="document", cascade="all, delete-orphan", uselist=False
    )
    recurring_series: Mapped[list[RecurringEventSeries]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    semester_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("syllabus_documents.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.QUEUED)
    stage_detail: Mapped[str | None] = mapped_column(String(240))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(default=0)
    primary_model: Mapped[str | None] = mapped_column(String(80))
    fallback_model: Mapped[str | None] = mapped_column(String(80))
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    fallback_reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[SyllabusDocument] = relationship(back_populates="job")


class RecurringEventSeries(Base):
    __tablename__ = "recurring_event_series"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    semester_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("syllabus_documents.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(240))
    event_type: Mapped[str] = mapped_column(String(40))
    rule_kind: Mapped[str] = mapped_column(String(40))
    rule_summary: Mapped[str] = mapped_column(Text)
    source_quote: Mapped[str] = mapped_column(Text)
    source_page: Mapped[int] = mapped_column(default=1)
    anchor_sources: Mapped[list[dict]] = mapped_column(JSON, default=list)
    rule_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[ConfidenceLevel] = mapped_column(Enum(ConfidenceLevel))
    warning_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    warning_reason: Mapped[str | None] = mapped_column(Text)
    extraction_model: Mapped[str | None] = mapped_column(String(80))
    fallback_reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    semester: Mapped[Semester] = relationship(back_populates="recurring_series")
    course: Mapped[Course] = relationship(back_populates="recurring_series")
    document: Mapped[SyllabusDocument | None] = relationship(back_populates="recurring_series")
    events: Mapped[list[ExtractedEvent]] = relationship(back_populates="recurring_series")

    @property
    def occurrence_count(self) -> int:
        return len(self.events)

    @property
    def computed_review_status(self) -> str:
        statuses = {event.review_status.value for event in self.events}
        if not statuses:
            return ReviewStatus.NEEDS_REVIEW.value
        if ReviewStatus.NEEDS_REVIEW.value in statuses:
            return ReviewStatus.NEEDS_REVIEW.value
        if len(statuses) == 1:
            return next(iter(statuses))
        return "mixed"


class ExtractedEvent(Base):
    __tablename__ = "extracted_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    semester_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("syllabus_documents.id", ondelete="SET NULL"), index=True
    )
    recurring_series_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recurring_event_series.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(240))
    event_type: Mapped[str] = mapped_column(String(40))
    event_date: Mapped[date | None] = mapped_column(Date)
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    timezone: Mapped[str] = mapped_column(String(80))
    is_all_day: Mapped[bool] = mapped_column(Boolean, default=True)
    source_quote: Mapped[str] = mapped_column(Text)
    source_page: Mapped[int] = mapped_column(default=1)
    confidence: Mapped[ConfidenceLevel] = mapped_column(Enum(ConfidenceLevel))
    warning_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    warning_reason: Mapped[str | None] = mapped_column(Text)
    extraction_model: Mapped[str | None] = mapped_column(String(80))
    fallback_reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    derivation_summary: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[ReviewStatus] = mapped_column(Enum(ReviewStatus))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    semester: Mapped[Semester] = relationship(back_populates="events")
    course: Mapped[Course] = relationship(back_populates="events")
    recurring_series: Mapped[RecurringEventSeries | None] = relationship(back_populates="events")
