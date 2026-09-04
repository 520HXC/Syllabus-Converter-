import { Monitor, Moon, Sun } from "lucide-react"

import { cn } from "../lib/utils"
import { useTheme } from "../theme/ThemeProvider"
import type { ThemePreference } from "../theme/theme"

const themeOptions: Array<{
  label: string
  shortLabel: string
  value: ThemePreference
  icon: typeof Sun
}> = [
  { label: "Light theme", shortLabel: "Light", value: "light", icon: Sun },
  { label: "Dark theme", shortLabel: "Dark", value: "dark", icon: Moon },
  { label: "System theme", shortLabel: "System", value: "system", icon: Monitor },
]

export function ThemeSelector({ compact = false }: { compact?: boolean }) {
  const { theme, setTheme } = useTheme()

  return (
    <div
      aria-label="Color theme"
      className={cn(
        "inline-flex w-full min-w-0 items-center gap-1 rounded-2xl border border-border/80 bg-panel-muted/80 p-1 shadow-sm backdrop-blur",
        compact && "rounded-xl",
      )}
      role="group"
    >
      {themeOptions.map(({ icon: Icon, label, shortLabel, value }) => {
        const active = theme === value
        return (
          <button
            aria-label={label}
            aria-pressed={active}
            className={cn(
              "inline-flex min-h-11 min-w-0 flex-auto items-center justify-center gap-1 rounded-xl px-1.5 text-sm font-semibold transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-bg-app",
              active
                ? "bg-panel text-text shadow-sm"
                : "text-text-muted hover:bg-panel/70 hover:text-text",
              compact && "px-2.5",
            )}
            key={value}
            onClick={() => setTheme(value)}
            type="button"
          >
            <Icon aria-hidden="true" className="size-4 shrink-0" />
            <span className={compact ? "sr-only" : "hidden shrink-0 whitespace-nowrap sm:inline"}>{shortLabel}</span>
          </button>
        )
      })}
    </div>
  )
}
