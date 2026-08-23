import { CalendarDays, CheckCircle2, ListChecks } from "lucide-react"

import { Button } from "./ui/Button"
import { Card } from "./ui/Card"

function SummaryStat({
  label,
  value,
  tone,
}: {
  label: string
  value: number
  tone: "confirmed" | "saved" | "removed"
}) {
  const toneClassName =
    tone === "confirmed"
      ? "border-accent/20 bg-accent/10 text-accent"
      : tone === "saved"
        ? "border-warning-border bg-warning-soft text-warning"
        : "border-border/80 bg-panel-muted/50 text-text-muted"

  return (
    <div className={`rounded-2xl border p-4 ${toneClassName}`}>
      <p className="text-xs font-semibold uppercase tracking-[0.16em]">{label}</p>
      <p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p>
    </div>
  )
}

export function ReviewCompletionState({
  semesterName,
  confirmedCount,
  savedForLaterCount,
  awaitingDateCount,
  savedRuleCount,
  removedCount,
  onOpenCalendar,
  onReviewDecisions,
}: {
  semesterName: string
  confirmedCount: number
  savedForLaterCount: number
  awaitingDateCount: number
  savedRuleCount: number
  removedCount: number
  onOpenCalendar: () => void
  onReviewDecisions: () => void
}) {
  return (
    <Card className="border-border/80 bg-panel/95 p-6 shadow-panel sm:p-7">
      <div className="mx-auto max-w-3xl space-y-6">
        <div className="space-y-3 text-center sm:text-left">
          <span className="inline-flex min-h-11 items-center gap-2 rounded-full border border-accent/20 bg-accent/10 px-4 text-sm font-semibold text-accent">
            <CheckCircle2 aria-hidden="true" className="size-4" />
            Review complete
          </span>
          <div className="space-y-2">
            <h1 className="text-3xl font-bold tracking-[-0.03em] text-text sm:text-4xl">
              Every decision for {semesterName} is saved
            </h1>
            <p className="max-w-2xl text-sm leading-6 text-text-muted">
              Open Calendar to see confirmed events in context, or review decisions to adjust confirmed events, saved items, and removed items.
            </p>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-4">
          <SummaryStat label="Confirmed" tone="confirmed" value={confirmedCount} />
          <SummaryStat label="Saved for later" tone="saved" value={savedForLaterCount} />
          <SummaryStat label="Saved rules" tone="saved" value={savedRuleCount} />
          <SummaryStat label="Removed" tone="removed" value={removedCount} />
        </div>

        <p className="text-sm leading-6 text-text-muted">
          Saved for later items stay off the calendar until you confirm them. Saved rules stay as reference details and do not enter the calendar until the syllabus gives you exact dates to confirm.
          {awaitingDateCount > 0
            ? ` ${awaitingDateCount} item${awaitingDateCount === 1 ? "" : "s"} still ${awaitingDateCount === 1 ? "needs" : "need"} a date.`
            : ""}
        </p>

        <div className="flex flex-col gap-3 sm:flex-row sm:justify-end">
          <Button onClick={onOpenCalendar} type="button">
            <CalendarDays aria-hidden="true" className="size-4" />
            Open Calendar
          </Button>
          <Button onClick={onReviewDecisions} type="button" variant="secondary">
            <ListChecks aria-hidden="true" className="size-4" />
            Review decisions
          </Button>
        </div>
      </div>
    </Card>
  )
}
