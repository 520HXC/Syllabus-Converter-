import { useEffect, useId, useLayoutEffect, useRef, useState } from "react"
import {
  AlertTriangle,
  CalendarClock,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock3,
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
import { getReviewAttentionTarget, getReviewFallbackMessage } from "../lib/review"
import type { EventUpdate, ExtractedEvent, ReviewStatus } from "../lib/types"
import { cn } from "../lib/utils"
import { Badge } from "./ui/Badge"
import { Button } from "./ui/Button"
import { Card } from "./ui/Card"
import { Input } from "./ui/Input"

type SaveAction = ReviewStatus | "changes"

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

function formatSuggestedDate(eventDate: string | null) {
  if (!eventDate) return "No date suggested yet"
  return new Intl.DateTimeFormat("en-US", { dateStyle: "long" }).format(
    new Date(`${eventDate}T12:00:00`),
  )
}

function formatTimeInputValue(time: string | null) {
  if (!time) return ""
  return time.slice(0, 5)
}

function normalizeTimeValue(time: string) {
  return time ? `${time}:00` : null
}

function getStatusChip(event: ExtractedEvent) {
  if (event.review_status === "pending") {
    return {
      copy: "Pending",
      className: "border border-warning-border bg-warning-soft text-warning",
    }
  }
  if (event.review_status === "confirmed") {
    return {
      copy: "Confirmed",
      className: "border border-accent/15 bg-accent/10 text-accent",
    }
  }
  return {
    copy: "Needs review",
    className: "border border-warning-border bg-warning-soft text-warning",
  }
}

function hasAmbiguousRecurrenceWarning(warningCodes: string[]) {
  return warningCodes.includes("AMBIGUOUS_RECURRENCE")
}

export function ReviewEventCard({
  event,
  courseLabel,
  courseColor,
  onSave,
  startEditing = false,
}: {
  event: ExtractedEvent
  courseLabel: string
  courseColor: string
  onSave: (eventId: string, update: EventUpdate) => Promise<void>
  startEditing?: boolean
}) {
  const fallbackReasons = formatFallbackReasons(event.fallback_reason_codes ?? [])
  const warningId = useId()
  const errorId = useId()
  const titleId = useId()
  const editorId = useId()
  const modifyButtonRef = useRef<HTMLButtonElement>(null)
  const titleRef = useRef<HTMLInputElement>(null)
  const eventDateRef = useRef<HTMLInputElement>(null)
  const [title, setTitle] = useState(event.title)
  const [eventType, setEventType] = useState(event.event_type)
  const [eventDate, setEventDate] = useState(event.event_date ?? "")
  const [startTime, setStartTime] = useState(formatTimeInputValue(event.start_time))
  const [endTime, setEndTime] = useState(formatTimeInputValue(event.end_time))
  const [isAllDay, setIsAllDay] = useState(event.is_all_day)
  const [isEditing, setIsEditing] = useState(false)
  const [editorFocusTarget, setEditorFocusTarget] = useState<"name" | "date" | null>(null)
  const [showMoreOptions, setShowMoreOptions] = useState(false)
  const [saving, setSaving] = useState<SaveAction | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [errorTarget, setErrorTarget] = useState<"date" | "general">("general")

  const attentionTarget = getReviewAttentionTarget(event.warning_codes)
  const hasAmbiguousRecurrence = hasAmbiguousRecurrenceWarning(event.warning_codes)
  const warningMessage = hasAmbiguousRecurrence
    ? getReviewFallbackMessage(event.warning_codes)
    : event.warning_reason ?? getReviewFallbackMessage(event.warning_codes)
  const isNeedsReview = event.review_status === "needs_review"
  const dateError = errorTarget === "date" ? error : null
  const generalError = errorTarget === "general" ? error : null
  const statusChip = getStatusChip(event)
  const dateDescriptionIds = [
    isNeedsReview && attentionTarget === "date" ? `review-warning-${warningId}` : null,
    errorTarget === "date" && error ? `review-error-${errorId}` : null,
  ]
    .filter(Boolean)
    .join(" ") || undefined
  const sourceDescriptionIds =
    isNeedsReview && attentionTarget === "source" ? `review-warning-${warningId}` : undefined
  const cardDescriptionIds =
    isNeedsReview && attentionTarget === "card" ? `review-warning-${warningId}` : undefined

  function resetDraft() {
    setTitle(event.title)
    setEventType(event.event_type)
    setEventDate(event.event_date ?? "")
    setStartTime(formatTimeInputValue(event.start_time))
    setEndTime(formatTimeInputValue(event.end_time))
    setIsAllDay(event.is_all_day)
    setError(null)
    setErrorTarget("general")
  }

  useEffect(() => {
    resetDraft()
  }, [event])

  useEffect(() => {
    if (!startEditing) return
    setEditorFocusTarget(attentionTarget === "date" ? "date" : "name")
    setIsEditing(true)
  }, [attentionTarget, event.id, startEditing])

  useLayoutEffect(() => {
    if (!isEditing || !editorFocusTarget) return
    if (editorFocusTarget === "date") eventDateRef.current?.focus()
    else titleRef.current?.focus()
    setEditorFocusTarget(null)
  }, [editorFocusTarget, isEditing])

  function openEditor() {
    setEditorFocusTarget(attentionTarget === "date" ? "date" : "name")
    setIsEditing(true)
    setError(null)
    setErrorTarget("general")
  }

  function cancelEditing() {
    resetDraft()
    setIsEditing(false)
    setShowMoreOptions(false)
    modifyButtonRef.current?.focus()
  }

  async function save(reviewStatus: ReviewStatus, closeEditor = false) {
    if (reviewStatus === "confirmed" && !eventDate) {
      setEditorFocusTarget("date")
      setIsEditing(true)
      setError("Add a date before confirming this event.")
      setErrorTarget("date")
      return
    }

    setSaving(closeEditor ? "changes" : reviewStatus)
    setError(null)
    setErrorTarget("general")
    try {
      await onSave(event.id, {
        title,
        event_type: eventType.trim() || event.event_type,
        event_date: eventDate || null,
        start_time: isAllDay ? null : normalizeTimeValue(startTime),
        end_time: isAllDay ? null : normalizeTimeValue(endTime),
        is_all_day: isAllDay,
        review_status: reviewStatus,
      })
      if (closeEditor) {
        setIsEditing(false)
        setShowMoreOptions(false)
        requestAnimationFrame(() => modifyButtonRef.current?.focus())
      }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "The event could not be saved."
      setError(message)
      setErrorTarget(message.includes("Add a date") ? "date" : "general")
      if (message.includes("Add a date")) {
        setEditorFocusTarget("date")
        setIsEditing(true)
      }
    } finally {
      setSaving(null)
    }
  }

  return (
    <Card
      aria-describedby={cardDescriptionIds}
      aria-labelledby={titleId}
      className={cn(
        "relative overflow-hidden border-border/80 bg-panel/95 p-4 shadow-panel sm:p-5",
        isNeedsReview && "border-warning-border",
        isNeedsReview && attentionTarget === "card" && "ring-2 ring-warning/20",
      )}
      data-focus-target={isNeedsReview && attentionTarget === "card" ? "card" : undefined}
      data-review-event-id={event.id}
      tabIndex={isNeedsReview && attentionTarget === "card" ? -1 : undefined}
    >
      <span
        aria-hidden="true"
        className="absolute inset-y-0 left-0 w-1"
        data-testid={`course-rail-${event.id}`}
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
            {hasAmbiguousRecurrence ? (
              <Badge className="border border-warning-border bg-warning-soft text-warning">
                <Repeat aria-hidden="true" className="mr-1 size-3.5" />
                Recurring rule
              </Badge>
            ) : null}
            <Badge className={statusChip.className}>{statusChip.copy}</Badge>
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
              <p className="mt-1 text-xs font-medium text-warning">Terra repaired {fallbackReasons}</p>
            ) : null}
          </div>
        </header>

        <div className="grid gap-3 md:grid-cols-[minmax(0,0.72fr)_minmax(0,1.28fr)]">
          <div
            aria-describedby={dateDescriptionIds}
            className={cn(
              "rounded-xl border border-border/80 bg-panel-muted/35 px-3.5 py-3",
              isNeedsReview && attentionTarget === "date" && "border-warning-border bg-warning-soft/60",
            )}
            data-focus-target={isNeedsReview && attentionTarget === "date" ? "date" : undefined}
            tabIndex={isNeedsReview && attentionTarget === "date" ? -1 : undefined}
          >
            <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-text-subtle">
              <CalendarClock aria-hidden="true" className="size-3.5 text-accent" />
              AI date
            </p>
            <p className="mt-1.5 text-sm font-semibold text-text">
              {formatSuggestedDate(event.event_date)}
            </p>
          </div>

          <div
            aria-describedby={sourceDescriptionIds}
            className={cn(
              "rounded-xl border border-border/80 bg-panel-muted/35 px-3.5 py-3",
              isNeedsReview && attentionTarget === "source" && "border-warning-border bg-warning-soft/60",
            )}
            data-focus-target={isNeedsReview && attentionTarget === "source" ? "source" : undefined}
            tabIndex={isNeedsReview && attentionTarget === "source" ? -1 : undefined}
          >
            <div className="flex items-center justify-between gap-3">
              <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-text-subtle">
                <FileText aria-hidden="true" className="size-3.5 text-accent" />
                Syllabus says
              </p>
              <span className="shrink-0 text-xs font-semibold text-text-muted">Page {event.source_page}</span>
            </div>
            <blockquote className="mt-1.5 border-l-2 border-border-strong pl-3 text-sm leading-6 text-text">
              "{event.source_quote}"
            </blockquote>
          </div>
        </div>

        {isNeedsReview ? (
          <div
            className="flex gap-2.5 rounded-xl border border-warning-border bg-warning-soft px-3.5 py-3 text-sm text-warning"
            id={`review-warning-${warningId}`}
          >
            <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <div>
              <p className="font-semibold">Needs attention</p>
              <p className="mt-0.5 leading-6">{warningMessage}</p>
            </div>
          </div>
        ) : null}

        {event.derivation_summary ? (
          <div className="rounded-xl border border-accent/20 bg-accent/10 px-3.5 py-3 text-sm text-text-muted">
            <p className="font-semibold text-text">
              {hasAmbiguousRecurrence ? "Why dates were not generated" : "Calculated date"}
            </p>
            <p className="mt-1 leading-6">{event.derivation_summary}</p>
          </div>
        ) : null}

        {isEditing ? (
          <section
            aria-label={`Modify ${event.title}`}
            className="rounded-xl border border-accent/25 bg-panel-muted/25 p-3.5 sm:p-4"
            data-review-editor
            id={editorId}
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
              <div className="grid gap-1.5" data-review-field="event-date">
                <label className="grid gap-1.5 text-sm font-semibold text-text">
                  Event date
                  <Input
                    aria-describedby={dateDescriptionIds}
                    aria-invalid={dateError ? "true" : undefined}
                    aria-label="Event date"
                    className={cn(
                      isNeedsReview &&
                        attentionTarget === "date" &&
                        "border-warning-border focus:border-warning focus:ring-warning/20",
                    )}
                    ref={eventDateRef}
                    type="date"
                    value={eventDate}
                    onChange={(nextEvent) => setEventDate(nextEvent.target.value)}
                  />
                </label>
                {dateError ? (
                  <p className="text-sm font-medium text-danger" id={`review-error-${errorId}`} role="alert">
                    {dateError}
                  </p>
                ) : null}
              </div>
            </div>

            <Button
              aria-expanded={showMoreOptions}
              className="mt-3 px-0"
              onClick={() => setShowMoreOptions((current) => !current)}
              type="button"
              variant="ghost"
            >
              {showMoreOptions ? "Fewer options" : "More options"}
              <ChevronDown
                aria-hidden="true"
                className={cn(
                  "size-4 transition-transform motion-reduce:transition-none",
                  showMoreOptions && "rotate-180",
                )}
              />
            </Button>

            {showMoreOptions ? (
              <div className="mt-3 grid gap-4 border-t border-border/80 pt-4 sm:grid-cols-2">
                <label className="grid gap-1.5 text-sm font-semibold text-text">
                  Event type
                  <Input
                    aria-label="Event type"
                    list="review-event-type-options"
                    value={eventType}
                    onChange={(nextEvent) => setEventType(nextEvent.target.value)}
                  />
                </label>
                <datalist id="review-event-type-options">
                  {eventTypeSuggestions.map((suggestion) => (
                    <option key={suggestion} value={suggestion} />
                  ))}
                </datalist>
                <label className="flex min-h-11 items-center gap-3 rounded-xl border border-border/80 bg-panel px-4 py-3 text-sm font-semibold text-text">
                  <input
                    aria-label="All day event"
                    checked={isAllDay}
                    className="size-4 accent-accent"
                    type="checkbox"
                    onChange={(nextEvent) => {
                      const checked = nextEvent.target.checked
                      setIsAllDay(checked)
                      if (checked) {
                        setStartTime("")
                        setEndTime("")
                      }
                    }}
                  />
                  All day event
                </label>
                {!isAllDay ? (
                  <>
                    <label className="grid gap-1.5 text-sm font-semibold text-text">
                      Start time
                      <Input
                        aria-label="Start time"
                        type="time"
                        value={startTime}
                        onChange={(nextEvent) => setStartTime(nextEvent.target.value)}
                      />
                    </label>
                    <label className="grid gap-1.5 text-sm font-semibold text-text">
                      End time
                      <Input
                        aria-label="End time"
                        type="time"
                        value={endTime}
                        onChange={(nextEvent) => setEndTime(nextEvent.target.value)}
                      />
                    </label>
                  </>
                ) : null}
              </div>
            ) : null}

            {generalError ? (
              <p className="mt-3 text-sm font-medium text-danger" id={`review-error-${errorId}`} role="alert">
                {generalError}
              </p>
            ) : null}

            <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:justify-end">
              <Button onClick={cancelEditing} type="button" variant="secondary">
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

        {!isEditing && generalError ? (
          <p className="text-sm font-medium text-danger" id={`review-error-${errorId}`} role="alert">
            {generalError}
          </p>
        ) : null}

        <div className="flex flex-col gap-3 border-t border-border/80 pt-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-text-muted">
            Confirm publishes this date. Keep pending leaves it outside the calendar.
          </p>
          <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:justify-end">
            <Button
              aria-controls={editorId}
              aria-expanded={isEditing}
              aria-label={`Modify ${event.title}`}
              onClick={isEditing ? cancelEditing : openEditor}
              ref={modifyButtonRef}
              type="button"
              variant="secondary"
            >
              <PencilLine aria-hidden="true" className="size-4" />
              {isEditing ? "Close editor" : "Modify"}
            </Button>
            <Button
              aria-label="Remove"
              loading={saving === "ignored"}
              onClick={() => void save("ignored")}
              type="button"
              variant="danger"
            >
              <Trash2 aria-hidden="true" className="size-4" />
              Remove
            </Button>
            <Button
              aria-label="Keep pending"
              loading={saving === "pending"}
              onClick={() => void save("pending")}
              type="button"
              variant="secondary"
            >
              <Clock3 aria-hidden="true" className="size-4" />
              Keep pending
            </Button>
            <Button
              aria-label="Confirm"
              loading={saving === "confirmed"}
              onClick={() => void save("confirmed")}
              type="button"
            >
              {event.review_status === "confirmed" ? (
                <CheckCircle2 aria-hidden="true" className="size-4" />
              ) : (
                <Check aria-hidden="true" className="size-4" />
              )}
              Confirm
            </Button>
          </div>
        </div>
      </div>
    </Card>
  )
}
