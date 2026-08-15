import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { ReviewEventCard } from "./ReviewEventCard"

const event = {
  id: "event-1",
  semester_id: "semester-1",
  course_id: "course-1",
  document_id: "document-1",
  title: "Final project",
  event_type: "project",
  event_date: "2026-12-10",
  start_time: null,
  end_time: null,
  timezone: "America/New_York",
  is_all_day: true,
  source_quote: "Final project due around December 10",
  source_page: 5,
  confidence: "low" as const,
  warning_codes: ["AMBIGUOUS_DATE"],
  warning_reason: "The date wording is tentative.",
  review_status: "needs_review" as const,
}

const defaultProps = {
  courseLabel: "CS 101",
  courseColor: "#0D9488",
}

test("shows a compact summary before modification", () => {
  render(<ReviewEventCard event={event} onSave={vi.fn()} {...defaultProps} />)

  expect(screen.getByRole("heading", { name: "Final project" })).toBeInTheDocument()
  expect(screen.getByText("December 10, 2026")).toBeInTheDocument()
  expect(screen.getByText(/Final project due around December 10/)).toBeInTheDocument()
  expect(screen.getByText("Page 5")).toBeInTheDocument()
  expect(screen.getByText("The date wording is tentative.")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Modify Final project" })).toHaveAttribute(
    "aria-expanded",
    "false",
  )
  expect(screen.queryByLabelText("Event name")).not.toBeInTheDocument()
  expect(screen.queryByLabelText("Event date")).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Save changes" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Guess is right" })).not.toBeInTheDocument()
})

test("uses distinct semantic colors for exam type and medium confidence", () => {
  render(
    <ReviewEventCard
      event={{
        ...event,
        event_type: "exam",
        confidence: "medium",
      }}
      onSave={vi.fn()}
      {...defaultProps}
    />,
  )

  const examBadge = screen.getByText("exam")
  const confidenceBadge = screen.getByText("Medium confidence")

  expect(examBadge).toHaveClass(
    "border-event-exam-border",
    "bg-event-exam-soft",
    "text-event-exam",
  )
  expect(confidenceBadge).toHaveClass(
    "border-confidence-medium-border",
    "bg-confidence-medium-soft",
    "text-confidence-medium",
  )
  expect(examBadge.className).not.toBe(confidenceBadge.className)
})

test("uses semantic confidence colors at both ends of the confidence scale", () => {
  const { rerender } = render(
    <ReviewEventCard
      event={{ ...event, confidence: "high" }}
      onSave={vi.fn()}
      {...defaultProps}
    />,
  )

  expect(screen.getByText("High confidence")).toHaveClass(
    "bg-confidence-high-soft",
    "text-confidence-high",
  )

  rerender(
    <ReviewEventCard
      event={{ ...event, confidence: "low" }}
      onSave={vi.fn()}
      {...defaultProps}
    />,
  )

  expect(screen.getByText("Low confidence")).toHaveClass(
    "bg-confidence-low-soft",
    "text-confidence-low",
  )
})

test.each([
  ["assignment", "text-event-assignment"],
  ["quiz", "text-event-quiz"],
  ["project", "text-event-project"],
  ["lecture", "text-event-lecture"],
  ["presentation", "text-event-presentation"],
  ["meeting", "text-event-meeting"],
])("uses a stable semantic color for %s events", (eventType, expectedClass) => {
  render(
    <ReviewEventCard
      event={{ ...event, event_type: eventType }}
      onSave={vi.fn()}
      {...defaultProps}
    />,
  )

  expect(screen.getByText(eventType)).toHaveClass(expectedClass)
})

test("modifies the title and date inline without changing review status", async () => {
  const user = userEvent.setup()
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<ReviewEventCard event={event} onSave={onSave} {...defaultProps} />)

  await user.click(screen.getByRole("button", { name: "Modify Final project" }))
  await user.clear(screen.getByLabelText("Event name"))
  await user.type(screen.getByLabelText("Event name"), "Final presentation")
  await user.clear(screen.getByLabelText("Event date"))
  await user.type(screen.getByLabelText("Event date"), "2026-12-12")
  await user.click(screen.getByRole("button", { name: "Save changes" }))

  expect(onSave).toHaveBeenCalledWith("event-1", {
    title: "Final presentation",
    event_type: "project",
    event_date: "2026-12-12",
    start_time: null,
    end_time: null,
    is_all_day: true,
    review_status: "needs_review",
  })
  expect(screen.queryByLabelText("Event name")).not.toBeInTheDocument()
})

