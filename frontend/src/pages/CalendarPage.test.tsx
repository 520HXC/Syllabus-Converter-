import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom"

import type { ExtractedEvent, ReviewPayload } from "../lib/types"
import { CalendarPage, getCurrentWeekRangeForTimezone } from "./CalendarPage"

function getReferenceNow() {
  const now = new Date()
  now.setHours(12, 0, 0, 0)
  return now
}

function getWeekStart(reference = getReferenceNow()) {
  const start = new Date(reference)
  const day = start.getDay()
  const offset = day === 0 ? -6 : 1 - day
  start.setDate(start.getDate() + offset)
  return start
}

function formatDate(date: Date) {
  const year = date.getFullYear()
  const month = `${date.getMonth() + 1}`.padStart(2, "0")
  const day = `${date.getDate()}`.padStart(2, "0")
  return `${year}-${month}-${day}`
}

function formatDateOffset(days: number) {
  const target = getReferenceNow()
  target.setDate(target.getDate() + days)
  return formatDate(target)
}

function formatShortDate(value: string) {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(
    new Date(`${value}T12:00:00`),
  )
}

function formatWeekRange(startOffset: number, endOffset: number) {
  return `${formatShortDate(formatDateOffset(startOffset))} to ${formatShortDate(formatDateOffset(endOffset))}`
}

function formatWeekRangeFromDates(start: Date, end: Date) {
  return `${formatShortDate(formatDate(start))} to ${formatShortDate(formatDate(end))}`
}

function getDateInCurrentWeek(daysFromMonday: number) {
  const date = getWeekStart()
  date.setDate(date.getDate() + daysFromMonday)
  return date
}

function createReviewEvent(overrides: Partial<ExtractedEvent>): ExtractedEvent {
  return {
    id: "review-event",
    semester_id: "semester-1",
    course_id: "course-1",
    document_id: "document-1",
    title: "Review event",
    event_type: "exam",
    event_date: null,
    start_time: null,
    end_time: null,
    timezone: "America/New_York",
    is_all_day: true,
    source_quote: "Review source quote",
    source_page: 1,
    confidence: "medium",
    warning_codes: [],
    warning_reason: null,
    review_status: "pending",
    recurring_series_id: null,
    ...overrides,
  }
}

const getCalendarMock = vi.hoisted(() => vi.fn(async () => new Blob(["BEGIN:VCALENDAR"])))
const scrollIntoViewMock = vi.hoisted(() => vi.fn())
const listEventsMock = vi.hoisted(() => vi.fn())
const reviewData = vi.hoisted(
  (): ReviewPayload => ({
  semester: {
    id: "semester-1",
    name: "Fall 2026",
    start_date: "2026-08-24",
    end_date: "2026-12-18",
    timezone: "America/New_York",
    review_completed_at: "2026-09-01T12:00:00Z",
    course_count: 2,
    document_count: 2,
    event_count: 1,
    needs_review_count: 0,
  },
  courses: [
    {
      id: "course-1",
      document_id: "document-1",
      code: "CS 101",
      name: "Intro to CS",
      instructor: "Dr. Rivera",
      color: "#0D9488",
    },
    {
      id: "course-2",
      document_id: "document-2",
      code: "MATH 201",
      name: "Discrete Math",
      instructor: "Prof. Stone",
      color: "#2563EB",
    },
  ],
  documents: [],
  events: [
    {
      id: "event-1",
      semester_id: "semester-1",
      course_id: "course-1",
      document_id: "document-1",
      title: "Final exam",
      event_type: "exam",
      event_date: null,
      start_time: null,
      end_time: null,
      timezone: "America/New_York",
      is_all_day: true,
      source_quote: "Final exam as scheduled by Registrar",
      source_page: 1,
      confidence: "low" as const,
      warning_codes: ["DATE_MISSING"],
      warning_reason: "The event does not have a confirmed date.",
      review_status: "pending" as const,
    },
  ],
}))

