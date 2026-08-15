import { useEffect, useRef, useState } from "react"
import dayGridPlugin from "@fullcalendar/daygrid"
import interactionPlugin from "@fullcalendar/interaction"
import FullCalendar from "@fullcalendar/react"
import { useQuery } from "@tanstack/react-query"
import {
  CalendarDays,
  ChevronRight,
  Download,
  FileUp,
  Filter,
  List,
  PanelLeftOpen,
} from "lucide-react"
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom"

import { AppShell } from "../components/AppShell"
import { ErrorState, LoadingState } from "../components/QueryState"
import { Button } from "../components/ui/Button"
import { Card } from "../components/ui/Card"
import { useApi } from "../lib/api"
import { resolveCourseDisplayColor } from "../lib/courseColors"
import { useSemester } from "../lib/semester"
import type { Course, ExtractedEvent } from "../lib/types"
import { cn } from "../lib/utils"
import { useTheme } from "../theme/ThemeProvider"

type CalendarView = "timeline" | "month" | "list"

const viewOptions: Array<{ label: string; value: CalendarView; icon: typeof PanelLeftOpen }> = [
  { label: "Timeline", value: "timeline", icon: PanelLeftOpen },
  { label: "Month", value: "month", icon: CalendarDays },
  { label: "List", value: "list", icon: List },
]

function isCalendarView(value: string | null): value is CalendarView {
  return value === "timeline" || value === "month" || value === "list"
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(
    new Date(`${value}T12:00:00`),
  )
}

function formatLongDate(value: string) {
  return new Intl.DateTimeFormat("en-US", { dateStyle: "long" }).format(
    new Date(`${value}T12:00:00`),
  )
}

function formatInputDate(value: Date) {
  const year = value.getFullYear()
  const month = `${value.getMonth() + 1}`.padStart(2, "0")
  const day = `${value.getDate()}`.padStart(2, "0")
  return `${year}-${month}-${day}`
}

function parseDateOnly(value: string) {
  return new Date(`${value}T12:00:00`)
}

function startOfWeek(value: Date) {
  const next = new Date(value)
  const weekday = next.getDay()
  const offset = weekday === 0 ? -6 : 1 - weekday
  next.setDate(next.getDate() + offset)
  next.setHours(0, 0, 0, 0)
  return next
}

export function getDateOnlyValueInTimeZone(value: Date, timeZone: string) {
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  })
  const parts = formatter.formatToParts(value)
  const year = parts.find((part) => part.type === "year")?.value
  const month = parts.find((part) => part.type === "month")?.value
  const day = parts.find((part) => part.type === "day")?.value

  if (!year || !month || !day) {
    throw new Error(`Unable to derive a calendar date for time zone ${timeZone}.`)
  }

  return `${year}-${month}-${day}`
}

export function getCurrentWeekRangeForTimezone(timeZone: string, referenceDate = new Date()) {
  const todayKey = getDateOnlyValueInTimeZone(referenceDate, timeZone)
  const firstThisWeek = startOfWeek(parseDateOnly(todayKey))
  const lastThisWeek = new Date(firstThisWeek)
  lastThisWeek.setDate(lastThisWeek.getDate() + 6)

  return {
    todayKey,
    startKey: formatInputDate(firstThisWeek),
    endKey: formatInputDate(lastThisWeek),
  }
}

function buildWeeks(startDate: string, endDate: string) {
  const firstWeek = startOfWeek(parseDateOnly(startDate))
  const finalDate = parseDateOnly(endDate)
  const weeks: Date[] = []
  for (const current = new Date(firstWeek); current <= finalDate; current.setDate(current.getDate() + 7)) {
    weeks.push(new Date(current))
  }
  return weeks
}

function getDefaultView(): CalendarView {
  return window.innerWidth <= 640 ? "list" : "timeline"
}

function getEventWeekIndex(eventDate: string, weeks: Date[]) {
  const target = startOfWeek(parseDateOnly(eventDate)).getTime()
  return weeks.findIndex((week) => week.getTime() === target)
}

