import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { vi } from "vitest"

import { ProcessingPage } from "./ProcessingPage"
import { UploadPage } from "./UploadPage"

const semestersState = vi.hoisted(() => ({
  items: [
    {
      id: "fall-2026",
      name: "Fall 2026",
      start_date: "2026-08-24",
      end_date: "2026-12-18",
      timezone: "America/New_York",
      review_completed_at: null,
      course_count: 0,
      document_count: 0,
      event_count: 0,
      needs_review_count: 0,
    },
    {
      id: "spring-2026",
      name: "Spring 2026",
      start_date: "2026-01-12",
      end_date: "2026-05-08",
      timezone: "America/New_York",
      review_completed_at: null,
      course_count: 0,
      document_count: 0,
      event_count: 0,
      needs_review_count: 0,
    },
  ],
}))
const setSemesterId = vi.fn()
const uploadSyllabi = vi.fn()
const listJobs = vi.fn()

vi.mock("../lib/api", () => ({
  useApi: () => ({
    listSemesters: async () => structuredClone(semestersState.items),
    listJobs,
    retryJob: vi.fn(),
    uploadSyllabi,
  }),
}))

vi.mock("../lib/semester", () => ({
  useSemester: () => ({ semesterId: "spring-2026", setSemesterId, ready: true }),
}))

vi.mock("../lib/auth", () => ({
  useAuth: () => ({
    user: { id: "user-a", email: "student@example.com" },
    loading: false,
    signOut: vi.fn(),
  }),
}))

function expectSemanticSurfaceClasses(root: HTMLElement) {
  const classText = Array.from(root.querySelectorAll("[class]"))
    .map((node) => node.getAttribute("class") ?? "")
    .join(" ")

  expect(classText).not.toMatch(/\b(bg|text|border)-(teal|slate|red)-|\b(?:bg|text|border)-warning-(?:50|100|500|700)\b/)
}

beforeEach(() => {
  semestersState.items = [
    {
      id: "fall-2026",
      name: "Fall 2026",
      start_date: "2026-08-24",
      end_date: "2026-12-18",
      timezone: "America/New_York",
      review_completed_at: null,
      course_count: 0,
      document_count: 0,
      event_count: 0,
      needs_review_count: 0,
    },
    {
      id: "spring-2026",
      name: "Spring 2026",
      start_date: "2026-01-12",
      end_date: "2026-05-08",
      timezone: "America/New_York",
      review_completed_at: null,
      course_count: 0,
      document_count: 0,
      event_count: 0,
      needs_review_count: 0,
    },
  ]
  listJobs.mockReset()
  setSemesterId.mockReset()
  uploadSyllabi.mockReset()
})

test("shows the saved semesters and keeps the last one selected", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <UploadPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )

  const selector = await screen.findByRole("combobox", { name: "Upload to semester" })
  expect(selector).toHaveValue("spring-2026")
  expect(screen.getByRole("option", { name: "Fall 2026" })).toBeVisible()
  expect(screen.getByRole("option", { name: "Spring 2026" })).toBeVisible()
  expect(screen.getByText("January 12, 2026 to May 8, 2026")).toBeInTheDocument()
  expect(screen.getAllByText("10 PDFs max")).toHaveLength(2)
  const pageRoot = screen.getByRole("heading", { name: "Add every course in one batch" }).parentElement?.parentElement
  expect(pageRoot).not.toBeNull()
  expectSemanticSurfaceClasses(pageRoot as HTMLElement)
})

test("uses semantic token classes for the no-semester upload empty state", async () => {
  semestersState.items = []
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <UploadPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )

  expect(await screen.findByRole("heading", { name: "Create a semester before uploading" })).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "Create a semester before uploading" })).toHaveClass("text-text")
  expect(screen.getByText("Your semester dates help the review step catch deadlines that look wrong.")).toHaveClass("text-text-muted")
  const pageRoot = screen.getByRole("heading", { name: "Create a semester before uploading" }).parentElement?.parentElement
  expect(pageRoot).not.toBeNull()
  expectSemanticSurfaceClasses(pageRoot as HTMLElement)
})

test("locks the semester selector while an upload is starting", async () => {
  uploadSyllabi.mockImplementationOnce(() => new Promise(() => undefined))
  const user = userEvent.setup()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <UploadPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )

  const selector = await screen.findByRole("combobox", { name: "Upload to semester" })
  await user.upload(screen.getByLabelText("Choose syllabus PDFs"), new File(["pdf"], "course.pdf", { type: "application/pdf" }))
  await user.click(screen.getByRole("button", { name: "Process 1 syllabus" }))

  expect(selector).toBeDisabled()
})

test("seeds returned jobs before navigating to processing so new uploads do not flash an empty state", async () => {
  const user = userEvent.setup()
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  const createdJobs = [
    {
      id: "job-1",
      document_id: "doc-1",
      filename: "course.pdf",
      status: "extracting_events",
      stage_detail: "Extracting course dates",
      error_message: null,
      attempts: 1,
    },
  ]
  uploadSyllabi.mockResolvedValueOnce({ jobs: createdJobs })
  listJobs.mockImplementationOnce(() => new Promise(() => undefined))

  render(
    <MemoryRouter initialEntries={["/upload"]}>
      <QueryClientProvider client={queryClient}>
        <Routes>
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/processing" element={<ProcessingPage />} />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>,
  )

  await screen.findByRole("combobox", { name: "Upload to semester" })
  await user.upload(await screen.findByLabelText("Choose syllabus PDFs"), new File(["pdf"], "course.pdf", { type: "application/pdf" }))
  await user.click(screen.getByRole("button", { name: "Process 1 syllabus" }))

  expect(await screen.findByText("1 file still processing")).toBeInTheDocument()
  expect(screen.queryByText("No syllabus files are waiting.")).not.toBeInTheDocument()
  expect(queryClient.getQueryData(["jobs", "spring-2026"])).toEqual(createdJobs)
})