vi.mock("@fullcalendar/react", () => ({ default: () => <div data-testid="calendar" /> }))
vi.mock("../lib/auth", () => ({
  useAuth: () => ({
    user: { id: "user-1", email: "student@example.com" },
    signOut: vi.fn(),
  }),
}))
vi.mock("../lib/semester", () => ({
  useSemester: () => ({
    semesterId: "semester-1",
    setSemesterId: vi.fn(),
  }),
}))
vi.mock("../lib/api", () => ({
  useApi: () => ({
    getReview: vi.fn().mockResolvedValue(reviewData),
    listEvents: listEventsMock,
    getCalendar: getCalendarMock,
  }),
}))

function LocationDisplay() {
  const location = useLocation()

  return <div aria-label="Current route">{`${location.pathname}${location.search}`}</div>
}

function renderCalendarPage(initialEntry = "/calendar") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <QueryClientProvider client={queryClient}>
        <Routes>
          <Route path="/calendar" element={<><LocationDisplay /><CalendarPage /></>} />
          <Route path="/review" element={<LocationDisplay />} />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

function getThisWeekSection() {
  const thisWeekHeading = screen.getByRole("heading", { name: "This week" })
  const thisWeekSection = thisWeekHeading.parentElement?.parentElement
  expect(thisWeekSection).not.toBeNull()
  return thisWeekSection as HTMLElement
}

beforeEach(() => {
  const currentWeekWednesday = getDateInCurrentWeek(2)
  reviewData.events = [
    createReviewEvent({
      id: "event-1",
      title: "Final exam",
      confidence: "low",
      source_quote: "Final exam as scheduled by Registrar",
      warning_codes: ["DATE_MISSING"],
      warning_reason: "The event does not have a confirmed date.",
    }),
  ]
  getCalendarMock.mockClear()
  listEventsMock.mockClear()
  listEventsMock.mockImplementation(async (): Promise<ExtractedEvent[]> => [
    {
      id: "event-4",
      semester_id: "semester-1",
      course_id: "course-1",
      document_id: "document-1",
      title: "Office hours kickoff",
      event_type: "meeting",
      event_date: formatDate(currentWeekWednesday),
      start_time: "14:30:00",
      end_time: null,
      timezone: "America/New_York",
      is_all_day: false,
      source_quote: "Office hours kickoff on September 18",
      source_page: 6,
      confidence: "medium" as const,
      warning_codes: [],
      warning_reason: null,
      review_status: "confirmed" as const,
    },
    {
      id: "event-2",
      semester_id: "semester-1",
      course_id: "course-1",
      document_id: "document-1",
      title: "Midterm",
      event_type: "exam",
      event_date: "2026-10-14",
      start_time: null,
      end_time: null,
      timezone: "America/New_York",
      is_all_day: true,
      source_quote: "Midterm exam October 14",
      source_page: 3,
      confidence: "high" as const,
      warning_codes: [],
      warning_reason: null,
      review_status: "confirmed" as const,
    },
    {
      id: "event-3",
      semester_id: "semester-1",
      course_id: "course-2",
      document_id: "document-2",
      title: "Quiz 1",
      event_type: "quiz",
      event_date: "2026-09-15",
      start_time: null,
      end_time: null,
      timezone: "America/New_York",
      is_all_day: true,
      source_quote: "Quiz 1 takes place on September 15",
      source_page: 2,
      confidence: "high" as const,
      warning_codes: [],
      warning_reason: null,
      review_status: "confirmed" as const,
    },
  ])
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: 1280,
  })
  global.URL.createObjectURL = vi.fn(() => "blob:calendar")
  global.URL.revokeObjectURL = vi.fn()
  HTMLAnchorElement.prototype.click = vi.fn()
  scrollIntoViewMock.mockReset()
  Object.defineProperty(window.HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: scrollIntoViewMock,
  })
})

