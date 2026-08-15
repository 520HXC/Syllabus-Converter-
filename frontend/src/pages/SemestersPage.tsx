import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CalendarDays, Clock3, FileUp, Plus, Trash2 } from "lucide-react"
import { Navigate, useNavigate } from "react-router-dom"

import { AppShell } from "../components/AppShell"
import { PageIntro } from "../components/PageIntro"
import { ErrorState, LoadingState } from "../components/QueryState"
import { Button } from "../components/ui/Button"
import { Card } from "../components/ui/Card"
import { useApi } from "../lib/api"
import { useAuth } from "../lib/auth"
import { semesterQueryKey } from "../lib/queryKeys"
import { useSemester } from "../lib/semester"
import type { Semester } from "../lib/types"

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(new Date(`${value}T12:00:00`))
}

function formatLongDate(value: string) {
  return new Intl.DateTimeFormat("en-US", { dateStyle: "long" }).format(new Date(`${value}T12:00:00`))
}

export function SemestersPage() {
  const api = useApi()
  const { user } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { semesterId, setSemesterId } = useSemester()
  const deleteDialogTitleId = useId()
  const cancelButtonRef = useRef<HTMLButtonElement>(null)
  const deleteTriggerRef = useRef<HTMLButtonElement | null>(null)
  const deleteDialogRef = useRef<HTMLDivElement>(null)
  const pageContentRef = useRef<HTMLDivElement>(null)
  const [semesterPendingDelete, setSemesterPendingDelete] = useState<Semester | null>(null)
  const [confirmedDelete, setConfirmedDelete] = useState(false)
  const semestersQuery = useQuery({
    queryKey: semesterQueryKey(user?.id),
    queryFn: api.listSemesters,
    enabled: Boolean(user),
  })
  const deleteMutation = useMutation({
    mutationFn: (semesterId: string) => api.deleteSemester(semesterId),
    onSuccess: (_, deletedSemesterId) => {
      const currentSemesters = semestersQuery.data ?? []
      const remainingSemesters = currentSemesters.filter((semester) => semester.id !== deletedSemesterId)
      queryClient.setQueryData(semesterQueryKey(user?.id), remainingSemesters)
      if (deletedSemesterId === semesterId) {
        setSemesterId(remainingSemesters[0]?.id ?? null)
      }
      setSemesterPendingDelete(null)
      setConfirmedDelete(false)
      if (!remainingSemesters.length) navigate("/setup")
    },
  })

  useEffect(() => {
    const pageContent = pageContentRef.current
    if (!pageContent) return
    if (!semesterPendingDelete) {
      pageContent.removeAttribute("aria-hidden")
      pageContent.removeAttribute("inert")
      return
    }
    pageContent.setAttribute("aria-hidden", "true")
    pageContent.setAttribute("inert", "")
    cancelButtonRef.current?.focus()

    return () => {
      pageContent.removeAttribute("aria-hidden")
      pageContent.removeAttribute("inert")
    }
  }, [semesterPendingDelete])

  function handleDeleteDialogKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault()
      closeDeleteDialog()
      return
    }
    if (event.key !== "Tab") return

    const focusableElements = Array.from(
      deleteDialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    )
    if (!focusableElements.length) return

    const firstElement = focusableElements[0]
    const lastElement = focusableElements[focusableElements.length - 1]

    if (event.shiftKey) {
      if (document.activeElement === firstElement || !deleteDialogRef.current?.contains(document.activeElement)) {
        event.preventDefault()
        lastElement.focus()
      }
      return
    }

    if (document.activeElement === lastElement) {
      event.preventDefault()
      firstElement.focus()
    }
  }

  if (semestersQuery.isPending) {
    return <AppShell><LoadingState label="Loading your semesters" /></AppShell>
  }
  if (semestersQuery.isError) {
    return (
      <AppShell>
        <ErrorState message={semestersQuery.error.message} onRetry={() => semestersQuery.refetch()} />
      </AppShell>
    )
  }
  if (!semestersQuery.data.length) return <Navigate replace to="/setup" />

  function open(semester: Semester, destination: "/upload" | "/calendar") {
    setSemesterId(semester.id)
    navigate(destination)
  }

  async function confirmDelete() {
    if (!semesterPendingDelete) return
    await deleteMutation.mutateAsync(semesterPendingDelete.id)
  }

  function closeDeleteDialog() {
    deleteMutation.reset()
    setSemesterPendingDelete(null)
    setConfirmedDelete(false)
    deleteTriggerRef.current?.focus()
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl" ref={pageContentRef}>
        <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <PageIntro
            eyebrow="Your semesters"
            title="Pick up where you left off"
            description="Open a calendar or add another syllabus without entering the same semester details again."
          />
          <Button className="w-full shrink-0 sm:w-auto" onClick={() => navigate("/setup")}>
            <Plus aria-hidden="true" className="size-4" />
            New semester
          </Button>
        </div>

        <div className="mt-7 grid gap-4 md:grid-cols-2">
          {semestersQuery.data.map((semester) => (
            <Card
              className={`flex h-full flex-col p-5 sm:p-6 ${
                semester.id === semesterId
                  ? "border-accent/35 bg-panel/95 ring-1 ring-accent/15"
                  : "border-border/80 bg-panel/95"
              }`}
              key={semester.id}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3">
                  <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-accent/10 text-accent">
                    <CalendarDays aria-hidden="true" className="size-5" />
                  </span>
                  <div className="min-w-0">
                    <h2 className="break-words text-xl font-bold tracking-[-0.03em] text-text">{semester.name}</h2>
                    <p className="mt-1 text-sm text-text-muted">
                      {formatDate(semester.start_date)} to {formatDate(semester.end_date)}
                    </p>
                  </div>
                </div>
                {semester.id === semesterId ? (
                  <span className="inline-flex min-h-8 items-center rounded-full bg-accent/10 px-3 text-xs font-semibold text-accent">
                    Current semester
                  </span>
                ) : null}
              </div>
              <p className="mt-5 flex items-center gap-2 text-sm text-text-muted">
                <Clock3 aria-hidden="true" className="size-4 text-accent" />
                {semester.timezone}
              </p>
              <div className="mt-5 grid grid-cols-2 gap-2 text-sm text-text-muted">
                <div className="rounded-2xl border border-border/80 bg-panel-muted/35 px-3 py-3">
                  <p className="font-semibold text-text">{semester.course_count} courses</p>
                  <p className="mt-1 text-xs text-text-subtle">{semester.document_count} syllabi</p>
                </div>
                <div className="rounded-2xl border border-border/80 bg-panel-muted/35 px-3 py-3">
                  <p className="font-semibold text-text">{semester.event_count} events</p>
                  <p className="mt-1 text-xs text-text-subtle">{semester.needs_review_count} to review</p>
                </div>
              </div>
              <div className="mt-6 grid gap-2">
                <Button onClick={() => open(semester, "/calendar")}>
                  <CalendarDays aria-hidden="true" className="size-4" />
                  Open calendar
                </Button>
                <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
                  <Button onClick={() => open(semester, "/upload")} variant="secondary">
                    <FileUp aria-hidden="true" className="size-4" />
                    Upload syllabus
                  </Button>
                  <Button
                    aria-label={`Delete ${semester.name} semester`}
                    onClick={(event) => {
                      deleteTriggerRef.current = event.currentTarget
                      deleteMutation.reset()
                      setConfirmedDelete(false)
                      setSemesterPendingDelete(semester)
                    }}
                    variant="danger"
                  >
                    <Trash2 aria-hidden="true" className="size-4" />
                    Delete
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      </div>
      {semesterPendingDelete ? (
        <div className="fixed inset-0 z-30 flex items-end bg-overlay/45 p-4 sm:items-center sm:justify-center">
          <div
            aria-labelledby={deleteDialogTitleId}
            aria-modal="true"
            className="w-full max-w-lg"
            onKeyDown={handleDeleteDialogKeyDown}
            ref={deleteDialogRef}
            role="dialog"
          >
            <Card className="border-danger/20 bg-panel p-5 shadow-2xl sm:p-6">
              <h2 className="text-2xl font-bold text-text" id={deleteDialogTitleId}>{`Delete ${semesterPendingDelete.name}?`}</h2>
              <p className="mt-3 text-sm leading-6 text-text-muted">
                {formatLongDate(semesterPendingDelete.start_date)} to {formatLongDate(semesterPendingDelete.end_date)}
              </p>
              <p className="mt-2 text-sm leading-6 text-text-muted">
                {`${semesterPendingDelete.course_count} courses, ${semesterPendingDelete.document_count} syllabi, ${semesterPendingDelete.event_count} events, ${semesterPendingDelete.needs_review_count} still to review`}
              </p>
              <label className="mt-5 flex min-h-11 cursor-pointer items-start gap-3 rounded-2xl border border-border/80 bg-panel-muted/35 px-4 py-3 text-sm text-text-muted">
                <input
                  aria-label="I understand this permanently deletes the semester"
                  checked={confirmedDelete}
                  className="mt-1 size-4 accent-danger"
                  onChange={(event) => setConfirmedDelete(event.target.checked)}
                  type="checkbox"
                />
                <span>I understand this permanently deletes the semester and every uploaded PDF.</span>
              </label>
              {deleteMutation.error ? <p className="mt-3 text-sm font-medium text-danger">{deleteMutation.error.message}</p> : null}
              <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                <Button
                  onClick={closeDeleteDialog}
                  ref={cancelButtonRef}
                  type="button"
                  variant="secondary"
                >
                  Cancel
                </Button>
                <Button
                  disabled={!confirmedDelete}
                  loading={deleteMutation.isPending}
                  onClick={() => void confirmDelete()}
                  type="button"
                  variant="danger"
                >
                  Delete semester
                </Button>
              </div>
            </Card>
          </div>
        </div>
      ) : null}
    </AppShell>
  )
}
