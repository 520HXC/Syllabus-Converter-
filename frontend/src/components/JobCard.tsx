import { AlertCircle, CheckCircle2, FileText, LoaderCircle, RefreshCw, RotateCcw, Sparkles } from "lucide-react"

import { cn } from "../lib/utils"
import type { ProcessingJob } from "../lib/types"
import { Badge } from "./ui/Badge"
import { Button } from "./ui/Button"
import { Card } from "./ui/Card"

const statusLabels: Record<ProcessingJob["status"], string> = {
  queued: "Queued",
  extracting_text: "Reading PDF",
  running_ocr: "Running OCR",
  extracting_events: "Extracting events",
  validating: "Checking details",
  needs_review: "Ready for review",
  completed: "Completed",
  failed: "Failed",
}

const processingStages = [
  { status: "queued", label: "Queued" },
  { status: "extracting_text", label: "Reading PDF" },
  { status: "running_ocr", label: "Running OCR" },
  { status: "extracting_events", label: "Extracting events" },
  { status: "validating", label: "Checking details" },
] as const

const activeStatuses = new Set<ProcessingJob["status"]>([
  "queued",
  "extracting_text",
  "running_ocr",
  "extracting_events",
  "validating",
])

function getStageIndex(status: ProcessingJob["status"]) {
  const directIndex = processingStages.findIndex((stage) => stage.status === status)
  if (directIndex >= 0) return directIndex
  if (status === "needs_review" || status === "completed") return processingStages.length - 1
  return 0
}

function formatWarningCode(code: string) {
  return code
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}

export function JobCard({
  job,
  onRetry,
  onReprocess,
  retrying = false,
  reprocessing = false,
}: {
  job: ProcessingJob
  onRetry: (jobId: string) => void
  onReprocess?: (jobId: string) => void
  retrying?: boolean
  reprocessing?: boolean
}) {
  const active = activeStatuses.has(job.status)
  const processingComplete = job.status === "needs_review" || job.status === "completed"
  const stageIndex = getStageIndex(job.status)
  const stageCount = processingStages.length
  const filename = job.filename ?? "Syllabus PDF"

  return (
    <Card className="border-border/80 bg-panel/95 p-4 sm:p-5">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-xl bg-accent/10 p-2 text-accent">
          <FileText aria-hidden="true" className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate font-semibold text-text">{filename}</p>
              <p className="mt-1 text-xs font-semibold uppercase tracking-[0.16em] text-text-subtle">
                Stage {stageIndex + 1} of {stageCount}
              </p>
            </div>
            <Badge
              className={
                job.status === "failed"
                  ? "bg-danger-soft text-danger"
                  : job.status === "needs_review"
                    ? "bg-warning-soft text-warning"
                    : "bg-accent/10 text-accent"
              }
            >
              {active ? (
                <LoaderCircle aria-hidden="true" className="mr-1.5 size-3.5 animate-spin motion-reduce:animate-none" />
              ) : job.status === "failed" ? (
                <AlertCircle aria-hidden="true" className="mr-1.5 size-3.5" />
              ) : (
                <CheckCircle2 aria-hidden="true" className="mr-1.5 size-3.5" />
              )}
              {statusLabels[job.status]}
            </Badge>
          </div>
          <p className="mt-2 text-sm leading-6 text-text-muted">{job.stage_detail ?? statusLabels[job.status]}</p>
          {job.primary_model ? (
            <div className="mt-4 rounded-2xl border border-border/80 bg-panel-muted/35 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Sparkles aria-hidden="true" className="size-4 text-accent" />
                <p className="text-sm font-semibold text-text">
                  {job.fallback_used ? "Terra rechecked flagged details" : "Processed with Luna"}
                </p>
              </div>
              <p className="mt-1 text-xs text-text-muted">
                {job.fallback_used
                  ? `Luna processed the PDF first. Terra then rechecked only the details that failed validation.`
                  : `${job.primary_model} completed the extraction without a model fallback.`}
              </p>
              {job.fallback_reason_codes?.length ? (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {job.fallback_reason_codes.map((code) => (
                    <Badge className="border border-warning-border bg-warning-soft text-warning" key={code}>
                      {formatWarningCode(code)}
                    </Badge>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
          <ol aria-label={`Processing timeline for ${filename}`} className="mt-4 grid gap-2 sm:grid-cols-5">
            {processingStages.map((stage, index) => {
              const state = processingComplete
                ? "complete"
                : index < stageIndex
                  ? "complete"
                  : index === stageIndex
                    ? job.status === "failed"
                      ? "failed"
                      : "current"
                    : "upcoming"

              return (
                <li
                  key={stage.status}
                  className={cn(
                    "rounded-2xl border px-3 py-3 text-xs font-semibold transition-colors",
                    state === "complete" && "border-accent/20 bg-accent/10 text-accent",
                    state === "current" && "border-border-strong bg-panel-muted/60 text-text",
                    state === "failed" && "border-danger/20 bg-danger-soft text-danger",
                    state === "upcoming" && "border-border/80 bg-panel text-text-subtle",
                  )}
                >
                  <span className="block text-[11px] uppercase tracking-[0.16em]">
                    {state === "complete"
                      ? "Done"
                      : state === "current"
                        ? "Current"
                        : state === "failed"
                          ? "Stopped"
                          : "Next"}
                  </span>
                  <span className="mt-1 block text-sm font-semibold">{stage.label}</span>
                </li>
              )
            })}
          </ol>
          {job.error_message ? (
            <div className="mt-4 rounded-2xl border border-danger/20 bg-danger-soft p-3 text-sm text-danger">
              <p>{job.error_message}</p>
              <Button
                aria-label={`Retry ${job.filename ?? "syllabus"}`}
                className="mt-3"
                loading={retrying}
                onClick={() => onRetry(job.id)}
                variant="secondary"
              >
                <RotateCcw aria-hidden="true" className="size-4" />
                Retry
              </Button>
            </div>
          ) : null}
          {onReprocess && (job.status === "needs_review" || job.status === "completed") ? (
            <Button
              aria-label={`Run extraction again for ${filename}`}
              className="mt-4"
              loading={reprocessing}
              onClick={() => onReprocess(job.id)}
              type="button"
              variant="secondary"
            >
              <RefreshCw aria-hidden="true" className="size-4" />
              Run extraction again
            </Button>
          ) : null}
        </div>
      </div>
    </Card>
  )
}
