import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { vi } from "vitest"

import { LandingPage } from "./LandingPage"

vi.mock("../lib/auth", () => ({
  useAuth: () => ({
    signIn: vi.fn(),
    isDemo: false,
  }),
}))

function expectSemanticSurfaceClasses(root: HTMLElement) {
  const classText = Array.from(root.querySelectorAll("[class]"))
    .map((node) => node.getAttribute("class") ?? "")
    .join(" ")

  expect(classText).not.toMatch(/\b(bg|text|border)-(teal|slate|red)-|\b(?:bg|text|border)-warning-(?:50|100|500|700)\b/)
}

test("shows a single real sign-in action beside an authentic workflow preview", () => {
  const { container } = render(
    <MemoryRouter>
      <LandingPage />
    </MemoryRouter>,
  )

  expect(screen.getByRole("button", { name: "Continue with Google" })).toBeInTheDocument()
  expect(screen.getAllByRole("button")).toHaveLength(1)
  expect(screen.getByRole("region", { name: "Preview of your semester workflow" })).toBeInTheDocument()
  expect(screen.getByText("This week in Fall 2026")).toBeInTheDocument()
  expect(screen.getByText(/2 files still need review/i)).toBeInTheDocument()
  expect(screen.getByText("2 blockers")).toHaveClass("bg-warning-soft", "text-warning")
  expect(screen.getByText("Needs review").closest("div")).toHaveClass("border-warning-border", "bg-warning-soft")
  expectSemanticSurfaceClasses(container)
})
