import { useEffect } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CalendarPlus } from "lucide-react"
import { useNavigate } from "react-router-dom"

import { AppShell } from "../components/AppShell"
import { PageIntro } from "../components/PageIntro"
import { ErrorState, LoadingState } from "../components/QueryState"
import { UploadPanel } from "../components/UploadPanel"
import { Button } from "../components/ui/Button"
import { Card } from "../components/ui/Card"
import { useApi } from "../lib/api"
import { useAuth } from "../lib/auth"
import { semesterQueryKey } from "../lib/queryKeys"
import { useSemester } from "../lib/semester"

function formatLongDate(value: string) {
  return new Intl.DateTimeFormat("en-US", { dateStyle: "long" }).format(new Date(`${value}T12:00:00`))
}

export function UploadPage() {
  const api = useApi()
  const { user } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { semesterId, setSemesterId, ready } = useSemester()
  const semestersQuery = useQuery({
    queryKey: semesterQueryKey(user?.id),
    queryFn: api.listSemesters,
    enabled: Boolean(user),
  })
  const mutation = useMutation({
    mutationFn: ({ currentSemesterId, files }: { currentSemesterId: string; files: File[] }) =>
      api.uploadSyllabi(currentSemesterId, files),
  })

  const semesters = semestersQuery.data ?? []
  const activeSemesterId = semesters.some((semester) => semester.id === semesterId)
    ? semesterId
    : semesters[0]?.id ?? null
  const activeSemester = semesters.find((semester) => semester.id === activeSemesterId)

  useEffect(() => {
    if (semestersQuery.isSuccess && activeSemesterId !== semesterId) setSemesterId(activeSemesterId)
  }, [activeSemesterId, semesterId, semestersQuery.isSuccess, setSemesterId])

  if (!ready || semestersQuery.isPending) {
    return <AppShell currentStep={2}><LoadingState label="Loading your semesters" /></AppShell>
  }
  if (semestersQuery.isError) {
    return (
      <AppShell currentStep={2}>
        <ErrorState message={semestersQuery.error.message} onRetry={() => semestersQuery.refetch()} />
      </AppShell>
    )
  }
  if (!activeSemesterId) {
    return (
      <AppShell currentStep={2}>
        <div className="mx-auto max-w-2xl">
          <Card className="p-6 text-center sm:p-8">
            <span className="mx-auto grid size-12 place-items-center rounded-xl bg-accent/10 text-accent">
              <CalendarPlus aria-hidden="true" className="size-6" />
            </span>
            <h1 className="mt-4 text-2xl font-bold text-text">Create a semester before uploading</h1>
            <p className="mt-2 text-text-muted">Your semester dates help the review step catch deadlines that look wrong.</p>
            <Button className="mt-6 w-full sm:w-auto" onClick={() => navigate("/setup")}>Create semester</Button>
          </Card>
        </div>
      </AppShell>
    )
  }
  const selectedSemesterId = activeSemesterId

  async function upload(files: File[]) {
    const response = await mutation.mutateAsync({ currentSemesterId: selectedSemesterId, files })
    queryClient.setQueryData(["jobs", selectedSemesterId], response.jobs)
    navigate("/processing")
  }

  return (
    <AppShell currentStep={2}>
      <div className="mx-auto max-w-5xl">
        <PageIntro
          eyebrow="Upload syllabi"
          title="Add every course in one batch"
          description="Each PDF gets its own processing job, so one difficult file will not hold up the rest."
        />
        <div className="grid gap-6 xl:grid-cols-[19rem_minmax(0,1fr)]">
          <Card className="self-start border-border/80 bg-panel/95 p-5">
            <label className="block text-sm font-semibold text-text" htmlFor="upload-semester">
              Upload to semester
            </label>
            <select
              className="mt-2 min-h-11 w-full cursor-pointer rounded-xl border border-border bg-panel px-3 py-2.5 text-base text-text outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-focus/20 disabled:cursor-not-allowed disabled:bg-panel-muted disabled:text-text-subtle"
              disabled={mutation.isPending}
              id="upload-semester"
              onChange={(event) => setSemesterId(event.target.value)}
              value={activeSemesterId}
            >
              {semesters.map((semester) => <option key={semester.id} value={semester.id}>{semester.name}</option>)}
            </select>
            <div className="mt-5 rounded-3xl border border-border/80 bg-panel-muted/35 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-text-subtle">Current semester range</p>
              <p className="mt-2 text-sm font-semibold text-text">
                {activeSemester ? `${formatLongDate(activeSemester.start_date)} to ${formatLongDate(activeSemester.end_date)}` : ""}
              </p>
              <p className="mt-2 text-sm leading-6 text-text-muted">
                These files will be added to {activeSemester?.name} and reviewed in {activeSemester?.timezone}.
              </p>
            </div>
            <div className="mt-5 flex flex-wrap gap-2">
              {["10 PDFs max", "20 MB each", "PDF only"].map((item) => (
                <span
                  key={item}
                  className="inline-flex min-h-8 items-center rounded-full border border-border bg-panel-muted/45 px-3 text-xs font-semibold text-text-muted"
                >
                  {item}
                </span>
              ))}
            </div>
          </Card>
          <UploadPanel onUpload={upload} />
        </div>
      </div>
    </AppShell>
  )
}
