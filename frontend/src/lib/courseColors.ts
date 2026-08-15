import type { ResolvedTheme } from "../theme/theme"

const darkCourseDisplayPalette = [
  "#FBBF24",
  "#4ADE80",
  "#FB7185",
  "#60A5FA",
  "#C084FC",
  "#22D3EE",
] as const

const defaultStoredCourseColor = "#0D9488"

function hashCourseId(courseId: string) {
  let hash = 2166136261
  for (const character of courseId) {
    hash ^= character.charCodeAt(0)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

export function resolveCourseDisplayColor(
  courseId: string,
  storedColor: string | null | undefined,
  resolvedTheme: ResolvedTheme,
) {
  if (resolvedTheme === "light") return storedColor ?? defaultStoredCourseColor
  return darkCourseDisplayPalette[hashCourseId(courseId) % darkCourseDisplayPalette.length]
}
