import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom"

import { SemestersPage } from "./SemestersPage"

const setSemesterIdMock = vi.hoisted(() => vi.fn())
const semestersState = vi.hoisted(() => ({
  items: [
    {
      id: "fall-2026",
      name: "Fall 2026",
      start_date: "2026-08-24",
      end_date: "2026-12-18",
      timezone: "America/New_York",
      review_completed_at: null,
      course_count: 2,
      document_count: 3,
      event_count: 9,
      needs_review_count: 1,
    },
    {
      id: "spring-2026",
      name: "Spring 2026",
      start_date: "2026-01-12",
      end_date: "2026-05-08",
      timezone: "America/New_York",
      review_completed_at: null,
      course_count: 1,
      document_count: 1,
      event_count: 4,
      needs_review_count: 0,
    },
  ],
}))
const listSemestersMock = vi.hoisted(() => vi.fn(async () => structuredClone(semestersState.items)))
const deleteSemesterMock = vi.hoisted(
  () =>
    vi.fn(async (semesterId: string) => {
      semestersState.items = semestersState.items.filter((semester) => semester.id !== semesterId)
    }),
)

vi.mock("../lib/api", () => ({
  useApi: () => ({
    listSemesters: listSemestersMock,
    deleteSemester: deleteSemesterMock,
  }),
}))

vi.mock("../lib/semester", () => ({
  useSemester: () => ({
    semesterId: "fall-2026",
    setSemesterId: setSemesterIdMock,
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

function LocationDisplay() {
  const location = useLocation()

  return <div aria-label="Current route">{location.pathname}</div>
}

function renderSemestersPage(initialEntries = ["/semesters"]) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <QueryClientProvider client={queryClient}>
        <Routes>
          <Route path="/semesters" element={<SemestersPage />} />
          <Route path="/setup" element={<LocationDisplay />} />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

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
      course_count: 2,
      document_count: 3,
      event_count: 9,
      needs_review_count: 1,
    },
    {
      id: "spring-2026",
      name: "Spring 2026",
      start_date: "2026-01-12",
      end_date: "2026-05-08",
      timezone: "America/New_York",
      review_completed_at: null,
      course_count: 1,
      document_count: 1,
      event_count: 4,
      needs_review_count: 0,
    },
  ]
  listSemestersMock.mockClear()
  deleteSemesterMock.mockClear()
  setSemesterIdMock.mockClear()
})

test("shows aggregate counts and requires explicit confirmation before deleting the current semester", async () => {
  const user = userEvent.setup()
  renderSemestersPage()

  expect(await screen.findByText("Current semester")).toBeInTheDocument()
  expect(await screen.findByText("2 courses")).toBeInTheDocument()
  expect(screen.getByText("3 syllabi")).toBeInTheDocument()
  expect(screen.getByText("9 events")).toBeInTheDocument()
  expect(screen.getByText("1 to review")).toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "Delete Fall 2026 semester" }))

  const dialog = screen.getByRole("dialog", { name: "Delete Fall 2026?" })
  expect(dialog).toHaveAttribute("aria-modal", "true")
  expect(dialog).toHaveAttribute("aria-labelledby")
  expect(screen.getByRole("heading", { name: "Delete Fall 2026?" })).toBeInTheDocument()
  expect(screen.getByText(/August 24, 2026/)).toBeInTheDocument()
  expect(screen.getByText(/2 courses, 3 syllabi, 9 events/)).toBeInTheDocument()
  expect(dialog.parentElement).toHaveClass("bg-overlay/45")
  expect(screen.getByRole("checkbox", { name: /I understand this permanently deletes/i })).toHaveClass("accent-danger")
  expect(screen.getAllByRole("button", { name: "Open calendar", hidden: true })[0].querySelectorAll("svg")).toHaveLength(1)
  expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus()
  const confirmButton = screen.getByRole("button", { name: "Delete semester" })
  expect(confirmButton).toBeDisabled()

  await user.click(screen.getByRole("checkbox", { name: /I understand this permanently deletes/i }))
  await user.click(confirmButton)

  await waitFor(() => expect(deleteSemesterMock).toHaveBeenCalledWith("fall-2026"))
  await waitFor(() => expect(setSemesterIdMock).toHaveBeenCalledWith("spring-2026"))
  const pageRoot = screen.getByRole("heading", { name: "Pick up where you left off" }).parentElement?.parentElement
  expect(pageRoot).not.toBeNull()
  expectSemanticSurfaceClasses(pageRoot as HTMLElement)
})

test("closes the delete dialog on Escape and returns focus to the trigger", async () => {
  const user = userEvent.setup()
  renderSemestersPage()

  const trigger = await screen.findByRole("button", { name: "Delete Fall 2026 semester" })
  await user.click(trigger)
  expect(screen.getByRole("dialog", { name: "Delete Fall 2026?" })).toBeInTheDocument()

  await user.keyboard("{Escape}")

  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Delete Fall 2026?" })).not.toBeInTheDocument())
  expect(trigger).toHaveFocus()
})

test("traps keyboard focus inside the delete dialog and makes the page content inert", async () => {
  const user = userEvent.setup()
  renderSemestersPage()

  await user.click(await screen.findByRole("button", { name: "Delete Fall 2026 semester" }))

  const checkbox = screen.getByRole("checkbox", { name: /I understand this permanently deletes/i })
  const cancelButton = screen.getByRole("button", { name: "Cancel" })
  const confirmButton = screen.getByRole("button", { name: "Delete semester" })

  expect(cancelButton).toHaveFocus()
  expect(screen.getAllByRole("button", { name: "Open calendar", hidden: true })[0].closest("[aria-hidden='true']")).not.toBeNull()

  await user.tab()
  expect(checkbox).toHaveFocus()

  await user.tab({ shift: true })
  expect(cancelButton).toHaveFocus()

  await user.click(checkbox)
  expect(checkbox).toHaveFocus()

  await user.tab()
  expect(cancelButton).toHaveFocus()

  await user.tab()
  expect(confirmButton).toHaveFocus()

  await user.tab()
  expect(checkbox).toHaveFocus()

  await user.tab({ shift: true })
  expect(confirmButton).toHaveFocus()
})

test("navigates to setup after deleting the last remaining semester", async () => {
  const user = userEvent.setup()
  semestersState.items = [semestersState.items[0]]
  renderSemestersPage()

  await user.click(await screen.findByRole("button", { name: "Delete Fall 2026 semester" }))
  await user.click(screen.getByRole("checkbox", { name: /I understand this permanently deletes/i }))
  await user.click(screen.getByRole("button", { name: "Delete semester" }))

  expect(await screen.findByLabelText("Current route")).toHaveTextContent("/setup")
})