test("shows the approved header actions, this week section, shared timeline scroller, and deep links", async () => {
  const user = userEvent.setup()
  const monday = getWeekStart()
  const sunday = new Date(monday)
  sunday.setDate(sunday.getDate() + 6)
  renderCalendarPage()

  expect(await screen.findByRole("heading", { name: "Fall 2026" })).toBeInTheDocument()
  expect(screen.queryByText("Semester calendar")).not.toBeInTheDocument()
  expect(screen.getByRole("link", { name: "Review 0 unresolved items" })).toHaveAttribute("href", "/review")
  expect(screen.getByRole("button", { name: "Add syllabi" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Export" })).toBeInTheDocument()
  expect(screen.getByRole("region", { name: "Course filters" })).toBeInTheDocument()
  expect(await screen.findByRole("button", { name: "Timeline" })).toHaveAttribute("aria-pressed", "true")
  expect(screen.getByLabelText("Current route")).toHaveTextContent("/calendar?view=timeline")
  expect(screen.getByRole("link", { name: /Final exam/i })).toHaveAttribute("href", "/review?eventId=event-1")
  const thisWeekSection = getThisWeekSection()
  expect(within(thisWeekSection).getByRole("link", { name: /Office hours kickoff/i })).toHaveAttribute("href", "/review?eventId=event-4")
  expect(screen.getByText(formatWeekRangeFromDates(monday, sunday))).toBeInTheDocument()
  expect(screen.getAllByTestId("timeline-scroll-region")).toHaveLength(1)
  expect(screen.getByRole("region", { name: "Semester timeline" })).toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "List" }))

  expect(screen.getByRole("button", { name: "List" })).toHaveAttribute("aria-pressed", "true")
  expect(screen.getByLabelText("Current route")).toHaveTextContent("/calendar?view=list")
})

test("defaults to list on mobile and exports only the selected course filters", async () => {
  const user = userEvent.setup()
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: 375,
  })
  renderCalendarPage()

  expect(await screen.findByRole("button", { name: "List" })).toHaveAttribute("aria-pressed", "true")
  await user.click(screen.getByRole("checkbox", { name: /MATH 201/i }))
  await user.click(screen.getByRole("button", { name: "Export" }))

  await waitFor(() => expect(getCalendarMock).toHaveBeenCalledWith("semester-1", ["course-1"]))
})

test("lets the user deselect all courses without auto-restoring the defaults", async () => {
  const user = userEvent.setup()
  renderCalendarPage()

  expect(await screen.findByRole("checkbox", { name: /CS 101/i })).toBeChecked()
  expect(screen.getByRole("checkbox", { name: /MATH 201/i })).toBeChecked()

  await user.click(screen.getByRole("checkbox", { name: /CS 101/i }))
  await user.click(screen.getByRole("checkbox", { name: /MATH 201/i }))

  expect(screen.getByRole("checkbox", { name: /CS 101/i })).not.toBeChecked()
  expect(screen.getByRole("checkbox", { name: /MATH 201/i })).not.toBeChecked()
  expect(screen.getByText("No confirmed events fall in this Monday through Sunday window.")).toBeInTheDocument()
  expect(
    screen.getByText("Select at least one course to export a filtered calendar."),
  ).toBeInTheDocument()

  const exportButton = screen.getByRole("button", { name: "Export" })
  expect(exportButton).toBeDisabled()
  expect(exportButton).toHaveAccessibleDescription("Select at least one course to export a filtered calendar.")
  await user.click(exportButton)

  await waitFor(() => expect(getCalendarMock).not.toHaveBeenCalled())
  expect(screen.getByRole("checkbox", { name: /CS 101/i })).not.toBeChecked()
  expect(screen.getByRole("checkbox", { name: /MATH 201/i })).not.toBeChecked()
})

test("replaces an invalid view query with the responsive default view", async () => {
  renderCalendarPage("/calendar?view=bogus")

  expect(await screen.findByRole("button", { name: "Timeline" })).toHaveAttribute("aria-pressed", "true")
  expect(screen.getByLabelText("Current route")).toHaveTextContent("/calendar?view=timeline")
  expect(screen.getByRole("region", { name: "Semester timeline" })).toBeInTheDocument()
})

