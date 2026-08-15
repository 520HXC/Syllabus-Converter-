export type ReviewAttentionTarget = "date" | "source" | "card"

const dateWarningCodes = new Set([
  "AMBIGUOUS_DATE",
  "DATE_MISSING",
  "DATE_CONFLICT",
  "OUTSIDE_SEMESTER",
  "YEAR_NOT_EXPLICIT",
])

const sourceWarningCodes = new Set(["SOURCE_MISMATCH", "SOURCE_PAGE_MISSING"])

export function getReviewAttentionTarget(warningCodes: string[]): ReviewAttentionTarget {
  if (warningCodes.some((code) => dateWarningCodes.has(code))) return "date"
  if (warningCodes.some((code) => sourceWarningCodes.has(code))) return "source"
  return "card"
}

export function getReviewFallbackMessage(warningCodes: string[]): string {
  return "Review this AI extracted event before continuing"
}
