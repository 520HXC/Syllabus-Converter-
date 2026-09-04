import { useEffect, useId, useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowRight, CircleCheckBig } from "lucide-react"
import { Navigate, useNavigate } from "react-router-dom"

import { AppShell } from "../components/AppShell"
import { JobCard } from "../components/JobCard"
import { PageIntro } from "../components/PageIntro"
import { ErrorState, LoadingState } from "../components/QueryState"
import { Button } from "../components/ui/Button"
import { Card } from "../components/ui/Card"
import { useApi } from "../lib/api"
import { useSemester } from "../lib/semester"
import type { ProcessingJob } from "../lib/types"

const activeStatuses = new Set<ProcessingJob["status"]>([
  "queued",
  "extracting_text",
  "running_ocr",
  "extracting_events",
  "validating",
])

export function ProcessingPage() {
  const api = useApi()
  const { semesterId } = useSemester()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [jobPendingReprocess, setJobPendingReprocess] = useState<ProcessingJob | null>(null)
  const [retryFailure, setRetryFailure] = useState<{ semesterId: string; jobId: string; message: string } | null>(null)
  const reprocessTitleId = useId()
  const reprocessDialogRef = useRef<HTMLDivElement>(null)
  const cancelReprocessRef = useRef<HTMLButtonElement>(null)
  const reprocessTriggerRef = useRef<HTMLElement | null>(null)
  const jobsQuery = useQuery({
    queryKey: ["jobs", semesterId],
    queryFn: () => api.listJobs(semesterId!),
    enabled: Boolean(semesterId),
    refetchInterval: (query) => {
      const jobs = query.state.data
      return jobs?.some((job) => activeStatuses.has(job.status)) ? 1500 : false
    },
  })
  const retryMutation = useMutation({
    mutationFn: ({ jobId }: { jobId: string; semesterId: string }) => api.retryJob(jobId),
    onMutate: () => setRetryFailure(null),
    onError: (error, variables) => {
      setRetryFailure({
        semesterId: variables.semesterId,
        jobId: variables.jobId,
        message: error instanceof Error ? error.message : "The retry could not be started.",
      })
    },
    onSuccess: (_data, variables) => queryClient.invalidateQueries({ queryKey: ["jobs", variables.semesterId] }),
  })
  const reprocessMutation = useMutation({
    mutationFn: ({ jobId }: { jobId: string; semesterId: string }) => api.reprocessJob(jobId),
    onSuccess: async (_data, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["jobs", variables.semesterId] }),
        queryClient.invalidateQueries({ queryKey: ["review", variables.semesterId] }),
        queryClient.invalidateQueries({ queryKey: ["events", variables.semesterId] }),
      ])
      closeReprocessDialog(true)
    },
  })

  useEffect(() => {
    if (jobPendingReprocess) cancelReprocessRef.current?.focus()
  }, [jobPendingReprocess])

  useEffect(() => {
    if (!semesterId) {
      setRetryFailure(null)
      return
    }
    setRetryFailure((current) => (current?.semesterId === semesterId ? current : null))
  }, [semesterId])

  function openReprocessDialog(job: ProcessingJob) {
    reprocessTriggerRef.current = document.activeElement as HTMLElement | null
    reprocessMutation.reset()
    setJobPendingReprocess(job)
  }

  function closeReprocessDialog(force = false) {
    if (reprocessMutation.isPending && !force) return
    setJobPendingReprocess(null)
    requestAnimationFrame(() => reprocessTriggerRef.current?.focus())
  }

  function handleReprocessDialogKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault()
      closeReprocessDialog()
      return
    }
    if (event.key !== "Tab") return
    const focusable = Array.from(
      reprocessDialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    )
    if (!focusable.length) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  if (!semesterId) return <Navigate replace to="/setup" />
  const activeSemesterId = semesterId

  const jobs = jobsQuery.data ?? []
  const working = jobs.some((job) => activeStatuses.has(job.status))
  const needsReview = jobs.some((job) => job.status === "needs_review")
  const allCompleted = jobs.length > 0 && jobs.every((job) => job.status === "completed")
  const processingCount = jobs.filter((job) => activeStatuses.has(job.status)).length
  const readyCount = jobs.filter((job) => job.status === "needs_review").length
  const completedCount = jobs.filter((job) => job.status === "completed").length
  const failedCount = jobs.filter((job) => job.status === "failed").length
  const currentStep = allCompleted ? 4 : needsReview ? 3 : 2
  const pageTitle = working ? "Reading your course plans" : failedCount > 0 ? "Some files need attention" : "Your files are ready"

  return (
    <AppShell currentStep={currentStep}>
      <div className="mx-auto max-w-5xl">
        <PageIntro
          eyebrow="Processing"
          title={pageTitle}
          description="Status is shown by real processing stage. This page refreshes each file independently."
        />

        {jobsQuery.isLoading ? <LoadingState label="Checking your files" /> : null}
        {jobsQuery.error ? (
          <ErrorState message={jobsQuery.error.message} onRetry={() => jobsQuery.refetch()} />
        ) : null}
        {retryFailure && retryFailure.semesterId === semesterId ? (
          <div className="mb-5">
            <ErrorState
              message={retryFailure.message}
              onRetry={() => retryMutation.mutate({ jobId: retryFailure.jobId, semesterId: activeSemesterId })}
            />
          </div>
        ) : null}
        {!jobsQuery.isLoading && !jobsQuery.error && !jobs.length ? (
          <Card className="border-border/80 bg-panel/95 p-6 text-center">
            <p className="font-semibold text-text">No syllabus files are waiting.</p>
            <Button className="mt-4" onClick={() => navigate("/upload")} variant="secondary">
              Go back to upload
            </Button>
          </Card>
        ) : null}
        {!jobsQuery.isLoading && !jobsQuery.error && jobs.length ? (
          <Card className="mb-5 border-border/80 bg-panel/95 p-4 sm:p-5">
            <div className="grid gap-3 sm:grid-cols-4">
              <div className="rounded-2xl border border-border/80 bg-panel-muted/35 px-4 py-4">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-text-subtle">In progress</p>
                <p className="mt-2 text-2xl font-bold tracking-[-0.03em] text-text">{processingCount}</p>
                <p className="mt-1 text-sm text-text-muted">
                  {processingCount === 1 ? "1 file still processing" : `${processingCount} files still processing`}
                </p>
              </div>
              <div className="rounded-2xl border border-warning-border bg-warning-soft px-4 py-4">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-warning">Needs review</p>
                <p className="mt-2 text-2xl font-bold tracking-[-0.03em] text-warning">{readyCount}</p>
                <p className="mt-1 text-sm text-warning">
                  {readyCount === 1 ? "1 ready for review" : `${readyCount} ready for review`}
                </p>
              </div>
              <div className="rounded-2xl border border-border/80 bg-panel-muted/35 px-4 py-4">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-text-subtle">Completed</p>
                <p className="mt-2 text-2xl font-bold tracking-[-0.03em] text-text">{completedCount}</p>
                <p className="mt-1 text-sm text-text-muted">
                  {completedCount === 1 ? "1 file fully reviewed" : `${completedCount} files fully reviewed`}
                </p>
              </div>
              <div className="rounded-2xl border border-danger/20 bg-danger-soft px-4 py-4">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-danger">Failed</p>
                <p className="mt-2 text-2xl font-bold tracking-[-0.03em] text-danger">{failedCount}</p>
                <p className="mt-1 text-sm text-danger">
                  {failedCount === 1 ? "1 file needs retry" : `${failedCount} files need retry`}
                </p>
              </div>
            </div>
          </Card>
        ) : null}
        <div className="grid gap-3">
          {jobs.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              onRetry={(jobId) => retryMutation.mutate({ jobId, semesterId: activeSemesterId })}
              onReprocess={() => openReprocessDialog(job)}
              retrying={retryMutation.isPending && retryMutation.variables?.jobId === job.id}
              reprocessing={reprocessMutation.isPending && reprocessMutation.variables?.jobId === job.id}
            />
          ))}
        </div>

        {(needsReview || allCompleted) && !working ? (
          <div className="mt-6 flex flex-col items-center justify-between gap-4 rounded-2xl border border-accent/20 bg-accent/10 p-5 sm:flex-row">
            <div className="flex gap-3">
              <CircleCheckBig aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-accent" />
              <div>
                <p className="font-semibold text-text">
                  {allCompleted ? "Review complete" : "Extraction is ready to check"}
                </p>
                <p className="mt-1 text-sm text-text-muted">
                  {allCompleted
                    ? "Your confirmed events are ready in the semester calendar."
                    : "Nothing enters your calendar until you confirm it."}
                </p>
              </div>
            </div>
            <Button
              className="w-full shrink-0 sm:w-auto"
              onClick={() => navigate(allCompleted ? "/calendar" : "/review")}
            >
              {allCompleted ? "Open calendar" : "Review details"}
              <ArrowRight aria-hidden="true" className="size-4" />
            </Button>
          </div>
        ) : null}
      </div>
      {jobPendingReprocess ? (
        <div className="fixed inset-0 z-30 flex items-end bg-overlay/55 p-4 sm:items-center sm:justify-center">
          <div
            aria-labelledby={reprocessTitleId}
            aria-modal="true"
            className="w-full max-w-lg"
            onKeyDown={handleReprocessDialogKeyDown}
            ref={reprocessDialogRef}
            role="dialog"
          >
            <Card className="border-warning-border bg-panel p-5 shadow-2xl sm:p-6">
              <h2 className="text-2xl font-bold tracking-[-0.03em] text-text" id={reprocessTitleId}>
                {`Run extraction again for ${jobPendingReprocess.filename ?? "syllabus"}?`}
              </h2>
              <p className="mt-3 text-sm leading-6 text-text-muted">
                This will run the latest Luna and Terra pipeline and replace the extracted events and review decisions for this PDF.
              </p>
              <div className="mt-4 rounded-2xl border border-warning-border bg-warning-soft p-3 text-sm text-warning">
                Your current results stay intact if the new processing attempt fails.
              </div>
              {reprocessMutation.error ? (
                <p className="mt-3 text-sm font-medium text-danger" role="alert">
                  {reprocessMutation.error.message}
                </p>
              ) : null}
              <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                <Button
                  onClick={() => closeReprocessDialog()}
                  ref={cancelReprocessRef}
                  type="button"
                  variant="secondary"
                >
                  Cancel
                </Button>
                <Button
                  loading={reprocessMutation.isPending}
                  onClick={() => reprocessMutation.mutate({ jobId: jobPendingReprocess.id, semesterId: activeSemesterId })}
                  type="button"
                >
                  Run extraction again
                </Button>
              </div>
            </Card>
          </div>
        </div>
      ) : null}
    </AppShell>
  )
}