test("shows the shared empty state in timeline, month, and list when no courses are selected", async () => {
  const user = userEvent.setup()
  renderCalendarPage()

  await screen.findByRole("checkbox", { name: /CS 101/i })
  await user.click(screen.getByRole("checkbox", { name: /CS 101/i }))
  await user.click(screen.getByRole("checkbox", { name: /MATH 201/i }))

  expect(screen.getByTestId("calendar-empty-state")).toHaveTextContent(
    "Select at least one course to see calendar events.",
  )

  await user.click(screen.getByRole("button", { name: "Month" }))
  expect(screen.getByTestId("calendar-empty-state")).toHaveTextContent(
    "Select at least one course to see calendar events.",
  )

  await user.click(screen.getByRole("button", { name: "List" }))
  expect(screen.getByTestId("calendar-empty-state")).toHaveTextContent(
    "Select at least one course to see calendar events.",
  )
})

test("scrolls the This week summary into view from list and month instead of no-op", async () => {
  const user = userEvent.setup()
  renderCalendarPage()

  await screen.findByRole("button", { name: "Timeline" })

  await user.click(screen.getByRole("button", { name: "List" }))
  await user.click(screen.getByRole("button", { name: "This week" }))
  expect(scrollIntoViewMock).toHaveBeenCalled()

  scrollIntoViewMock.mockClear()
  await user.click(screen.getByRole("button", { name: "Month" }))
  await user.click(screen.getByRole("button", { name: "This week" }))
  expect(scrollIntoViewMock).toHaveBeenCalled()
})

test("uses the natural Monday through Sunday window for This week", async () => {
  const monday = getWeekStart()
  const sunday = new Date(monday)
  sunday.setDate(sunday.getDate() + 6)
  const nextMonday = new Date(monday)
  nextMonday.setDate(nextMonday.getDate() + 7)

  listEventsMock.mockImplementationOnce(async (): Promise<ExtractedEvent[]> => [
    {
      id: "event-monday",
      semester_id: "semester-1",
      course_id: "course-1",
      document_id: "document-1",
      title: "Monday recap",
      event_type: "meeting",
      event_date: formatDate(monday),
      start_time: "09:00:00",
      end_time: null,
      timezone: "America/New_York",
      is_all_day: false,
      source_quote: "Monday recap in the current week",
      source_page: 1,
      confidence: "high",
      warning_codes: [],
      warning_reason: null,
      review_status: "confirmed" as const,
    },
    {
      id: "event-sunday",
      semester_id: "semester-1",
      course_id: "course-1",
      document_id: "document-1",
      title: "Sunday workshop",
      event_type: "meeting",
      event_date: formatDate(sunday),
      start_time: "11:00:00",
      end_time: null,
      timezone: "America/New_York",
      is_all_day: false,
      source_quote: "Sunday workshop in the current week",
      source_page: 2,
      confidence: "high",
      warning_codes: [],
      warning_reason: null,
      review_status: "confirmed" as const,
    },
    {
      id: "event-next-monday",
      semester_id: "semester-1",
      course_id: "course-1",
      document_id: "document-1",
      title: "Next Monday kickoff",
      event_type: "meeting",
      event_date: formatDate(nextMonday),
      start_time: "10:00:00",
      end_time: null,
      timezone: "America/New_York",
      is_all_day: false,
      source_quote: "Next Monday kickoff in the following week",
      source_page: 3,
      confidence: "high",
      warning_codes: [],
      warning_reason: null,
      review_status: "confirmed" as const,
    },
  ])

  renderCalendarPage()

  await screen.findByRole("heading", { name: "This week" })
  const thisWeekSection = getThisWeekSection()
  expect(within(thisWeekSection as HTMLElement).getByText(formatWeekRangeFromDates(monday, sunday))).toBeInTheDocument()
  expect(within(thisWeekSection as HTMLElement).getByText("Monday recap")).toBeInTheDocument()
  expect(within(thisWeekSection as HTMLElement).getByText("Sunday workshop")).toBeInTheDocument()
  expect(within(thisWeekSection as HTMLElement).queryByText("Next Monday kickoff")).not.toBeInTheDocument()
})

