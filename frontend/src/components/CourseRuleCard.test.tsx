import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { CourseRuleCard } from "./CourseRuleCard"

const courseRule = {
  id: "rule-1",
  semester_id: "semester-1",
  course_id: "course-1",
  document_id: "document-1",
  title: "Quick Checks",
  event_type: "quiz",
  event_date: null,
  start_time: null,
  end_time: null,
  timezone: "America/New_York",
  is_all_day: true,
  source_quote: "Quick Checks are due the morning of each lecture",
  source_page: 3,
  confidence: "medium" as const,
  warning_codes: ["AMBIGUOUS_RECURRENCE"],
  warning_reason: "This generic warning should not be shown.",
  review_status: "needs_review" as const,
  extraction_model: "gpt-5.6-terra",
  fallback_reason_codes: ["LOW_CONFIDENCE"],
  derivation_summary: "The syllabus names the rule, but it does not list every lecture date.",
}

const defaultProps = {
  courseLabel: "CS 101",
  courseColor: "#0D9488",
}

test("shows a rule-focused summary and only title and type controls while editing", async () => {
  const user = userEvent.setup()

  render(<CourseRuleCard event={courseRule} onSave={vi.fn()} {...defaultProps} />)

  expect(screen.getByText("Recurring rule")).toBeInTheDocument()
  expect(screen.getByText("Needs review")).toBeInTheDocument()
  expect(screen.getByText("Why dates were not generated")).toBeInTheDocument()
  expect(
    screen.getByText("Dates were not generated because the syllabus does not identify every occurrence"),
  ).toBeInTheDocument()
  expect(screen.queryByText("AI date")).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Keep pending" })).not.toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "Modify Quick Checks" }))

  expect(screen.getByLabelText("Event name")).toHaveValue("Quick Checks")
  expect(screen.getByLabelText("Event type")).toHaveValue("quiz")
  expect(screen.queryByLabelText("Event date")).not.toBeInTheDocument()
  expect(screen.queryByLabelText("All day event")).not.toBeInTheDocument()
  expect(screen.queryByLabelText("Start time")).not.toBeInTheDocument()
  expect(screen.queryByLabelText("End time")).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Save changes" })).toBeInTheDocument()
})

test("saves course rules as pending and preserves the current status when saving edits", async () => {
  const user = userEvent.setup()
  const onSave = vi.fn().mockResolvedValue(undefined)
  const { rerender } = render(
    <CourseRuleCard event={courseRule} onSave={onSave} {...defaultProps} />,
  )

  await user.click(screen.getByRole("button", { name: "Save course rule" }))

  expect(onSave).toHaveBeenCalledWith("rule-1", {
    title: "Quick Checks",
    event_type: "quiz",
    review_status: "pending",
  })

  rerender(
    <CourseRuleCard
      event={{ ...courseRule, review_status: "pending" }}
      onSave={onSave}
      {...defaultProps}
    />,
  )

  await user.click(screen.getByRole("button", { name: "Modify Quick Checks" }))
  await user.clear(screen.getByLabelText("Event name"))
  await user.type(screen.getByLabelText("Event name"), "Quick Checks policy")
  await user.clear(screen.getByLabelText("Event type"))
  await user.type(screen.getByLabelText("Event type"), "assignment")
  await user.click(screen.getByRole("button", { name: "Save changes" }))

  expect(onSave).toHaveBeenLastCalledWith("rule-1", {
    title: "Quick Checks policy",
    event_type: "assignment",
    review_status: "pending",
  })
})

test("keeps edited values visible and shows an inline error when saving fails", async () => {
  const user = userEvent.setup()
  const onSave = vi.fn().mockRejectedValue(new Error("The course rule could not be saved."))

  render(<CourseRuleCard event={courseRule} onSave={onSave} {...defaultProps} />)

  await user.click(screen.getByRole("button", { name: "Modify Quick Checks" }))
  await user.clear(screen.getByLabelText("Event name"))
  await user.type(screen.getByLabelText("Event name"), "Quick Checks policy")
  await user.click(screen.getByRole("button", { name: "Save course rule" }))

  expect(await screen.findByRole("alert")).toHaveTextContent("The course rule could not be saved.")
  expect(screen.getByLabelText("Event name")).toHaveValue("Quick Checks policy")
})

