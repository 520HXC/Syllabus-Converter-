import type { ConfidenceLevel } from "./types"

const eventTypeBadgeClasses: Record<string, string> = {
  assignment: "border-event-assignment-border bg-event-assignment-soft text-event-assignment",
  exam: "border-event-exam-border bg-event-exam-soft text-event-exam",
  lecture: "border-event-lecture-border bg-event-lecture-soft text-event-lecture",
  meeting: "border-event-meeting-border bg-event-meeting-soft text-event-meeting",
  presentation: "border-event-presentation-border bg-event-presentation-soft text-event-presentation",
  project: "border-event-project-border bg-event-project-soft text-event-project",
  quiz: "border-event-quiz-border bg-event-quiz-soft text-event-quiz",
}

const confidenceBadgeClasses: Record<ConfidenceLevel, string> = {
  high: "border-confidence-high-border bg-confidence-high-soft text-confidence-high",
  medium: "border-confidence-medium-border bg-confidence-medium-soft text-confidence-medium",
  low: "border-confidence-low-border bg-confidence-low-soft text-confidence-low",
}

export function getEventTypeBadgeClass(eventType: string) {
  return eventTypeBadgeClasses[eventType.trim().toLowerCase()] ?? "border-border bg-panel-muted/70 text-text-muted"
}

export function getConfidenceBadgeClass(confidence: ConfidenceLevel) {
  return confidenceBadgeClasses[confidence]
}