test("cancels draft changes and returns focus to Modify", async () => {
  const user = userEvent.setup()
  render(<ReviewEventCard event={event} onSave={vi.fn()} {...defaultProps} />)

  const modifyButton = screen.getByRole("button", { name: "Modify Final project" })
  await user.click(modifyButton)
  await user.clear(screen.getByLabelText("Event name"))
  await user.type(screen.getByLabelText("Event name"), "Wrong draft")
  await user.click(screen.getByRole("button", { name: "Cancel" }))

  expect(modifyButton).toHaveFocus()
  await user.click(modifyButton)
  expect(screen.getByLabelText("Event name")).toHaveValue("Final project")
})

test("keeps advanced fields behind More options", async () => {
  const user = userEvent.setup()
  render(
    <ReviewEventCard
      event={{
        ...event,
        is_all_day: false,
        start_time: "09:00:00",
        end_time: "10:15:00",
      }}
      onSave={vi.fn()}
      {...defaultProps}
    />,
  )

  await user.click(screen.getByRole("button", { name: "Modify Final project" }))
  expect(screen.queryByLabelText("Event type")).not.toBeInTheDocument()
  expect(screen.queryByLabelText("Start time")).not.toBeInTheDocument()
  expect(screen.queryByLabelText("End time")).not.toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "More options" }))
  expect(screen.getByLabelText("Event type")).toHaveValue("project")
  expect(screen.getByLabelText("Start time")).toHaveValue("09:00")
  expect(screen.getByLabelText("End time")).toHaveValue("10:15")
})

test("explains why Terra replaced the Luna extraction", () => {
  render(
    <ReviewEventCard
      event={{
        ...event,
        extraction_model: "gpt-5.6-terra",
        fallback_reason_codes: ["LOW_CONFIDENCE", "SOURCE_MISMATCH"],
      }}
      onSave={vi.fn()}
      {...defaultProps}
    />,
  )

  expect(screen.getByText("Terra repaired Low Confidence and Source Mismatch")).toBeInTheDocument()
})

test("shows a save error next to the review actions", async () => {
  const user = userEvent.setup()
  const onSave = vi.fn().mockRejectedValue(new Error("The event could not be saved."))
  render(<ReviewEventCard event={event} onSave={onSave} {...defaultProps} />)

  await user.click(screen.getByRole("button", { name: "Confirm" }))

  expect(await screen.findByRole("alert")).toHaveTextContent("The event could not be saved.")
})

test("shows a date error and still lets an undated event be saved for later", async () => {
  const user = userEvent.setup()
  const onSave = vi.fn().mockResolvedValue(undefined)
  const undatedEvent = {
    ...event,
    event_date: null,
    warning_codes: ["DATE_MISSING"],
    warning_reason: "The event does not have a confirmed date.",
  }
  render(<ReviewEventCard event={undatedEvent} onSave={onSave} {...defaultProps} />)

  await user.click(screen.getByRole("button", { name: "Confirm" }))
  const dateField = screen.getByLabelText("Event date")
  expect(dateField).toHaveValue("")
  expect(await screen.findByRole("alert")).toHaveTextContent("Add a date before confirming this event.")
  expect(dateField.closest('[data-review-field="event-date"]')).toHaveTextContent(
    "Add a date before confirming this event.",
  )
  expect(dateField).toHaveAttribute("aria-describedby", expect.stringContaining("review-error"))
  expect(screen.getAllByText("Add a date before confirming this event.")).toHaveLength(1)

  await user.click(screen.getByRole("button", { name: "Keep pending" }))

  expect(onSave).toHaveBeenCalledWith("event-1", {
    title: "Final project",
    event_type: "project",
    event_date: null,
    start_time: null,
    end_time: null,
    is_all_day: true,
    review_status: "pending",
  })
})

test("edits event type and times, then saves the full payload", async () => {
  const user = userEvent.setup()
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(
    <ReviewEventCard
      event={{
        ...event,
        event_type: "exam",
        is_all_day: false,
        start_time: "09:00:00",
        end_time: "10:15:00",
      }}
      onSave={onSave}
      {...defaultProps}
    />,
  )

  await user.click(screen.getByRole("button", { name: "Modify Final project" }))
  await user.click(screen.getByRole("button", { name: "More options" }))
  await user.clear(screen.getByLabelText("Event type"))
  await user.type(screen.getByLabelText("Event type"), "presentation")
  await user.clear(screen.getByLabelText("Start time"))
  await user.type(screen.getByLabelText("Start time"), "13:30")
  await user.clear(screen.getByLabelText("End time"))
  await user.type(screen.getByLabelText("End time"), "14:45")
  await user.click(screen.getByRole("button", { name: "Keep pending" }))

  expect(onSave).toHaveBeenCalledWith("event-1", {
    title: "Final project",
    event_type: "presentation",
    event_date: "2026-12-10",
    start_time: "13:30:00",
    end_time: "14:45:00",
    is_all_day: false,
    review_status: "pending",
  })
})

