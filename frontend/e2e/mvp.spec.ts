import { expect, test } from "@playwright/test"
import { readFile } from "node:fs/promises"

const E2E_API_URL = "http://127.0.0.1:8010/api"
const DEMO_USER_ID = "11111111-1111-4111-8111-111111111111"

async function signIn(page: import("@playwright/test").Page) {
  await page.goto("/")
  const demoButton = page.getByRole("button", { name: "Try the local demo" })
  if (await demoButton.isVisible()) await demoButton.click()
  await expect(page).toHaveURL(/\/(semesters|setup)$/)
}

async function createSemester(page: import("@playwright/test").Page, name: string) {
  if (!page.url().endsWith("/setup")) {
    const newSemester = page.getByRole("button", { name: "New semester" })
    await Promise.race([
      page.waitForURL(/\/setup$/),
      newSemester.waitFor({ state: "visible" }),
    ])
    if (!page.url().endsWith("/setup")) await newSemester.click()
  }
  await expect(page).toHaveURL(/\/setup$/)
  await page.getByLabel("Semester name").fill(name)
  await page.getByLabel("First day").fill("2026-08-24")
  await page.getByLabel("Last day").fill("2026-12-18")
  await page.getByLabel("Timezone").fill("America/New_York")
  await page.getByRole("button", { name: "Save semester" }).click()
  await expect(page).toHaveURL(/\/upload$/)
}

