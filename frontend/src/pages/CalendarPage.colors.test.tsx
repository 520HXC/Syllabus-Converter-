import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"

import type { ExtractedEvent } from "../lib/types"
import { CalendarPage } from "./CalendarPage"

const fullCalendarPropsSpy = vi.hoisted(() => vi.fn())
function getCurrentWeekDate() {
  const today = new Date()
  today.setHours(12, 0, 0, 0)
  const monday = new Date(today)
  const day = monday.getDay()
  const offset = day === 0 ? -6 : 1 - day
  monday.setDate(monday.getDate() + offset + 2)
  const year = monday.getFullYear()
  const month = `${monday.getMonth() + 1}`.padStart(2, "0")
  const date = `${monday.getDate()}`.padStart(2, "0")
  return `${year}-${month}-${date}`
}

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
      id: "pending-event",
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
      source_quote: "Pending exam date",
      source_page: 1,
      confidence: "low" as const,
      warning_codes: ["DATE_MISSING"],
      warning_reason: "Missing date",
      review_status: "pending" as const,
    },
  ],
}))
const listEventsMock = vi.hoisted(() => vi.fn())

vi.mock("@fullcalendar/react", () => ({
  default: (props: unknown) => {
    fullCalendarPropsSpy(props)
    return <div data-testid="calendar" />
  },
}))
vi.mock("../theme/ThemeProvider", () => ({
  useTheme: () => ({
    theme: "dark",
    resolvedTheme: "dark",
    setTheme: vi.fn(),
  }),
}))
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
    getCalendar: vi.fn(async () => new Blob(["BEGIN:VCALENDAR"])),
  }),
}))

function renderCalendarPage(initialEntry = "/calendar") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <QueryClientProvider client={queryClient}>
        <Routes>
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/review" element={<div>Review page</div>} />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  listEventsMock.mockReset()
  fullCalendarPropsSpy.mockReset()
  const currentWeekDate = getCurrentWeekDate()
  listEventsMock.mockResolvedValue([
    {
      id: "event-1",
      semester_id: "semester-1",
      course_id: "course-1",
      document_id: "document-1",
      title: "Office hours kickoff",
      event_type: "meeting",
      event_date: currentWeekDate,
      start_time: "14:30:00",
      end_time: null,
      timezone: "America/New_York",
      is_all_day: false,
      source_quote: "Office hours kickoff on September 16",
      source_page: 6,
      confidence: "medium" as const,
      warning_codes: [],
      warning_reason: null,
      review_status: "confirmed" as const,
    },
    {
      id: "event-2",
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
  ] satisfies ExtractedEvent[])
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: 1280,
  })
})

test("maps calendar course visuals onto the dark display palette across filters, timeline, month, and list", async () => {
  const user = userEvent.setup()
  renderCalendarPage()

  expect(await screen.findByRole("heading", { name: "Fall 2026" })).toBeInTheDocument()

  const csFilter = screen.getByRole("checkbox", { name: /CS 101/i }).closest("label")
  const mathFilter = screen.getByRole("checkbox", { name: /MATH 201/i }).closest("label")
  expect(within(csFilter as HTMLElement).getByText("CS 101").previousElementSibling).toHaveStyle({
    backgroundColor: "#C084FC",
  })
  expect(within(mathFilter as HTMLElement).getByText("MATH 201").previousElementSibling).toHaveStyle({
    backgroundColor: "#22D3EE",
  })

  const thisWeekCard = await screen.findByRole("link", { name: /Office hours kickoff/i })
  expect(within(thisWeekCard).getByText("CS 101").parentElement?.previousElementSibling).toHaveStyle({
    backgroundColor: "#C084FC",
  })

  const timelineRegion = screen.getByRole("region", { name: "Semester timeline" })
  const timelineCourseLabel = within(timelineRegion).getByText("CS 101")
  expect(timelineCourseLabel.parentElement?.previousElementSibling).toHaveStyle({
    backgroundColor: "#C084FC",
  })

  await user.click(screen.getByRole("button", { name: "Month" }))
  await waitFor(() => expect(fullCalendarPropsSpy).toHaveBeenCalled())
  const monthProps = fullCalendarPropsSpy.mock.calls.at(-1)?.[0] as {
    events: Array<{ id: string; backgroundColor: string; borderColor: string }>
  }
  expect(monthProps.events).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ id: "event-1", backgroundColor: "#C084FC", borderColor: "#C084FC" }),
      expect.objectContaining({ id: "event-2", backgroundColor: "#22D3EE", borderColor: "#22D3EE" }),
    ]),
  )

  await user.click(screen.getByRole("button", { name: "List" }))
  const officeHoursListItem = screen.getAllByText("Office hours kickoff").at(-1)?.closest("a")
  const listCourseLabel = within(officeHoursListItem as HTMLElement).getByText("CS 101")
  expect(listCourseLabel.closest("div.min-w-0")?.previousElementSibling).toHaveStyle({ backgroundColor: "#C084FC" })
})
