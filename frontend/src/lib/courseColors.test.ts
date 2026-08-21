import { expect, test } from "vitest"

import { resolveCourseDisplayColor } from "./courseColors"

test("keeps the stored course color in light theme", () => {
  expect(resolveCourseDisplayColor("course-1", "#0D9488", "light")).toBe("#0D9488")
})

test("keeps the stored course color in dark theme", () => {
  expect(resolveCourseDisplayColor("course-1", "#0D9488", "dark")).toBe("#0D9488")
  expect(resolveCourseDisplayColor("course-2", "#2563EB", "dark")).toBe("#2563EB")
})

test("falls back to the default course color when the stored value is missing or invalid", () => {
  expect(resolveCourseDisplayColor("course-1", null, "light")).toBe("#0D9488")
  expect(resolveCourseDisplayColor("course-1", undefined, "dark")).toBe("#0D9488")
  expect(resolveCourseDisplayColor("course-1", "teal", "light")).toBe("#0D9488")
  expect(resolveCourseDisplayColor("course-1", "#12345", "dark")).toBe("#0D9488")
})
