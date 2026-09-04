import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, vi } from "vitest"

import { ProcessingPage } from "./ProcessingPage"

const reprocessJobMock = vi.hoisted(() => vi.fn(async () => ({ id: "job-2", status: "queued" })))
const listJobsMock = vi.hoisted(() => vi.fn())
const retryJobMock = vi.hoisted(() => vi.fn())
const semesterState = vi.hoisted(() => ({ semesterId: "fall-2026" }))

vi.mock("../lib/api", () => ({
  useApi: () => ({
    listJobs: listJobsMock,
    retryJob: retryJobMock,
    reprocessJob: reprocessJobMock,
  }),
}))

beforeEach(() => {
  listJobsMock.mockResolvedValue([
    {
      id: "job-1",
      document_id: "doc-1",
      filename: "biology.pdf",
      status: "extracting_events",
      stage_detail: "Extracting course dates",
      error_message: null,
      attempts: 1,
    },
    {
      id: "job-2",
      document_id: "doc-2",
      filename: "history.pdf",
      status: "needs_review",
      stage_detail: "Ready to confirm",
      error_message: null,
      attempts: 1,
    },
  ])
  reprocessJobMock.mockClear()
  retryJobMock.mockReset()
  semesterState.semesterId = "fall-2026"
})

vi.mock("../lib/semester", () => ({
  useSemester: () => ({
    semesterId: semesterState.semesterId,
    setSemesterId: vi.fn(),
    ready: true,
  }),
}))

vi.mock("../lib/auth", () => ({
  useAuth: () => ({
    user: { id: "user-1", email: "student@example.com" },
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

test("summarizes file-level processing states before the job list", async () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <ProcessingPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )

  expect(await screen.findByText("1 file still processing")).toBeInTheDocument()
  expect(screen.getByText("1 ready for review")).toBeInTheDocument()
  expect(screen.getByText("Needs review").closest("div")).toHaveClass("border-warning-border", "bg-warning-soft")
  expect(screen.getByText("Ready for review").closest("span")).toHaveClass("bg-warning-soft", "text-warning")
  const pageRoot = screen.getByRole("heading", { name: "Reading your course plans" }).parentElement?.parentElement
  expect(pageRoot).not.toBeNull()
  expectSemanticSurfaceClasses(pageRoot as HTMLElement)
})

test("requires confirmation before replacing an existing extraction", async () => {
  const user = userEvent.setup()
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <ProcessingPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )

  await user.click(await screen.findByRole("button", { name: "Run extraction again for history.pdf" }))
  const dialog = screen.getByRole("dialog", { name: "Run extraction again for history.pdf?" })
  expect(dialog).toHaveTextContent("replace the extracted events and review decisions")
  expect(reprocessJobMock).not.toHaveBeenCalled()

  await user.click(screen.getByRole("button", { name: "Run extraction again" }))
  expect(reprocessJobMock).toHaveBeenCalledWith("job-2")
})

test("shows the review action while any file still needs a decision", async () => {
  listJobsMock.mockResolvedValue([
    {
      id: "job-review",
      document_id: "doc-review",
      filename: "review.pdf",
      status: "needs_review",
      stage_detail: "Ready to confirm",
      error_message: null,
      attempts: 1,
    },
  ])
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <ProcessingPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )

  expect(await screen.findByRole("button", { name: "Review details" })).toBeInTheDocument()
  expect(screen.getAllByText("Step 3 of 4").length).toBeGreaterThan(0)
})

test("opens the calendar and finishes the stepper after every file is reviewed", async () => {
  const user = userEvent.setup()
  listJobsMock.mockResolvedValue([
    {
      id: "job-completed",
      document_id: "doc-completed",
      filename: "completed.pdf",
      status: "completed",
      stage_detail: "Review completed",
      error_message: null,
      attempts: 1,
    },
  ])
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  render(
    <MemoryRouter initialEntries={["/processing"]}>
      <QueryClientProvider client={queryClient}>
        <Routes>
          <Route path="/processing" element={<ProcessingPage />} />
          <Route path="/calendar" element={<h1>Calendar destination</h1>} />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>,
  )

  expect(await screen.findByText("1 file fully reviewed")).toBeInTheDocument()
  expect(screen.getAllByText("Step 4 of 4").length).toBeGreaterThan(0)
  expect(screen.queryByRole("button", { name: "Review details" })).not.toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "Open calendar" }))
  expect(screen.getByRole("heading", { name: "Calendar destination" })).toBeInTheDocument()
})

