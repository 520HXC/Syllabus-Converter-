import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { UploadPanel } from "./UploadPanel"

test("accepts PDF syllabi and shows the selected files before upload", async () => {
  const user = userEvent.setup()
  render(<UploadPanel onUpload={vi.fn()} />)
  const file = new File(["%PDF-1.7"], "cs101.pdf", { type: "application/pdf" })

  await user.upload(screen.getByLabelText("Choose syllabus PDFs"), file)

  expect(screen.getByText("1 file selected")).toBeInTheDocument()
  expect(screen.getByText("1 KB total")).toBeInTheDocument()
  expect(screen.getByText("cs101.pdf")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Process 1 syllabus" })).toBeEnabled()
})

test("accepts PDFs with an empty MIME type when the filename ends in .pdf", async () => {
  const user = userEvent.setup()
  render(<UploadPanel onUpload={vi.fn()} />)
  const file = new File(["%PDF-1.7"], "scan.PDF", { type: "" })

  await user.upload(screen.getByLabelText("Choose syllabus PDFs"), file)

  expect(screen.queryByText("Only PDF syllabus files are supported.")).not.toBeInTheDocument()
  expect(screen.getByText("scan.PDF")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Process 1 syllabus" })).toBeEnabled()
})

test("rejects files larger than 20 MB before sending them", async () => {
  const user = userEvent.setup()
  render(<UploadPanel onUpload={vi.fn()} />)
  const file = new File([new Uint8Array(20 * 1024 * 1024 + 1)], "too-large.pdf", {
    type: "application/pdf",
  })

  await user.upload(screen.getByLabelText("Choose syllabus PDFs"), file)

  expect(screen.getByText("Each PDF must be 20 MB or smaller.")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Process syllabi" })).toBeDisabled()
})

test("locks file selection and removal while an upload is in progress", async () => {
  const user = userEvent.setup()
  const onUpload = vi.fn(() => new Promise<void>(() => undefined))
  render(<UploadPanel onUpload={onUpload} />)
  const file = new File(["%PDF-1.7"], "cs101.pdf", { type: "application/pdf" })

  await user.upload(screen.getByLabelText("Choose syllabus PDFs"), file)
  await user.click(screen.getByRole("button", { name: "Process 1 syllabus" }))

  expect(screen.getByLabelText("Choose syllabus PDFs")).toBeDisabled()
  expect(screen.getByRole("button", { name: "Remove cs101.pdf" })).toBeDisabled()
})
