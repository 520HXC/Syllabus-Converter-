import type { ResolvedTheme } from "../theme/theme"

const defaultStoredCourseColor = "#0D9488"

function isStoredCourseColor(value: string | null | undefined): value is string {
  return Boolean(value && /^#[0-9A-Fa-f]{6}$/.test(value))
}

export function resolveCourseDisplayColor(
  _courseId: string,
  storedColor: string | null | undefined,
  _resolvedTheme: ResolvedTheme,
) {
  return isStoredCourseColor(storedColor) ? storedColor : defaultStoredCourseColor
}