function createPdf(lines: string[]) {
  const escape = (value: string) => value.replaceAll("\\", "\\\\").replaceAll("(", "\\(").replaceAll(")", "\\)")
  const stream = ["BT", "/F1 12 Tf", "72 720 Td", "16 TL", ...lines.flatMap((line, index) => [`(${escape(line)}) Tj`, ...(index < lines.length - 1 ? ["T*"] : [])]), "ET"].join("\n")
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`,
  ]
  let pdf = "%PDF-1.4\n"
  const offsets = [0]
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(pdf))
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`
  })
  const xrefOffset = Buffer.byteLength(pdf)
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  pdf += offsets.slice(1).map((offset) => `${offset.toString().padStart(10, "0")} 00000 n \n`).join("")
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`
  return Buffer.from(pdf)
}

async function uploadSyllabi(page: import("@playwright/test").Page) {
  await page.getByLabel("Choose syllabus PDFs").setInputFiles([
    {
      name: "cs101.pdf",
      mimeType: "application/pdf",
      buffer: createPdf([
        "CS 101 Introduction to Computer Science",
        "Instructor: Dr. Rivera",
        "This syllabus contains the complete course schedule and grading policies.",
        "Final project December 10",
      ]),
    },
    {
      name: "math201.pdf",
      mimeType: "application/pdf",
      buffer: createPdf([
        "MATH 201 Discrete Mathematics",
        "Instructor: Prof. Stone",
        "Midterm exam October 14, 2026",
      ]),
    },
  ])
  await page.getByRole("button", { name: "Process 2 syllabi" }).click()
}

async function makeExtractedEventUndated(
  page: import("@playwright/test").Page,
  semesterName: string,
  eventTitle: string,
) {
  const headers = { Authorization: `Bearer ${DEMO_USER_ID}` }
  const semestersResponse = await page.request.get(`${E2E_API_URL}/semesters`, { headers })
  expect(semestersResponse.ok()).toBe(true)
  const semesters = await semestersResponse.json() as Array<{ id: string; name: string }>
  const semester = semesters.find((item) => item.name === semesterName)
  expect(semester).toBeDefined()

  const reviewResponse = await page.request.get(
    `${E2E_API_URL}/semesters/${semester!.id}/review`,
    { headers },
  )
  expect(reviewResponse.ok()).toBe(true)
  const review = await reviewResponse.json() as { events: Array<{ id: string; title: string }> }
  const event = review.events.find((item) => item.title === eventTitle)
  expect(event).toBeDefined()

  const updateResponse = await page.request.patch(`${E2E_API_URL}/extracted-events/${event!.id}`, {
    headers,
    data: { event_date: null },
  })
  expect(updateResponse.ok()).toBe(true)
}

test("applies the LifeTrack palette only when dark mode is resolved", async ({ page }) => {
  await page.goto("/")
  await page.evaluate(() => window.localStorage.setItem("syllabus-calendar-theme", "dark"))
  await page.reload()

  await expect(page.locator("html")).toHaveClass(/dark/)
  await expect.poll(() => page.evaluate(() => {
    const styles = getComputedStyle(document.documentElement)
    return {
      background: styles.getPropertyValue("--bg-app").trim(),
      panel: styles.getPropertyValue("--panel").trim(),
      accent: styles.getPropertyValue("--accent").trim(),
      themeColor: document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')?.content,
    }
  })).toEqual({
    background: "10 10 10",
    panel: "20 20 20",
    accent: "251 191 36",
    themeColor: "#0a0a0a",
  })
  await expect(page.getByRole("button", { name: "Try the local demo" })).toHaveCSS(
    "background-color",
    "rgb(251, 191, 36)",
  )
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBe(1280)

  await page.evaluate(() => window.localStorage.setItem("syllabus-calendar-theme", "light"))
  await page.reload()

  await expect(page.locator("html")).not.toHaveClass(/dark/)
  await expect.poll(() => page.evaluate(() => {
    const styles = getComputedStyle(document.documentElement)
    return {
      background: styles.getPropertyValue("--bg-app").trim(),
      panel: styles.getPropertyValue("--panel").trim(),
      accent: styles.getPropertyValue("--accent").trim(),
    }
  })).toEqual({
    background: "244 247 251",
    panel: "255 255 255",
    accent: "15 118 110",
  })
})

test("keeps the session and saved semester after a refresh", async ({ page }) => {
  await page.goto("/")
  await expect(page.getByRole("heading", { name: "Turn your syllabi into one reviewed calendar." })).toBeVisible()
  await signIn(page)
  await createSemester(page, "Saved Semester 2026")
  await expect(page.getByText("Add every course in one batch")).toBeVisible()
  await expect(page.getByRole("combobox", { name: "Upload to semester" })).toHaveValue(/.+/)
  await expect(page.getByText("10 PDFs max").first()).toBeVisible()
  await expect(page.getByText("20 MB each").first()).toBeVisible()
  await expect(page.getByText("PDF only").first()).toBeVisible()

  await page.goto("/")
  await expect(page).toHaveURL(/\/semesters$/)
  await expect(page.getByRole("heading", { name: "Pick up where you left off" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "Saved Semester 2026" }).first()).toBeVisible()

  await page.getByRole("button", { name: "Sign out" }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole("heading", { name: "Turn your syllabi into one reviewed calendar." })).toBeVisible()
})

test("isolates review flow across documents and keeps the sticky footer clear at 375px", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await signIn(page)
  await createSemester(page, "Fall 2026")
  await uploadSyllabi(page)

  await expect(page).toHaveURL(/\/processing$/)
  await expect(page.getByText("Ready for review").first()).toBeVisible({ timeout: 15_000 })
  await makeExtractedEventUndated(page, "Fall 2026", "Final project")
  await page.getByRole("button", { name: "Review details" }).click()

  await expect(page).toHaveURL(/\/review$/)
  await expect(page.getByRole("button", { name: /cs101\.pdf/i })).toHaveText(/1 unresolved/i)
  await expect(page.getByRole("button", { name: /math201\.pdf/i })).toHaveText(/1 unresolved/i)

  await page.setViewportSize({ width: 1280, height: 900 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBe(1280)
  await page.setViewportSize({ width: 375, height: 812 })

  await page.getByRole("button", { name: /math201\.pdf/i }).click()
  const reviewUrl = page.url()
  const mathCard = page.locator("[data-review-event-id]").filter({ hasText: "Midterm" })
  await mathCard.getByRole("button", { name: /Modify Midterm/ }).click()
  await expect(page.getByTestId("review-sticky-footer")).toBeHidden()
  await mathCard.getByLabel("Event name").fill("Midterm exam")
  await mathCard.getByLabel("Event date").fill("2026-10-21")
  await mathCard.getByRole("button", { name: "Save changes" }).click()
  await expect(page).toHaveURL(reviewUrl)
  await expect(page.getByRole("heading", { name: "Midterm exam" })).toBeVisible()
  await expect(page.getByTestId("review-sticky-footer")).toBeVisible()
  await page.getByRole("button", { name: "Confirm", exact: true }).click()
  await expect(page.getByRole("button", { name: "Review next" })).toBeVisible()
  await page.getByRole("button", { name: "Review next" }).click()
  await expect(page.getByRole("heading", { name: "Final project" })).toBeVisible()
  await expect(page.getByLabel("Event date")).toBeFocused()

  await page.getByRole("button", { name: "Cancel" }).click()
  await page.getByRole("button", { name: "Remove", exact: true }).click()
  await expect(page.getByText("Event removed.")).toBeVisible()
  await expect(page.getByRole("button", { name: /Removed events \(1\)/i })).toBeVisible()
  await expect(page.getByText("Removed from the active review list")).toHaveCount(0)
  await page.getByRole("button", { name: /Removed events \(1\)/i }).click()
  await page.getByRole("button", { name: "Restore" }).click()
  await expect(page.getByRole("heading", { name: "Final project" })).toBeVisible()
  await page.reload()
  await expect(page.getByRole("heading", { name: "Final project" })).toBeVisible()
  await page.getByRole("button", { name: "Save for later", exact: true }).click()
  await expect(page.getByRole("button", { name: "Finish and open Calendar" })).toBeVisible()
  await page.reload()
  await expect(page.getByRole("button", { name: "Finish and open Calendar" })).toBeVisible()
  await page.getByRole("button", { name: /Saved for later \(1\)/i }).click()
  const pendingCard = page.locator("[data-review-event-id]").filter({ hasText: "Final project" })
  await expect(pendingCard.getByText("Pending date", { exact: true })).toBeVisible()
  await expect(pendingCard.getByText("Saved for later", { exact: true })).toBeVisible()

  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
  const footerBox = await page.getByRole("button", { name: "Finish and open Calendar" }).boundingBox()
  const stickyFooterBox = await page.getByTestId("review-sticky-footer").boundingBox()
  const mobileNavigationBox = await page.getByRole("navigation", { name: "Mobile navigation" }).boundingBox()
  const savedForLaterSectionBox = await page
    .getByRole("button", { name: /Saved for later \(1\)/i })
    .boundingBox()
  expect(footerBox).not.toBeNull()
  expect(stickyFooterBox).not.toBeNull()
  expect(mobileNavigationBox).not.toBeNull()
  expect(savedForLaterSectionBox).not.toBeNull()
  expect((savedForLaterSectionBox?.y ?? 0) + (savedForLaterSectionBox?.height ?? 0)).toBeLessThanOrEqual(
    footerBox?.y ?? 0,
  )
  expect((stickyFooterBox?.y ?? 0) + (stickyFooterBox?.height ?? 0)).toBeLessThanOrEqual(
    mobileNavigationBox?.y ?? 0,
  )

  await page.getByRole("button", { name: "Finish and open Calendar" }).click()
  await expect(page).toHaveURL(/\/calendar\?view=list$/)
  await expect(page.getByRole("navigation", { name: "Setup progress" })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "List", exact: true })).toHaveAttribute("aria-pressed", "true")
  await expect(page.getByRole("heading", { name: "Awaiting dates" })).toBeVisible()
  await expect(page.getByRole("link", { name: /Final project/i })).toBeVisible()
  await expect(page.getByRole("link", { name: /Midterm/i })).toBeVisible()
  await expect
    .poll(() => page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    })))
    .toEqual({ clientWidth: 375, scrollWidth: 375 })
  await page.getByRole("button", { name: "Change color for CS 101" }).click()
  await expect(page.getByRole("group", { name: "Choose a color for CS 101" })).toBeVisible()
  const paletteBox = await page.getByRole("group", { name: "Choose a color for CS 101" }).boundingBox()
  expect(paletteBox).not.toBeNull()
  expect(paletteBox!.x).toBeGreaterThanOrEqual(0)
  expect(paletteBox!.x + paletteBox!.width).toBeLessThanOrEqual(375)
  expect(paletteBox!.y + paletteBox!.height).toBeLessThanOrEqual(812)
  await expect
    .poll(() => page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    })))
    .toEqual({ clientWidth: 375, scrollWidth: 375 })
  await page.keyboard.press("Escape")
  await expect(page.getByRole("group", { name: "Choose a color for CS 101" })).toBeHidden()
  const mathColorButton = page.getByRole("button", { name: "Change color for MATH 201" })
  const mathCourseRow = page.locator('[data-testid^="course-filter-row-"]').filter({ hasText: "MATH 201" })
  const courseColorPatchResponse = page.waitForResponse((response) => (
    response.request().method() === "PATCH" &&
    /\/api\/courses\/[^/]+$/.test(response.url()) &&
    response.status() === 200
  ))
  await mathColorButton.click()
  await page.getByRole("group", { name: "Choose a color for MATH 201" }).getByRole("button", { name: "Pink" }).click()
  await courseColorPatchResponse
  await expect(mathColorButton).toBeEnabled()
  await expect(mathCourseRow.getByText("Saving color...")).toHaveCount(0)
  await expect(page.getByTestId(/course-filter-swatch-/).nth(1)).toHaveCSS("background-color", "rgb(219, 39, 119)")
  await expect(page.getByTestId(/calendar-course-rail-list-/).first()).toHaveCSS("background-color", "rgb(219, 39, 119)")
  await page.reload()
  await expect(page).toHaveURL(/\/calendar\?view=list$/)
  await expect(page.getByTestId(/course-filter-swatch-/).nth(1)).toHaveCSS("background-color", "rgb(219, 39, 119)")
  await expect(page.getByTestId(/calendar-course-rail-list-/).first()).toHaveCSS("background-color", "rgb(219, 39, 119)")

  await page.setViewportSize({ width: 1280, height: 720 })
  await mathColorButton.click()
  const desktopPaletteBox = await page
    .getByRole("group", { name: "Choose a color for MATH 201" })
    .boundingBox()
  const desktopMainBox = await page.locator("main").boundingBox()
  expect(desktopPaletteBox).not.toBeNull()
  expect(desktopMainBox).not.toBeNull()
  expect(desktopPaletteBox!.x).toBeGreaterThanOrEqual(desktopMainBox!.x)
  expect(desktopPaletteBox!.x + desktopPaletteBox!.width).toBeLessThanOrEqual(1280)
  await page.keyboard.press("Escape")
  await page.setViewportSize({ width: 375, height: 812 })

  await page.getByRole("navigation", { name: "Mobile navigation" }).getByRole("link", { name: "Review", exact: true }).click()
  await expect(page).toHaveURL(/\/review$/)
  await expect(page.getByText("Review complete")).toBeVisible()
  await expect(page.getByRole("button", { name: "Open Calendar" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Review decisions" })).toBeVisible()
  await expect(page.getByText("Confirmed", { exact: true })).toBeVisible()
  await expect(page.getByText("Saved for later", { exact: true })).toBeVisible()
  await expect(page.getByText("Saved rules", { exact: true })).toBeVisible()
  await expect(page.getByText("Removed", { exact: true })).toBeVisible()
  await expect(page.getByText("Previewing")).toHaveCount(0)

  await page.getByRole("button", { name: "Review decisions" }).click()
  await expect(page).toHaveURL(/\/review\?mode=edit$/)
  await expect(page.getByRole("button", { name: "Done editing" })).toBeVisible()
  const editingFooterBox = await page.getByTestId("review-sticky-footer").boundingBox()
  const editingNavigationBox = await page.getByRole("navigation", { name: "Mobile navigation" }).boundingBox()
  expect(editingFooterBox).not.toBeNull()
  expect(editingNavigationBox).not.toBeNull()
  expect((editingFooterBox?.y ?? 0) + (editingFooterBox?.height ?? 0)).toBeLessThanOrEqual(
    editingNavigationBox?.y ?? 0,
  )
  await page.getByRole("button", { name: "Done editing" }).click()
  await expect(page).toHaveURL(/\/review$/)
  await expect(page.getByText("Review complete")).toBeVisible()

  await page.getByRole("button", { name: "Open Calendar" }).click()
  await expect(page).toHaveURL(/\/calendar\?view=list$/)

  await page.getByRole("link", { name: /Final project/i }).click()
  await expect(page).toHaveURL(/\/review\?eventId=[^&]+$/)
  await expect(page.getByRole("heading", { name: "Final project" })).toBeVisible()
  await expect(page.getByLabel("Event date")).toBeFocused()
  await expect(page.getByTestId("review-sticky-footer")).toBeHidden()
  await page.getByLabel("Event date").fill("2026-12-10")
  await page.getByRole("button", { name: "Save and confirm" }).click()
  await expect(page.getByRole("button", { name: /Reviewed events \(1\)/i })).toBeVisible()

  await page.goBack()
  await expect(page).toHaveURL(/\/calendar\?view=list$/)
  await expect(page.getByRole("button", { name: "List", exact: true })).toHaveAttribute("aria-pressed", "true")
  await expect(page.getByRole("heading", { name: "Awaiting dates" })).toHaveCount(0)
  await expect(page.getByRole("link", { name: /Final project/i })).toBeVisible()

  await page.getByRole("button", { name: "Month", exact: true }).click()
  await expect(page).toHaveURL(/\/calendar\?view=month$/)
  await expect(page.getByRole("button", { name: "Month", exact: true })).toHaveAttribute("aria-pressed", "true")

  await page.goto("/calendar?view=timeline")
  await expect(page).toHaveURL(/\/calendar\?view=timeline$/)
  await expect(page.getByRole("button", { name: "Timeline", exact: true })).toHaveAttribute("aria-pressed", "true")
  await expect(page.getByTestId("timeline-scroll-region")).toBeVisible()

  await page.goto("/calendar?view=list")
  await expect(page).toHaveURL(/\/calendar\?view=list$/)
  await expect(page.getByRole("button", { name: "List", exact: true })).toHaveAttribute("aria-pressed", "true")

  const downloadPromise = page.waitForEvent("download")
  await page.getByRole("button", { name: "Export" }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe("fall-2026.ics")
  const path = await download.path()
  expect(path).not.toBeNull()
  const ics = await readFile(path!, "utf8")
  expect(ics).toContain("Midterm exam")
  expect(ics).toContain("Final project")
})

test("reviews a recurring schedule once while preserving individual changes", async ({ page }) => {
  await signIn(page)
  await createSemester(page, "Recurring Fall 2026")

  await page.getByLabel("Choose syllabus PDFs").setInputFiles({
    name: "weekly-homework.pdf",
    mimeType: "application/pdf",
    buffer: createPdf([
      "CS 101 Syllabus",
      "Homework due every Friday from Sep 4, 2026 through Dec 4, 2026 except Nov 27, 2026.",
    ]),
  })
  await page.getByRole("button", { name: "Process 1 syllabus" }).click()

  await expect(page).toHaveURL(/\/processing$/)
  await expect(page.getByText("Ready for review").first()).toBeVisible({ timeout: 15_000 })
  await page.getByRole("button", { name: "Review details" }).click()

  const series = page.locator('[data-recurring-series-id]').filter({ hasText: "Homework" })
  await expect(series).toBeVisible()
  await expect(series.getByText("13 generated dates")).toBeVisible()
  await series.getByRole("button", { name: "Show 13 dates" }).click()

  const occurrenceCards = series.locator('[data-review-event-id]')
  await expect(occurrenceCards).toHaveCount(13)
  await occurrenceCards.nth(1).getByRole("button", { name: "Modify Homework" }).click()
  await occurrenceCards.nth(1).getByLabel("Event date").fill("2026-09-12")
  const confirmedOccurrence = page.waitForResponse((response) =>
    response.url().includes("/api/extracted-events/") && response.request().method() === "PATCH" &&
    response.request().postDataJSON().review_status === "confirmed" && response.ok(),
  )
  await occurrenceCards.nth(1).getByRole("button", { name: "Confirm", exact: true }).click()
  await confirmedOccurrence

  let releaseRemoval!: () => void
  const removalGate = new Promise<void>((resolve) => { releaseRemoval = resolve })
  let removalStarted!: () => void
  const removalRequestStarted = new Promise<void>((resolve) => { removalStarted = resolve })
  await page.route("**/api/extracted-events/*", async (route) => {
    if (route.request().method() === "PATCH" && route.request().postDataJSON().review_status === "ignored") {
      removalStarted()
      await removalGate
    }
    await route.continue()
  })
  const removedOccurrence = page.waitForResponse((response) =>
    response.url().includes("/api/extracted-events/") && response.request().method() === "PATCH" &&
    response.request().postDataJSON().review_status === "ignored" && response.ok(),
  )
  try {
    await occurrenceCards.first().getByRole("button", { name: "Remove", exact: true }).click()
    await removalRequestStarted
    await expect(series.getByRole("button", { name: "Confirm series" })).toBeDisabled()
    await expect(series.getByRole("button", { name: "Keep pending", exact: true })).toBeDisabled()
  } finally {
    releaseRemoval()
  }
  const removedEvent = await (await removedOccurrence).json()
  expect(removedEvent.review_status).toBe("ignored")

  let releaseSeries!: () => void
  const seriesGate = new Promise<void>((resolve) => { releaseSeries = resolve })
  let seriesStarted!: () => void
  const seriesRequestStarted = new Promise<void>((resolve) => { seriesStarted = resolve })
  await page.route("**/api/recurring-series/*", async (route) => {
    if (route.request().method() === "PATCH") {
      seriesStarted()
      await seriesGate
    }
    await route.continue()
  })
  try {
    await series.getByRole("button", { name: "Confirm series" }).click()
    await seriesRequestStarted
    await expect(series.getByRole("button", { name: "Modify Homework" }).first()).toBeDisabled()
    await expect(series.getByRole("button", { name: "Remove series", exact: true })).toBeDisabled()
  } finally {
    releaseSeries()
  }
  await expect(page.getByRole("button", { name: "Finish and open Calendar" })).toBeVisible()
  await page.getByRole("button", { name: "Finish and open Calendar" }).click()

  await page.getByRole("button", { name: "List", exact: true }).click()
  await expect(page).toHaveURL(/\/calendar\?view=list$/)
  await expect(page.getByRole("heading", { name: "September 12, 2026" })).toBeVisible()
  // This week's summary may link to the same event again. Count actual list
  // occurrences and separately ensure the removed date is absent everywhere.
  await expect(page.getByRole("link", { name: /Homework/i }).filter({
    has: page.getByTestId(/^calendar-course-rail-list-/),
  })).toHaveCount(12)
  await expect(page.locator(`a[href="/review?eventId=${removedEvent.id}"]`)).toHaveCount(0)
})
