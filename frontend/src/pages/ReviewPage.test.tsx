import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom"

import { semesterQueryKey } from "../lib/queryKeys"
import type { ReviewPayload } from "../lib/types"
import { ReviewPage } from "./ReviewPage"

const reviewState = vi.hoisted<ReviewPayload>(() => ({
  semester: {
    id: "semester-1",
    name: "Fall 2026",
    start_date: "2026-08-24",
    end_date: "2026-12-18",
    timezone: "America/New_York",
    review_completed_at: null,
    course_count: 3,
    document_count: 2,
    event_count: 3,
    needs_review_count: 2,
  },
  documents: [
    { id: "document-1", filename: "cs101.pdf", size_bytes: 100, used_ocr: false },
    { id: "document-2", filename: "math201.pdf", size_bytes: 100, used_ocr: false },
  ],
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
    {
      id: "course-3",
      document_id: "document-1",
      code: "ENG 220",
      name: "Writing Studio",
      instructor: "Prof. March",
      color: "#EA580C",
    },
  ],
  events: [
    {
      id: "event-1",
      semester_id: "semester-1",
      course_id: "course-1",
      document_id: "document-1",
      title: "Final project",
      event_type: "project",
      event_date: "2026-12-10",
      start_time: null,
      end_time: null,
      timezone: "America/New_York",
      is_all_day: true,
      source_quote: "Final project due around December 10",
      source_page: 5,
      confidence: "low" as const,
      warning_codes: ["AMBIGUOUS_DATE"],
      warning_reason: "The date wording is tentative.",
      review_status: "needs_review" as const,
    },
    {
      id: "event-3",
      semester_id: "semester-1",
      course_id: "course-3",
      document_id: "document-1",
      title: "Workshop reflection",
      event_type: "assignment",
      event_date: "2026-10-02",
      start_time: null,
      end_time: null,
      timezone: "America/New_York",
      is_all_day: true,
      source_quote: "Workshop reflection due October 2",
      source_page: 7,
      confidence: "medium" as const,
      warning_codes: ["AMBIGUOUS_DATE"],
      warning_reason: "The syllabus references an approximate workshop date.",
      review_status: "needs_review" as const,
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
  ],
}))

const completeReviewMock = vi.hoisted(() => vi.fn())
const getReviewMock = vi.hoisted(() => vi.fn(async () => structuredClone(reviewState)))
const updateEventMock = vi.hoisted(() =>
  vi.fn(async (eventId: string, payload: Record<string, unknown>): Promise<any> => {
    const event = reviewState.events.find((item) => item.id === eventId)
    if (!event) throw new Error("Missing event")
    Object.assign(event, payload)
    return structuredClone(event)
  }),
)
const updateCourseMock = vi.hoisted(() =>
  vi.fn(async (courseId: string, values: Record<string, unknown>) => {
    const course = reviewState.courses.find((item) => item.id === courseId)
    if (!course) throw new Error("Missing course")
    Object.assign(course, values)
    return structuredClone(course)
  }),
)
const updateRecurringSeriesMock = vi.hoisted(() =>
  vi.fn(async (seriesId: string, payload: Record<string, unknown>) => {
    const series = ((reviewState as any).recurring_series ?? []).find(
      (item: { id: string }) => item.id === seriesId,
    )
    if (!series) throw new Error("Missing series")
    const nextStatus = payload.review_status
    reviewState.events.forEach((event: any) => {
      if (event.recurring_series_id === seriesId && event.review_status !== "ignored") {
        event.review_status = nextStatus
      }
    })
    series.review_status = nextStatus
    return structuredClone(series)
  }),
)
const scrollIntoViewMock = vi.hoisted(() => vi.fn())

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location-probe">{`${location.pathname}${location.search}`}</div>
}

function ReviewRouteControls() {
  const navigate = useNavigate()
  return (
    <div>
      <button onClick={() => navigate("/review")} type="button">
        Open plain review
      </button>
      <button onClick={() => navigate("/review?eventId=event-2")} type="button">
        Open event 2
      </button>
    </div>
  )
}

function createDeferredPromise() {
  let resolve!: () => void
  const promise = new Promise<void>((nextResolve) => {
    resolve = nextResolve
  })
  return { promise, resolve }
}

vi.mock("../components/PdfViewer", () => ({
  PdfViewer: ({ filename }: { filename: string }) => <div>Previewing {filename}</div>,
}))

vi.mock("../lib/auth", () => ({
  useAuth: () => ({
    user: { id: "user-1", email: "student@example.com" },
    signOut: vi.fn(),
    getAccessToken: vi.fn(),
  }),
}))

vi.mock("../lib/semester", () => ({
  useSemester: () => ({ semesterId: "semester-1" }),
}))

vi.mock("../lib/api", () => ({
  useApi: () => ({
    getReview: getReviewMock,
    updateEvent: updateEventMock,
    updateCourse: updateCourseMock,
    updateRecurringSeries: updateRecurringSeriesMock,
    completeReview: completeReviewMock,
  }),
}))

