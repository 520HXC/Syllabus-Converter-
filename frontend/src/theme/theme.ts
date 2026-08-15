export const themeStorageKey = "syllabus-calendar-theme"

export type ThemePreference = "light" | "dark" | "system"
export type ResolvedTheme = "light" | "dark"

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === "light" || value === "dark" || value === "system"
}

export function readStoredTheme(storage: Pick<Storage, "getItem"> | null | undefined): ThemePreference {
  if (!storage) return "system"
  try {
    const stored = storage.getItem(themeStorageKey)
    return isThemePreference(stored) ? stored : "system"
  } catch {
    return "system"
  }
}

export function resolveTheme(theme: ThemePreference, prefersDark: boolean): ResolvedTheme {
  if (theme === "system") return prefersDark ? "dark" : "light"
  return theme
}

export function applyThemePreference(
  root: HTMLElement,
  theme: ThemePreference,
  prefersDark: boolean,
): ResolvedTheme {
  const resolvedTheme = resolveTheme(theme, prefersDark)
  root.dataset.theme = theme
  root.dataset.resolvedTheme = resolvedTheme
  root.style.colorScheme = resolvedTheme
  root.classList.toggle("dark", resolvedTheme === "dark")
  return resolvedTheme
}

export function getSystemThemeMatcher() {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null
  return window.matchMedia("(prefers-color-scheme: dark)")
}
