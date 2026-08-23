import { useEffect, useId, useRef, useState } from "react"
import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  PencilLine,
  Repeat,
  Save,
  Trash2,
  X,
} from "lucide-react"

import { EventTypeBadge } from "./EventTypeBadge"
import { formatFallbackReasons } from "../lib/modelRouting"
import { getConfidenceBadgeClass } from "../lib/reviewBadges"
import { getReviewFallbackMessage } from "../lib/review"
import type { EventUpdate, ExtractedEvent } from "../lib/types"
import { cn } from "../lib/utils"
import { Badge } from "./ui/Badge"
import { Button } from "./ui/Button"
import { Card } from "./ui/Card"
import { Input } from "./ui/Input"

const eventTypeSuggestions = [
  "assignment",
  "class",
  "deadline",
  "exam",
  "lecture",
  "meeting",
  "other",
  "presentation",
  "project",
  "quiz",
  "reading",
]

function formatConfidence(confidence: ExtractedEvent["confidence"]) {
  if (confidence === "high") return "High confidence"
  if (confidence === "medium") return "Medium confidence"
  return "Low confidence"
}

function getStatusCopy(reviewStatus: ExtractedEvent["review_status"]) {
  if (reviewStatus === "needs_review") {
    return {
      copy: "Needs review",
      className: "border border-warning-border bg-warning-soft text-warning",
    }
  }
  return {
    copy: "Saved",
    className: "border border-accent/15 bg-accent/10 text-accent",
  }
}

function normalizeReason(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, " ").replace(/[.!?]+$/g, "")
}

