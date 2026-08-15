import { render, screen, within } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { vi } from "vitest"

import { ThemeProvider } from "../theme/ThemeProvider"
import { AppShell } from "./AppShell"

const authState = vi.hoisted(() => ({
  user: { id: "user-a", email: "student@example.com" } as { id: string; email: string } | null,
  signOut: vi.fn(),
}))

vi.mock("../lib/auth", () => ({
  useAuth: () => authState,
}))

test("renders desktop and mobile navigation with live theme controls for signed-in users", () => {
  render(
    <MemoryRouter initialEntries={["/calendar"]}>
      <ThemeProvider>
        <AppShell currentStep={3}>
          <div>Page content</div>
        </AppShell>
      </ThemeProvider>
    </MemoryRouter>,
  )

  const desktopNav = screen.getByRole("navigation", { name: "Primary navigation" })
  expect(within(desktopNav).getByRole("link", { name: "Calendar" })).toHaveAttribute("aria-current", "page")
  expect(within(desktopNav).getByRole("link", { name: "Semesters" })).toBeVisible()
  expect(within(desktopNav).getByRole("link", { name: "Review" })).toBeVisible()
  expect(within(desktopNav).getByRole("link", { name: "Upload" })).toBeVisible()

  const mobileNav = screen.getByRole("navigation", { name: "Mobile navigation" })
  expect(within(mobileNav).getAllByRole("link")).toHaveLength(4)

  const mobileBrand = screen.getAllByRole("link", { name: /Syllabus Calendar/ })[1]
  expect(mobileBrand).toHaveClass("min-w-0", "flex-1")

  expect(screen.getAllByText("student@example.com")).toHaveLength(2)
  expect(screen.getAllByRole("button", { name: "Sign out" }).length).toBeGreaterThan(0)

  const [themePicker] = screen.getAllByRole("group", { name: "Color theme" })
  expect(within(themePicker).getByRole("button", { name: "Light theme" })).toBeVisible()
  expect(within(themePicker).getByRole("button", { name: "Dark theme" })).toBeVisible()
  expect(within(themePicker).getByRole("button", { name: "System theme" })).toBeVisible()

  expect(screen.getByText("Page content")).toBeVisible()
})
