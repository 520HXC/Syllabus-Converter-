import type { ExtractedEvent } from "./types"

export function isCourseRule(
  event: Pick<ExtractedEvent, "warning_codes" | "recurring_series_id">,
) {
  return (
    event.warning_codes.includes("AMBIGUOUS_RECURRENCE") &&
    (event.recurring_series_id === null || typeof event.recurring_series_id === "undefined")
  )
}
