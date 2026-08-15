import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { vi } from "vitest"

import { SemesterSetupPage } from "./SemesterSetupPage"

vi.mock("../lib/api", () => ({
  useApi: () => ({
    createSemester: vi.fn(),
  }),
}))

vi.mock("../lib/auth", () => ({
  useAuth: () => ({
    user: { id: "user-1", email: "student@example.com" },
    loading: false,
    signOut: vi.fn(),
  }),
}))

vi.mock("../lib/semester", () => ({
  useSemester: () => ({
    setSemesterId: vi.fn(),
  }),
}))

test("shows compact setup context alongside the semester form", () => {
  const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } })

  render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <SemesterSetupPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )

  expect(screen.getByText("What this locks in")).toBeInTheDocument()
  expect(screen.getByText("Review flags compare extracted dates against this range.")).toBeInTheDocument()
  expect(screen.getByText("Calendar export keeps every all-day event in this timezone.")).toBeInTheDocument()
})