test("shows a retry recovery alert when retrying a failed job fails, then clears it after a successful retry", async () => {
  const user = userEvent.setup()
  listJobsMock.mockResolvedValue([
    {
      id: "job-failed",
      document_id: "doc-failed",
      filename: "history.pdf",
      status: "failed",
      stage_detail: "Processing failed",
      error_message: "OCR could not run.",
      attempts: 1,
    },
  ])
  retryJobMock
    .mockRejectedValueOnce(new Error("Retry request failed."))
    .mockResolvedValueOnce({ id: "job-failed", status: "queued" })

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <ProcessingPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )

  expect(await screen.findByRole("heading", { name: "Some files need attention" })).toBeInTheDocument()
  await user.click(await screen.findByRole("button", { name: "Retry history.pdf" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("Retry request failed.")
  expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled()

  await user.click(screen.getByRole("button", { name: "Try again" }))

  await waitFor(() => expect(retryJobMock).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(screen.queryByText("Retry request failed.")).not.toBeInTheDocument())
})

test("clears retry recovery state when the selected semester changes so failures do not leak across semesters", async () => {
  const user = userEvent.setup()
  listJobsMock.mockImplementation(async (semesterId: string) => [
    {
      id: `${semesterId}-job-failed`,
      document_id: `${semesterId}-doc-failed`,
      filename: `${semesterId}.pdf`,
      status: "failed",
      stage_detail: "Processing failed",
      error_message: "OCR could not run.",
      attempts: 1,
    },
  ])
  retryJobMock.mockRejectedValueOnce(new Error("Retry request failed."))

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  const view = render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <ProcessingPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )

  await user.click(await screen.findByRole("button", { name: "Retry fall-2026.pdf" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("Retry request failed.")

  semesterState.semesterId = "spring-2026"
  view.rerender(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <ProcessingPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )

  await screen.findByRole("button", { name: "Retry spring-2026.pdf" })
  expect(screen.queryByText("Retry request failed.")).not.toBeInTheDocument()
})

test("closes the reprocess dialog after a successful rerun and invalidates jobs review and events", async () => {
  const user = userEvent.setup()
  let resolveReprocess: (value: { id: string; status: string }) => void = () => undefined
  reprocessJobMock.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        resolveReprocess = resolve
      }),
  )

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries")

  render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <ProcessingPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )

  await user.click(await screen.findByRole("button", { name: "Run extraction again for history.pdf" }))
  expect(screen.getByRole("dialog", { name: "Run extraction again for history.pdf?" })).toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "Run extraction again" }))
  expect(reprocessJobMock).toHaveBeenCalledWith("job-2")

  resolveReprocess({ id: "job-2", status: "queued" })

  await waitFor(() =>
    expect(screen.queryByRole("dialog", { name: "Run extraction again for history.pdf?" })).not.toBeInTheDocument(),
  )
  expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["jobs", "fall-2026"] })
  expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["review", "fall-2026"] })
  expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["events", "fall-2026"] })
})

test("keeps reprocess refreshes scoped to the semester where the rerun started even after semester context changes", async () => {
  const user = userEvent.setup()
  let resolveReprocess: (value: { id: string; status: string }) => void = () => undefined
  listJobsMock.mockImplementation(async (semesterId: string) =>
    semesterId === "fall-2026"
      ? [
          {
            id: "job-2",
            document_id: "doc-2",
            filename: "history.pdf",
            status: "needs_review",
            stage_detail: "Ready to confirm",
            error_message: null,
            attempts: 1,
          },
        ]
      : [],
  )
  reprocessJobMock.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        resolveReprocess = resolve
      }),
  )

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries")

  const view = render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <ProcessingPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )

  await user.click(await screen.findByRole("button", { name: "Run extraction again for history.pdf" }))
  await user.click(screen.getByRole("button", { name: "Run extraction again" }))

  semesterState.semesterId = "spring-2026"
  view.rerender(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <ProcessingPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )

  resolveReprocess({ id: "job-2", status: "queued" })

  await waitFor(() =>
    expect(screen.queryByRole("dialog", { name: "Run extraction again for history.pdf?" })).not.toBeInTheDocument(),
  )
  expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["jobs", "fall-2026"] })
  expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["review", "fall-2026"] })
  expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["events", "fall-2026"] })
  expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ["review", "spring-2026"] })
  expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ["events", "spring-2026"] })
})

test("keeps the reprocess dialog open when cancel or Escape is used during an active rerun", async () => {
  const user = userEvent.setup()
  reprocessJobMock.mockImplementationOnce(() => new Promise(() => undefined))

  render(
    <MemoryRouter>
      <QueryClientProvider
        client={new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })}
      >
        <ProcessingPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )

  await user.click(await screen.findByRole("button", { name: "Run extraction again for history.pdf" }))
  const dialogName = "Run extraction again for history.pdf?"
  expect(screen.getByRole("dialog", { name: dialogName })).toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "Run extraction again" }))
  await user.click(screen.getByRole("button", { name: "Cancel" }))
  expect(screen.getByRole("dialog", { name: dialogName })).toBeInTheDocument()

  await user.keyboard("{Escape}")
  expect(screen.getByRole("dialog", { name: dialogName })).toBeInTheDocument()
})