export function CourseRuleCard({
  event,
  courseLabel,
  courseColor,
  onSave,
}: {
  event: ExtractedEvent
  courseLabel: string
  courseColor: string
  onSave: (eventId: string, update: EventUpdate) => Promise<void>
}) {
  const errorId = useId()
  const titleId = useId()
  const eventTypeListId = useId()
  const fallbackReasons = formatFallbackReasons(event.fallback_reason_codes ?? [])
  const modifyButtonRef = useRef<HTMLButtonElement>(null)
  const titleRef = useRef<HTMLInputElement>(null)
  const previousEventIdRef = useRef(event.id)
  const [title, setTitle] = useState(event.title)
  const [eventType, setEventType] = useState(event.event_type)
  const [isEditing, setIsEditing] = useState(false)
  const [saving, setSaving] = useState<"pending" | "ignored" | "changes" | null>(null)
  const [error, setError] = useState<string | null>(null)

  const status = getStatusCopy(event.review_status)
  const isSavedRule = event.review_status === "pending"
  const attentionReason = getReviewFallbackMessage(event.warning_codes)
  const showDerivationSummary = Boolean(event.derivation_summary) &&
    (event.review_status !== "needs_review" ||
      normalizeReason(event.derivation_summary ?? "") !== normalizeReason(attentionReason))

  useEffect(() => {
    if (previousEventIdRef.current !== event.id) {
      previousEventIdRef.current = event.id
      setTitle(event.title)
      setEventType(event.event_type)
      setIsEditing(false)
      setError(null)
      return
    }
    if (isEditing) return
    setTitle(event.title)
    setEventType(event.event_type)
    setError(null)
  }, [event.id, event.title, event.event_type, isEditing])

  useEffect(() => {
    if (!isEditing) return
    titleRef.current?.focus()
  }, [isEditing])

  function openEditor() {
    setIsEditing(true)
    setError(null)
  }

  function closeEditor() {
    setTitle(event.title)
    setEventType(event.event_type)
    setIsEditing(false)
    setError(null)
    modifyButtonRef.current?.focus()
  }

  async function save(nextStatus: ExtractedEvent["review_status"], closeAfterSave = false) {
    setSaving(closeAfterSave ? "changes" : nextStatus === "ignored" ? "ignored" : "pending")
    setError(null)

    try {
      await onSave(event.id, {
        title,
        event_type: eventType.trim() || event.event_type,
        review_status: nextStatus,
      })
      if (closeAfterSave) {
        setIsEditing(false)
        requestAnimationFrame(() => modifyButtonRef.current?.focus())
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The course rule could not be saved.")
    } finally {
      setSaving(null)
    }
  }

  return (
    <Card
      aria-labelledby={titleId}
      className={cn(
        "relative overflow-hidden border-border/80 bg-panel/95 p-4 shadow-panel sm:p-5",
        event.review_status === "needs_review" && "border-warning-border",
      )}
      data-review-event-id={event.id}
      tabIndex={-1}
    >
      <span
        aria-hidden="true"
        className="absolute inset-y-0 left-0 w-1"
        style={{ backgroundColor: courseColor }}
      />

      <div className="flex flex-col gap-3 pl-1">
        <header className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge
              className="border border-border bg-panel text-text"
              style={{ boxShadow: `inset 0 0 0 1px ${courseColor}22` }}
            >
              {courseLabel}
            </Badge>
            <EventTypeBadge eventType={event.event_type} />
            <Badge className={cn("border", getConfidenceBadgeClass(event.confidence))}>
              {formatConfidence(event.confidence)}
            </Badge>
            <Badge className="border border-warning-border bg-warning-soft text-warning">
              <Repeat aria-hidden="true" className="mr-1 size-3.5" />
              Recurring rule
            </Badge>
            <Badge className={status.className}>
              {status.copy === "Saved" ? (
                <CheckCircle2 aria-hidden="true" className="mr-1 size-3.5" />
              ) : null}
              {status.copy}
            </Badge>
            {event.extraction_model ? (
              <Badge className="border border-border bg-panel text-text-muted">
                {event.extraction_model.includes("terra") ? "Terra" : "Luna"}
              </Badge>
            ) : null}
          </div>

          <div className="mt-3">
            <h3 className="text-lg font-semibold tracking-[-0.02em] text-text" id={titleId}>
              {event.title}
            </h3>
            {event.extraction_model?.includes("terra") && fallbackReasons ? (
              <p className="mt-1 text-xs font-medium text-warning">
                Terra repaired {fallbackReasons}
              </p>
            ) : null}
          </div>
        </header>

        <div className="rounded-xl border border-border/80 bg-panel-muted/35 px-3.5 py-3">
          <div className="flex items-center justify-between gap-3">
            <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-text-subtle">
              <FileText aria-hidden="true" className="size-3.5 text-accent" />
              Syllabus says
            </p>
            <span className="shrink-0 text-xs font-semibold text-text-muted">
              Page {event.source_page}
            </span>
          </div>
          <blockquote className="mt-1.5 border-l-2 border-border-strong pl-3 text-sm leading-6 text-text">
            "{event.source_quote}"
          </blockquote>
        </div>

        {event.review_status === "needs_review" ? (
          <div className="flex gap-2.5 rounded-xl border border-warning-border bg-warning-soft px-3.5 py-3 text-sm text-warning">
            <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <div>
              <p className="font-semibold">Needs attention</p>
              <p className="mt-0.5 leading-6">{attentionReason}</p>
            </div>
          </div>
        ) : null}

        {showDerivationSummary ? (
          <div className="rounded-xl border border-accent/20 bg-accent/10 px-3.5 py-3 text-sm text-text-muted">
            <p className="font-semibold text-text">Why dates were not generated</p>
            <p className="mt-1 leading-6">{event.derivation_summary}</p>
          </div>
        ) : null}

        {isEditing ? (
          <section
            aria-label={`Modify ${event.title}`}
            className="rounded-xl border border-accent/25 bg-panel-muted/25 p-3.5 sm:p-4"
          >
            <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(11rem,0.55fr)]">
              <label className="grid gap-1.5 text-sm font-semibold text-text">
                Event name
                <Input
                  aria-label="Event name"
                  ref={titleRef}
                  value={title}
                  onChange={(nextEvent) => setTitle(nextEvent.target.value)}
                />
              </label>
              <label className="grid gap-1.5 text-sm font-semibold text-text">
                Event type
                <Input
                  aria-label="Event type"
                  list={eventTypeListId}
                  value={eventType}
                  onChange={(nextEvent) => setEventType(nextEvent.target.value)}
                />
              </label>
              <datalist id={eventTypeListId}>
                {eventTypeSuggestions.map((suggestion) => (
                  <option key={suggestion} value={suggestion} />
                ))}
              </datalist>
            </div>

            {error ? (
              <p className="mt-3 text-sm font-medium text-danger" id={`review-error-${errorId}`} role="alert">
                {error}
              </p>
            ) : null}

            <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:justify-end">
              <Button onClick={closeEditor} type="button" variant="secondary">
                <X aria-hidden="true" className="size-4" />
                Cancel
              </Button>
              <Button
                loading={saving === "changes"}
                onClick={() => void save(event.review_status, true)}
                type="button"
              >
                <Save aria-hidden="true" className="size-4" />
                Save changes
              </Button>
            </div>
          </section>
        ) : null}

        {!isEditing && error ? (
          <p className="text-sm font-medium text-danger" id={`review-error-${errorId}`} role="alert">
            {error}
          </p>
        ) : null}

        <div className="flex flex-col gap-3 border-t border-border/80 pt-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-text-muted">
            {isSavedRule
              ? "Saved in Course rules. You can modify or remove it anytime."
              : "Save course rule keeps this recurring policy available for later date generation."}
          </p>
          <div
            aria-live="polite"
            className="grid grid-cols-1 gap-2 sm:flex sm:flex-wrap sm:justify-end"
          >
            <Button
              aria-expanded={isEditing}
              aria-label={`Modify ${event.title}`}
              onClick={isEditing ? closeEditor : openEditor}
              ref={modifyButtonRef}
              type="button"
              variant="secondary"
            >
              <PencilLine aria-hidden="true" className="size-4" />
              {isEditing ? "Close editor" : "Modify"}
            </Button>
            <Button
              loading={saving === "ignored"}
              onClick={() => void save("ignored")}
              type="button"
              variant="danger"
            >
              <Trash2 aria-hidden="true" className="size-4" />
              Remove
            </Button>
            {isSavedRule ? (
              <Button
                className="border-accent/25 bg-accent/10 text-accent disabled:bg-accent/10 disabled:text-accent disabled:opacity-100"
                disabled
                type="button"
                variant="secondary"
              >
                <CheckCircle2 aria-hidden="true" className="size-4" />
                Saved to Course rules
              </Button>
            ) : (
              <Button loading={saving === "pending"} onClick={() => void save("pending")} type="button">
                <Save aria-hidden="true" className="size-4" />
                Save course rule
              </Button>
            )}
          </div>
        </div>
      </div>
    </Card>
  )
}