function renderReviewPage(initialEntry = "/review") {
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
          <Route path="/review" element={<><LocationProbe /><ReviewPage /></>} />
          <Route path="/calendar" element={<><div>Calendar page</div><LocationProbe /></>} />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

function renderReviewPageWithClient(queryClient: QueryClient, initialEntry = "/review", includeControls = false) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <QueryClientProvider client={queryClient}>
        <Routes>
          <Route
            path="/review"
            element={
              <>
                <LocationProbe />
                {includeControls ? <ReviewRouteControls /> : null}
                <ReviewPage />
              </>
            }
          />
          <Route path="/calendar" element={<><div>Calendar page</div><LocationProbe /></>} />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  updateRecurringSeriesMock.mockClear()
  ;(reviewState as any).recurring_series = []
  reviewState.semester.review_completed_at = null
  reviewState.events = [
    {
      id: "event-1",
      semester_id: "semester-1",
      course_id: "course-1",
      document_id: "document-1",
      title: "Final project",
      event_type: "project",
      event_date: "2026-12-10",
      start_time: null,
      end_time: null,
      timezone: "America/New_York",
      is_all_day: true,
      source_quote: "Final project due around December 10",
      source_page: 5,
      confidence: "low",
      warning_codes: ["AMBIGUOUS_DATE"],
      warning_reason: "The date wording is tentative.",
      review_status: "needs_review",
    },
    {
      id: "event-3",
      semester_id: "semester-1",
      course_id: "course-3",
      document_id: "document-1",
      title: "Workshop reflection",
      event_type: "assignment",
      event_date: "2026-10-02",
      start_time: null,
      end_time: null,
      timezone: "America/New_York",
      is_all_day: true,
      source_quote: "Workshop reflection due October 2",
      source_page: 7,
      confidence: "medium",
      warning_codes: ["AMBIGUOUS_DATE"],
      warning_reason: "The syllabus references an approximate workshop date.",
      review_status: "needs_review",
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
      confidence: "high",
      warning_codes: [],
      warning_reason: null,
      review_status: "confirmed",
    },
  ]
  getReviewMock.mockReset()
  getReviewMock.mockImplementation(async () => structuredClone(reviewState))
  updateEventMock.mockClear()
  updateCourseMock.mockClear()
  completeReviewMock.mockReset()
  scrollIntoViewMock.mockReset()
  Object.defineProperty(window.HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: scrollIntoViewMock,
  })
})

test("reviews a recurring series once while keeping individual dates editable", async () => {
  const user = userEvent.setup()
  ;(reviewState as any).recurring_series = [
    {
      id: "series-1",
      semester_id: "semester-1",
      course_id: "course-1",
      document_id: "document-1",
      title: "Quick Checks",
      event_type: "quiz",
      rule_kind: "relative_to_anchor",
      rule_summary: "8:00 AM on each lecture date",
      source_quote: "Quick Checks - 8AM the morning of the lecture",
      source_page: 2,
      anchor_sources: [
        { event_date: "2026-09-08", source_page: 4, source_quote: "8-Sep Monday" },
        { event_date: "2026-09-10", source_page: 4, source_quote: "10-Sep Wednesday" },
      ],
      confidence: "medium",
      warning_codes: ["DERIVED_DATE"],
      warning_reason: "Dates were calculated from the lecture schedule.",
      extraction_model: "gpt-5.6-terra",
      fallback_reason_codes: ["LOW_CONFIDENCE"],
      occurrence_count: 2,
      review_status: "needs_review",
    },
  ]
  reviewState.events.push(
    {
      ...reviewState.events[0],
      id: "quick-check-1",
      title: "Quick Check",
      event_type: "quiz",
      event_date: "2026-09-08",
      source_quote: "Quick Checks - 8AM the morning of the lecture",
      source_page: 2,
      confidence: "medium",
      warning_codes: ["DERIVED_DATE"],
      warning_reason: "Calculated from the lecture schedule.",
      recurring_series_id: "series-1",
      extraction_model: "gpt-5.6-terra",
      derivation_summary: "Lecture on September 8, due the same day at 8:00 AM",
    } as any,
    {
      ...reviewState.events[0],
      id: "quick-check-2",
      title: "Quick Check",
      event_type: "quiz",
      event_date: "2026-09-10",
      source_quote: "Quick Checks - 8AM the morning of the lecture",
      source_page: 2,
      confidence: "medium",
      warning_codes: ["DERIVED_DATE"],
      warning_reason: "Calculated from the lecture schedule.",
      recurring_series_id: "series-1",
      extraction_model: "gpt-5.6-terra",
      derivation_summary: "Lecture on September 10, due the same day at 8:00 AM",
    } as any,
  )

  renderReviewPage()

  expect(await screen.findByRole("heading", { name: "Quick Checks" })).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "3 of 4 decisions left" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: /cs101\.pdf/i })).toHaveTextContent("3 unresolved")
  expect(screen.getByText("2 generated dates")).toBeInTheDocument()
  expect(screen.getByText("Terra fallback")).toBeInTheDocument()
  expect(screen.getByText("Terra repaired Low Confidence")).toBeInTheDocument()
  expect(screen.queryByText("Lecture on September 8, due the same day at 8:00 AM")).not.toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "Show 2 dates" }))
  expect(screen.getByText("Lecture on September 8, due the same day at 8:00 AM")).toBeInTheDocument()
  await user.click(screen.getAllByRole("button", { name: "Modify Quick Check" })[0])
  expect(screen.getByLabelText("Event date", { selector: "input[value='2026-09-08']" })).toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "Confirm series" }))
  await waitFor(() =>
    expect(updateRecurringSeriesMock).toHaveBeenCalledWith("series-1", {
      review_status: "confirmed",
    }),
  )
})

