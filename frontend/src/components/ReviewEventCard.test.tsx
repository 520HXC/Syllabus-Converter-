import { render, screen, waitFor } from "@testing-library/react"
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

function createDeferredPromise() {
  let resolve!: () => void
  const promise = new Promise<void>((nextResolve) => {
    resolve = nextResolve
  })

  return { promise, resolve }
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
  ["class", "text-event-class"],
  ["deadline", "text-event-deadline"],
  ["quiz", "text-event-quiz"],
  ["project", "text-event-project"],
  ["reading", "text-event-reading"],
  ["lecture", "text-event-lecture"],
  ["presentation", "text-event-presentation"],
  ["meeting", "text-event-meeting"],
  ["other", "text-event-other"],
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

test("shows a neutral fallback for an unknown event type label", () => {
  render(
    <ReviewEventCard
      event={{ ...event, event_type: "capstone" }}
      onSave={vi.fn()}
      {...defaultProps}
    />,
  )

  expect(screen.getByText("unknown")).toHaveClass("border-border", "bg-panel-muted/70", "text-text-muted")
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

  await waitFor(() => expect(modifyButton).toHaveFocus())
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
  const suggestionValues = Array.from(
    document.querySelectorAll<HTMLOptionElement>("#review-event-type-options option"),
  ).map((option) => option.value)
  expect(suggestionValues).toContain("class")
  expect(suggestionValues).toContain("deadline")
  expect(suggestionValues).toContain("reading")
  expect(suggestionValues).toContain("other")
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

test("shows a compact syllabus typo note and hides legacy Terra repair details", () => {
  render(
    <ReviewEventCard
      event={{
        ...event,
        event_type: "class",
        title: "No Lecture / Friday schedule",
        event_date: "2025-11-27",
        warning_codes: ["DATE_CONFLICT"],
        warning_reason:
          "Syllabus typo. The written date and weekday do not match. The numeric date was kept.",
        extraction_model: "gpt-5.6-terra",
        fallback_reason_codes: ["DATE_CONFLICT"],
        derivation_summary: "Legacy explanation that should stay hidden.",
      }}
      onSave={vi.fn()}
      {...defaultProps}
    />,
  )

  expect(screen.getByText("Syllabus typo")).toBeInTheDocument()
  expect(
    screen.getByText(
      "Syllabus typo. The written date and weekday do not match. The numeric date was kept.",
    ),
  ).toBeInTheDocument()
  expect(screen.queryByText("Needs attention")).not.toBeInTheDocument()
  expect(screen.queryByText("Terra repaired Date Conflict")).not.toBeInTheDocument()
  expect(screen.queryByText("Calculated date")).not.toBeInTheDocument()
  expect(screen.queryByText("Legacy explanation that should stay hidden.")).not.toBeInTheDocument()
  expect(screen.getByText("Syllabus says").closest("div")?.parentElement).toHaveAttribute(
    "aria-describedby",
    expect.stringMatching(/^:?.+/),
  )
  expect(screen.getByText("AI date").closest("div")).not.toHaveAttribute("aria-describedby")
  expect(screen.getByText("AI date").closest("div")).not.toHaveAttribute("data-focus-target")
  expect(screen.getByText("November 27, 2025")).not.toHaveClass("text-warning")
  expect(screen.getByText("AI date").closest("div")).not.toHaveAttribute("tabindex")
})

test("shows a save error next to the review actions", async () => {
  const user = userEvent.setup()
  const onSave = vi.fn().mockRejectedValue(new Error("The event could not be saved."))
  render(<ReviewEventCard event={event} onSave={onSave} {...defaultProps} />)

  await user.click(screen.getByRole("button", { name: "Confirm" }))

  expect(await screen.findByRole("alert")).toHaveTextContent("The event could not be saved.")
})

test("lets an undated event be saved for later from the closed state", async () => {
  const user = userEvent.setup()
  const onSave = vi.fn().mockResolvedValue(undefined)
  const undatedEvent = {
    ...event,
    event_date: null,
    warning_codes: ["DATE_MISSING"],
    warning_reason: "The event does not have a confirmed date.",
  }
  render(<ReviewEventCard event={undatedEvent} onSave={onSave} {...defaultProps} />)

  expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "Save for later" }))

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

test("shows Save for later in the editor for undated needs review events and closes after saving", async () => {
  const user = userEvent.setup()
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(
    <ReviewEventCard
      event={{
        ...event,
        event_date: null,
        warning_codes: ["DATE_MISSING"],
        warning_reason: "The event does not have a confirmed date.",
      }}
      onSave={onSave}
      startEditing
      {...defaultProps}
    />,
  )

  const saveForLaterButton = await screen.findByRole("button", { name: "Save for later" })
  expect(saveForLaterButton).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Save and confirm" })).not.toBeInTheDocument()

  await user.clear(screen.getByLabelText("Event name"))
  await user.type(screen.getByLabelText("Event name"), "Final project follow-up")
  await user.click(saveForLaterButton)

  expect(onSave).toHaveBeenCalledWith("event-1", {
    title: "Final project follow-up",
    event_type: "project",
    event_date: null,
    start_time: null,
    end_time: null,
    is_all_day: true,
    review_status: "pending",
  })
  expect(screen.queryByLabelText("Event name")).not.toBeInTheDocument()
})

test("disables Save for later and shows loading copy while the editor save is pending", async () => {
  const user = userEvent.setup()
  const saveRequest = createDeferredPromise()
  const onSave = vi.fn().mockReturnValue(saveRequest.promise)
  render(
    <ReviewEventCard
      event={{
        ...event,
        event_date: null,
        warning_codes: ["DATE_MISSING"],
        warning_reason: "The event does not have a confirmed date.",
      }}
      onSave={onSave}
      startEditing
      {...defaultProps}
    />,
  )

  await user.click(await screen.findByRole("button", { name: "Save for later" }))

  const loadingButton = screen.getByRole("button", { name: "Save for later" })
  expect(loadingButton).toBeDisabled()
  expect(loadingButton).toHaveTextContent("Saving for later...")

  saveRequest.resolve()

  await waitFor(() => expect(screen.queryByLabelText("Event name")).not.toBeInTheDocument())
})

test("keeps undated drafts visible when Save for later fails", async () => {
  const user = userEvent.setup()
  const onSave = vi.fn().mockRejectedValue(new Error("Could not save for later. Try again."))
  render(
    <ReviewEventCard
      event={{
        ...event,
        event_date: null,
        warning_codes: ["DATE_MISSING"],
        warning_reason: "The event does not have a confirmed date.",
      }}
      onSave={onSave}
      startEditing
      {...defaultProps}
    />,
  )

  await user.clear(screen.getByLabelText("Event name"))
  await user.type(screen.getByLabelText("Event name"), "Draft that should stay")
  await user.click(await screen.findByRole("button", { name: "Save for later" }))

  expect(await screen.findByRole("alert")).toHaveTextContent("Could not save for later. Try again.")
  expect(screen.getByLabelText("Event name")).toHaveValue("Draft that should stay")
  expect(screen.getByRole("button", { name: "Save for later" })).toBeInTheDocument()
})

test("shows saved for later state for pending undated events and confirms after a date is added", async () => {
  const user = userEvent.setup()
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(
    <ReviewEventCard
      event={{
        ...event,
        event_date: null,
        warning_codes: ["DATE_MISSING"],
        warning_reason: "The event does not have a confirmed date.",
        review_status: "pending",
      }}
      onSave={onSave}
      {...defaultProps}
    />,
  )

  expect(screen.getByText("Pending date")).toBeInTheDocument()
  expect(screen.getByText("Saved for later")).toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "Add date" }))
  await user.type(screen.getByLabelText("Event date"), "2026-12-12")
  expect(await screen.findByRole("button", { name: "Save and confirm" })).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "Save and confirm" }))

  expect(onSave).toHaveBeenCalledWith("event-1", {
    title: "Final project",
    event_type: "project",
    event_date: "2026-12-12",
    start_time: null,
    end_time: null,
    is_all_day: true,
    review_status: "confirmed",
  })
})

