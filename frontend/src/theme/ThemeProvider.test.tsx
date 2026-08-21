import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

import { ThemeProvider, useTheme } from "./ThemeProvider"

type MatchMediaController = {
  setMatches: (nextMatches: boolean) => void
}

function ThemeProbe() {
  const { theme, resolvedTheme, setTheme } = useTheme()

  return (
    <div>
      <output aria-label="theme">{theme}</output>
      <output aria-label="resolved-theme">{resolvedTheme}</output>
      <button onClick={() => setTheme("dark")} type="button">
        Dark
      </button>
      <button onClick={() => setTheme("system")} type="button">
        System
      </button>
    </div>
  )
}

function installMatchMedia(initialMatches: boolean): MatchMediaController {
  let matches = initialMatches
  const listeners = new Set<(event: MediaQueryListEvent) => void>()

  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      media: query,
      matches,
      onchange: null,
      addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
        listeners.add(listener)
      },
      removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
        listeners.delete(listener)
      },
      addListener: (listener: (event: MediaQueryListEvent) => void) => {
        listeners.add(listener)
      },
      removeListener: (listener: (event: MediaQueryListEvent) => void) => {
        listeners.delete(listener)
      },
      dispatchEvent: () => true,
    })),
  })

  return {
    setMatches(nextMatches) {
      matches = nextMatches
      const event = { matches: nextMatches, media: "(prefers-color-scheme: dark)" } as MediaQueryListEvent
      for (const listener of listeners) listener(event)
    },
  }
}

beforeEach(() => {
  localStorage.clear()
  document.documentElement.className = ""
  document.documentElement.removeAttribute("data-theme")
  document.documentElement.style.colorScheme = ""
  document.head.innerHTML = '<meta name="theme-color" content="#f4f7fb" />'
})

afterEach(() => {
  vi.restoreAllMocks()
})

test("defaults to dark when no theme preference has been stored", async () => {
  installMatchMedia(false)

  render(
    <ThemeProvider>
      <ThemeProbe />
    </ThemeProvider>,
  )

  expect(screen.getByLabelText("theme")).toHaveTextContent("dark")
  expect(screen.getByLabelText("resolved-theme")).toHaveTextContent("dark")
  expect(document.documentElement).toHaveClass("dark")
  expect(document.documentElement).toHaveAttribute("data-theme", "dark")
  expect(document.documentElement.style.colorScheme).toBe("dark")
  await waitFor(() => {
    expect(localStorage.getItem("syllabus-calendar-theme")).toBe("dark")
  })
})

test("persists an explicit theme choice and applies the dark class to the document", async () => {
  installMatchMedia(false)
  const user = userEvent.setup()

  render(
    <ThemeProvider>
      <ThemeProbe />
    </ThemeProvider>,
  )

  await user.click(screen.getByRole("button", { name: "Dark" }))

  expect(screen.getByLabelText("theme")).toHaveTextContent("dark")
  expect(screen.getByLabelText("resolved-theme")).toHaveTextContent("dark")
  expect(localStorage.getItem("syllabus-calendar-theme")).toBe("dark")
  expect(document.documentElement).toHaveClass("dark")
  expect(document.documentElement).toHaveAttribute("data-theme", "dark")
  expect(document.documentElement.style.colorScheme).toBe("dark")
  expect(document.querySelector('meta[name="theme-color"]')).toHaveAttribute("content", "#0a0a0a")
})

test("keeps the system preference live when the user selects system theme", async () => {
  const media = installMatchMedia(false)
  const user = userEvent.setup()

  render(
    <ThemeProvider>
      <ThemeProbe />
    </ThemeProvider>,
  )

  await user.click(screen.getByRole("button", { name: "System" }))

  expect(screen.getByLabelText("theme")).toHaveTextContent("system")
  expect(screen.getByLabelText("resolved-theme")).toHaveTextContent("light")
  expect(document.documentElement).not.toHaveClass("dark")

  await act(async () => {
    media.setMatches(true)
  })

  await waitFor(() => {
    expect(screen.getByLabelText("resolved-theme")).toHaveTextContent("dark")
  })
  expect(document.documentElement).toHaveClass("dark")
  expect(document.documentElement).toHaveAttribute("data-theme", "system")
  expect(document.documentElement.style.colorScheme).toBe("dark")
  expect(document.querySelector('meta[name="theme-color"]')).toHaveAttribute("content", "#0a0a0a")
})

test("keeps the UI theme in sync even when localStorage writes fail", async () => {
  installMatchMedia(false)
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("storage unavailable")
  })
  const user = userEvent.setup()

  render(
    <ThemeProvider>
      <ThemeProbe />
    </ThemeProvider>,
  )

  await user.click(screen.getByRole("button", { name: "Dark" }))

  expect(screen.getByLabelText("theme")).toHaveTextContent("dark")
  expect(screen.getByLabelText("resolved-theme")).toHaveTextContent("dark")
  expect(document.documentElement).toHaveClass("dark")
  expect(document.documentElement).toHaveAttribute("data-theme", "dark")
  expect(document.documentElement.style.colorScheme).toBe("dark")
})