test("opens a recurring occurrence deep link inside its series", async () => {
  ;(reviewState as any).recurring_series = [
    {
      id: "series-1",
      semester_id: "semester-1",
      course_id: "course-1",
      document_id: "document-1",
      title: "Weekly homework",
      event_type: "assignment",
      rule_kind: "weekly_fixed",
      rule_summary: "Every Friday",
      source_quote: "Homework is due every Friday",
      source_page: 2,
      anchor_sources: [],
      confidence: "high",
      warning_codes: [],
      warning_reason: null,
      extraction_model: "gpt-5.6-luna",
      fallback_reason_codes: [],
      occurrence_count: 1,
      review_status: "confirmed",
    },
  ]
  reviewState.events.push({
    ...reviewState.events[0],
    id: "weekly-homework-1",
    title: "Weekly homework",
    event_date: "2026-09-11",
    review_status: "confirmed",
    warning_codes: [],
    warning_reason: null,
    recurring_series_id: "series-1",
    extraction_model: "gpt-5.6-luna",
    derivation_summary: "Generated from the Friday homework rule",
  } as any)

  renderReviewPage("/review?eventId=weekly-homework-1")

  expect(await screen.findByText("Generated from the Friday homework rule")).toBeInTheDocument()
  await waitFor(() =>
    expect(
      screen.getByLabelText("Event name", { selector: "input[value='Weekly homework']" }),
    ).toHaveFocus(),
  )
})

test("keeps manual reprocessing reachable from the review workspace", async () => {
  renderReviewPage()

  const manageFilesLink = await screen.findByRole("link", { name: "Manage syllabus files" })
  expect(manageFilesLink).toHaveAttribute("href", "/processing")
})

test("opens the first document with unresolved items and shows unresolved tab counts", async () => {
  renderReviewPage()

  expect(await screen.findByText("Previewing cs101.pdf")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: /cs101\.pdf/i })).toHaveTextContent("2 unresolved")
  expect(screen.getByRole("button", { name: /math201\.pdf/i })).toHaveTextContent("0 unresolved")
  expect(screen.getByRole("button", { name: /cs101\.pdf/i })).toHaveAttribute("data-has-unresolved", "true")
  expect(screen.getByRole("button", { name: /cs101\.pdf/i })).toHaveAttribute("data-selected", "true")
})

test("uses accessible mobile tabs and compact review summary structure", async () => {
  renderReviewPage()

  expect(await screen.findByRole("tablist", { name: "Review workspace" })).toBeInTheDocument()
  const resultsTab = screen.getByRole("tab", { name: "Extracted details" })
  const documentTab = screen.getByRole("tab", { name: "PDF" })
  expect(resultsTab).toHaveAttribute("aria-selected", "true")
  expect(documentTab).toHaveAttribute("aria-selected", "false")
  expect(resultsTab).toHaveAttribute("aria-controls", "review-results-panel")
  const resultsPanel = document.getElementById("review-results-panel")
  expect(resultsPanel).not.toBeNull()
  expect(resultsPanel).toHaveAttribute("role", "tabpanel")
  expect(resultsPanel).toHaveAttribute("aria-labelledby", "review-results-tab")
  expect(screen.getByRole("heading", { name: "2 of 3 decisions left" })).toBeInTheDocument()
  expect(screen.getByTestId("review-progress-summary")).toHaveTextContent("Review progress")
  expect(screen.getByTestId("review-progress-summary")).toHaveTextContent("2 unresolved")
  expect(screen.getByTestId("review-progress-summary")).toHaveTextContent("33%")
  expect(within(screen.getByTestId("review-results-panel")).queryByTestId("review-progress-summary")).not.toBeInTheDocument()
  expect(screen.getByTestId("review-progress-summary")).not.toHaveTextContent("Needs review")
  expect(screen.getByTestId("review-progress-summary")).not.toHaveTextContent("Ready")
  expect(screen.getByTestId("review-progress-summary")).not.toHaveTextContent("Total")
})

test("shows review progress, blocker summary, course groups, and redesigned evidence details", async () => {
  renderReviewPage()

  expect(await screen.findByRole("heading", { name: "2 of 3 decisions left" })).toBeInTheDocument()
  expect(screen.getByText("1 resolved")).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "CS 101" })).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "ENG 220" })).toBeInTheDocument()
  expect(screen.getByText("Medium confidence")).toBeInTheDocument()
  expect(screen.getAllByText("AI date")).not.toHaveLength(0)
  expect(screen.getByText("Page 5")).toBeInTheDocument()
  expect(screen.getByText(/Final project due around December 10/i)).toBeInTheDocument()
  expect(screen.getByTestId("course-rail-event-1")).toHaveStyle({ backgroundColor: "#0D9488" })
})

test("shows an unresolved event when its recurring series no longer exists", async () => {
  reviewState.events[0].recurring_series_id = "missing-series"
  reviewState.events[1].review_status = "confirmed"

  renderReviewPage()

  expect(await screen.findByRole("heading", { name: "1 of 3 decisions left" })).toBeInTheDocument()
  expect(screen.getByText("Final project")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Review next" })).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Finish and open Calendar" })).not.toBeInTheDocument()
})

test("review next returns to the hidden blocking document and focuses the first unresolved field", async () => {
  const user = userEvent.setup()
  renderReviewPage()

  await user.click(await screen.findByRole("button", { name: /math201\.pdf/i }))
  expect(screen.getByText("Previewing math201.pdf")).toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "Review next" }))

  await waitFor(() => expect(screen.getByText("Previewing cs101.pdf")).toBeInTheDocument())
  await waitFor(() => expect(scrollIntoViewMock).toHaveBeenCalled())
  const workshopCard = screen.getByText("Workshop reflection").closest("[data-review-event-id]")
  expect(workshopCard).not.toBeNull()
  await waitFor(() => {
    expect(within(workshopCard as HTMLElement).getByLabelText("Event date")).toHaveFocus()
  })
})