test("shows deadline-only events at end_time in this week and list while keeping explicit all-day events marked", async () => {
  const user = userEvent.setup()
  const thisWeekWednesday = getDateInCurrentWeek(2)
  listEventsMock.mockImplementationOnce(async (): Promise<ExtractedEvent[]> => [
    {
      id: "deadline-only",
      semester_id: "semester-1",
      course_id: "course-1",
      document_id: "document-1",
      title: "Deadline only event",
      event_type: "deadline",
      event_date: formatDate(thisWeekWednesday),
      start_time: null,
      end_time: "23:59:00-05:00",
      timezone: "America/New_York",
      is_all_day: false,
      source_quote: "Deadline only event for end time test",
      source_page: 9,
      confidence: "medium" as const,
      warning_codes: [],
      warning_reason: null,
      review_status: "confirmed" as const,
    },
    {
      id: "all-day-event",
      semester_id: "semester-1",
      course_id: "course-1",
      document_id: "document-1",
      title: "Explicit all-day event",
      event_type: "assignment",
      event_date: formatDate(getDateInCurrentWeek(1)),
      start_time: null,
      end_time: "21:00:00",
      timezone: "America/New_York",
      is_all_day: true,
      source_quote: "All-day event with time noise",
      source_page: 8,
      confidence: "medium" as const,
      warning_codes: [],
      warning_reason: null,
      review_status: "confirmed" as const,
    },
  ])

  renderCalendarPage()

  const thisWeekSection = await screen.findByRole("heading", { name: "This week" }).then((heading) => {
    const section = heading.parentElement?.parentElement
    expect(section).not.toBeNull()
    return section as HTMLElement
  })
  const timelineRegion = screen.getByRole("region", { name: "Semester timeline" })
  expect(within(timelineRegion).getByRole("link", { name: /Deadline only event/i })).toHaveTextContent(/23:59/)
  const deadlineCard = within(thisWeekSection).getByRole("link", { name: /Deadline only event/i })
  expect(within(deadlineCard).getByText(/\b23:59\b/)).toBeInTheDocument()
  const allDayCard = within(thisWeekSection).getByRole("link", { name: /Explicit all-day event/i })
  expect(within(allDayCard).queryByText(/23:59/)).not.toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "List" }))
  const listDeadlineCard = await waitFor(() =>
    screen.getByTestId("calendar-course-rail-list-deadline-only").closest("a"),
  )
  expect(listDeadlineCard).not.toBeNull()
  expect(within(listDeadlineCard as HTMLElement).getByText(/\b23:59\b/)).toBeInTheDocument()
  expect(within(listDeadlineCard as HTMLElement).queryByText("All day")).not.toBeInTheDocument()
  const allDayListCard = screen.getByTestId("calendar-course-rail-list-all-day-event").closest("a")
  expect(allDayListCard).not.toBeNull()
  expect(within(allDayListCard as HTMLElement).getByText("All day")).toBeInTheDocument()
  expect(within(allDayListCard as HTMLElement).queryByText(/\b21:00\b/)).not.toBeInTheDocument()
})

test("computes the current natural week in the semester timezone instead of browser local time", () => {
  const range = getCurrentWeekRangeForTimezone(
    "America/New_York",
    new Date("2026-08-17T02:30:00.000Z"),
  )

  expect(range.startKey).toBe("2026-08-10")
  expect(range.endKey).toBe("2026-08-16")
})

