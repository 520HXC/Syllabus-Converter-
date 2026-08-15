import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { SemesterForm } from "./SemesterForm"

test("rejects an end date before the semester start", async () => {
  const user = userEvent.setup()
  render(<SemesterForm defaultTimezone="America/New_York" onSubmit={vi.fn()} />)

  await user.type(screen.getByLabelText("Semester name"), "Fall 2026")
  await user.type(screen.getByLabelText("First day"), "2026-12-18")
  await user.type(screen.getByLabelText("Last day"), "2026-08-24")
  await user.click(screen.getByRole("button", { name: "Save semester" }))

  expect(await screen.findByText("The last day must be on or after the first day.")).toBeInTheDocument()
})

test("submits the four semester fields", async () => {
  const user = userEvent.setup()
  const onSubmit = vi.fn().mockResolvedValue(undefined)
  render(<SemesterForm defaultTimezone="America/New_York" onSubmit={onSubmit} />)

  await user.type(screen.getByLabelText("Semester name"), "Fall 2026")
  await user.type(screen.getByLabelText("First day"), "2026-08-24")
  await user.type(screen.getByLabelText("Last day"), "2026-12-18")
  await user.click(screen.getByRole("button", { name: "Save semester" }))

  expect(onSubmit).toHaveBeenCalledWith({
    name: "Fall 2026",
    start_date: "2026-08-24",
    end_date: "2026-12-18",
    timezone: "America/New_York",
  })
})