test("removes an event from the active list, announces undo, and restores it", async () => {
  const user = userEvent.setup()
  renderReviewPage()

  const finalProjectCard = (await screen.findByText("Final project")).closest("[data-review-event-id]")
  expect(finalProjectCard).not.toBeNull()
  await user.click(within(finalProjectCard as HTMLElement).getByRole("button", { name: "Remove" }))

  await waitFor(() =>
    expect(within(finalProjectCard as HTMLElement).queryByRole("button", { name: "Remove" })).not.toBeInTheDocument(),
  )
  expect(screen.getByText("Event removed.")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument()
  expect(await screen.findByRole("button", { name: /Removed events/i })).toHaveTextContent("1")
  expect(screen.queryByText("Removed from the active review list")).not.toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: /Removed events/i }))
  expect(screen.getByText("Removed from the active review list")).toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "Undo" }))

  await screen.findByText("Final project")
  expect(updateEventMock).toHaveBeenLastCalledWith("event-1", expect.objectContaining({ review_status: "needs_review" }))
})

test("hides a removed event optimistically before the save resolves", async () => {
  const user = userEvent.setup()
  let resolveSave: ((value: Record<string, unknown>) => void) | null = null
  updateEventMock.mockImplementationOnce(
    () =>
      new Promise<Record<string, unknown>>((resolve) => {
        resolveSave = resolve
      }),
  )
  renderReviewPage()

  const finalProjectCard = (await screen.findByText("Final project")).closest("[data-review-event-id]")
  expect(finalProjectCard).not.toBeNull()
  await user.click(within(finalProjectCard as HTMLElement).getByRole("button", { name: "Remove" }))

  expect(within(finalProjectCard as HTMLElement).queryByRole("button", { name: "Remove" })).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: /cs101\.pdf/i })).toHaveTextContent("1 unresolved")
  expect(screen.getByRole("button", { name: "Review next" })).toBeEnabled()
  expect(updateEventMock).toHaveBeenCalledTimes(1)

  expect(resolveSave).not.toBeNull()
  resolveSave!({
    ...reviewState.events[0],
    review_status: "ignored",
  })

  await screen.findByText("Event removed.")
})

test("rolls back an optimistic remove when the save fails", async () => {
  const user = userEvent.setup()
  let rejectSave: ((error: Error) => void) | null = null
  updateEventMock.mockImplementationOnce(
    () =>
      new Promise((_, reject) => {
        rejectSave = reject
      }),
  )
  renderReviewPage()

  const finalProjectCard = (await screen.findByText("Final project")).closest("[data-review-event-id]")
  expect(finalProjectCard).not.toBeNull()
  await user.click(within(finalProjectCard as HTMLElement).getByRole("button", { name: "Remove" }))

  expect(within(finalProjectCard as HTMLElement).queryByRole("button", { name: "Remove" })).not.toBeInTheDocument()
  expect(rejectSave).not.toBeNull()
  rejectSave!(new Error("The event could not be saved."))
  expect(await screen.findByText("The event could not be saved.")).toBeInTheDocument()
  expect(screen.getAllByText("The event could not be saved.")).toHaveLength(1)
  const restoredCard = screen.getByText("Final project").closest("[data-review-event-id]")
  expect(restoredCard).not.toBeNull()
  expect(within(restoredCard as HTMLElement).getByRole("button", { name: "Remove" })).toBeInTheDocument()
})

test("keeps a successful remove in local state when the review refresh fails", async () => {
  const user = userEvent.setup()
  renderReviewPage()

  const finalProjectCard = (await screen.findByText("Final project")).closest("[data-review-event-id]")
  expect(finalProjectCard).not.toBeNull()
  getReviewMock.mockRejectedValueOnce(new Error("Refresh failed"))
  await user.click(within(finalProjectCard as HTMLElement).getByRole("button", { name: "Remove" }))

  expect(await screen.findByText("Event removed.")).toBeInTheDocument()
  expect(within(finalProjectCard as HTMLElement).queryByRole("button", { name: "Remove" })).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Review next" })).toBeEnabled()
  expect(screen.getByText("Event saved, but the review list could not be refreshed.")).toBeInTheDocument()
})

test("uses structured blocking ids from review completion failures to jump to the real blocker", async () => {
  const user = userEvent.setup()
  const readyToFinish = structuredClone(reviewState)
  readyToFinish.events[0].review_status = "confirmed"
  readyToFinish.events[1].review_status = "confirmed"
  getReviewMock.mockReset()
  getReviewMock
    .mockResolvedValueOnce(readyToFinish)
    .mockImplementation(async () => structuredClone(reviewState))
  completeReviewMock.mockRejectedValueOnce(
    Object.assign(new Error("Resolve every event before finishing review."), {
      blocking_event_ids: ["event-1"],
      blocking_document_ids: ["document-1"],
      blocking_count: 1,
    }),
  )
  renderReviewPage()

  await user.click(await screen.findByRole("button", { name: "Finish and open Calendar" }))

  const footer = screen.getByTestId("review-sticky-footer")
  expect(await within(footer).findByRole("alert")).toHaveTextContent(
    "Resolve every event before finishing review.",
  )
  await waitFor(() => expect(screen.getByText("Previewing cs101.pdf")).toBeInTheDocument())
  const finalProjectCard = screen.getByText("Final project").closest("[data-review-event-id]")
  expect(finalProjectCard).not.toBeNull()
  await waitFor(() =>
    expect(within(finalProjectCard as HTMLElement).getByLabelText("Event date")).toHaveFocus(),
  )
})