function groupEventsByDate(events: ExtractedEvent[], courses: Course[]) {
  const grouped = new Map<string, Array<{ event: ExtractedEvent; course: Course | undefined }>>()
  for (const event of events) {
    if (!event.event_date) continue
    const current = grouped.get(event.event_date) ?? []
    current.push({
      event,
      course: courses.find((course) => course.id === event.course_id),
    })
    grouped.set(event.event_date, current)
  }
  return [...grouped.entries()].sort(([left], [right]) => left.localeCompare(right))
}

function getReviewStatusLabel(status: ExtractedEvent["review_status"]) {
  if (status === "needs_review") return "Needs review"
  if (status === "pending") return "Pending"
  if (status === "ignored") return "Removed"
  return "Confirmed"
}

function CalendarEmptyState({ message }: { message: string }) {
  return (
    <Card className="border-border/80 bg-panel/95 p-6 sm:p-7" data-testid="calendar-empty-state">
      <p className="text-sm font-medium text-text-muted">{message}</p>
    </Card>
  )
}

export function CalendarPage() {
  const api = useApi()
  const navigate = useNavigate()
  const { semesterId } = useSemester()
  const { resolvedTheme } = useTheme()
  const [searchParams, setSearchParams] = useSearchParams()
  const [selectedCourseIds, setSelectedCourseIds] = useState<Set<string>>(new Set())
  const [initializedCourseFiltersForSemester, setInitializedCourseFiltersForSemester] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const timelineScrollerRef = useRef<HTMLDivElement>(null)
  const thisWeekSummaryRef = useRef<HTMLDivElement>(null)
  const reviewQuery = useQuery({
    queryKey: ["review", semesterId],
    queryFn: () => api.getReview(semesterId!),
    enabled: Boolean(semesterId),
  })
  const eventsQuery = useQuery({
    queryKey: ["events", semesterId],
    queryFn: () => api.listEvents(semesterId!),
    enabled: Boolean(semesterId),
  })

  const requestedView = searchParams.get("view")
  const defaultView = getDefaultView()
  const currentView = isCalendarView(requestedView) ? requestedView : defaultView

  useEffect(() => {
    if (requestedView !== currentView) {
      const next = new URLSearchParams(searchParams)
      next.set("view", currentView)
      setSearchParams(next, { replace: true })
    }
  }, [currentView, requestedView, searchParams, setSearchParams])

  useEffect(() => {
    if (!reviewQuery.data) return
    if (initializedCourseFiltersForSemester === reviewQuery.data.semester.id) return
    setSelectedCourseIds(new Set(reviewQuery.data.courses.map((course) => course.id)))
    setInitializedCourseFiltersForSemester(reviewQuery.data.semester.id)
  }, [initializedCourseFiltersForSemester, reviewQuery.data])

  if (!semesterId) return <Navigate replace to="/setup" />
  if (reviewQuery.isPending || eventsQuery.isPending) {
    return (
      <AppShell>
        <LoadingState label="Building your semester calendar" />
      </AppShell>
    )
  }
  const error = reviewQuery.error ?? eventsQuery.error
  if (error || !reviewQuery.data) {
    return (
      <AppShell>
        <ErrorState message={error?.message ?? "Calendar data is not available."} />
      </AppShell>
    )
  }

  const { semester, courses, events: reviewEvents } = reviewQuery.data
  const courseDisplayColors = new Map(
    courses.map((course) => [
      course.id,
      resolveCourseDisplayColor(course.id, course.color, resolvedTheme),
    ]),
  )
  const courseById = new Map(courses.map((course) => [course.id, course]))
  const weeks = buildWeeks(semester.start_date, semester.end_date)
  const thisWeekRange = getCurrentWeekRangeForTimezone(semester.timezone)
  const filteredCourseIds = [...selectedCourseIds]
  const hasSelectedCourses = selectedCourseIds.size > 0
  const exportDisabledReason = hasSelectedCourses ? null : "Select at least one course to export a filtered calendar."
  const visibleEvents = (eventsQuery.data ?? []).filter((event) => selectedCourseIds.has(event.course_id))
  const pendingItems = reviewEvents.filter(
    (event) =>
      selectedCourseIds.has(event.course_id) &&
      (event.review_status === "needs_review" || event.review_status === "pending"),
  )
  const groupedEvents = groupEventsByDate(visibleEvents, courses)
  const timelineCourses = courses.filter((course) => selectedCourseIds.has(course.id))
  const unresolvedCount = reviewEvents.filter((event) => event.review_status === "needs_review").length
  const thisWeekEvents = visibleEvents
    .filter(
      (event) =>
        event.event_date &&
        event.event_date >= thisWeekRange.startKey &&
        event.event_date <= thisWeekRange.endKey,
    )
    .sort((left, right) => (left.event_date ?? "").localeCompare(right.event_date ?? "") || left.title.localeCompare(right.title))
  const monthEvents = visibleEvents.flatMap((event) => {
    if (!event.event_date) return []
    const course = courseById.get(event.course_id)
    const displayColor =
      courseDisplayColors.get(event.course_id) ??
      resolveCourseDisplayColor(event.course_id, course?.color, resolvedTheme)
    return [
      {
        id: event.id,
        title: `${course?.code || course?.name || "Course"} ${event.title}`,
        start: event.start_time ? `${event.event_date}T${event.start_time}` : event.event_date,
        allDay: event.is_all_day,
        backgroundColor: displayColor,
        borderColor: displayColor,
      },
    ]
  })

  function setView(view: CalendarView) {
    const next = new URLSearchParams(searchParams)
    next.set("view", view)
    setSearchParams(next)
  }

  function toggleCourse(courseId: string) {
    setSelectedCourseIds((current) => {
      const next = new Set(current)
      if (next.has(courseId)) next.delete(courseId)
      else next.add(courseId)
      return next
    })
  }

  async function handleExport() {
    if (!hasSelectedCourses) return
    setDownloading(true)
    setDownloadError(null)
    try {
      const blob = await api.getCalendar(semesterId!, filteredCourseIds)
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = `${semester.name.toLowerCase().replace(/\s+/g, "-")}.ics`
      link.click()
      URL.revokeObjectURL(url)
    } catch (caught) {
      setDownloadError(caught instanceof Error ? caught.message : "The calendar could not be downloaded.")
    } finally {
      setDownloading(false)
    }
  }

  function jumpToThisWeek() {
    thisWeekSummaryRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })
    const scroller = timelineScrollerRef.current
    if (!scroller) return
    const targetWeek = getEventWeekIndex(thisWeekRange.startKey, weeks)
    if (targetWeek < 0) return
    const weekWidth = 184
    scroller.scrollTo({
      left: Math.max(targetWeek * weekWidth, 0),
      behavior: "smooth",
    })
  }

  function openReview(eventId: string) {
    navigate(`/review?eventId=${eventId}`)
  }

  return (
    <AppShell>
      <div className="overflow-x-hidden">
        <Card className="border-border/80 bg-panel/95 p-5 shadow-panel sm:p-6">
          <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex min-h-8 items-center rounded-full border border-border bg-panel-muted/50 px-3 text-xs font-semibold uppercase tracking-[0.16em] text-text-subtle">
                  Term view
                </span>
                <span className="inline-flex min-h-8 items-center rounded-full border border-border bg-panel px-3 text-xs font-semibold text-text-muted">
                  {courses.length} course{courses.length === 1 ? "" : "s"}
                </span>
              </div>
              <div>
                <h1 className="text-3xl font-bold tracking-[-0.03em] text-text">
                  {semester.name}
                </h1>
                <p className="mt-2 text-sm text-text-muted">
                  {formatLongDate(semester.start_date)} to {formatLongDate(semester.end_date)}
                </p>
              </div>
            </div>
            <div className="flex flex-col gap-2 sm:items-end">
              <div className="flex flex-col gap-2 sm:flex-row">
                <Link
                  className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-accent-contrast transition-colors hover:bg-accent-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-bg-app"
                  to="/review"
                >
                  Review {unresolvedCount} unresolved items
                </Link>
                <Button onClick={() => navigate("/upload")} type="button" variant="secondary">
                  <FileUp aria-hidden="true" className="size-4" />
                  Add syllabi
                </Button>
                <Button
                  aria-describedby={exportDisabledReason ? "calendar-export-hint" : undefined}
                  disabled={!hasSelectedCourses}
                  loading={downloading}
                  onClick={() => void handleExport()}
                  type="button"
                >
                  <Download aria-hidden="true" className="size-4" />
                  Export
                </Button>
              </div>
              {exportDisabledReason ? (
                <p className="text-sm text-text-muted" id="calendar-export-hint">
                  {exportDisabledReason}
                </p>
              ) : null}
            </div>
          </div>

          <div className="mt-5 flex flex-col gap-3 border-t border-border/80 pt-5 lg:flex-row lg:items-center lg:justify-between">
            <div className="inline-flex flex-wrap gap-2 rounded-2xl border border-border/80 bg-panel-muted/50 p-1">
              {viewOptions.map(({ icon: Icon, label, value }) => (
                <button
                  key={value}
                  aria-pressed={currentView === value}
                  className={cn(
                    "inline-flex min-h-11 items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-bg-app",
                    currentView === value
                      ? "bg-panel text-accent shadow-sm"
                      : "text-text-muted hover:text-text",
                  )}
                  onClick={() => setView(value)}
                  type="button"
                >
                  <Icon aria-hidden="true" className="size-4" />
                  {label}
                </button>
              ))}
            </div>
            <Button onClick={jumpToThisWeek} type="button" variant="secondary">
              This week
            </Button>
          </div>

          <div className="mt-5 grid gap-5 xl:grid-cols-[16rem_minmax(0,1fr)]">
            <aside aria-label="Course filters" role="region">
              <Card className="border-border/80 bg-panel-muted/35 p-4">
                <div className="flex items-center gap-2 font-semibold text-text">
                  <Filter aria-hidden="true" className="size-4 text-accent" />
                  Course filters
                </div>
                <p className="mt-2 text-sm text-text-muted">
                  These same filters drive timeline, month, list, and ICS export.
                </p>
                <div className="mt-4 grid gap-2">
                  {courses.map((course) => (
                    <label
                      className="flex min-h-11 cursor-pointer items-center gap-3 rounded-2xl border border-transparent px-3 py-2 text-sm font-medium text-text-muted transition-colors hover:border-border hover:bg-panel"
                      key={course.id}
                    >
                      <input
                        aria-label={course.code || course.name}
                        checked={selectedCourseIds.has(course.id)}
                        className="size-4 accent-accent"
                        onChange={() => toggleCourse(course.id)}
                        type="checkbox"
                      />
                      <span
                        className="size-2.5 shrink-0 rounded-full"
                        style={{ backgroundColor: courseDisplayColors.get(course.id) ?? course.color }}
                      />
                      <span className="truncate">{course.code || course.name}</span>
                    </label>
                  ))}
                </div>
              </Card>
            </aside>

            <div className="min-w-0 space-y-4">
              <div ref={thisWeekSummaryRef}>
                <Card className="border-border/80 bg-panel/95 p-4 sm:p-5">
                <div className="flex items-center justify-between gap-3">
                  <h2 className="text-lg font-semibold text-text">This week</h2>
                  <p className="text-sm text-text-subtle">
                    {formatDate(thisWeekRange.startKey)} to {formatDate(thisWeekRange.endKey)}
                  </p>
                </div>
                {thisWeekEvents.length ? (
                  <div className="mt-4 grid gap-3">
                    {thisWeekEvents.map((event) => {
                      const course = courseById.get(event.course_id)
                      const courseDisplayColor =
                        courseDisplayColors.get(event.course_id) ??
                        resolveCourseDisplayColor(event.course_id, course?.color, resolvedTheme)
                      return (
                        <Link
                          key={event.id}
                          className="rounded-2xl border border-border/80 bg-panel-muted/35 px-4 py-4 transition-colors hover:border-accent hover:bg-panel focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-bg-app"
                          to={`/review?eventId=${event.id}`}
                        >
                          <div className="flex items-center gap-3">
                            <span
                              aria-hidden="true"
                              className="h-10 w-1.5 rounded-full"
                              style={{ backgroundColor: courseDisplayColor }}
                            />
                            <div className="min-w-0">
                              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-text-subtle">
                                {course?.code || course?.name || "Course"}
                              </p>
                              <p className="mt-1 font-semibold text-text">{event.title}</p>
                              <p className="mt-1 text-sm text-text-muted">
                                {formatDate(event.event_date!)}
                                {event.start_time ? `  ${event.start_time.slice(0, 5)}` : ""}
                              </p>
                            </div>
                          </div>
                        </Link>
                      )
                    })}
                  </div>
                ) : (
                  <p className="mt-4 text-sm text-text-muted">
                    No confirmed events fall in this Monday through Sunday window.
                  </p>
                )}
                </Card>
              </div>

              {pendingItems.length ? (
                <Card className="border-warning-border bg-warning-soft p-4">
                  <div className="flex items-center justify-between gap-3">
                    <h2 className="text-lg font-semibold text-text">Pending items</h2>
                    <span className="rounded-full border border-warning-border bg-panel px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em] text-warning">
                      Needs attention
                    </span>
                  </div>
                  <div className="mt-3 grid gap-2">
                    {pendingItems.map((event) => {
                      const course = courseById.get(event.course_id)
                      return (
                        <button
                          key={event.id}
                          className="flex min-h-11 items-center justify-between gap-3 rounded-2xl border border-border/80 bg-panel px-4 py-3 text-left text-sm text-text-muted transition-colors hover:border-warning-border hover:bg-warning-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-bg-app"
                          onClick={() => openReview(event.id)}
                          onKeyDown={(keyEvent) => {
                            if (keyEvent.key === " " || keyEvent.key === "Enter") {
                              keyEvent.preventDefault()
                              openReview(event.id)
                            }
                          }}
                          type="button"
                        >
                          <div className="min-w-0">
                            <p className="font-semibold text-text">
                              {course?.code || course?.name || "Course"}
                            </p>
                            <p className="truncate">{event.title}</p>
                            <p className="mt-1 text-xs text-text-subtle">
                              Page {event.source_page}  {getReviewStatusLabel(event.review_status)}
                            </p>
                          </div>
                          <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-text-subtle" />
                        </button>
                      )
                    })}
                  </div>
                </Card>
              ) : null}

              {downloadError ? <p className="text-sm font-medium text-danger">{downloadError}</p> : null}

              {currentView === "timeline" ? (
                hasSelectedCourses ? (
                  <Card className="overflow-hidden border-border/80 bg-panel/95" role="region" aria-label="Semester timeline">
                    <div className="overflow-x-auto" data-testid="timeline-scroll-region" ref={timelineScrollerRef}>
                      <div
                        className="grid min-w-[calc(14rem+11.5rem)]"
                        style={{ gridTemplateColumns: `14rem repeat(${weeks.length}, minmax(11.5rem, 11.5rem))` }}
                      >
                        <div className="sticky left-0 z-30 border-b border-r border-border bg-panel-muted/75 px-4 py-3 text-sm font-semibold text-text">
                          Course
                        </div>
                        {weeks.map((week) => (
                          <div
                            className="border-b border-l border-border bg-panel-muted/75 px-4 py-3 text-sm font-semibold text-text"
                            key={week.toISOString()}
                          >
                            {new Intl.DateTimeFormat("en-US", {
                              month: "short",
                              day: "numeric",
                            }).format(week)}
                          </div>
                        ))}

                        {timelineCourses.map((course) => (
                          <FragmentRow
                            key={course.id}
                            course={course}
                            courseColor={courseDisplayColors.get(course.id) ?? course.color}
                            courseEvents={visibleEvents.filter((event) => event.course_id === course.id)}
                            weeks={weeks}
                          />
                        ))}
                      </div>
                    </div>
                  </Card>
                ) : (
                  <CalendarEmptyState message="Select at least one course to see calendar events." />
                )
              ) : null}

              {currentView === "month" ? (
                hasSelectedCourses ? (
                  <Card className="overflow-hidden border-border/80 p-3 sm:p-4">
                    <FullCalendar
                      eventClick={(info) => {
                        info.jsEvent.preventDefault()
                        navigate(`/review?eventId=${info.event.id}`)
                      }}
                      events={monthEvents}
                      firstDay={1}
                      fixedWeekCount={false}
                      headerToolbar={{ left: "prev,next", center: "title", right: "today" }}
                      initialDate={semester.start_date}
                      plugins={[dayGridPlugin, interactionPlugin]}
                      showNonCurrentDates={false}
                    />
                  </Card>
                ) : (
                  <CalendarEmptyState message="Select at least one course to see calendar events." />
                )
              ) : null}

              {currentView === "list" ? (
                !hasSelectedCourses ? (
                  <CalendarEmptyState message="Select at least one course to see calendar events." />
                ) : (
                  <Card className="border-border/80 bg-panel/95 p-4 sm:p-5">
                    <div className="space-y-5">
                      {groupedEvents.map(([eventDate, items]) => (
                        <section key={eventDate}>
                          <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-text-subtle">
                            {formatLongDate(eventDate)}
                          </h2>
                          <div className="mt-3 grid gap-3">
                            {items.map(({ event, course }) => {
                              const courseDisplayColor =
                                courseDisplayColors.get(event.course_id) ??
                                resolveCourseDisplayColor(event.course_id, course?.color, resolvedTheme)
                              return (
                                <Link
                                  className="rounded-2xl border border-border/80 bg-panel-muted/35 px-4 py-4 transition-colors hover:border-accent hover:bg-panel focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-bg-app"
                                  key={event.id}
                                  to={`/review?eventId=${event.id}`}
                                >
                                  <div className="flex items-start gap-3">
                                    <span
                                      aria-hidden="true"
                                      className="mt-0.5 h-10 w-1.5 shrink-0 rounded-full"
                                      style={{ backgroundColor: courseDisplayColor }}
                                    />
                                    <div className="min-w-0">
                                      <div className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-text-subtle">
                                        <span>{course?.code || course?.name || "Course"}</span>
                                        <span>{event.event_type}</span>
                                      </div>
                                      <p className="mt-2 text-base font-semibold text-text">{event.title}</p>
                                      <p className="mt-1 text-sm text-text-muted">
                                        {event.start_time ? event.start_time.slice(0, 5) : "All day"}
                                      </p>
                                    </div>
                                  </div>
                                </Link>
                              )
                            })}
                          </div>
                        </section>
                      ))}
                      {!groupedEvents.length ? (
                        <p className="text-sm text-text-muted">
                          No confirmed dates match the current course filters.
                        </p>
                      ) : null}
                    </div>
                  </Card>
                )
              ) : null}
            </div>
          </div>
        </Card>
      </div>
    </AppShell>
  )
}

