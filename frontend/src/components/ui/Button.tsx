import { forwardRef, type ButtonHTMLAttributes } from "react"
import { LoaderCircle } from "lucide-react"

import { cn } from "../../lib/utils"

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger"

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  loading?: boolean
}

const variants: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-accent-contrast hover:bg-accent-strong focus-visible:ring-focus disabled:bg-panel-muted disabled:text-text-subtle",
  secondary:
    "border border-border bg-panel text-text hover:border-accent hover:text-accent focus-visible:ring-focus",
  ghost: "text-text-muted hover:bg-panel-muted hover:text-text focus-visible:ring-focus",
  danger:
    "border border-danger/20 bg-panel text-danger hover:bg-danger-soft focus-visible:ring-danger",
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", loading = false, disabled, children, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-bg-app disabled:cursor-not-allowed disabled:opacity-70",
        variants[variant],
        className,
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin motion-reduce:animate-none" /> : null}
      {children}
    </button>
  ),
)

Button.displayName = "Button"