test("updates the course heading from the mutation response before refresh and shows a refresh warning on failure", async () => {
  const user = userEvent.setup()
  renderReviewPage()

  const csCourseSection = await screen.findByRole("heading", { name: "CS 101" }).then((heading) =>
    heading.closest("section"),
  )
  expect(csCourseSection).not.toBeNull()
  const courseCodeInput = within(csCourseSection as HTMLElement).getByLabelText("Course code")

  getReviewMock.mockRejectedValueOnce(new Error("Refresh failed"))
  await user.clear(courseCodeInput)
  await user.type(courseCodeInput, "CS 105")
  await user.click(within(csCourseSection as HTMLElement).getByRole("button", { name: "Save course" }))

  expect(await screen.findByRole("heading", { name: "CS 105" })).toBeInTheDocument()
  expect(screen.getByDisplayValue("CS 105")).toBeInTheDocument()
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Course saved, but the review list could not be refreshed.",
  )
  expect(screen.queryByText("Saved")).not.toBeInTheDocument()
})

test("disables finish review while the last optimistic remove is still saving", async () => {
  const user = userEvent.setup()
  let resolveSave: ((value: Record<string, unknown>) => void) | null = null
  reviewState.events[1].review_status = "confirmed"
  updateEventMock.mockImplementationOnce(
    () =>
      new Promise<Record<string, unknown>>((resolve) => {
        resolveSave = resolve
      }),
  )
  renderReviewPage()

  const finalProjectCard = (await screen.findByText("Final project")).closest("[data-review-event-id]")
  expect(finalProjectCard).not.toBeNull()
  await user.click(within(finalProjectCard as HTMLElement).getByRole("button", { name: "Remove" }))

  const footer = await screen.findByTestId("review-sticky-footer")
  await waitFor(() => expect(footer).toHaveTextContent("Everything has a decision"))
  const finishButton = within(footer).getByRole("button")
  expect(finishButton).toHaveAccessibleName("Finish and open Calendar")
  expect(finishButton).toBeDisabled()

  expect(resolveSave).not.toBeNull()
  const removedEvent = {
    ...reviewState.events[0],
    review_status: "ignored" as const,
  }
  ;(reviewState.events as Array<(typeof removedEvent) | (typeof reviewState.events)[number]>)[0] =
    removedEvent
  resolveSave!(removedEvent)

  await waitFor(() => expect(screen.getByRole("button", { name: "Finish and open Calendar" })).toBeEnabled())
})

test("eventId query selects the correct document, opens the reviewed group, and focuses the requested event", async () => {
  renderReviewPage("/review?eventId=event-2")

  expect(await screen.findByText("Previewing math201.pdf")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: /Reviewed events/i })).toHaveAttribute("aria-expanded", "true")
  const quizCard = screen.getByText("Quiz 1").closest("[data-review-event-id]")
  expect(quizCard).not.toBeNull()
  await waitFor(() => expect(within(quizCard as HTMLElement).getByDisplayValue("Quiz 1")).toHaveFocus())
})

test("pending undated standard events move into Saved for later and do not block finishing review", async () => {
  reviewState.events = [
    {
      ...reviewState.events[0],
      id: "event-awaiting-date",
      title: "Final project",
      event_date: null,
      warning_codes: ["DATE_MISSING"],
      warning_reason: "The event does not have a confirmed date.",
      review_status: "pending",
    },
    {
      ...reviewState.events[1],
      id: "event-confirmed-1",
      review_status: "confirmed",
    },
    {
      ...reviewState.events[2],
      id: "event-confirmed-2",
      review_status: "confirmed",
    },
  ]

  renderReviewPage()

  expect(await screen.findByRole("heading", { name: "0 of 3 decisions left" })).toBeInTheDocument()
  const savedForLaterButton = screen.getByRole("button", { name: /Saved for later/i })
  expect(savedForLaterButton).toHaveTextContent("1")
  expect(savedForLaterButton).toHaveAttribute("aria-controls", "saved-for-later-panel")
  expect(screen.getByRole("button", { name: /Reviewed events/i })).toHaveTextContent("1")
  expect(screen.getByRole("button", { name: "Finish and open Calendar" })).toBeInTheDocument()
  expect(
    screen.getByText("Saved for later items stay off the calendar until you confirm them."),
  ).toBeInTheDocument()

  await userEvent.setup().click(savedForLaterButton)
  const savedForLaterPanel = document.getElementById("saved-for-later-panel")
  expect(savedForLaterPanel).not.toBeNull()
  expect(savedForLaterButton).toHaveAttribute("aria-expanded", "true")
  expect(screen.getByText("Final project")).toBeInTheDocument()
})

test("eventId query focuses the date field for pending undated events without warning codes", async () => {
  reviewState.events = [
    {
      ...reviewState.events[0],
      id: "event-awaiting-date",
      course_id: "course-2",
      document_id: "document-2",
      title: "Quiz 1",
      event_date: null,
      warning_codes: [],
      warning_reason: null,
      review_status: "pending",
    },
    {
      ...reviewState.events[1],
      id: "event-confirmed-1",
      review_status: "confirmed",
    },
    {
      ...reviewState.events[2],
      id: "event-confirmed-2",
      review_status: "confirmed",
    },
  ]

  renderReviewPage("/review?eventId=event-awaiting-date")

  expect(await screen.findByText("Previewing math201.pdf")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: /Saved for later/i })).toHaveAttribute("aria-expanded", "true")
  const awaitingCard = screen.getByText("Quiz 1").closest("[data-review-event-id]")
  expect(awaitingCard).not.toBeNull()
  await waitFor(() => expect(within(awaitingCard as HTMLElement).getByLabelText("Event date")).toHaveFocus())
})

