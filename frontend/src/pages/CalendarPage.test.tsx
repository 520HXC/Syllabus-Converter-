import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom"

import type { ExtractedEvent } from "../lib/types"
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

const getCalendarMock = vi.hoisted(() => vi.fn(async () => new Blob(["BEGIN:VCALENDAR"])))
const scrollIntoViewMock = vi.hoisted(() => vi.fn())
const listEventsMock = vi.hoisted(() => vi.fn())
const reviewData = vi.hoisted(() => ({
  semester: {
    id: "semester-1",
    name: "Fall 2026",
    start_date: "2026-08-24",
    end_date: "2026-12-18",
    timezone: "America/New_York",
    review_completed_at: "2026-09-01T12:00:00Z",
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

beforeEach(() => {
  const currentWeekWednesday = getDateInCurrentWeek(2)
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
  expect(screen.getByRole("button", { name: /Final exam/i })).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "This week" })).toBeInTheDocument()
  expect(screen.getByRole("link", { name: /Office hours kickoff/i })).toHaveAttribute("href", "/review?eventId=event-4")
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

  const thisWeekHeading = await screen.findByRole("heading", { name: "This week" })
  const thisWeekSection = thisWeekHeading.parentElement?.parentElement
  expect(thisWeekSection).not.toBeNull()
  expect(within(thisWeekSection as HTMLElement).getByText(formatWeekRangeFromDates(monday, sunday))).toBeInTheDocument()
  expect(within(thisWeekSection as HTMLElement).getByText("Monday recap")).toBeInTheDocument()
  expect(within(thisWeekSection as HTMLElement).getByText("Sunday workshop")).toBeInTheDocument()
  expect(within(thisWeekSection as HTMLElement).queryByText("Next Monday kickoff")).not.toBeInTheDocument()
})

test("computes the current natural week in the semester timezone instead of browser local time", () => {
  const range = getCurrentWeekRangeForTimezone(
    "America/New_York",
    new Date("2026-08-17T02:30:00.000Z"),
  )

  expect(range.startKey).toBe("2026-08-10")
  expect(range.endKey).toBe("2026-08-16")
})