test("disables Save and confirm and shows loading copy while confirmation is pending", async () => {
  const user = userEvent.setup()
  const saveRequest = createDeferredPromise()
  const onSave = vi.fn().mockReturnValue(saveRequest.promise)
  render(
    <ReviewEventCard
      event={{
        ...event,
        event_date: null,
        warning_codes: ["DATE_MISSING"],
        warning_reason: "The event does not have a confirmed date.",
        review_status: "pending",
      }}
      onSave={onSave}
      startEditing
      {...defaultProps}
    />,
  )

  await user.type(screen.getByLabelText("Event date"), "2026-12-12")
  await user.click(screen.getByRole("button", { name: "Save and confirm" }))

  const loadingButton = screen.getByRole("button", { name: "Save and confirm" })
  expect(loadingButton).toBeDisabled()
  expect(loadingButton).toHaveTextContent("Saving and confirming...")

  saveRequest.resolve()

  await waitFor(() => expect(screen.queryByLabelText("Event name")).not.toBeInTheDocument())
})

test("does not show saved for later pending controls for recurring series members", () => {
  render(
    <ReviewEventCard
      event={{
        ...event,
        event_date: null,
        review_status: "pending",
        recurring_series_id: "series-1",
        warning_codes: [],
        warning_reason: null,
      }}
      onSave={vi.fn()}
      {...defaultProps}
    />,
  )

  expect(screen.queryByText("Saved for later")).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Add date" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Save for later" })).not.toBeInTheDocument()
})

