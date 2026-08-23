import { expect, test, type Page } from "@playwright/test"

async function signIn(page: Page) {
  await page.goto("/")
  const demoButton = page.getByRole("button", { name: "Try the local demo" })
  if (await demoButton.isVisible()) await demoButton.click()
  await expect(page).toHaveURL(/\/(semesters|setup)$/)
}

async function createSemester(page: Page) {
  if (new URL(page.url()).pathname !== "/setup") await page.goto("/setup")

  await expect(page).toHaveURL(/\/setup$/)
  await page.getByLabel("Semester name").fill("Course Rules Fall 2026")
  await page.getByLabel("First day").fill("2026-08-24")
  await page.getByLabel("Last day").fill("2026-12-18")
  await page.getByLabel("Timezone").fill("America/New_York")
  await page.getByRole("button", { name: "Save semester" }).click()
  await expect(page).toHaveURL(/\/upload$/)
}

function createPdf(lines: string[]) {
  const escape = (value: string) =>
    value.replaceAll("\\", "\\\\").replaceAll("(", "\\(").replaceAll(")", "\\)")
  const stream = [
    "BT",
    "/F1 12 Tf",
    "72 720 Td",
    "16 TL",
    ...lines.flatMap((line, index) => [
      `(${escape(line)}) Tj`,
      ...(index < lines.length - 1 ? ["T*"] : []),
    ]),
    "ET",
  ].join("\n")
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
  pdf += offsets
    .slice(1)
    .map((offset) => `${offset.toString().padStart(10, "0")} 00000 n \n`)
    .join("")
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`
  return Buffer.from(pdf)
}

test("saves an ambiguous recurrence as a course rule without publishing a calendar event", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await signIn(page)
  await createSemester(page)

  await page.getByLabel("Choose syllabus PDFs").setInputFiles({
    name: "course-rules.pdf",
    mimeType: "application/pdf",
    buffer: createPdf([
      "CS 101 Introduction to Computer Science",
      "Instructor: Dr. Rivera",
      "Exercise Sets: usually due the morning after lecture.",
    ]),
  })
  await page.getByRole("button", { name: "Process 1 syllabus" }).click()

  await expect(page).toHaveURL(/\/processing$/)
  await expect(page.getByText("Ready for review").first()).toBeVisible({ timeout: 15_000 })
  await page.getByRole("button", { name: "Review details" }).click()

  await expect(page).toHaveURL(/\/review$/)
  const ruleCard = page.locator("[data-review-event-id]").filter({ hasText: "Exercise Sets" })
  await expect(page.getByRole("heading", { name: "Course rules" })).toBeVisible()
  await expect(ruleCard).toBeVisible()
  await expect(ruleCard.getByText("Recurring rule", { exact: true })).toBeVisible()
  await expect(ruleCard.getByText("Needs review", { exact: true })).toBeVisible()
  await expect(ruleCard.getByLabel("Event date")).toHaveCount(0)
  await expect(ruleCard.getByText(/AI date/i)).toHaveCount(0)
  await expect(ruleCard.getByRole("button", { name: "Confirm", exact: true })).toHaveCount(0)

  const eventId = await ruleCard.getAttribute("data-review-event-id")
  expect(eventId).toBeTruthy()
  const saveResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" &&
      response.url().endsWith(`/api/extracted-events/${eventId}`) &&
      response.status() === 200,
  )
  await ruleCard.getByRole("button", { name: "Save course rule" }).click()
  const savedRule = (await (await saveResponsePromise).json()) as { review_status: string }
  expect(savedRule.review_status).toBe("pending")
  await expect(ruleCard).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Finish and open Calendar" })).toBeVisible()

  await page.reload()
  await expect(page.locator(`[data-review-event-id="${eventId}"]`)).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Finish and open Calendar" })).toBeVisible()
  await page.setViewportSize({ width: 375, height: 812 })
  await expect
    .poll(() =>
      page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      })),
    )
    .toEqual({ clientWidth: 375, scrollWidth: 375 })
  await page.getByRole("button", { name: "Finish and open Calendar" }).click()

  await expect(page).toHaveURL(/\/calendar\?view=list$/)

  await page.getByRole("button", { name: "CS 101", exact: true }).click()
  const courseDetails = page.locator('[id^="course-details-panel-"]')
  await expect(courseDetails.getByText("Exercise Sets", { exact: true })).toBeVisible()
  await expect(courseDetails.getByText("Saved", { exact: true })).toBeVisible()
  await expect(page.getByRole("region", { name: "Review queue" })).toHaveCount(0)
  await expect(page.getByText("No confirmed dates match the current course filters.")).toBeVisible()
  await expect(page.getByTestId(/calendar-course-rail-list-/)).toHaveCount(0)
  await expect
    .poll(() =>
      page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      })),
    )
    .toEqual({ clientWidth: 375, scrollWidth: 375 })

  await courseDetails.getByRole("link", { name: /Exercise Sets/ }).click()
  await expect(page).toHaveURL(new RegExp(`/review\\?eventId=${eventId}$`))
  const deepLinkedRule = page.locator(`[data-review-event-id="${eventId}"]`)
  await expect(deepLinkedRule).toBeVisible()
  await expect(deepLinkedRule.getByRole("button", { name: "Modify Exercise Sets" })).toBeFocused()
  await expect(deepLinkedRule.getByLabel("Event date")).toHaveCount(0)
})
