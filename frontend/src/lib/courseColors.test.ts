import { expect, test } from "vitest"

import { resolveCourseDisplayColor } from "./courseColors"

test("keeps the stored course color in light theme", () => {
  expect(resolveCourseDisplayColor("course-1", "#0D9488", "light")).toBe("#0D9488")
})

test("uses a stable dark palette derived from the course id instead of the stored color", () => {
  expect(resolveCourseDisplayColor("course-1", "#0D9488", "dark")).toBe("#C084FC")
  expect(resolveCourseDisplayColor("course-1", "#2563EB", "dark")).toBe("#C084FC")
  expect(resolveCourseDisplayColor("course-2", "#0D9488", "dark")).toBe("#22D3EE")
  expect(resolveCourseDisplayColor("course-3", "#0D9488", "dark")).toBe("#FBBF24")
})
