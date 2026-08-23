import { AlertTriangle, CheckCircle2, FileText } from "lucide-react"
import { Link } from "react-router-dom"

import type { Course, ExtractedEvent } from "../lib/types"
import { cn } from "../lib/utils"
import { Card } from "./ui/Card"

function getCourseRuleStatus(status: ExtractedEvent["review_status"]) {
  if (status === "needs_review") {
    return {
      icon: AlertTriangle,
      label: "Needs review",
      className: "border-warning-border bg-warning-soft text-warning",
    }
  }

  return {
    icon: CheckCircle2,
    label: "Saved",
    className: "border-accent/20 bg-accent/10 text-accent",
  }
}

export function CourseDetailsPanel({
  course,
  courseColor,
  confirmedCount,
  awaitingDateCount,
  savedRuleCount,
  rules,
  panelId,
}: {
  course: Course
  courseColor: string
  confirmedCount: number
  awaitingDateCount: number
  savedRuleCount: number
  rules: ExtractedEvent[]
  panelId: string
}) {
  return (
    <Card
      className="mt-3 overflow-hidden border-border/80 bg-panel/95 p-4 shadow-panel"
      id={panelId}
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className="mt-1 h-10 w-1.5 shrink-0 rounded-full"
          style={{ backgroundColor: courseColor }}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-col gap-1">
            <p className="text-sm font-semibold uppercase tracking-[0.14em] text-text-subtle">
              {course.code || course.name}
            </p>
            <h3 className="text-base font-semibold text-text">{course.name}</h3>
            {course.instructor ? (
              <p className="text-sm text-text-muted">{course.instructor}</p>
            ) : null}
          </div>

          <dl className="mt-4 space-y-2" data-testid="course-details-stats">
            <div className="flex items-center justify-between gap-3 rounded-2xl border border-border/80 bg-panel-muted/35 px-3 py-3">
              <dt className="text-xs font-semibold uppercase tracking-[0.14em] text-text-subtle">
                Confirmed events
              </dt>
              <dd className="text-lg font-semibold tabular-nums text-text">{confirmedCount}</dd>
            </div>
            <div className="flex items-center justify-between gap-3 rounded-2xl border border-border/80 bg-panel-muted/35 px-3 py-3">
              <dt className="text-xs font-semibold uppercase tracking-[0.14em] text-text-subtle">
                Awaiting dates
              </dt>
              <dd className="text-lg font-semibold tabular-nums text-text">{awaitingDateCount}</dd>
            </div>
            <div className="flex items-center justify-between gap-3 rounded-2xl border border-border/80 bg-panel-muted/35 px-3 py-3">
              <dt className="text-xs font-semibold uppercase tracking-[0.14em] text-text-subtle">
                Saved rules
              </dt>
              <dd className="text-lg font-semibold tabular-nums text-text">{savedRuleCount}</dd>
            </div>
          </dl>

          <div className="mt-4">
            <div className="flex flex-col items-start gap-1.5" data-testid="course-rules-header">
              <p className="text-sm font-semibold text-text">Rules on file</p>
              <p className="text-xs font-medium text-text-subtle">
                Saved rules stay off the calendar until dates are confirmed
              </p>
            </div>

            {rules.length ? (
              <div className="mt-3 grid gap-2">
                {rules.map((rule) => {
                  const status = getCourseRuleStatus(rule.review_status)
                  const StatusIcon = status.icon

                  return (
                    <Link
                      className="rounded-2xl border border-border/80 bg-panel-muted/30 px-3.5 py-3 transition-colors hover:border-accent hover:bg-panel focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-bg-app"
                      key={rule.id}
                      to={`/review?eventId=${rule.id}`}
                    >
                      <div className="flex items-start gap-3">
                        <span
                          aria-hidden="true"
                          className="mt-0.5 h-10 w-1.5 shrink-0 rounded-full"
                          style={{ backgroundColor: courseColor }}
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-col items-start gap-2">
                            <div className="min-w-0">
                              <p className="font-semibold text-text">{rule.title}</p>
                              <p
                                className="mt-1 overflow-hidden text-sm leading-6 text-text-muted [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:2]"
                                title={rule.source_quote}
                              >
                                {rule.source_quote}
                              </p>
                            </div>
                            <span
                              className={cn(
                                "inline-flex min-h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-xs font-semibold",
                                status.className,
                              )}
                            >
                              <StatusIcon aria-hidden="true" className="size-3.5" />
                              {status.label}
                            </span>
                          </div>
                          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs font-medium text-text-subtle">
                            <span className="inline-flex items-center gap-1.5">
                              <FileText aria-hidden="true" className="size-3.5" />
                              Page {rule.source_page}
                            </span>
                          </div>
                        </div>
                      </div>
                    </Link>
                  )
                })}
              </div>
            ) : (
              <p className="mt-3 text-sm text-text-muted">
                No course rules on file yet.
              </p>
            )}
          </div>
        </div>
      </div>
    </Card>
  )
}