test("separates review queue and awaiting dates while exposing course rules from course details", async () => {
  const user = userEvent.setup()
  const longRuleQuote =
    "Weekly reading reflection due every Friday after lecture with a short response that cites one question from the assigned chapter and one idea you want to revisit during section."
  reviewData.events = [
    createReviewEvent({
      id: "rule-1",
      title: "Weekly reading cadence",
      source_quote: longRuleQuote,
      source_page: 4,
      warning_codes: ["AMBIGUOUS_RECURRENCE"],
      review_status: "needs_review",
    }),
    createReviewEvent({
      id: "rule-2",
      title: "Lab attendance policy",
      source_quote: "Lab attendance required every Tuesday",
      source_page: 5,
      warning_codes: ["AMBIGUOUS_RECURRENCE"],
      review_status: "pending",
    }),
    createReviewEvent({
      id: "awaiting-1",
      title: "Final exam date mismatch",
      source_quote: "Final exam on December 10",
      source_page: 8,
      warning_codes: ["DATE_MISSING"],
      review_status: "pending",
    }),
    createReviewEvent({
      id: "queue-1",
      title: "Project demo date mismatch",
      event_date: "2026-10-20",
      source_quote: "Project demo on October 20",
      source_page: 11,
      warning_codes: ["DATE_CONFLICT"],
      review_status: "needs_review",
    }),
    createReviewEvent({
      id: "recurring-pending-1",
      title: "Recurring pending member",
      recurring_series_id: "series-1",
      review_status: "pending",
    }),
    createReviewEvent({
      id: "recurring-review-1",
      title: "Recurring review member",
      event_date: "2026-10-22",
      recurring_series_id: "series-1",
      warning_codes: ["DATE_CONFLICT"],
      review_status: "needs_review",
    }),
    createReviewEvent({
      id: "rule-confirmed",
      title: "Confirmed office hour pattern",
      source_quote: "Office hours rotate every Thursday afternoon",
      source_page: 9,
      warning_codes: ["AMBIGUOUS_RECURRENCE"],
      review_status: "confirmed",
    }),
    createReviewEvent({
      id: "rule-ignored",
      title: "Ignored attendance pattern",
      source_quote: "Attendance discussion repeats each Friday",
      source_page: 10,
      warning_codes: ["AMBIGUOUS_RECURRENCE"],
      review_status: "ignored",
    }),
  ]

  renderCalendarPage()

  expect(screen.queryByRole("heading", { name: "Course rules" })).not.toBeInTheDocument()
  const courseDetailsButton = await screen.findByRole("button", { name: "CS 101" })
  expect(courseDetailsButton).toHaveAttribute("aria-controls", "course-details-panel-course-1")
  expect(courseDetailsButton).toHaveAttribute("aria-expanded", "false")
  const calendarContentGrid = screen.getByRole("region", { name: "Course filters" })
    .closest("aside")?.parentElement
  expect(calendarContentGrid).toHaveClass("xl:grid-cols-[20rem_minmax(0,1fr)]")

  await user.click(courseDetailsButton)

  expect(courseDetailsButton).toHaveAttribute("aria-expanded", "true")
  const detailsPanel = document.getElementById("course-details-panel-course-1")
  expect(detailsPanel).not.toBeNull()
  const statsList = within(detailsPanel as HTMLElement).getByTestId("course-details-stats")
  const rulesHeader = within(detailsPanel as HTMLElement).getByTestId("course-rules-header")
  expect(within(detailsPanel as HTMLElement).getByText("Intro to CS")).toBeInTheDocument()
  expect(within(detailsPanel as HTMLElement).getByText("Dr. Rivera")).toBeInTheDocument()
  expect(statsList).toHaveClass("space-y-2")
  expect(statsList).not.toHaveClass("sm:grid-cols-3")
  expect(within(detailsPanel as HTMLElement).getByText("Confirmed events").parentElement).toHaveTextContent("2")
  expect(within(detailsPanel as HTMLElement).getByText("Awaiting dates").parentElement).toHaveTextContent("1")
  expect(within(detailsPanel as HTMLElement).getByText("Saved rules").parentElement).toHaveTextContent("1")
  expect(rulesHeader).toHaveClass("flex-col", "items-start")
  expect(
    within(detailsPanel as HTMLElement).getByRole("link", { name: /Weekly reading cadence/i }),
  ).toHaveAttribute("href", "/review?eventId=rule-1")
  expect(within(detailsPanel as HTMLElement).getByText("Needs review")).toBeInTheDocument()
  const savedRuleStatus = within(detailsPanel as HTMLElement).getByText("Saved")
  expect(savedRuleStatus).toBeInTheDocument()
  expect(savedRuleStatus.parentElement).toHaveClass("flex-col")
  expect(savedRuleStatus.parentElement).not.toHaveClass("sm:flex-row")
  const longQuote = within(detailsPanel as HTMLElement).getByText(longRuleQuote)
  expect(longQuote).toBeInTheDocument()
  expect(longQuote).toHaveAttribute("title", longRuleQuote)
  expect(within(detailsPanel as HTMLElement).getByText("Page 4")).toBeInTheDocument()
  expect(within(detailsPanel as HTMLElement).getByText("Lab attendance required every Tuesday")).toBeInTheDocument()
  expect(within(detailsPanel as HTMLElement).queryByText("Confirmed office hour pattern")).not.toBeInTheDocument()
  expect(within(detailsPanel as HTMLElement).queryByText("Ignored attendance pattern")).not.toBeInTheDocument()
  expect(within(getThisWeekSection()).getByText("Office hours kickoff")).toBeInTheDocument()

  const reviewQueueHeading = screen.getByRole("heading", { name: "Review queue" })
  const reviewQueueCard = reviewQueueHeading.closest("section")
  expect(reviewQueueCard).not.toBeNull()
  expect(within(reviewQueueCard as HTMLElement).getByText("Project demo date mismatch")).toBeInTheDocument()
  const recurringReviewButton = within(reviewQueueCard as HTMLElement).getByRole("button", {
    name: /Recurring review member/i,
  })
  expect(recurringReviewButton).toBeInTheDocument()
  expect(within(reviewQueueCard as HTMLElement).queryByText("Final exam date mismatch")).not.toBeInTheDocument()
  expect(within(reviewQueueCard as HTMLElement).queryByText("Weekly reading cadence")).not.toBeInTheDocument()
  expect(within(reviewQueueCard as HTMLElement).queryByText("Lab attendance policy")).not.toBeInTheDocument()
  expect(within(reviewQueueCard as HTMLElement).queryByText("Confirmed office hour pattern")).not.toBeInTheDocument()
  expect(within(reviewQueueCard as HTMLElement).queryByText("Ignored attendance pattern")).not.toBeInTheDocument()

  const awaitingHeading = screen.getByRole("heading", { name: "Awaiting dates" })
  const awaitingCard = awaitingHeading.closest("section")
  expect(awaitingCard).not.toBeNull()
  expect(within(awaitingCard as HTMLElement).getByText("Final exam date mismatch")).toBeInTheDocument()
  expect(within(awaitingCard as HTMLElement).getByText("Awaiting date")).toBeInTheDocument()
  expect(within(awaitingCard as HTMLElement).queryByText("Weekly reading cadence")).not.toBeInTheDocument()
  expect(within(awaitingCard as HTMLElement).queryByText("Lab attendance policy")).not.toBeInTheDocument()
  expect(within(awaitingCard as HTMLElement).queryByText("Recurring pending member")).not.toBeInTheDocument()

  const weeklyReadingLink = screen.getByRole("link", { name: /Weekly reading cadence/i })
  expect(weeklyReadingLink).toHaveAttribute("href", "/review?eventId=rule-1")

  await user.click(recurringReviewButton)
  expect(screen.getByLabelText("Current route")).toHaveTextContent("/review?eventId=recurring-review-1")
})

