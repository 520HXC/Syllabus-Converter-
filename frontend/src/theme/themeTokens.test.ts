import { readFileSync } from "node:fs"
import { resolve } from "node:path"

import { expect, test } from "vitest"

const indexCss = readFileSync(resolve(import.meta.dirname, "../index.css"), "utf8").replace(/\r\n/g, "\n")

test("uses the approved high-contrast dark theme tokens without teal gradients", () => {
  expect(indexCss).toContain("--bg-app: 10 10 10;")
  expect(indexCss).toContain("--panel: 20 20 20;")
  expect(indexCss).toContain("--panel-muted: 31 31 31;")
  expect(indexCss).toContain("--panel-soft: 31 31 31;")
  expect(indexCss).toContain("--border: 42 42 42;")
  expect(indexCss).toContain("--border-strong: 82 82 82;")
  expect(indexCss).toContain("--text: 255 255 255;")
  expect(indexCss).toContain("--text-muted: 229 229 229;")
  expect(indexCss).toContain("--text-subtle: 163 163 163;")
  expect(indexCss).toContain("--accent: 251 191 36;")
  expect(indexCss).toContain("--accent-strong: 253 230 138;")
  expect(indexCss).toContain(":root.dark {\n  --bg-app: 10 10 10;")
  expect(indexCss).toContain(":root.dark {\n  --bg-app: 10 10 10;")
  expect(indexCss).toContain("html.dark {\n  background: rgb(var(--bg-app));\n}")
  expect(indexCss).toContain(".dark .page-hero-glow {\n    background: none;\n  }")
  expect(indexCss).not.toContain(":root.dark {\n  --bg-app: 7 15 24;")
})

test("defines semantic review badge colors for both themes", () => {
  expect(indexCss).toContain("--event-exam: 190 24 93;")
  expect(indexCss).toContain("--event-class: 21 128 61;")
  expect(indexCss).toContain("--event-deadline: 180 83 9;")
  expect(indexCss).toContain("--confidence-medium: 180 83 9;")
  expect(indexCss).toContain("--confidence-high: 21 128 61;")
  expect(indexCss).toContain("--confidence-low: 185 28 28;")
  expect(indexCss).toContain("--event-exam: 253 164 175;")
  expect(indexCss).toContain("--event-class: 134 239 172;")
  expect(indexCss).toContain("--event-deadline: 251 191 36;")
  expect(indexCss).toContain("--event-reading: 94 234 212;")
  expect(indexCss).toContain("--event-other: 100 116 139;")
  expect(indexCss).toContain("--confidence-medium: 251 191 36;")
  expect(indexCss).toContain("--confidence-high: 134 239 172;")
  expect(indexCss).toContain("--confidence-low: 253 164 175;")
})
