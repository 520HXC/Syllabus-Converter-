import type { ReactNode } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom"

import type { Course, ExtractedEvent } from "../lib/types"
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

function createDeferredCourseUpdate() {
  let resolve!: (value: Course) => void
  let reject!: (error: Error) => void
  const promise = new Promise<Course>((nextResolve, nextReject) => {
    resolve = nextResolve
    reject = nextReject
  })
  return { promise, resolve, reject }
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
const updateCourseMock = vi.hoisted(() => vi.fn())

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
    getReview: vi.fn().mockImplementation(async () => structuredClone(reviewData)),
    listEvents: listEventsMock,
    updateCourse: updateCourseMock,
    getCalendar: vi.fn(async () => new Blob(["BEGIN:VCALENDAR"])),
  }),
}))

function renderCalendarPage(initialEntry = "/calendar") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
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

function LocationDisplay() {
  const location = useLocation()

  return <div aria-label="Current route">{`${location.pathname}${location.search}`}</div>
}

beforeEach(() => {
  reviewData.courses[0].color = "#0D9488"
  reviewData.courses[1].color = "#2563EB"
  listEventsMock.mockReset()
  updateCourseMock.mockReset()
  fullCalendarPropsSpy.mockReset()
  const currentWeekDate = getCurrentWeekDate()
  listEventsMock.mockResolvedValue([
    {
      id: "event-1",
      semester_id: "semester-1",
      course_id: "course-1",
      document_id: "document-1",
      title: "Assigned chapter",
      event_type: "reading",
      event_date: currentWeekDate,
      start_time: "14:30:00",
      end_time: null,
      timezone: "America/New_York",
      is_all_day: false,
      source_quote: "Assigned chapter due this week",
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
      title: "Portfolio checkpoint",
      event_type: "deadline",
      event_date: "2026-09-15",
      start_time: null,
      end_time: null,
      timezone: "America/New_York",
      is_all_day: true,
      source_quote: "Portfolio checkpoint due on September 15",
      source_page: 2,
      confidence: "high" as const,
      warning_codes: [],
      warning_reason: null,
      review_status: "confirmed" as const,
    },
  ] satisfies ExtractedEvent[])
  updateCourseMock.mockImplementation(async (courseId: string, values: Record<string, unknown>) => {
    const course = reviewData.courses.find((item) => item.id === courseId)
    if (!course) throw new Error("Missing course")
    Object.assign(course, values)
    return structuredClone(course)
  })
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: 1280,
  })
})

test("uses stored course colors in dark mode and shared type labels across filters, this week, timeline, month, and list", async () => {
  const user = userEvent.setup()
  renderCalendarPage()

  expect(await screen.findByRole("heading", { name: "Fall 2026" })).toBeInTheDocument()
  expect(screen.getByTestId("course-filter-swatch-course-1")).toHaveStyle({ backgroundColor: "#0D9488" })
  expect(screen.getByTestId("course-filter-swatch-course-2")).toHaveStyle({ backgroundColor: "#2563EB" })

  const thisWeekCard = await screen.findByRole("link", { name: /Assigned chapter/i })
  expect(within(thisWeekCard).getByText("reading")).toBeInTheDocument()
  expect(screen.getByTestId("calendar-course-rail-this-week-event-1")).toHaveStyle({
    backgroundColor: "#0D9488",
  })

  const timelineRegion = screen.getByRole("region", { name: "Semester timeline" })
  expect(within(timelineRegion).getByText("deadline")).toBeInTheDocument()
  expect(screen.getByTestId("calendar-course-dot-timeline-course-1")).toHaveStyle({
    backgroundColor: "#0D9488",
  })

  await user.click(screen.getByRole("button", { name: "Month" }))
  await waitFor(() => expect(fullCalendarPropsSpy).toHaveBeenCalled())
  const monthProps = fullCalendarPropsSpy.mock.calls.at(-1)?.[0] as {
    eventClick: (arg: {
      event: { id: string }
      jsEvent: { preventDefault: () => void }
    }) => void
    eventContent: (arg: { event: { title: string; extendedProps: Record<string, unknown> } }) => ReactNode
    events: Array<{ id: string; backgroundColor: string; borderColor: string; extendedProps: Record<string, unknown> }>
  }
  expect(monthProps.events).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ id: "event-1", backgroundColor: "#0D9488", borderColor: "#0D9488" }),
      expect.objectContaining({ id: "event-2", backgroundColor: "#2563EB", borderColor: "#2563EB" }),
    ]),
  )
  const monthEventContent = render(
    <>{monthProps.eventContent({
      event: {
        title: "Portfolio checkpoint",
        extendedProps: monthProps.events.find((event) => event.id === "event-2")?.extendedProps ?? {},
      },
    })}</>,
  )
  expect(monthEventContent.getByText("deadline")).toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "List" }))
  const listItem = screen.getAllByText("Assigned chapter").at(-1)?.closest("a")
  expect(listItem).not.toBeNull()
  expect(within(listItem as HTMLElement).getByText("reading")).toBeInTheDocument()
  expect(screen.getByTestId("calendar-course-rail-list-event-1")).toHaveStyle({
    backgroundColor: "#0D9488",
  })
})