test("revisiting the same eventId after clearing the query focuses it again", async () => {
  const user = userEvent.setup()
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  renderReviewPageWithClient(queryClient, "/review?eventId=event-2", true)

  const quizCard = await screen.findByText("Quiz 1").then((element) => element.closest("[data-review-event-id]"))
  expect(quizCard).not.toBeNull()
  await waitFor(() => expect(within(quizCard as HTMLElement).getByDisplayValue("Quiz 1")).toHaveFocus())
  await waitFor(() => expect(scrollIntoViewMock).toHaveBeenCalledTimes(1))

  await user.click(screen.getByRole("button", { name: "Open plain review" }))
  expect(await screen.findByTestId("location-probe")).toHaveTextContent("/review")

  await user.click(screen.getByRole("button", { name: "Open event 2" }))
  await waitFor(() => expect(screen.getByTestId("location-probe")).toHaveTextContent("/review?eventId=event-2"))
  await waitFor(() => expect(scrollIntoViewMock).toHaveBeenCalledTimes(2))
  expect(within(quizCard as HTMLElement).getByDisplayValue("Quiz 1")).toHaveFocus()
})

test("invalid eventId shows a notice and falls back to the first unresolved blocker", async () => {
  renderReviewPage("/review?eventId=missing-event")

  expect(await screen.findByText("We could not find that calendar item.")).toBeInTheDocument()
  expect(screen.getByText("Previewing cs101.pdf")).toBeInTheDocument()
  const workshopCard = await screen.findByText("Workshop reflection").then((element) => element.closest("[data-review-event-id]"))
  expect(workshopCard).not.toBeNull()
  await waitFor(() => expect(within(workshopCard as HTMLElement).getByLabelText("Event date")).toHaveFocus())
})

test("shows the completed review summary with confirmed, saved for later, saved rules, and removed counts", async () => {
  reviewState.semester.review_completed_at = "2026-08-14T15:00:00Z"
  reviewState.events = [
    {
      ...reviewState.events[0],
      id: "event-confirmed",
      title: "Final project",
      review_status: "confirmed",
      warning_codes: [],
      warning_reason: null,
    },
    {
      ...reviewState.events[1],
      id: "event-awaiting-date",
      title: "Final exam",
      event_date: null,
      warning_codes: ["DATE_MISSING"],
      warning_reason: "The event does not have a confirmed date.",
      review_status: "pending",
    },
    {
      ...reviewState.events[2],
      id: "course-rule-saved",
      title: "Weekly reading cadence",
      event_date: null,
      warning_codes: ["AMBIGUOUS_RECURRENCE"],
      warning_reason: null,
      derivation_summary: "The syllabus names the rule, but not every lecture date.",
      review_status: "pending",
    },
    {
      ...reviewState.events[2],
      id: "event-removed",
      title: "Removed workshop",
      review_status: "ignored",
    },
  ]
  renderReviewPage()

  expect(await screen.findByText("Review complete")).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "Every decision for Fall 2026 is saved" })).toBeInTheDocument()
  expect(screen.getByText("Confirmed").parentElement).toHaveTextContent("1")
  expect(screen.getByText("Saved for later").parentElement).toHaveTextContent("1")
  expect(screen.getByText("Saved rules").parentElement).toHaveTextContent("1")
  expect(screen.getByText("Removed").parentElement).toHaveTextContent("1")
  expect(screen.queryByText("Pending")).not.toBeInTheDocument()
  expect(
    screen.getByText(/Saved for later items stay off the calendar until you confirm them\./i),
  ).toBeInTheDocument()
  expect(
    screen.getByText(/Saved rules stay as reference details and do not enter the calendar until the syllabus gives you exact dates to confirm\./i),
  ).toBeInTheDocument()
  expect(screen.getByText(/1 item still needs a date\./i)).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Open Calendar" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Review decisions" })).toBeInTheDocument()
  expect(screen.queryByText(/Previewing cs101\.pdf/i)).not.toBeInTheDocument()
  expect(screen.queryByRole("tablist", { name: "Review workspace" })).not.toBeInTheDocument()
  expect(screen.queryByTestId("review-sticky-footer")).not.toBeInTheDocument()
})

test("mode edit keeps a completed review in editing mode and uses done editing", async () => {
  reviewState.semester.review_completed_at = "2026-08-14T15:00:00Z"
  reviewState.events[0].review_status = "confirmed"
  reviewState.events[1].review_status = "pending"
  renderReviewPage("/review?mode=edit")

  expect(await screen.findByText("Previewing cs101.pdf")).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "0 of 3 decisions left" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Done editing" })).toBeInTheDocument()
  expect(screen.queryByText("Review complete")).not.toBeInTheDocument()
})

