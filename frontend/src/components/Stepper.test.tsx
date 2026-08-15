import { render, screen } from "@testing-library/react"

import { Stepper } from "./Stepper"

test("marks the active setup step for assistive technology", () => {
  const { container } = render(<Stepper currentStep={2} />)

  expect(screen.getByText("Upload")).toHaveAttribute("aria-current", "step")
  expect(screen.getByText("Semester")).not.toHaveAttribute("aria-current")
  expect(screen.getByText("Step 2 of 4")).toBeInTheDocument()

  const classText = Array.from(container.querySelectorAll("[class]"))
    .map((node) => node.getAttribute("class") ?? "")
    .join(" ")

  expect(screen.getByText("Step 2 of 4")).toHaveClass("text-text-subtle")
  expect(classText).toContain("bg-border")
  expect(classText).toContain("bg-accent")
  expect(classText).toContain("text-accent")
  expect(classText).toContain("text-text")
  expect(classText).not.toMatch(/\b(?:bg|text)-(?:slate|teal)-/)
})
