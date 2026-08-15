import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { JobCard } from "./JobCard"

test("shows the real processing stage without a made-up percentage", () => {
  render(
    <JobCard
      job={{
        id: "job-1",
        document_id: "doc-1",
        filename: "biology.pdf",
        status: "extracting_events",
        stage_detail: "Extracting course dates",
        error_message: null,
        attempts: 1,
      }}
      onRetry={() => undefined}
    />,
  )

  expect(screen.getByText("Stage 4 of 5")).toBeInTheDocument()
  expect(screen.getByRole("list", { name: "Processing timeline for biology.pdf" })).toBeInTheDocument()
  expect(screen.getAllByText("Extracting events")).toHaveLength(2)
  expect(screen.getByText("Extracting course dates")).toBeInTheDocument()
  expect(screen.queryByText(/%/)).not.toBeInTheDocument()
})

test("offers a working retry action only for failed jobs", async () => {
  const user = userEvent.setup()
  const onRetry = vi.fn()
  render(
    <JobCard
      job={{
        id: "job-2",
        document_id: "doc-2",
        filename: "history.pdf",
        status: "failed",
        stage_detail: "Processing failed",
        error_message: "OCR could not run.",
        attempts: 1,
      }}
      onRetry={onRetry}
    />,
  )

  await user.click(screen.getByRole("button", { name: "Retry history.pdf" }))
  expect(onRetry).toHaveBeenCalledWith("job-2")
})

test("shows the actual model route and offers reprocess for reviewable jobs", async () => {
  const user = userEvent.setup()
  const onReprocess = vi.fn()
  render(
    <JobCard
      job={{
        id: "job-3",
        document_id: "doc-3",
        filename: "calculus.pdf",
        status: "needs_review",
        stage_detail: "Ready for review",
        error_message: null,
        attempts: 1,
        primary_model: "gpt-5.6-luna",
        fallback_model: "gpt-5.6-terra",
        fallback_used: true,
        fallback_reason_codes: ["LOW_CONFIDENCE", "SOURCE_MISMATCH"],
      } as any}
      onRetry={() => undefined}
      onReprocess={onReprocess as any}
    />,
  )

  expect(screen.getByText("Terra rechecked flagged details")).toBeInTheDocument()
  expect(screen.getByText(/Luna processed the PDF first/i)).toBeInTheDocument()
  expect(screen.getByText(/Low confidence/i)).toBeInTheDocument()
  expect(screen.getByText(/Source mismatch/i)).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "Run extraction again for calculus.pdf" }))
  expect(onReprocess).toHaveBeenCalledWith("job-3")
})

test.each(["needs_review", "completed"] as const)(
  "marks every processing stage done when the job is %s",
  (status) => {
    render(
      <JobCard
        job={{
          id: `job-${status}`,
          document_id: "doc-terminal",
          filename: "finished.pdf",
          status,
          stage_detail: status === "completed" ? "Review completed" : "Ready for review",
          error_message: null,
          attempts: 1,
        }}
        onRetry={() => undefined}
      />,
    )

    const timeline = screen.getByRole("list", { name: "Processing timeline for finished.pdf" })
    expect(timeline.querySelectorAll("li")).toHaveLength(5)
    expect(screen.getAllByText("Done")).toHaveLength(5)
    expect(screen.queryByText("Current")).not.toBeInTheDocument()
    expect(screen.getByText("Stage 5 of 5")).toBeInTheDocument()
  },
)