test("keeps the editor open and preserves the draft when the same rule rerenders", async () => {
  const user = userEvent.setup()
  const { rerender } = render(
    <CourseRuleCard event={courseRule} onSave={vi.fn()} {...defaultProps} />,
  )

  await user.click(screen.getByRole("button", { name: "Modify Quick Checks" }))
  await user.clear(screen.getByLabelText("Event name"))
  await user.type(screen.getByLabelText("Event name"), "Quick Checks policy")

  rerender(
    <CourseRuleCard
      event={{ ...courseRule, warning_reason: null }}
      onSave={vi.fn()}
      {...defaultProps}
    />,
  )

  expect(screen.getByRole("region", { name: "Modify Quick Checks" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Modify Quick Checks" })).toHaveAttribute(
    "aria-expanded",
    "true",
  )
  expect(screen.getByLabelText("Event name")).toHaveValue("Quick Checks policy")
})

test("uses a unique datalist id for each editing card", async () => {
  const user = userEvent.setup()

  render(
    <>
      <CourseRuleCard event={courseRule} onSave={vi.fn()} {...defaultProps} />
      <CourseRuleCard
        event={{ ...courseRule, id: "rule-2", title: "Attendance policy" }}
        onSave={vi.fn()}
        courseLabel="ENG 220"
        courseColor="#EA580C"
      />
    </>,
  )

  await user.click(screen.getByRole("button", { name: "Modify Quick Checks" }))
  await user.click(screen.getByRole("button", { name: "Modify Attendance policy" }))

  const eventTypeInputs = screen.getAllByLabelText("Event type")
  const datalists = document.querySelectorAll("datalist")
  expect(datalists).toHaveLength(2)

  const listIds = eventTypeInputs.map((input) => input.getAttribute("list"))
  expect(listIds[0]).toBeTruthy()
  expect(listIds[1]).toBeTruthy()
  expect(listIds[0]).not.toBe(listIds[1])
  expect(Array.from(datalists).map((node) => node.id)).toEqual(listIds)
})

test("labels the focusable card with its heading", () => {
  render(<CourseRuleCard event={courseRule} onSave={vi.fn()} {...defaultProps} />)

  const card = screen.getByText("Quick Checks").closest("[data-review-event-id]")
  expect(card).not.toBeNull()
  expect(card).toHaveAttribute("aria-labelledby")
  expect(within(card as HTMLElement).getByRole("heading", { name: "Quick Checks" }).id).toBe(
    card?.getAttribute("aria-labelledby"),
  )
})

test("does not repeat an identical missing-dates reason on a rule that needs review", () => {
  render(
    <CourseRuleCard
      event={{
        ...courseRule,
        derivation_summary:
          "Dates were not generated because the syllabus does not identify every occurrence.",
      }}
      onSave={vi.fn()}
      {...defaultProps}
    />,
  )

  expect(
    screen.getAllByText(
      /Dates were not generated because the syllabus does not identify every occurrence/i,
    ),
  ).toHaveLength(1)
  expect(screen.queryByText("Why dates were not generated")).not.toBeInTheDocument()
})

test("keeps the rule explanation visible after the rule is saved", () => {
  render(
    <CourseRuleCard
      event={{
        ...courseRule,
        review_status: "pending",
        derivation_summary:
          "Dates were not generated because the syllabus does not identify every occurrence.",
      }}
      onSave={vi.fn()}
      {...defaultProps}
    />,
  )

  expect(screen.getByText("Why dates were not generated")).toBeInTheDocument()
  expect(
    screen.getByText(
      "Dates were not generated because the syllabus does not identify every occurrence.",
    ),
  ).toBeInTheDocument()
})

test("replaces the save action with an unmistakable completed state after the rule is saved", () => {
  render(
    <CourseRuleCard
      event={{ ...courseRule, review_status: "pending" }}
      onSave={vi.fn()}
      {...defaultProps}
    />,
  )

  expect(screen.queryByRole("button", { name: "Save course rule" })).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Saved to Course rules" })).toBeDisabled()
  expect(screen.getByText("Saved in Course rules. You can modify or remove it anytime.")).toBeVisible()
})
