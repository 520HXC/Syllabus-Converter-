export type JobStatus =
  | "queued"
  | "extracting_text"
  | "running_ocr"
  | "extracting_events"
  | "validating"
  | "needs_review"
  | "completed"
  | "failed"

export type ConfidenceLevel = "high" | "medium" | "low"
export type ReviewStatus = "needs_review" | "pending" | "confirmed" | "ignored"
export type RecurringSeriesStatus = ReviewStatus | "mixed"

export interface Semester {
  id: string
  name: string
  start_date: string
  end_date: string
  timezone: string
  review_completed_at: string | null
  course_count: number
  document_count: number
  event_count: number
  needs_review_count: number
}

export interface Course {
  id: string
  document_id: string | null
  code: string | null
  name: string
  instructor: string | null
  color: string
}

export type CourseUpdatePayload = Partial<Pick<Course, "code" | "name" | "instructor" | "color">>

export interface SyllabusDocument {
  id: string
  filename: string
  size_bytes: number
  used_ocr: boolean
}

export interface ProcessingJob {
  id: string
  document_id: string
  filename: string | null
  status: JobStatus
  stage_detail: string | null
  error_message: string | null
  attempts: number
  primary_model?: string | null
  fallback_model?: string | null
  fallback_used?: boolean
  fallback_reason_codes?: string[]
}

export interface ExtractedEvent {
  id: string
  semester_id: string
  course_id: string
  document_id: string | null
  title: string
  event_type: string
  event_date: string | null
  start_time: string | null
  end_time: string | null
  timezone: string
  is_all_day: boolean
  source_quote: string
  source_page: number
  confidence: ConfidenceLevel
  warning_codes: string[]
  warning_reason: string | null
  review_status: ReviewStatus
  extraction_model?: string | null
  fallback_reason_codes?: string[]
  recurring_series_id?: string | null
  derivation_summary?: string | null
}

export interface RecurringSourceReference {
  event_date?: string | null
  source_page: number
  source_quote: string
  [key: string]: unknown
}

export interface RecurringEventSeries {
  id: string
  semester_id: string
  course_id: string
  document_id: string | null
  title: string
  event_type: string
  rule_kind: "weekly_fixed" | "relative_to_anchor"
  rule_summary: string
  rule_payload?: Record<string, unknown>
  source_quote: string
  source_page: number
  anchor_sources: RecurringSourceReference[]
  confidence: ConfidenceLevel
  warning_codes: string[]
  warning_reason: string | null
  extraction_model: string | null
  fallback_reason_codes?: string[]
  occurrence_count: number
  review_status: RecurringSeriesStatus
}

export interface ReviewPayload {
  semester: Semester
  courses: Course[]
  documents: SyllabusDocument[]
  events: ExtractedEvent[]
  recurring_series?: RecurringEventSeries[]
}

export interface ReviewBlockingDetail {
  detail: string
  blocking_event_ids: string[]
  blocking_document_ids: string[]
  blocking_count: number
}

export interface ReviewCompleteResponse {
  review_completed_at: string
}

export interface EventUpdate {
  title?: string
  event_type?: string
  event_date?: string | null
  start_time?: string | null
  end_time?: string | null
  is_all_day?: boolean
  review_status?: ReviewStatus
}

export interface RecurringSeriesUpdate {
  review_status: ReviewStatus
}
