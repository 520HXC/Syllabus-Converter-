import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { CalendarCheck2, Check, FileSearch, ShieldCheck } from "lucide-react"

import { useAuth } from "../lib/auth"
import { Button } from "../components/ui/Button"

function GoogleMark() {
  return (
    <svg aria-hidden="true" className="size-4" viewBox="0 0 24 24">
      <path fill="#4285F4" d="M21.6 12.23c0-.71-.06-1.4-.18-2.07H12v3.92h5.38a4.6 4.6 0 0 1-2 3.02v2.54h3.24c1.9-1.75 2.98-4.33 2.98-7.41Z" />
      <path fill="#34A853" d="M12 22c2.7 0 4.98-.9 6.63-2.36l-3.24-2.54c-.9.6-2.05.96-3.39.96-2.61 0-4.82-1.77-5.61-4.14H3.04v2.62A10 10 0 0 0 12 22Z" />
      <path fill="#FBBC05" d="M6.39 13.92A6.01 6.01 0 0 1 6.08 12c0-.67.12-1.32.31-1.92V7.46H3.04A10 10 0 0 0 2 12c0 1.62.39 3.16 1.04 4.54l3.35-2.62Z" />
      <path fill="#EA4335" d="M12 5.94c1.47 0 2.79.51 3.83 1.5l2.87-2.88A9.64 9.64 0 0 0 12 2a10 10 0 0 0-8.96 5.46l3.35 2.62C7.18 7.71 9.39 5.94 12 5.94Z" />
    </svg>
  )
}

export function LandingPage() {
  const { signIn, isDemo } = useAuth()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function continueToApp() {
    setLoading(true)
    setError(null)
    try {
      await signIn()
      if (isDemo) navigate("/semesters")
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Sign in could not be started.")
      setLoading(false)
    }
  }

  return (
    <main className="relative min-h-screen overflow-hidden px-4 py-6 sm:px-6 sm:py-10">
      <div className="page-hero-glow pointer-events-none absolute inset-0" />
      <div className="relative mx-auto flex min-h-[calc(100vh-3rem)] max-w-6xl flex-col">
        <div className="flex items-center gap-2.5 font-bold text-text">
          <span className="grid size-10 place-items-center rounded-2xl bg-accent text-accent-contrast shadow-sm">
            <CalendarCheck2 aria-hidden="true" className="size-5" />
          </span>
          <span>Syllabus Calendar</span>
        </div>

        <section className="mx-auto my-auto grid w-full max-w-5xl items-center gap-10 py-12 lg:grid-cols-[1.02fr_0.98fr] lg:py-16">
          <div className="max-w-2xl">
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-text-subtle">A calmer semester starts here</p>
            <h1 className="mt-4 max-w-2xl text-4xl font-bold leading-tight tracking-[-0.04em] text-text sm:text-5xl lg:text-6xl">
              Turn your syllabi into one reviewed calendar.
            </h1>
            <p className="mt-5 max-w-xl text-lg leading-8 text-text-muted">
              Upload your course PDFs, check every extracted date, and export a clean calendar without copying deadlines by hand.
            </p>
            <div className="mt-8 grid gap-3 sm:grid-cols-3">
              {["See processing status", "Review uncertain dates", "Export one ICS file"].map((item) => (
                <div key={item} className="rounded-2xl border border-border/80 bg-panel/85 px-4 py-4 shadow-panel backdrop-blur">
                  <span className="inline-flex size-8 items-center justify-center rounded-xl bg-accent/10 text-accent">
                    <Check aria-hidden="true" className="size-4" />
                  </span>
                  <p className="mt-3 text-sm font-semibold text-text">{item}</p>
                </div>
              ))}
            </div>
            <Button className="mt-8 w-full sm:w-auto" loading={loading} onClick={continueToApp}>
              {isDemo ? <FileSearch aria-hidden="true" className="size-4" /> : <GoogleMark />}
              {isDemo ? "Try the local demo" : "Continue with Google"}
            </Button>
            {error ? <p className="mt-3 text-sm font-medium text-danger">{error}</p> : null}
            <p className="mt-4 flex items-center gap-2 text-xs text-text-subtle">
              <ShieldCheck aria-hidden="true" className="size-4" />
              Your calendar stays private to your account.
            </p>
          </div>

          <section
            aria-label="Preview of your semester workflow"
            className="mx-auto w-full max-w-xl rounded-[2rem] border border-border/80 bg-panel/92 p-5 shadow-panel backdrop-blur sm:p-6"
          >
            <div className="flex items-start justify-between gap-4 border-b border-border/80 pb-5">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-text-subtle">Preview</p>
                <h2 className="mt-2 text-2xl font-bold tracking-[-0.03em] text-text">This week in Fall 2026</h2>
                <p className="mt-2 text-sm leading-6 text-text-muted">3 course files uploaded. 2 files still need review.</p>
              </div>
              <div className="grid size-11 place-items-center rounded-2xl bg-accent/10 text-accent">
                <CalendarCheck2 className="size-5" />
              </div>
            </div>
            <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_13rem]">
              <div className="rounded-3xl border border-border/80 bg-panel-muted/35 p-4">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-semibold text-text">Upcoming review queue</p>
                  <span className="rounded-full bg-warning-soft px-2.5 py-1 text-xs font-semibold text-warning">2 blockers</span>
                </div>
                <ul className="mt-4 grid gap-3" role="list">
                  {[
                    { title: "BIO 201 lab report", when: "Tue, Sep 9", state: "Ready to confirm" },
                    { title: "PSY 110 midterm window", when: "Thu, Sep 18", state: "Needs source check" },
                    { title: "CHEM 140 final exam", when: "Mon, Dec 14", state: "Confirmed after review" },
                  ].map((item) => (
                    <li key={item.title} className="rounded-2xl border border-border/80 bg-panel px-4 py-3">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-sm font-semibold text-text">{item.title}</p>
                        <span className="text-xs font-semibold text-text-subtle">{item.when}</span>
                      </div>
                      <p className="mt-1 text-sm text-text-muted">{item.state}</p>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="grid gap-3">
                <div className="rounded-3xl border border-border/80 bg-panel-muted/35 p-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-text-subtle">Files</p>
                  <p className="mt-2 text-3xl font-bold tracking-[-0.04em] text-text">3</p>
                  <p className="mt-1 text-sm text-text-muted">Uploaded PDFs</p>
                </div>
                <div className="rounded-3xl border border-warning-border bg-warning-soft p-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-warning">Needs review</p>
                  <p className="mt-2 text-3xl font-bold tracking-[-0.04em] text-warning">2</p>
                  <p className="mt-1 text-sm text-warning">Files still need review</p>
                </div>
                <div className="rounded-3xl border border-border/80 bg-panel-muted/35 p-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-text-subtle">Export</p>
                  <p className="mt-2 text-lg font-semibold text-text">One clean ICS</p>
                  <p className="mt-1 text-sm text-text-muted">Ready after confirmation</p>
                </div>
              </div>
            </div>
          </section>
        </section>
      </div>
    </main>
  )
}
