import { readFileSync } from "node:fs"
import { resolve } from "node:path"

import { beforeEach, expect, test, vi } from "vitest"

const indexHtml = readFileSync(resolve(import.meta.dirname, "../../index.html"), "utf8")
const bootstrapScriptMatch = indexHtml.match(/<script>\s*([\s\S]*?)\s*<\/script>/)

if (!bootstrapScriptMatch) {
  throw new Error("The pre-React theme bootstrap script was not found in index.html")
}

const bootstrapScript = bootstrapScriptMatch[1]

function runBootstrap({
  hasMatchMedia = true,
  prefersDark,
  storedTheme,
  throwOnStorageRead = false,
}: {
  hasMatchMedia?: boolean
  prefersDark: boolean
  storedTheme: "dark" | "light" | "system" | null
  throwOnStorageRead?: boolean
}) {
  document.documentElement.className = ""
  document.documentElement.removeAttribute("data-theme")
  document.documentElement.removeAttribute("data-resolved-theme")
  document.documentElement.style.colorScheme = ""
  document.head.innerHTML = '<meta name="theme-color" content="#0A0A0A" />'
  document.body.innerHTML = '<div id="root"></div>'
  localStorage.clear()
  if (storedTheme) localStorage.setItem("syllabus-calendar-theme", storedTheme)

  if (throwOnStorageRead) {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage unavailable")
    })
  }

  if (hasMatchMedia) {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        media: query,
        matches: prefersDark,
      })),
    })
  } else {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: undefined,
    })
  }

  Function(bootstrapScript)()
}

beforeEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

test("applies a stored dark theme before React mounts", () => {
  runBootstrap({ storedTheme: "dark", prefersDark: false })

  expect(document.documentElement).toHaveClass("dark")
  expect(document.documentElement).toHaveAttribute("data-theme", "dark")
  expect(document.documentElement).toHaveAttribute("data-resolved-theme", "dark")
  expect(document.documentElement.style.colorScheme).toBe("dark")
  expect(document.querySelector('meta[name="theme-color"]')).toHaveAttribute("content", "#0a0a0a")
})

test("applies system dark mode before React mounts when the OS is dark", () => {
  runBootstrap({ storedTheme: "system", prefersDark: true })

  expect(document.documentElement).toHaveClass("dark")
  expect(document.documentElement).toHaveAttribute("data-theme", "system")
  expect(document.documentElement).toHaveAttribute("data-resolved-theme", "dark")
  expect(document.documentElement.style.colorScheme).toBe("dark")
  expect(document.querySelector('meta[name="theme-color"]')).toHaveAttribute("content", "#0a0a0a")
})

test("falls back to system light before React mounts when storage read fails and matchMedia is unavailable", () => {
  expect(() =>
    runBootstrap({
      hasMatchMedia: false,
      prefersDark: false,
      storedTheme: null,
      throwOnStorageRead: true,
    }),
  ).not.toThrow()

  expect(document.documentElement).not.toHaveClass("dark")
  expect(document.documentElement).toHaveAttribute("data-theme", "system")
  expect(document.documentElement).toHaveAttribute("data-resolved-theme", "light")
  expect(document.documentElement.style.colorScheme).toBe("light")
  expect(document.querySelector('meta[name="theme-color"]')).toHaveAttribute("content", "#f4f7fb")
})
