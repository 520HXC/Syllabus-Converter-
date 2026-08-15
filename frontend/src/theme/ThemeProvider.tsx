import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react"

import {
  applyThemePreference,
  getSystemThemeMatcher,
  readStoredTheme,
  resolveTheme,
  themeStorageKey,
  type ResolvedTheme,
  type ThemePreference,
} from "./theme"

type ThemeContextValue = {
  theme: ThemePreference
  resolvedTheme: ResolvedTheme
  setTheme: (theme: ThemePreference) => void
}

const defaultThemeContext: ThemeContextValue = {
  theme: "system",
  resolvedTheme: "light",
  setTheme: () => undefined,
}

const ThemeContext = createContext<ThemeContextValue>(defaultThemeContext)

type LegacyMediaQueryList = MediaQueryList & {
  addListener: (listener: (event: MediaQueryListEvent) => void) => void
  removeListener: (listener: (event: MediaQueryListEvent) => void) => void
}

function getInitialSystemPreference() {
  return getSystemThemeMatcher()?.matches ?? false
}

function syncMetaThemeColor(resolvedTheme: ResolvedTheme) {
  const metaThemeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
  if (!metaThemeColor) return
  metaThemeColor.content = resolvedTheme === "dark" ? "#0a0a0a" : "#f4f7fb"
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<ThemePreference>(() =>
    typeof window === "undefined" ? "system" : readStoredTheme(window.localStorage),
  )
  const [prefersDark, setPrefersDark] = useState(getInitialSystemPreference)

  useEffect(() => {
    const matcher = getSystemThemeMatcher()
    if (!matcher) return

    const handleChange = (event: MediaQueryListEvent) => {
      setPrefersDark(event.matches)
    }

    setPrefersDark(matcher.matches)
    if (typeof matcher.addEventListener === "function") {
      matcher.addEventListener("change", handleChange)
    } else {
      ;(matcher as LegacyMediaQueryList).addListener(handleChange)
    }

    return () => {
      if (typeof matcher.removeEventListener === "function") {
        matcher.removeEventListener("change", handleChange)
      } else {
        ;(matcher as LegacyMediaQueryList).removeListener(handleChange)
      }
    }
  }, [])

  useEffect(() => {
    const resolvedTheme = applyThemePreference(document.documentElement, theme, prefersDark)
    syncMetaThemeColor(resolvedTheme)
    try {
      window.localStorage.setItem(themeStorageKey, theme)
    } catch {
      return
    }
  }, [prefersDark, theme])

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme,
      resolvedTheme: resolveTheme(theme, prefersDark),
      setTheme,
    }),
    [prefersDark, theme],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  return useContext(ThemeContext)
}
