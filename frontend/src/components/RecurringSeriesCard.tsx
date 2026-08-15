import { useEffect, useState } from "react"
import { AlertTriangle, CalendarRange, Check, ChevronDown, Clock3, RotateCcw, Trash2 } from "lucide-react"

import type { EventUpdate, ExtractedEvent, RecurringEventSeries, ReviewStatus } from "../lib/types"
import { formatFallbackReasons } from "../lib/modelRouting"
import { cn } from "../lib/utils"
import { Badge } from "./ui/Badge"
import { Button } from "./ui/Button"
import { Card } from "./ui/Card"
import { ReviewEventCard } from "./ReviewEventCard"

type SeriesAction = "confirmed" | "pending" | "ignored" | "needs_review"

function statusLabel(status: RecurringEventSeries["review_status"]) {
  if (status === "confirmed") return "Confirmed series"
  if (status === "pending") return "Pending series"
  if (status === "ignored") return "Removed series"
  if (status === "mixed") return "Mixed decisions"
  return "Needs review"
}

export function RecurringSeriesCard({
  series,
  occurrences,
  courseLabel,
  courseColor,
  focusEventId,
  onSaveSeries,
  onSaveEvent,
}: {
  series: RecurringEventSeries
  occurrences: ExtractedEvent[]
  courseLabel: string
  courseColor: string
  focusEventId?: string | null
  onSaveSeries: (seriesId: string, reviewStatus: ReviewStatus) => Promise<void>
  onSaveEvent: (eventId: string, update: EventUpdate) => Promise<void>
}) {
  const [expanded, setExpanded] = useState(false)
  const [saving, setSaving] = useState<SeriesAction | null>(null)
  const [error, setError] = useState<string | null>(null)
  const showOccurrences = expanded || Boolean(focusEventId)
  const fallbackReasons = formatFallbackReasons(series.fallback_reason_codes ?? [])

  useEffect(() => {
    if (focusEventId) setExpanded(true)
  }, [focusEventId])

  async function save(reviewStatus: SeriesAction) {
    setSaving(reviewStatus)
    setError(null)
    try {
      await onSaveSeries(series.id, reviewStatus)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The series could not be saved.")
    } finally {
      setSaving(null)
    }
  }

  return (
    <Card
      className={cn("overflow-hidden border-border/80 bg-panel/95", series.review_status === "needs_review" && "border-warning-border")}
      data-recurring-series-id={series.id}
      tabIndex={-1}
    >
      <div className="relative p-4 sm:p-5">
        <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1.5" style={{ backgroundColor: courseColor }} />
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <Badge className="border border-border bg-panel text-text">{courseLabel}</Badge>
                <Badge className="bg-panel-muted/70 text-text">Recurring series</Badge>
                <Badge className={series.review_status === "needs_review" ? "bg-warning-soft text-warning" : "bg-accent/10 text-accent"}>
                  {statusLabel(series.review_status)}
                </Badge>
                {series.extraction_model ? (
                  <Badge className="border border-border bg-panel text-text-muted">
                    {series.extraction_model.includes("terra") ? "Terra fallback" : "Luna"}
                  </Badge>
                ) : null}
              </div>
              <h3 className="mt-3 text-lg font-semibold tracking-[-0.02em] text-text">{series.title}</h3>
              <p className="mt-1 text-sm text-text-muted">{series.rule_summary}</p>
              {series.extraction_model?.includes("terra") && fallbackReasons ? (
                <p className="mt-1 text-xs font-medium text-warning">Terra repaired {fallbackReasons}</p>
              ) : null}
            </div>
            <div className="rounded-2xl border border-border/80 bg-panel-muted/35 px-4 py-3 sm:min-w-40">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-text-subtle">Generated schedule</p>
              <p className="mt-1 text-lg font-semibold text-text">{series.occurrence_count} generated dates</p>
            </div>
          </div>

          {series.warning_reason ? (
            <div className="flex gap-3 rounded-2xl border border-warning-border bg-warning-soft p-3 text-sm text-warning">
              <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              <p>{series.warning_reason}</p>
            </div>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-2xl border border-border/80 bg-panel-muted/35 p-3">
              <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-text-subtle">
                <Clock3 aria-hidden="true" className="size-3.5 text-accent" />
                Rule source
              </p>
              <p className="mt-2 text-sm text-text">{series.source_quote}</p>
              <p className="mt-1 text-xs text-text-muted">Page {series.source_page}</p>
            </div>
            <div className="rounded-2xl border border-border/80 bg-panel-muted/35 p-3">
              <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-text-subtle">
                <CalendarRange aria-hidden="true" className="size-3.5 text-accent" />
                Schedule evidence
              </p>
              <p className="mt-2 text-sm text-text">{series.anchor_sources.length} dated anchors were used</p>
              <p className="mt-1 text-xs text-text-muted">Each generated date remains editable below</p>
            </div>
          </div>

          {error ? <p className="text-sm font-medium text-danger" role="alert">{error}</p> : null}

          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
            {series.review_status === "ignored" ? (
              <Button loading={saving === "needs_review"} onClick={() => void save("needs_review")} variant="secondary">
                <RotateCcw aria-hidden="true" className="size-4" />
                Restore series
              </Button>
            ) : (
              <>
                <Button loading={saving === "confirmed"} onClick={() => void save("confirmed")}>
                  <Check aria-hidden="true" className="size-4" />
                  Confirm series
                </Button>
                <Button loading={saving === "pending"} onClick={() => void save("pending")} variant="secondary">
                  <Clock3 aria-hidden="true" className="size-4" />
                  Keep pending
                </Button>
                <Button loading={saving === "ignored"} onClick={() => void save("ignored")} variant="danger">
                  <Trash2 aria-hidden="true" className="size-4" />
                  Remove series
                </Button>
              </>
            )}
            <Button
              aria-expanded={showOccurrences}
              className="sm:ml-auto"
              onClick={() => setExpanded((current) => !current)}
              variant="ghost"
            >
              {showOccurrences ? "Hide dates" : `Show ${occurrences.length} dates`}
              <ChevronDown aria-hidden="true" className={cn("size-4 transition-transform motion-reduce:transition-none", showOccurrences && "rotate-180")} />
            </Button>
          </div>
        </div>
      </div>

      {showOccurrences ? (
        <div className="grid gap-4 border-t border-border/80 bg-panel-muted/20 p-4 sm:p-5">
          {occurrences.map((event) => (
            <ReviewEventCard
              courseColor={courseColor}
              courseLabel={courseLabel}
              event={event}
              key={event.id}
              onSave={onSaveEvent}
              startEditing={focusEventId === event.id}
            />
          ))}
        </div>
      ) : null}
    </Card>
  )
}