test("toggling all-day clears times and removes them from remove payload", async () => {
  const user = userEvent.setup()
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(
    <ReviewEventCard
      event={{
        ...event,
        is_all_day: false,
        start_time: "11:00:00",
        end_time: "12:30:00",
      }}
      onSave={onSave}
      {...defaultProps}
    />,
  )

  await user.click(screen.getByRole("button", { name: "Modify Final project" }))
  await user.click(screen.getByRole("button", { name: "More options" }))
  expect(screen.getByLabelText("Start time")).toBeEnabled()
  expect(screen.getByLabelText("End time")).toBeEnabled()

  await user.click(screen.getByLabelText("All day event"))

  expect(screen.getByLabelText("All day event")).toBeChecked()
  expect(screen.queryByLabelText("Start time")).not.toBeInTheDocument()
  expect(screen.queryByLabelText("End time")).not.toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "Remove" }))

  expect(onSave).toHaveBeenCalledWith("event-1", {
    title: "Final project",
    event_type: "project",
    event_date: "2026-12-10",
    start_time: null,
    end_time: null,
    is_all_day: true,
    review_status: "ignored",
  })
})

test("shows fallback attention copy when a review warning has no reason text", () => {
  render(
    <ReviewEventCard
      event={{
        ...event,
        event_date: "2026-12-10",
        warning_reason: null,
      }}
      onSave={vi.fn()}
      {...defaultProps}
    />,
  )

  expect(screen.getByText("Needs attention")).toBeInTheDocument()
  expect(
    screen.getByText("Review this AI extracted event before continuing"),
  ).toBeInTheDocument()
})

test("maps a missing date warning to the date field accessibility description", async () => {
  const user = userEvent.setup()
  render(
    <ReviewEventCard
      event={{
        ...event,
        event_date: null,
        warning_codes: ["DATE_MISSING"],
        warning_reason: null,
      }}
      onSave={vi.fn()}
      {...defaultProps}
    />,
  )

  await user.click(screen.getByRole("button", { name: "Modify Final project" }))
  const dateField = screen.getByLabelText("Event date")
  const describedBy = dateField.getAttribute("aria-describedby")

  expect(describedBy).toBeTruthy()
  expect(describedBy).toContain("review-warning")
})

test("maps a source mismatch warning to the source evidence description", () => {
  render(
    <ReviewEventCard
      event={{
        ...event,
        warning_codes: ["SOURCE_MISMATCH"],
        warning_reason: "The quote does not match the source page.",
      }}
      onSave={vi.fn()}
      {...defaultProps}
    />,
  )

  const sourceHeading = screen.getByText("Syllabus says")
  const evidencePanel = sourceHeading.closest("div")?.parentElement

  expect(evidencePanel).toHaveAttribute("aria-describedby")
  expect(evidencePanel?.getAttribute("aria-describedby")).toContain("review-warning")
})

test("keeps a backend date validation error next to the event date field without duplicating it", async () => {
  const user = userEvent.setup()
  const onSave = vi.fn().mockRejectedValue(new Error("Add a date before confirming this event."))
  render(
    <ReviewEventCard
      event={{
        ...event,
        event_date: "2026-12-10",
      }}
      onSave={onSave}
      {...defaultProps}
    />,
  )

  await user.click(screen.getByRole("button", { name: "Modify Final project" }))
  const dateField = screen.getByLabelText("Event date")
  await user.clear(dateField)
  await user.click(screen.getByRole("button", { name: "Confirm" }))

  expect(await screen.findByRole("alert")).toHaveTextContent("Add a date before confirming this event.")
  expect(dateField.closest('[data-review-field="event-date"]')).toHaveTextContent(
    "Add a date before confirming this event.",
  )
  expect(dateField).toHaveAttribute("aria-describedby", expect.stringContaining("review-error"))
  expect(screen.getAllByText("Add a date before confirming this event.")).toHaveLength(1)
})
