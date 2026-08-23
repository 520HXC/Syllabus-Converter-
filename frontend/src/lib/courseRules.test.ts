import type { ExtractedEvent } from "./types"
import { isCourseRule } from "./courseRules"

const baseEvent: ExtractedEvent = {
  id: "event-1",
  semester_id: "semester-1",
  course_id: "course-1",
  document_id: "document-1",
  title: "Weekly quiz policy",
  event_type: "quiz",
  event_date: null,
  start_time: null,
  end_time: null,
  timezone: "America/New_York",
  is_all_day: true,
  source_quote: "Weekly quizzes happen during lecture",
  source_page: 2,
  confidence: "medium",
  warning_codes: [],
  warning_reason: null,
  review_status: "needs_review",
}

test("treats standalone ambiguous recurrence events as course rules", () => {
  expect(
    isCourseRule({
      ...baseEvent,
      warning_codes: ["AMBIGUOUS_RECURRENCE"],
      recurring_series_id: null,
    }),
  ).toBe(true)

  expect(
    isCourseRule({
      ...baseEvent,
      warning_codes: ["AMBIGUOUS_RECURRENCE"],
    }),
  ).toBe(true)
})

test("does not treat exact recurring series members or other warnings as course rules", () => {
  expect(
    isCourseRule({
      ...baseEvent,
      warning_codes: ["AMBIGUOUS_RECURRENCE"],
      recurring_series_id: "series-1",
    }),
  ).toBe(false)

  expect(
    isCourseRule({
      ...baseEvent,
      warning_codes: ["DATE_MISSING"],
      recurring_series_id: null,
    }),
  ).toBe(false)
})
