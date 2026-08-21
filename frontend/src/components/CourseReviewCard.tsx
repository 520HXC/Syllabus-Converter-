import { useEffect, useState } from "react"
import { BookOpen, Save } from "lucide-react"

import type { Course, CourseUpdatePayload } from "../lib/types"
import { Button } from "./ui/Button"
import { Card } from "./ui/Card"
import { Input } from "./ui/Input"

export function CourseReviewCard({
  course,
  courseDisplayColor,
  onSave,
}: {
  course: Course
  courseDisplayColor?: string
  onSave: (courseId: string, values: CourseUpdatePayload) => Promise<void>
}) {
  const [code, setCode] = useState(course.code ?? "")
  const [name, setName] = useState(course.name)
  const [instructor, setInstructor] = useState(course.instructor ?? "")
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setCode(course.code ?? "")
    setName(course.name)
    setInstructor(course.instructor ?? "")
  }, [course])

  async function save() {
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      await onSave(course.id, { code: code || null, name, instructor: instructor || null })
      setSaved(true)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The course could not be saved.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card className="border-border/80 bg-panel/95 p-4 shadow-panel sm:p-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-center gap-3">
          <span
            className="grid size-10 place-items-center rounded-2xl text-accent-contrast shadow-sm"
            style={{ backgroundColor: courseDisplayColor ?? course.color }}
          >
            <BookOpen aria-hidden="true" className="size-4" />
          </span>
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.16em] text-text-subtle">Course details</p>
            <p className="mt-1 text-sm text-text-muted">Clean up the label students will see in review and calendar views.</p>
          </div>
        </div>
        {saved ? (
          <span className="inline-flex min-h-11 items-center rounded-full border border-accent/15 bg-accent/10 px-3 text-sm font-semibold text-accent">
            Saved
          </span>
        ) : null}
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-[10rem_minmax(0,1fr)]">
        <label className="grid gap-1.5 text-sm font-semibold text-text">
          Course code
          <Input aria-label="Course code" value={code} onChange={(event) => setCode(event.target.value)} />
        </label>
        <label className="grid gap-1.5 text-sm font-semibold text-text">
          Course name
          <Input aria-label="Course name" value={name} onChange={(event) => setName(event.target.value)} />
        </label>
      </div>

      <label className="mt-4 grid gap-1.5 text-sm font-semibold text-text">
        Instructor
        <Input aria-label="Instructor" value={instructor} onChange={(event) => setInstructor(event.target.value)} />
      </label>

      <div className="mt-4 flex flex-col gap-3 border-t border-border/80 pt-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-text-muted">These edits also flow into the grouped review sections and calendar filters.</p>
        <Button disabled={!name.trim()} loading={saving} onClick={save} type="button" variant="secondary">
          <Save aria-hidden="true" className="size-4" />
          Save course
        </Button>
      </div>
      {error ? <p className="mt-3 text-sm font-medium text-danger" role="alert">{error}</p> : null}
    </Card>
  )
}
