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
  tone: "confirmed" | "pending" | "removed"
}) {
  const toneClassName =
    tone === "confirmed"
      ? "border-accent/20 bg-accent/10 text-accent"
      : tone === "pending"
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
  pendingCount,
  removedCount,
  onOpenCalendar,
  onReviewDecisions,
}: {
  semesterName: string
  confirmedCount: number
  pendingCount: number
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
              Open Calendar to see confirmed events in context, or review decisions to adjust confirmed, pending, and removed items.
            </p>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <SummaryStat label="Confirmed" tone="confirmed" value={confirmedCount} />
          <SummaryStat label="Pending" tone="pending" value={pendingCount} />
          <SummaryStat label="Removed" tone="removed" value={removedCount} />
        </div>

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
