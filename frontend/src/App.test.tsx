import { render, screen } from "@testing-library/react"
import { MemoryRouter, useLocation } from "react-router-dom"
import { vi } from "vitest"

import App from "./App"

const authState = vi.hoisted(() => ({
  user: { id: "user-a", email: "student@example.com" } as { id: string; email: string } | null,
  loading: false,
}))
const semesterState = vi.hoisted(() => ({ ready: true }))

vi.mock("./lib/auth", () => ({
  useAuth: () => ({
    ...authState,
    isDemo: true,
    signIn: vi.fn(),
    signOut: vi.fn(),
    getAccessToken: vi.fn(),
  }),
}))

vi.mock("./lib/semester", () => ({
  useSemester: () => semesterState,
}))

vi.mock("./pages/SemestersPage", () => ({
  SemestersPage: () => <h1>Saved semesters</h1>,
}))

vi.mock("./pages/UploadPage", () => ({
  UploadPage: () => <h1>Upload syllabi</h1>,
}))

function LocationProbe() {
  const location = useLocation()
  return <output aria-label="Current route">{location.pathname}</output>
}

test("sends an existing session from the landing route to saved semesters", async () => {
  render(
    <MemoryRouter initialEntries={["/"]}>
      <App />
      <LocationProbe />
    </MemoryRouter>,
  )

  expect(await screen.findByRole("heading", { name: "Saved semesters" })).toBeVisible()
  expect(screen.getByLabelText("Current route")).toHaveTextContent("/semesters")
})

test("waits for the saved semester before opening a protected deep link", async () => {
  semesterState.ready = false

  render(
    <MemoryRouter initialEntries={["/upload"]}>
      <App />
    </MemoryRouter>,
  )

  expect(await screen.findByText("Restoring your semester")).toBeVisible()
  expect(screen.queryByRole("heading", { name: "Upload syllabi" })).not.toBeInTheDocument()
  semesterState.ready = true
})
