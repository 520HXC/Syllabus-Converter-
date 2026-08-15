import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"

import { ReviewPage } from "./ReviewPage"

const reviewState = vi.hoisted(() => ({
  semester: {
    id: "semester-1",
    name: "Fall 2026",
    start_date: "2026-08-24",
    end_date: "2026-12-18",
    timezone: "America/New_York",
    review_completed_at: null,
    course_count: 2,
    document_count: 1,
    event_count: 3,
    needs_review_count: 1,
  },
  documents: [
    { id: "document-1", filename: "cs101.pdf", size_bytes: 100, used_ocr: false },
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
      document_id: "document-1",
      code: "MATH 201",
      name: "Discrete Math",
      instructor: "Prof. Stone",
      color: "#2563EB",
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
      id: "event-2",
      semester_id: "semester-1",
      course_id: "course-2",
      document_id: "document-1",
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
    {
      id: "event-3",
      semester_id: "semester-1",
      course_id: "course-1",
      document_id: "document-1",
      title: "Old reminder",
      event_type: "meeting",
      event_date: "2026-09-01",
      start_time: null,
      end_time: null,
      timezone: "America/New_York",
      is_all_day: true,
      source_quote: "Old reminder",
      source_page: 1,
      confidence: "medium" as const,
      warning_codes: [],
      warning_reason: null,
      review_status: "ignored" as const,
    },
  ],
}))

vi.mock("../theme/ThemeProvider", () => ({
  useTheme: () => ({
    theme: "dark",
    resolvedTheme: "dark",
    setTheme: vi.fn(),
  }),
}))
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
    getReview: vi.fn(async () => structuredClone(reviewState)),
    updateEvent: vi.fn(async (eventId: string, payload: Record<string, unknown>) => {
      const event = reviewState.events.find((item) => item.id === eventId)
      if (!event) throw new Error("Missing event")
      Object.assign(event, payload)
      return structuredClone(event)
    }),
    updateCourse: vi.fn(async (courseId: string, values: Record<string, unknown>) => {
      const course = reviewState.courses.find((item) => item.id === courseId)
      if (!course) throw new Error("Missing course")
      Object.assign(course, values)
      return structuredClone(course)
    }),
    completeReview: vi.fn(),
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
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/calendar" element={<div>Calendar page</div>} />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

test("maps review course colors onto the dark display palette for active, reviewed, and removed groups", async () => {
  const user = userEvent.setup()
  renderReviewPage()

  expect(await screen.findByText("Previewing cs101.pdf")).toBeInTheDocument()
  expect(screen.getByTestId("course-rail-event-1")).toHaveStyle({ backgroundColor: "#C084FC" })

  const courseSection = screen.getByRole("heading", { name: "CS 101" }).closest("section")
  expect(courseSection?.querySelector("span[style]")).toHaveStyle({ backgroundColor: "#C084FC" })

  await user.click(screen.getByRole("button", { name: /Reviewed events/i }))
  expect(screen.getByTestId("course-rail-event-2")).toHaveStyle({ backgroundColor: "#22D3EE" })

  await user.click(screen.getByRole("button", { name: /Removed events/i }))
  expect(screen.getByText("Old reminder").parentElement?.previousElementSibling).toHaveStyle({
    backgroundColor: "#C084FC",
  })
})