test("does not switch recurring series members into the ordinary undated editor flow", async () => {
  const user = userEvent.setup()
  render(
    <ReviewEventCard
      event={{
        ...event,
        event_date: null,
        review_status: "needs_review",
        recurring_series_id: "series-1",
        warning_codes: ["DATE_MISSING"],
        warning_reason: "The recurring instance still needs a date.",
      }}
      onSave={vi.fn()}
      startEditing
      {...defaultProps}
    />,
  )

  expect(screen.getByRole("button", { name: "Save changes" })).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Save for later" })).not.toBeInTheDocument()

  await user.clear(screen.getByLabelText("Event name"))
  await user.type(screen.getByLabelText("Event name"), "Recurring quiz instance")
  expect(screen.getByLabelText("Event name")).toHaveValue("Recurring quiz instance")
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
  await user.click(screen.getByRole("button", { name: "Save for later" }))

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

test("shows a recurring rule badge and fixed copy for ambiguous recurrence warnings", () => {
  render(
    <ReviewEventCard
      event={{
        ...event,
        event_date: null,
        warning_codes: ["AMBIGUOUS_RECURRENCE"],
        warning_reason: "This generic warning should be replaced.",
      }}
      onSave={vi.fn()}
      {...defaultProps}
    />,
  )

  expect(screen.getByText("Recurring rule")).toBeInTheDocument()
  expect(
    screen.getByText("Dates were not generated because the syllabus does not identify every occurrence"),
  ).toBeInTheDocument()
  expect(screen.queryByText("This generic warning should be replaced.")).not.toBeInTheDocument()
})

test("treats ambiguous recurrence as a date-focused review warning", async () => {
  const user = userEvent.setup()
  render(
    <ReviewEventCard
      event={{
        ...event,
        event_date: null,
        warning_codes: ["AMBIGUOUS_RECURRENCE"],
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

test("explains why dates were not generated instead of showing a calculated date title", () => {
  render(
    <ReviewEventCard
      event={{
        ...event,
        event_date: null,
        derivation_summary: "Quick Checks are due the morning of the lecture, but the syllabus does not list every lecture date.",
        warning_codes: ["AMBIGUOUS_RECURRENCE"],
        warning_reason: null,
      }}
      onSave={vi.fn()}
      {...defaultProps}
    />,
  )

  expect(screen.getByText("Why dates were not generated")).toBeInTheDocument()
  expect(screen.queryByText("Calculated date")).not.toBeInTheDocument()
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
