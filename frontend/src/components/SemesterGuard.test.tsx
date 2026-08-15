import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { vi } from "vitest"

import { SemesterGuard } from "./SemesterGuard"

const setSemesterId = vi.fn()

vi.mock("../lib/api", () => ({
  useApi: () => ({
    listSemesters: async () => [
      {
        id: "valid-semester",
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
    ],
  }),
}))

vi.mock("../lib/auth", () => ({
  useAuth: () => ({ user: { id: "user-a", email: "student@example.com" } }),
}))

vi.mock("../lib/semester", () => ({
  useSemester: () => ({ semesterId: "deleted-semester", setSemesterId }),
}))

test("replaces an invalid stored semester before rendering a semester route", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <SemesterGuard><h1>Protected semester content</h1></SemesterGuard>
      </QueryClientProvider>
    </MemoryRouter>,
  )

  expect(screen.queryByRole("heading", { name: "Protected semester content" })).not.toBeInTheDocument()
  await waitFor(() => expect(setSemesterId).toHaveBeenCalledWith("valid-semester"))
})