function FragmentRow({
  course,
  courseColor,
  courseEvents,
  weeks,
}: {
  course: Course
  courseColor: string
  courseEvents: ExtractedEvent[]
  weeks: Date[]
}) {
  return (
    <>
      <div className="sticky left-0 z-20 flex items-center gap-3 border-b border-r border-border bg-panel px-4 py-4">
        <span className="size-3 rounded-full" style={{ backgroundColor: courseColor }} />
        <div className="min-w-0">
          <p className="truncate font-semibold text-text">{course.code || course.name}</p>
          <p className="truncate text-xs text-text-subtle">{course.name}</p>
        </div>
      </div>
      {weeks.map((week, weekIndex) => {
        const eventsForCell = courseEvents.filter(
          (event) =>
            event.event_date &&
            getEventWeekIndex(event.event_date, weeks) === weekIndex,
        )
        return (
          <div className="min-h-28 border-b border-l border-border px-3 py-3" key={`${course.id}-${week.toISOString()}`}>
            <div className="grid gap-2">
              {eventsForCell.map((event) => (
                <Link
                  key={event.id}
                  className="rounded-2xl border px-3 py-2 text-sm font-medium text-text transition-colors hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-bg-app"
                  style={{
                    backgroundColor: `${courseColor}15`,
                    borderColor: `${courseColor}55`,
                  }}
                  to={`/review?eventId=${event.id}`}
                >
                  <p className="line-clamp-2">{event.title}</p>
                  <p className="mt-1 text-xs text-text-muted">{formatDate(event.event_date!)}</p>
                </Link>
              ))}
            </div>
          </div>
        )
      })}
    </>
  )
}
