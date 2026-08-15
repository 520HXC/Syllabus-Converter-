import { forwardRef, type InputHTMLAttributes } from "react"

import { cn } from "../../lib/utils"

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "min-h-11 w-full rounded-xl border border-border bg-panel px-3.5 py-2.5 text-base text-text outline-none transition-colors placeholder:text-text-subtle focus:border-accent focus:ring-2 focus:ring-focus/15 disabled:cursor-not-allowed disabled:bg-panel-muted sm:text-sm",
        className,
      )}
      {...props}
    />
  ),
)

Input.displayName = "Input"
