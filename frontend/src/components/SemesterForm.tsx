import { useId } from "react"
import { zodResolver } from "@hookform/resolvers/zod"
import { CalendarDays } from "lucide-react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { Button } from "./ui/Button"
import { Input } from "./ui/Input"

const semesterSchema = z
  .object({
    name: z.string().trim().min(1, "Enter a semester name."),
    start_date: z.string().min(1, "Choose the first day."),
    end_date: z.string().min(1, "Choose the last day."),
    timezone: z.string().trim().min(1, "Choose a timezone."),
  })
  .superRefine((data, context) => {
    if (data.start_date && data.end_date && data.end_date < data.start_date) {
      context.addIssue({
        code: "custom",
        path: ["end_date"],
        message: "The last day must be on or after the first day.",
      })
    }
  })

export type SemesterFormValues = z.infer<typeof semesterSchema>

export function SemesterForm({
  defaultTimezone,
  onSubmit,
}: {
  defaultTimezone: string
  onSubmit: (values: SemesterFormValues) => Promise<void>
}) {
  const idBase = useId()
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<SemesterFormValues>({
    resolver: zodResolver(semesterSchema),
    defaultValues: { name: "", start_date: "", end_date: "", timezone: defaultTimezone },
  })

  const fieldClass = "grid gap-1.5 text-sm font-semibold text-text"
  const errorClass = "text-sm font-medium text-danger"
  const hintClass = "text-sm font-normal leading-6 text-text-muted"

  return (
    <form className="grid gap-6" onSubmit={handleSubmit((values) => onSubmit(values))} noValidate>
      <div className="rounded-3xl border border-border/80 bg-panel-muted/35 p-4">
        <p className="text-sm font-semibold text-text">Semester basics</p>
        <p className="mt-1 text-sm leading-6 text-text-muted">
          Use the official term name plus the first and last class day from your syllabus.
        </p>
      </div>

      <fieldset className="grid gap-5">
        <legend className="sr-only">Semester basics</legend>
        <div className={fieldClass}>
          <label htmlFor={`${idBase}-name`}>Semester name</label>
          <Input
            aria-describedby="semester-name-hint"
            autoComplete="off"
            id={`${idBase}-name`}
            placeholder="Fall 2026"
            {...register("name")}
          />
          <span className={hintClass} id="semester-name-hint">This shows up in your calendar picker and exports.</span>
          {errors.name ? <span className={errorClass} role="alert">{errors.name.message}</span> : null}
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <div className={fieldClass}>
            <label htmlFor={`${idBase}-start`}>First day</label>
            <Input aria-describedby="semester-start-hint" id={`${idBase}-start`} type="date" {...register("start_date")} />
            <span className={hintClass} id="semester-start-hint">Early dates before this are flagged for review.</span>
            {errors.start_date ? <span className={errorClass} role="alert">{errors.start_date.message}</span> : null}
          </div>
          <div className={fieldClass}>
            <label htmlFor={`${idBase}-end`}>Last day</label>
            <Input aria-describedby="semester-end-hint" id={`${idBase}-end`} type="date" {...register("end_date")} />
            <span className={hintClass} id="semester-end-hint">Late deadlines after this stay visible until you confirm them.</span>
            {errors.end_date ? <span className={errorClass} role="alert">{errors.end_date.message}</span> : null}
          </div>
        </div>
      </fieldset>

      <div className={fieldClass}>
        <label htmlFor={`${idBase}-timezone`}>Timezone</label>
        <Input
          aria-describedby="semester-timezone-hint"
          autoComplete="off"
          id={`${idBase}-timezone`}
          placeholder="America/New_York"
          {...register("timezone")}
        />
        <span className={hintClass} id="semester-timezone-hint">
          Dates will use this timezone in your calendar export.
        </span>
        {errors.timezone ? <span className={errorClass} role="alert">{errors.timezone.message}</span> : null}
      </div>

      <Button className="mt-1 w-full sm:w-auto sm:justify-self-end" loading={isSubmitting} type="submit">
        <CalendarDays aria-hidden="true" className="size-4" />
        Save semester
      </Button>
    </form>
  )
}
