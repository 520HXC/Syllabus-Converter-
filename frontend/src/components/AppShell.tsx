import type { ReactNode } from "react"
import {
  Calendar1,
  CalendarCheck2,
  FileUp,
  Files,
  ListChecks,
  LogOut,
} from "lucide-react"
import { Link, NavLink } from "react-router-dom"

import { useAuth } from "../lib/auth"
import { cn } from "../lib/utils"
import { ThemeSelector } from "./ThemeSelector"
import { Button } from "./ui/Button"
import { Stepper } from "./Stepper"

const navItems = [
  { icon: Calendar1, label: "Calendar", to: "/calendar" },
  { icon: Files, label: "Semesters", to: "/semesters" },
  { icon: ListChecks, label: "Review", to: "/review" },
  { icon: FileUp, label: "Upload", to: "/upload" },
] as const

function ShellNavLink({
  icon: Icon,
  label,
  mobile = false,
  to,
}: {
  icon: typeof Calendar1
  label: string
  mobile?: boolean
  to: string
}) {
  return (
    <NavLink
      className={({ isActive }) =>
        cn(
          "group inline-flex min-h-11 items-center gap-3 rounded-2xl border border-transparent px-3.5 py-3 text-sm font-semibold transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-bg-app",
          mobile
            ? "flex-1 flex-col justify-center gap-1 rounded-xl px-2 py-2.5 text-[0.72rem]"
            : "w-full",
          isActive
            ? "bg-accent text-accent-contrast shadow-sm"
            : "text-text-muted hover:border-border hover:bg-panel hover:text-text",
        )
      }
      to={to}
    >
      <Icon aria-hidden="true" className={cn("size-4 shrink-0", mobile && "size-4.5")} />
      <span>{label}</span>
    </NavLink>
  )
}

export function AppShell({
  children,
  currentStep,
}: {
  children: ReactNode
  currentStep?: number
}) {
  const { user, signOut } = useAuth()

  return (
    <div className="app-shell-theme min-h-dvh bg-bg-app text-text" data-app-shell>
      <aside className="fixed inset-y-0 left-0 hidden w-72 border-r border-border/80 bg-panel/95 px-5 py-6 shadow-[0_18px_48px_rgba(15,23,42,0.08)] backdrop-blur lg:flex lg:flex-col">
        <Link
          className="flex min-h-11 items-center gap-3 rounded-2xl px-2 py-2 text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-panel"
          to="/semesters"
        >
          <span className="grid size-11 place-items-center rounded-2xl bg-accent text-accent-contrast shadow-sm">
            <CalendarCheck2 aria-hidden="true" className="size-5" />
          </span>
          <span>
            <span className="block text-base font-bold tracking-[-0.02em]">Syllabus Calendar</span>
            <span className="block text-sm font-medium text-text-muted">AI learning assistant</span>
          </span>
        </Link>

        <nav aria-label="Primary navigation" className="mt-8 grid gap-2">
          {navItems.map((item) => <ShellNavLink key={item.to} {...item} />)}
        </nav>

        <div className="mt-8 flex-1">
          {currentStep ? (
            <div className="rounded-3xl border border-border/80 bg-panel-muted/70 p-4">
              <Stepper currentStep={currentStep} />
            </div>
          ) : null}
        </div>

        <div className="space-y-3 pt-4">
          <ThemeSelector />
          {user ? (
            <div className="rounded-3xl border border-border/80 bg-panel-muted/85 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-text-subtle">Account</p>
              <p className="mt-2 break-all text-sm font-medium text-text">{user.email}</p>
              <Button
                aria-label="Sign out"
                className="mt-4 w-full"
                onClick={() => signOut()}
                variant="ghost"
              >
                <LogOut aria-hidden="true" className="size-4" />
                <span>Sign out</span>
              </Button>
            </div>
          ) : null}
        </div>
      </aside>

      <div className="lg:pl-72">
        <header className="sticky top-0 z-30 border-b border-border/70 bg-panel/90 backdrop-blur lg:hidden">
          <div className="px-4 py-3 sm:px-6">
            <div className="flex items-center justify-between gap-3">
              <Link
                className="flex min-h-11 min-w-0 flex-1 items-center gap-2.5 rounded-2xl font-bold text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-panel"
                to="/semesters"
              >
                <span className="grid size-10 place-items-center rounded-2xl bg-accent text-accent-contrast shadow-sm">
                  <CalendarCheck2 aria-hidden="true" className="size-5" />
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm tracking-[-0.02em]">Syllabus Calendar</span>
                  <span className="block truncate text-xs font-medium text-text-muted">Study workflow</span>
                </span>
              </Link>
              <div className="flex items-center gap-2">
                <ThemeSelector compact />
                {user ? (
                  <Button aria-label="Sign out" className="px-3" onClick={() => signOut()} variant="ghost">
                    <LogOut aria-hidden="true" className="size-4" />
                  </Button>
                ) : null}
              </div>
            </div>
            {user ? <p className="mt-2 text-sm text-text-muted">{user.email}</p> : null}
          </div>
        </header>

        <main className="mx-auto w-full max-w-7xl px-4 py-6 pb-28 sm:px-6 sm:py-8 sm:pb-32 lg:px-8 lg:pb-10">
          {currentStep ? (
            <div className="mb-7 rounded-3xl border border-border/80 bg-panel/80 p-4 shadow-sm lg:hidden">
              <Stepper currentStep={currentStep} />
            </div>
          ) : null}
          {children}
        </main>

        <nav
          aria-label="Mobile navigation"
          className="fixed inset-x-0 bottom-0 z-30 border-t border-border/80 bg-panel/[0.96] px-3 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] pt-3 shadow-[0_-10px_30px_rgba(15,23,42,0.08)] backdrop-blur lg:hidden"
        >
          <div className="mx-auto flex max-w-2xl gap-2">
            {navItems.map((item) => <ShellNavLink key={item.to} mobile {...item} />)}
          </div>
        </nav>
      </div>
    </div>
  )
}
