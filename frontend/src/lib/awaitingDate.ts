import { isCourseRule } from "./courseRules"
import type { ExtractedEvent } from "./types"

export function isAwaitingDate(
  event: Pick<ExtractedEvent, "event_date" | "review_status" | "warning_codes" | "recurring_series_id">,
) {
  return (
    event.review_status === "pending" &&
    event.event_date === null &&
    (event.recurring_series_id === null || typeof event.recurring_series_id === "undefined") &&
    !isCourseRule(event)
  )
}
