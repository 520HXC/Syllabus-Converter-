import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"

import { AppShell } from "../components/AppShell"
import { PageIntro } from "../components/PageIntro"
import { SemesterForm, type SemesterFormValues } from "../components/SemesterForm"
import { Card } from "../components/ui/Card"
import { useApi } from "../lib/api"
import { useAuth } from "../lib/auth"
import { semesterQueryKey } from "../lib/queryKeys"
import { useSemester } from "../lib/semester"

export function SemesterSetupPage() {
  const api = useApi()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { setSemesterId } = useSemester()
  const mutation = useMutation({ mutationFn: api.createSemester })
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "America/New_York"

  async function save(values: SemesterFormValues) {
    const semester = await mutation.mutateAsync(values)
    setSemesterId(semester.id)
    queryClient.setQueryData(semesterQueryKey(user?.id), (current: unknown) =>
      Array.isArray(current) ? [semester, ...current] : [semester],
    )
    navigate("/upload")
  }

  return (
    <AppShell currentStep={1}>
      <div className="mx-auto max-w-5xl">
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_18rem]">
          <div>
            <PageIntro
              description="These dates help catch deadlines that look wrong before they reach your calendar."
              eyebrow="Semester setup"
              title="Set the boundaries for your calendar"
            />
            <Card className="border-border/80 bg-panel/95 p-5 sm:p-7">
              <SemesterForm defaultTimezone={timezone} onSubmit={save} />
              {mutation.error ? (
                <p className="mt-4 text-sm font-medium text-danger">{mutation.error.message}</p>
              ) : null}
            </Card>
          </div>
          <aside className="self-start">
            <Card className="border-border/80 bg-panel/90 p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-text-subtle">What this locks in</p>
              <ul className="mt-4 grid gap-4" role="list">
                <li>
                  <p className="text-sm font-semibold text-text">Review coverage</p>
                  <p className="mt-1 text-sm leading-6 text-text-muted">
                    Review flags compare extracted dates against this range.
                  </p>
                </li>
                <li>
                  <p className="text-sm font-semibold text-text">Calendar export</p>
                  <p className="mt-1 text-sm leading-6 text-text-muted">
                    Calendar export keeps every all-day event in this timezone.
                  </p>
                </li>
                <li>
                  <p className="text-sm font-semibold text-text">Default target</p>
                  <p className="mt-1 text-sm leading-6 text-text-muted">
                    Your next upload will start in {timezone}.
                  </p>
                </li>
              </ul>
            </Card>
          </aside>
        </div>
      </div>
    </AppShell>
  )
}