test("routes month event clicks to the review deep link", async () => {
  const user = userEvent.setup()
  renderCalendarPage()

  expect(await screen.findByRole("heading", { name: "Fall 2026" })).toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "Month" }))
  await waitFor(() => expect(fullCalendarPropsSpy).toHaveBeenCalled())
  const monthProps = fullCalendarPropsSpy.mock.calls.at(-1)?.[0] as {
    eventClick: (arg: {
      event: { id: string }
      jsEvent: { preventDefault: () => void }
    }) => void
  }

  const preventDefault = vi.fn()
  await act(async () => {
    monthProps.eventClick({
      event: { id: "event-2" },
      jsEvent: { preventDefault },
    })
  })

  expect(preventDefault).toHaveBeenCalledTimes(1)
  expect(screen.getByLabelText("Current route")).toHaveTextContent("/review?eventId=event-2")
})

test("clicking the visible course color dot opens the palette without toggling the checkbox", async () => {
  const user = userEvent.setup()
  renderCalendarPage()

  const courseCheckbox = await screen.findByRole("checkbox", { name: /CS 101/i })
  expect(courseCheckbox).toBeChecked()

  await user.click(screen.getByTestId("course-color-button-course-1"))
  expect(courseCheckbox).toBeChecked()

  const colorPicker = screen.getByRole("group", { name: "Choose a color for CS 101" })
  expect(within(colorPicker).getAllByRole("button")).toHaveLength(8)
  expect(within(colorPicker).getByRole("button", { name: "Teal" })).toHaveClass("min-h-11")
  const redButton = within(colorPicker).getByRole("button", { name: "Red" })
  expect(redButton).toHaveClass("min-h-11")
  redButton.focus()
  expect(redButton).toHaveFocus()

  await user.keyboard("{Escape}")
  expect(screen.queryByRole("group", { name: "Choose a color for CS 101" })).not.toBeInTheDocument()

  await user.click(screen.getByTestId("course-color-button-course-1"))
  await user.click(screen.getByTestId("course-color-button-course-2"))
  expect(screen.queryByRole("group", { name: "Choose a color for CS 101" })).not.toBeInTheDocument()
  expect(screen.getByRole("group", { name: "Choose a color for MATH 201" })).toBeInTheDocument()

  await user.click(document.body)
  expect(screen.queryByRole("group", { name: "Choose a color for MATH 201" })).not.toBeInTheDocument()
})

test("optimistically updates the current course visuals and persists the saved color", async () => {
  const user = userEvent.setup()
  const deferred = createDeferredCourseUpdate()
  updateCourseMock.mockImplementationOnce(() => deferred.promise)
  renderCalendarPage()

  expect(await screen.findByRole("heading", { name: "Fall 2026" })).toBeInTheDocument()

  await user.click(screen.getByTestId("course-color-button-course-1"))
  await user.click(within(screen.getByRole("group", { name: "Choose a color for CS 101" })).getByRole("button", { name: "Red" }))

  expect(updateCourseMock).toHaveBeenCalledWith("course-1", { color: "#DC2626" })
  expect(screen.getByTestId("course-filter-swatch-course-1")).toHaveStyle({ backgroundColor: "#DC2626" })
  expect(screen.getByTestId("calendar-course-rail-this-week-event-1")).toHaveStyle({ backgroundColor: "#DC2626" })

  deferred.resolve({ ...reviewData.courses[0], color: "#DC2626" })

  await waitFor(() => expect(screen.queryByText("The course color could not be saved.")).not.toBeInTheDocument())
  expect(screen.getByTestId("course-filter-swatch-course-1")).toHaveStyle({ backgroundColor: "#DC2626" })
})

test("rolls back an optimistic color update and shows a course-level alert when the save fails", async () => {
  const user = userEvent.setup()
  const deferred = createDeferredCourseUpdate()
  updateCourseMock.mockImplementationOnce(() => deferred.promise)
  renderCalendarPage()

  expect(await screen.findByRole("heading", { name: "Fall 2026" })).toBeInTheDocument()

  await user.click(screen.getByTestId("course-color-button-course-1"))
  await user.click(within(screen.getByRole("group", { name: "Choose a color for CS 101" })).getByRole("button", { name: "Red" }))

  expect(updateCourseMock).toHaveBeenCalledWith("course-1", { color: "#DC2626" })
  expect(screen.getByTestId("course-filter-swatch-course-1")).toHaveStyle({ backgroundColor: "#DC2626" })

  deferred.reject(new Error("The course color could not be saved."))

  const courseRow = screen.getByTestId("course-filter-row-course-1")
  expect(await within(courseRow).findByRole("alert")).toHaveTextContent("The course color could not be saved.")
  expect(screen.getByTestId("course-filter-swatch-course-1")).toHaveStyle({ backgroundColor: "#0D9488" })
  expect(screen.getByTestId("calendar-course-rail-this-week-event-1")).toHaveStyle({ backgroundColor: "#0D9488" })
})
