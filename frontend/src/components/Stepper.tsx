import { Check } from "lucide-react"

import { cn } from "../lib/utils"

const steps = ["Semester", "Upload", "Review", "Calendar"]

export function Stepper({ currentStep }: { currentStep: number }) {
  return (
    <nav aria-label="Setup progress" className="w-full">
      <p className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-text-subtle">
        Step {currentStep} of {steps.length}
      </p>
      <ol className="grid grid-cols-4 gap-2">
        {steps.map((step, index) => {
          const stepNumber = index + 1
          const complete = stepNumber < currentStep
          const active = stepNumber === currentStep
          return (
            <li key={step} className="min-w-0">
              <div
                className={cn(
                  "mb-2 h-1.5 rounded-full bg-border",
                  stepNumber <= currentStep && "bg-accent",
                )}
              />
              <span
                aria-current={active ? "step" : undefined}
                className={cn(
                  "flex items-center gap-1 truncate text-xs font-medium text-text-subtle sm:text-sm",
                  active && "text-accent",
                  complete && "text-text",
                )}
              >
                {complete ? <Check aria-hidden="true" className="size-3.5 shrink-0" /> : null}
                {step}
              </span>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