test("event deep links keep completed reviews in editing mode", async () => {
  reviewState.semester.review_completed_at = "2026-08-14T15:00:00Z"
  reviewState.events[0].review_status = "confirmed"
  reviewState.events[1].review_status = "pending"
  renderReviewPage("/review?eventId=event-2")

  expect(await screen.findByText("Previewing math201.pdf")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Done editing" })).toBeInTheDocument()
  expect(screen.queryByText("Review complete")).not.toBeInTheDocument()
})

test("unresolved items override a stored completed review and stay active", async () => {
  reviewState.semester.review_completed_at = "2026-08-14T15:00:00Z"
  renderReviewPage()

  expect(await screen.findByRole("heading", { name: "2 of 3 decisions left" })).toBeInTheDocument()
  expect(screen.queryByText("Review complete")).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Review next" })).toBeInTheDocument()
})

test("finishing review waits for cache refreshes before opening calendar", async () => {
  const user = userEvent.setup()
  reviewState.events[0].review_status = "confirmed"
  reviewState.events[1].review_status = "pending"
  completeReviewMock.mockResolvedValue({ review_completed_at: "2026-08-14T18:00:00Z" })

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  const reviewInvalidate = createDeferredPromise()
  const eventsInvalidate = createDeferredPromise()
  const semestersInvalidate = createDeferredPromise()
  const setQueryData = vi.spyOn(queryClient, "setQueryData")
  const invalidateQueries = vi
    .spyOn(queryClient, "invalidateQueries")
    .mockImplementation((filters) => {
      const queryKey = filters?.queryKey
      if (JSON.stringify(queryKey) === JSON.stringify(["review", "semester-1"])) {
        return reviewInvalidate.promise as ReturnType<QueryClient["invalidateQueries"]>
      }
      if (JSON.stringify(queryKey) === JSON.stringify(["events", "semester-1"])) {
        return eventsInvalidate.promise as ReturnType<QueryClient["invalidateQueries"]>
      }
      if (JSON.stringify(queryKey) === JSON.stringify(semesterQueryKey("user-1"))) {
        return semestersInvalidate.promise as ReturnType<QueryClient["invalidateQueries"]>
      }
      return Promise.resolve() as ReturnType<QueryClient["invalidateQueries"]>
    })
  queryClient.setQueryData(["review", "semester-1"], structuredClone(reviewState))
  queryClient.setQueryData(["events", "semester-1"], [{ id: "calendar-event-1" }])
  queryClient.setQueryData(semesterQueryKey("user-1"), [{ id: "semester-1", review_completed_at: null }])
  render(
    <MemoryRouter initialEntries={["/review"]}>
      <QueryClientProvider client={queryClient}>
        <Routes>
          <Route path="/review" element={<><LocationProbe /><ReviewPage /></>} />
          <Route path="/calendar" element={<><div>Calendar page</div><LocationProbe /></>} />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>,
  )

  await user.click(await screen.findByRole("button", { name: "Finish and open Calendar" }))

  await waitFor(() => expect(setQueryData).toHaveBeenCalledWith(["review", "semester-1"], expect.any(Function)))
  expect(completeReviewMock).toHaveBeenCalledTimes(1)
  expect(invalidateQueries).toHaveBeenCalledWith(expect.objectContaining({ queryKey: ["review", "semester-1"] }))
  expect(invalidateQueries).toHaveBeenCalledWith(expect.objectContaining({ queryKey: ["events", "semester-1"] }))
  expect(invalidateQueries).toHaveBeenCalledWith(expect.objectContaining({ queryKey: semesterQueryKey("user-1") }))
  expect(screen.queryByText("Calendar page")).not.toBeInTheDocument()
  expect(screen.getByTestId("location-probe")).toHaveTextContent("/review")

  reviewInvalidate.resolve()
  await Promise.resolve()
  expect(screen.queryByText("Calendar page")).not.toBeInTheDocument()

  eventsInvalidate.resolve()
  await Promise.resolve()
  expect(screen.queryByText("Calendar page")).not.toBeInTheDocument()

  semestersInvalidate.resolve()

  await screen.findByText("Calendar page")
  expect(screen.getByTestId("location-probe")).toHaveTextContent("/calendar")

  setQueryData.mockRestore()
  invalidateQueries.mockRestore()
})

test("done editing returns to the completed route without completing again", async () => {
  const user = userEvent.setup()
  reviewState.semester.review_completed_at = "2026-08-14T15:00:00Z"
  reviewState.events[0].review_status = "confirmed"
  reviewState.events[1].review_status = "pending"
  renderReviewPage("/review?mode=edit")

  await user.click(await screen.findByRole("button", { name: "Done editing" }))

  expect(await screen.findByText("Review complete")).toBeInTheDocument()
  expect(screen.getByTestId("location-probe")).toHaveTextContent("/review")
  expect(completeReviewMock).not.toHaveBeenCalled()
})

test("completed editing removes pending items from the calendar cache immediately and invalidates events", async () => {
  const user = userEvent.setup()
  reviewState.semester.review_completed_at = "2026-08-14T15:00:00Z"
  reviewState.events[0].review_status = "confirmed"
  reviewState.events[1].review_status = "confirmed"
  reviewState.events[2].review_status = "confirmed"
  getReviewMock.mockReset()
  getReviewMock
    .mockResolvedValueOnce(structuredClone(reviewState))
    .mockRejectedValueOnce(new Error("Refresh failed"))

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  queryClient.setQueryData(["events", "semester-1"], structuredClone(reviewState.events))
  const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries")

  renderReviewPageWithClient(queryClient, "/review?mode=edit")

  await user.click(await screen.findByRole("button", { name: /Reviewed events/i }))
  const finalProjectCard = await screen.findByText("Final project").then((element) => element.closest("[data-review-event-id]"))
  expect(finalProjectCard).not.toBeNull()

  await user.click(within(finalProjectCard as HTMLElement).getByRole("button", { name: "Save for later" }))

  await waitFor(() => expect(updateEventMock).toHaveBeenCalledWith("event-1", expect.objectContaining({ review_status: "pending" })))
  await waitFor(() =>
    expect(
      ((queryClient.getQueryData(["events", "semester-1"]) as ReviewPayload["events"] | undefined) ?? []).map((event) => event.id),
    ).not.toContain("event-1"),
  )
  expect(invalidateQueries).toHaveBeenCalledWith(expect.objectContaining({ queryKey: ["events", "semester-1"] }))
})

test("shows only unresolved course rules in the default workspace and keeps saved rules out of event groups", async () => {
  reviewState.events[0] = {
    ...reviewState.events[0],
    id: "course-rule-needs-review",
    title: "Quick Checks",
    event_type: "quiz",
    event_date: null,
    warning_codes: ["AMBIGUOUS_RECURRENCE"],
    warning_reason: null,
    derivation_summary: "The syllabus names the rule, but not every lecture date.",
    review_status: "needs_review",
  }
  reviewState.events.push({
    ...reviewState.events[0],
    id: "course-rule-saved",
    title: "Attendance policy",
    event_type: "class",
    source_quote: "Attendance is required for every lecture",
    source_page: 4,
    review_status: "pending",
  })
  reviewState.events.push({
    ...reviewState.events[0],
    id: "course-rule-confirmed",
    title: "Legacy confirmed rule",
    source_quote: "Legacy course rule that should not render here",
    source_page: 6,
    review_status: "confirmed",
  })
  reviewState.events.push({
    ...reviewState.events[0],
    id: "course-rule-ignored",
    title: "Removed course rule",
    source_quote: "Removed course rule should stay out of the active group",
    source_page: 7,
    review_status: "ignored",
  })
  reviewState.events[1].review_status = "confirmed"

  renderReviewPage()

  expect(await screen.findByRole("heading", { name: "1 of 5 decisions left" })).toBeInTheDocument()
  expect(screen.getByText("5 extracted events")).toBeInTheDocument()
  const section = await screen.findByTestId("course-rules-section")
  expect(within(section).getByText("Quick Checks")).toBeInTheDocument()
  expect(within(section).queryByText("Attendance policy")).not.toBeInTheDocument()
  expect(within(section).queryByText("Legacy confirmed rule")).not.toBeInTheDocument()
  expect(within(section).queryByText("Removed course rule")).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: /Reviewed events/i })).toHaveTextContent("1")
  expect(screen.getByRole("button", { name: /Removed events/i })).toHaveTextContent("1")
  expect(screen.getByRole("button", { name: "Review next" })).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Finish and open Calendar" })).not.toBeInTheDocument()
})