test("course detail disclosure is independent from color and checkbox controls", async () => {
  const user = userEvent.setup()
  renderCalendarPage()

  const row = await screen.findByTestId("course-filter-row-course-1")
  const courseDetailsButton = await screen.findByRole("button", { name: "CS 101" })
  const colorButton = screen.getByRole("button", { name: "Change color for CS 101" })
  const checkbox = screen.getByRole("checkbox", { name: "CS 101" })
  const checkboxHitArea = within(row).getByTestId("course-filter-checkbox-hit-area-course-1")

  expect(within(row).getByRole("checkbox", { name: "CS 101" })).toBe(checkbox)
  expect(within(row).getByRole("button", { name: "Change color for CS 101" })).toBe(colorButton)
  expect(within(row).getByRole("button", { name: "CS 101" })).toBe(courseDetailsButton)
  expect(checkboxHitArea).toHaveClass("min-h-11", "min-w-11", "cursor-pointer", "focus-within:ring-2")
  expect(courseDetailsButton).toHaveAttribute("aria-controls", "course-details-panel-course-1")
  expect(courseDetailsButton).toHaveAttribute("aria-expanded", "false")
  expect(checkbox).toBeChecked()

  await user.click(colorButton)

  expect(screen.getByRole("group", { name: "Choose a color for CS 101" })).toBeInTheDocument()
  expect(courseDetailsButton).toHaveAttribute("aria-expanded", "false")
  expect(checkbox).toBeChecked()

  await user.click(checkbox)

  expect(checkbox).not.toBeChecked()
  expect(courseDetailsButton).toHaveAttribute("aria-expanded", "false")

  await user.click(courseDetailsButton)

  expect(courseDetailsButton).toHaveAttribute("aria-expanded", "true")
  const detailsPanel = document.getElementById("course-details-panel-course-1")
  expect(detailsPanel).not.toBeNull()
  expect(within(detailsPanel as HTMLElement).getByText("Intro to CS")).toBeInTheDocument()
})

