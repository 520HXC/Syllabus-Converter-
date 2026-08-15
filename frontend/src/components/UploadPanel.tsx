import { useRef, useState, type ChangeEvent, type DragEvent } from "react"
import { FileText, Trash2, UploadCloud } from "lucide-react"

import { cn } from "../lib/utils"
import { formatBytes } from "../lib/utils"
import { Button } from "./ui/Button"
import { Card } from "./ui/Card"

const MAX_FILES = 10
const MAX_BYTES = 20 * 1024 * 1024

function validate(files: File[]) {
  if (files.length > MAX_FILES) return "Upload at most 10 PDF files at a time."
  if (
    files.some((file) => file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf"))
  ) {
    return "Only PDF syllabus files are supported."
  }
  if (files.some((file) => file.size > MAX_BYTES)) return "Each PDF must be 20 MB or smaller."
  return null
}

export function UploadPanel({ onUpload }: { onUpload: (files: File[]) => Promise<void> }) {
  const [files, setFiles] = useState<File[]>([])
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  function selectFiles(selected: File[]) {
    const validationError = validate(selected)
    setError(validationError)
    setFiles(validationError ? [] : selected)
    if (inputRef.current && validationError) inputRef.current.value = ""
  }

  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    if (uploading) return
    selectFiles(Array.from(event.target.files ?? []))
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    if (uploading) return
    selectFiles(Array.from(event.dataTransfer.files))
  }

  async function submit() {
    if (!files.length) return
    setUploading(true)
    setError(null)
    try {
      await onUpload(files)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The upload could not be started.")
    } finally {
      setUploading(false)
    }
  }

  const buttonLabel = files.length
    ? `Process ${files.length} ${files.length === 1 ? "syllabus" : "syllabi"}`
    : "Process syllabi"
  const fileSummaryLabel = `${files.length} ${files.length === 1 ? "file" : "files"} selected`
  const totalBytes = files.reduce((sum, file) => sum + file.size, 0)

  return (
    <div className="grid gap-4">
      <div
        aria-disabled={uploading}
        className={cn(
          "flex min-h-56 flex-col items-center justify-center rounded-[1.75rem] border-2 border-dashed border-border bg-panel px-5 py-8 text-center transition-colors duration-150 aria-disabled:cursor-not-allowed aria-disabled:bg-panel-muted/60 aria-disabled:opacity-70",
          dragging ? "border-accent bg-accent/5" : "hover:border-accent",
        )}
        onDragEnter={(event) => {
          event.preventDefault()
          if (!uploading) setDragging(true)
        }}
        onDragLeave={(event) => {
          event.preventDefault()
          if (event.currentTarget.contains(event.relatedTarget as Node | null)) return
          setDragging(false)
        }}
        onDragOver={(event) => event.preventDefault()}
        onDrop={handleDrop}
      >
        <div className="rounded-2xl bg-accent/10 p-3 text-accent">
          <UploadCloud aria-hidden="true" className="size-7" />
        </div>
        <p className="mt-4 font-semibold text-text">Drop your syllabus PDFs here</p>
        <p className="mt-1 max-w-md text-sm leading-6 text-text-muted">
          Each file becomes its own processing job, so one scan issue does not block the rest of the batch.
        </p>
        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
          {["PDF only", "10 PDFs max", "20 MB each"].map((item) => (
            <span
              key={item}
              className="inline-flex min-h-8 items-center rounded-full border border-border bg-panel-muted/45 px-3 text-xs font-semibold text-text-muted"
            >
              {item}
            </span>
          ))}
        </div>
        <label
          aria-disabled={uploading}
          className="mt-5 inline-flex min-h-11 cursor-pointer items-center rounded-xl border border-border bg-panel px-4 py-2.5 text-sm font-semibold text-text transition-colors hover:border-accent hover:text-accent focus-within:ring-2 focus-within:ring-focus focus-within:ring-offset-2 focus-within:ring-offset-bg-app aria-disabled:cursor-not-allowed aria-disabled:bg-panel-muted aria-disabled:text-text-subtle"
        >
          Choose files
          <input
            ref={inputRef}
            aria-label="Choose syllabus PDFs"
            accept="application/pdf,.pdf"
            className="sr-only"
            disabled={uploading}
            multiple
            onChange={handleChange}
            type="file"
          />
        </label>
      </div>

      {error ? (
        <div role="alert" className="rounded-2xl border border-danger/20 bg-danger-soft p-3 text-sm font-medium text-danger">
          {error}
        </div>
      ) : null}

      {files.length ? (
        <Card className="overflow-hidden border-border/80 bg-panel/95">
          <div className="flex flex-col gap-1 border-b border-border/80 px-4 py-4 sm:flex-row sm:items-end sm:justify-between sm:px-5">
            <div>
              <p className="text-sm font-semibold text-text">{fileSummaryLabel}</p>
              <p className="mt-1 text-sm text-text-muted">{formatBytes(totalBytes)} total</p>
            </div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-text-subtle">Ready to process</p>
          </div>
          <div className="divide-y divide-border/70 px-4 sm:px-5">
            {files.map((file) => (
              <div key={`${file.name}-${file.size}`} className="flex items-center gap-3 py-3">
                <div className="grid size-11 shrink-0 place-items-center rounded-2xl bg-accent/10 text-accent">
                  <FileText aria-hidden="true" className="size-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-text">{file.name}</p>
                  <p className="text-xs text-text-muted">{formatBytes(file.size)}</p>
                </div>
                <button
                  aria-label={`Remove ${file.name}`}
                  className="grid size-11 cursor-pointer place-items-center rounded-xl text-text-subtle transition-colors hover:bg-panel-muted hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={uploading}
                  onClick={() => {
                    if (inputRef.current) inputRef.current.value = ""
                    setFiles((current) => current.filter((item) => item !== file))
                  }}
                  type="button"
                >
                  <Trash2 aria-hidden="true" className="size-4" />
                </button>
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      <Button className="w-full sm:w-auto sm:justify-self-end" disabled={!files.length} loading={uploading} onClick={submit}>
        {buttonLabel}
      </Button>
    </div>
  )
}
