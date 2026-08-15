import { AlertCircle, LoaderCircle } from "lucide-react"

import { Button } from "./ui/Button"

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div aria-live="polite" className="flex min-h-48 items-center justify-center gap-3 text-sm font-medium text-text-muted" role="status">
      <LoaderCircle aria-hidden="true" className="size-5 animate-spin text-accent motion-reduce:animate-none" />
      {label}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="rounded-2xl border border-danger/20 bg-danger-soft p-5 text-danger" role="alert">
      <div className="flex gap-3">
        <AlertCircle aria-hidden="true" className="mt-0.5 size-5 shrink-0" />
        <div>
          <p className="font-semibold">Something needs attention</p>
          <p className="mt-1 text-sm">{message}</p>
          {onRetry ? (
            <Button className="mt-4" onClick={onRetry} variant="secondary">
              Try again
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  )
}