test("saving a course rule resolves the blocker and keeps the saved rule out of the default workspace", async () => {
  const user = userEvent.setup()
  reviewState.events = [
    {
      ...reviewState.events[0],
      id: "course-rule-1",
      course_id: "course-2",
      document_id: "document-2",
      title: "Quick Checks",
      event_type: "quiz",
      event_date: null,
      warning_codes: ["AMBIGUOUS_RECURRENCE"],
      warning_reason: null,
      derivation_summary: "The syllabus names the rule, but not every lecture date.",
      review_status: "needs_review",
    },
    {
      ...reviewState.events[1],
      id: "event-confirmed-1",
      document_id: "document-1",
      review_status: "confirmed",
      warning_codes: [],
      warning_reason: null,
    },
    {
      ...reviewState.events[2],
      id: "event-confirmed-2",
      review_status: "confirmed",
    },
  ]

  renderReviewPage("/review?eventId=course-rule-1")

  expect(await screen.findByText("Previewing math201.pdf")).toBeInTheDocument()
  const ruleCard = await screen.findByText("Quick Checks").then((element) => element.closest("[data-review-event-id]"))
  expect(ruleCard).not.toBeNull()
  await waitFor(() =>
    expect(within(ruleCard as HTMLElement).getByRole("button", { name: "Modify Quick Checks" })).toHaveFocus(),
  )
  expect(within(ruleCard as HTMLElement).queryByLabelText("Event date")).not.toBeInTheDocument()

  await user.click(within(ruleCard as HTMLElement).getByRole("button", { name: "Save course rule" }))

  await waitFor(() =>
    expect(updateEventMock).toHaveBeenCalledWith(
      "course-rule-1",
      expect.objectContaining({ review_status: "pending" }),
    ),
  )
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Done editing" })).toBeInTheDocument(),
  )

  await user.click(screen.getByRole("button", { name: "Done editing" }))

  expect(await screen.findByText("Previewing math201.pdf")).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "0 of 3 decisions left" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Finish and open Calendar" })).toBeInTheDocument()
  expect(screen.queryByTestId("course-rules-section")).not.toBeInTheDocument()
  expect(screen.queryByText("Quick Checks")).not.toBeInTheDocument()
})

test("saved course rules stay available when deep linked after review is complete", async () => {
  reviewState.semester.review_completed_at = "2026-08-14T15:00:00Z"
  reviewState.events = [
    {
      ...reviewState.events[0],
      id: "course-rule-1",
      course_id: "course-2",
      document_id: "document-2",
      title: "Quick Checks",
      event_type: "quiz",
      event_date: null,
      warning_codes: ["AMBIGUOUS_RECURRENCE"],
      warning_reason: null,
      derivation_summary: "The syllabus names the rule, but not every lecture date.",
      review_status: "pending",
    },
    {
      ...reviewState.events[1],
      id: "event-confirmed-1",
      review_status: "confirmed",
      warning_codes: [],
      warning_reason: null,
    },
  ]

  renderReviewPage("/review?eventId=course-rule-1")

  expect(await screen.findByText("Previewing math201.pdf")).toBeInTheDocument()
  const ruleCard = await screen.findByText("Quick Checks").then((element) => element.closest("[data-review-event-id]"))
  expect(ruleCard).not.toBeNull()
  expect(within(ruleCard as HTMLElement).getByText("Saved")).toBeInTheDocument()
  expect(within(ruleCard as HTMLElement).queryByLabelText("Event date")).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Done editing" })).toBeInTheDocument()
})
