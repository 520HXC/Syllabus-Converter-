import type { ConfidenceLevel } from "./types"

const eventTypeBadgeClasses: Record<string, string> = {
  class: "border-event-class-border bg-event-class-soft text-event-class",
  deadline: "border-event-deadline-border bg-event-deadline-soft text-event-deadline",
  assignment: "border-event-assignment-border bg-event-assignment-soft text-event-assignment",
  exam: "border-event-exam-border bg-event-exam-soft text-event-exam",
  reading: "border-event-reading-border bg-event-reading-soft text-event-reading",
  lecture: "border-event-lecture-border bg-event-lecture-soft text-event-lecture",
  meeting: "border-event-meeting-border bg-event-meeting-soft text-event-meeting",
  other: "border-event-other-border bg-event-other-soft text-event-other",
  presentation: "border-event-presentation-border bg-event-presentation-soft text-event-presentation",
  project: "border-event-project-border bg-event-project-soft text-event-project",
  quiz: "border-event-quiz-border bg-event-quiz-soft text-event-quiz",
}

const fallbackEventTypeBadgeClass = "border-border bg-panel-muted/70 text-text-muted"

const confidenceBadgeClasses: Record<ConfidenceLevel, string> = {
  high: "border-confidence-high-border bg-confidence-high-soft text-confidence-high",
  medium: "border-confidence-medium-border bg-confidence-medium-soft text-confidence-medium",
  low: "border-confidence-low-border bg-confidence-low-soft text-confidence-low",
}

export function normalizeEventType(eventType: string) {
  const normalized = eventType.trim().toLowerCase()
  return normalized in eventTypeBadgeClasses ? normalized : "unknown"
}

export function getEventTypeBadgeClass(eventType: string) {
  const normalized = normalizeEventType(eventType)
  return eventTypeBadgeClasses[normalized] ?? fallbackEventTypeBadgeClass
}

export function getEventTypeLabel(eventType: string) {
  return normalizeEventType(eventType)
}

export function getConfidenceBadgeClass(confidence: ConfidenceLevel) {
  return confidenceBadgeClasses[confidence]
}