test("course details empty state uses the updated rule copy", async () => {
  const user = userEvent.setup()
  reviewData.events = [
    createReviewEvent({
      id: "event-1",
      title: "Office hours kickoff",
      event_date: formatDateOffset(2),
      warning_codes: [],
      review_status: "confirmed",
    }),
  ]

  renderCalendarPage()

  await user.click(await screen.findByRole("button", { name: "CS 101" }))
  const detailsPanel = document.getElementById("course-details-panel-course-1")
  expect(detailsPanel).not.toBeNull()
  expect(within(detailsPanel as HTMLElement).getByText("No course rules on file yet.")).toBeInTheDocument()
  expect(within(detailsPanel as HTMLElement).queryByText("No saved or pending course rules yet.")).not.toBeInTheDocument()
})

test("only one course details panel stays open at a time", async () => {
  const user = userEvent.setup()
  reviewData.events = [
    createReviewEvent({
      id: "rule-1",
      course_id: "course-1",
      title: "Weekly reading cadence",
      source_quote: "Weekly reading reflection due every Friday",
      source_page: 4,
      warning_codes: ["AMBIGUOUS_RECURRENCE"],
      review_status: "pending",
    }),
    createReviewEvent({
      id: "rule-2",
      course_id: "course-2",
      document_id: "document-2",
      title: "Discussion post rhythm",
      source_quote: "Discussion post due every Wednesday night",
      source_page: 6,
      warning_codes: ["AMBIGUOUS_RECURRENCE"],
      review_status: "needs_review",
    }),
  ]

  renderCalendarPage()

  const csCourseButton = await screen.findByRole("button", { name: "CS 101" })
  const mathCourseButton = screen.getByRole("button", { name: "MATH 201" })

  await user.click(csCourseButton)
  expect(csCourseButton).toHaveAttribute("aria-expanded", "true")
  expect(mathCourseButton).toHaveAttribute("aria-expanded", "false")
  expect(screen.getByText("Weekly reading cadence")).toBeInTheDocument()

  await user.click(mathCourseButton)

  expect(csCourseButton).toHaveAttribute("aria-expanded", "false")
  expect(mathCourseButton).toHaveAttribute("aria-expanded", "true")
  expect(screen.queryByText("Weekly reading cadence")).not.toBeInTheDocument()
  expect(screen.getByText("Discussion post rhythm")).toBeInTheDocument()
})
