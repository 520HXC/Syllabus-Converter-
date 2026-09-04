import { expect, test, type Page } from "@playwright/test"
import { readFile } from "node:fs/promises"

const API = "http://127.0.0.1:8010/api"
const headers = { Authorization: "Bearer 11111111-1111-4111-8111-111111111111" }

test.use({ timezoneId: "Asia/Tokyo" })

async function setup(page: Page, name: string) {
  await page.goto("/")
  const demo = page.getByRole("button", { name: "Try the local demo" })
  if (await demo.isVisible()) await demo.click()
  await expect(page).toHaveURL(/\/(semesters|setup)$/)
  return createSemester(page, name)
}

async function createSemester(page: Page, name: string) {
  await page.goto("/setup")
  await page.getByLabel("Semester name").fill(name)
  await page.getByLabel("First day").fill("2026-08-24")
  await page.getByLabel("Last day").fill("2026-12-18")
  await page.getByLabel("Timezone").fill("America/New_York")
  const response = page.waitForResponse((res) => res.request().method() === "POST" && res.url().endsWith("/api/semesters"))
  await page.getByRole("button", { name: "Save semester" }).click()
  const semester = await (await response).json() as { id: string }
  await expect(page).toHaveURL(/\/upload$/)
  return semester.id
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


function syllabus(name: string) {
  return {
    name,
    mimeType: "application/pdf",
    buffer: createPdf([
      "CS 101 Introduction to Computer Science",
      "Instructor: Dr. Rivera",
      "This syllabus contains the complete course schedule and grading policies.",
      "Final project December 10, 2026",
    ]),
  }
}

async function upload(page: Page, filename: string) {
  await page.getByLabel("Choose syllabus PDFs").setInputFiles(syllabus(filename))
  await page.getByRole("button", { name: "Process 1 syllabus", exact: true }).click()
  await expect(page).toHaveURL(/\/processing$/)
  await expect(page.getByText("Ready for review", { exact: true }).first()).toBeVisible({ timeout: 15_000 })
}

async function reviewEvent(page: Page, semesterId: string) {
  const response = await page.request.get(`${API}/semesters/${semesterId}/review`, { headers })
  expect(response.ok()).toBe(true)
  const review = await response.json() as { events: Array<{ id: string; title: string }> }
  expect(review.events).toHaveLength(1)
  return review.events[0]
}

async function downloadedCalendar(page: Page) {
  const downloaded = page.waitForEvent("download")
  await page.getByRole("button", { name: "Export", exact: true }).click()
  const download = await downloaded
  const path = await download.path()
  expect(path).not.toBeNull()
  return readFile(path!, "utf8")
}

test("preserves a New York deadline in every calendar view with a Tokyo browser", async ({ page }, testInfo) => {
  await page.clock.setFixedTime(new Date("2026-12-10T12:00:00Z"))
  const semester = await setup(page, "Timezone reliability")
  await upload(page, "deadline.pdf")
  const event = await reviewEvent(page, semester)
  const updated = await page.request.patch(`${API}/extracted-events/${event.id}`, {
    headers,
    data: { start_time: null, end_time: "23:59:00", is_all_day: false, review_status: "confirmed" },
  })
  expect(updated.ok()).toBe(true)

  await page.goto("/calendar?view=list")
  const thisWeek = page.getByRole("heading", { name: "This week", exact: true }).locator("../..")
  await expect(thisWeek).toContainText("23:59")
  const deadline = page.getByRole("link").filter({ hasText: "Final project" })
  await expect(deadline.last()).toContainText("23:59")
  await expect(deadline.last()).not.toContainText("All day")
  await page.screenshot({ path: testInfo.outputPath("desktop-list.png"), fullPage: true })

  await page.getByRole("button", { name: "Timeline", exact: true }).click()
  await expect(page.getByRole("link").filter({ hasText: "Final project" }).last()).toContainText("23:59")
  await page.getByRole("button", { name: "Month", exact: true }).click()
  for (let index = 0; index < 4; index++) await page.getByRole("button", { name: "Next month" }).click()
  const day = page.locator('.fc-daygrid-day[data-date="2026-12-10"]')
  await expect(day).toContainText("Final project")
  await expect(day.locator(".fc-event")).toContainText(/11:59p|23:59/)
  const dayBox = await day.boundingBox()
  const eventBox = await day.locator(".fc-event").boundingBox()
  expect(dayBox).not.toBeNull()
  expect(eventBox).not.toBeNull()
  expect(eventBox!.x + eventBox!.width).toBeLessThanOrEqual(dayBox!.x + dayBox!.width + 1)
  await expect(page.locator('.fc-daygrid-day[data-date="2026-12-11"]')).not.toContainText("Final project")

  const ics = await downloadedCalendar(page)
  const block = ics.split("BEGIN:VEVENT").find((entry) => entry.includes("Final project"))!
  expect(block).toContain("DTSTART;TZID=America/New_York:20261210T235900")
  expect(block).not.toContain("DTEND")
  expect(block).not.toContain("DURATION")
  await page.screenshot({ path: testInfo.outputPath("desktop-month.png"), fullPage: true })
  for (const theme of ["light", "dark"]) {
    await page.setViewportSize({ width: 375, height: 812 })
    await page.evaluate((value) => localStorage.setItem("syllabus-calendar-theme", value), theme)
    await page.goto("/calendar?view=list")
    await expect(page.getByRole("link").filter({ hasText: "Final project" }).last()).toContainText("23:59")
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBe(375)
    await page.screenshot({ path: testInfo.outputPath(`mobile-${theme}.png`), fullPage: true })
  }
})

test("recovers upload, status, edit and export failures without losing the user's draft", async ({ page }) => {
  const semester = await setup(page, "Recovery reliability")
  const uploadUrl = `${API}/semesters/${semester}/syllabi`
  await page.route(uploadUrl, (route) => route.fulfill({ status: 503, json: { detail: "Upload temporarily unavailable" } }))
  await page.getByLabel("Choose syllabus PDFs").setInputFiles(syllabus("recovery.pdf"))
  const process = page.getByRole("button", { name: "Process 1 syllabus", exact: true })
  await process.click()
  await expect(page.getByRole("alert")).toContainText("Upload temporarily unavailable")
  await expect(page.getByText("recovery.pdf", { exact: true })).toBeVisible()
  await expect(process).toBeEnabled()
  await page.unroute(uploadUrl)
  await process.click()
  await expect(page).toHaveURL(/\/processing$/)
  await expect(page.getByText("Ready for review", { exact: true }).first()).toBeVisible({ timeout: 15_000 })
  const jobsUrl = `${API}/semesters/${semester}/jobs`
  const jobs = await (await page.request.get(jobsUrl, { headers })).json() as unknown[]
  expect(jobs).toHaveLength(1)

  await page.route(jobsUrl, (route) => route.fulfill({ status: 503, json: { detail: "Status temporarily unavailable" } }))
  await page.reload()
  await expect(page.getByRole("alert")).toContainText("Status temporarily unavailable")
  await page.unroute(jobsUrl)
  await page.getByRole("button", { name: "Try again", exact: true }).click()
  await expect(page.getByText("Ready for review", { exact: true }).first()).toBeVisible()
  await expect(page.getByRole("alert")).toHaveCount(0)

  const event = await reviewEvent(page, semester)
  await page.getByRole("button", { name: "Review details" }).click()
  const card = page.locator(`[data-review-event-id="${event.id}"]`)
  await card.getByRole("button", { name: /Modify Final project/ }).click()
  await card.getByLabel("Event name").fill("Manually corrected project")
  const editUrl = `${API}/extracted-events/${event.id}`
  await page.route(editUrl, (route) => route.request().method() === "PATCH"
    ? route.fulfill({ status: 503, json: { detail: "Save temporarily unavailable" } })
    : route.continue())
  await card.getByRole("button", { name: "Save changes", exact: true }).click()
  await expect(card.getByRole("alert")).toContainText("Save temporarily unavailable")
  await expect(card.getByLabel("Event name")).toHaveValue("Manually corrected project")
  await expect(card.getByRole("button", { name: "Save changes", exact: true })).toBeEnabled()
  await page.unroute(editUrl)
  await card.getByRole("button", { name: "Save changes", exact: true }).click()
  await expect(card.getByRole("heading", { name: "Manually corrected project" })).toBeVisible()
  expect((await reviewEvent(page, semester)).title).toBe("Manually corrected project")
  await card.getByRole("button", { name: "Confirm", exact: true }).click()

  await page.goto("/calendar?view=list")
  const exportUrl = `${API}/semesters/${semester}/calendar.ics*`
  await page.route(exportUrl, (route) => route.fulfill({ status: 503, json: { detail: "Export temporarily unavailable" } }))
  await page.getByRole("button", { name: "Export", exact: true }).click()
  await expect(page.getByRole("alert")).toContainText("Export temporarily unavailable")
  await expect(page.getByRole("button", { name: "Export", exact: true })).toBeEnabled()
  await page.unroute(exportUrl)
  expect(await downloadedCalendar(page)).toContain("Manually corrected project")
  await expect(page.getByRole("alert")).toHaveCount(0)
})

test("refreshes processing and switches semesters without showing another semester's jobs", async ({ page }) => {
  const semesterA = await setup(page, "Processing semester A")
  await upload(page, "semester-a.pdf")
  const jobsAUrl = `${API}/semesters/${semesterA}/jobs`
  const jobsA = await (await page.request.get(jobsAUrl, { headers })).json() as Array<Record<string, unknown>>
  await page.route(jobsAUrl, (route) => route.fulfill({ json: jobsA.map((job) => ({ ...job, status: "extracting_events", stage_detail: "Simulated processing" })) }))
  await page.reload()
  await expect(page.getByRole("heading", { name: "Reading your course plans" })).toBeVisible()
  await expect(page.getByText("semester-a.pdf", { exact: true })).toBeVisible()
  const semesterB = await createSemester(page, "Processing semester B")
  await upload(page, "semester-b.pdf")
  await expect(page.getByText("semester-a.pdf", { exact: true })).toHaveCount(0)
  await page.reload()
  await expect(page.getByText("semester-b.pdf", { exact: true })).toBeVisible()
  await expect(page.getByText("semester-a.pdf", { exact: true })).toHaveCount(0)
  await page.goto("/upload")
  await page.getByRole("combobox", { name: "Upload to semester" }).selectOption(semesterA)
  await page.goto("/processing")
  await expect(page.getByRole("heading", { name: "Reading your course plans" })).toBeVisible()
  await expect(page.getByText("semester-a.pdf", { exact: true })).toBeVisible()
  await expect(page.getByText("semester-b.pdf", { exact: true })).toHaveCount(0)
  await page.unroute(jobsAUrl)
  await expect(page.getByText("Ready for review", { exact: true }).first()).toBeVisible()
  expect(semesterB).not.toBe(semesterA)
})


test("reprocess confirmation preserves reviewed edits on failure and replaces only the selected PDF on success", async ({ page }) => {
  const semester = await setup(page, "Reprocess reliability")
  await page.getByLabel("Choose syllabus PDFs").setInputFiles([
    syllabus("target.pdf"),
    { name: "sibling.pdf", mimeType: "application/pdf", buffer: createPdf([
      "MATH 201 Discrete Mathematics", "Instructor: Prof. Stone", "Midterm exam October 14, 2026",
    ]) },
  ])
  await page.getByRole("button", { name: "Process 2 syllabi" }).click()
  await expect(page.getByRole("button", { name: "Review details" })).toBeVisible({ timeout: 15_000 })
  const jobs = await (await page.request.get(`${API}/semesters/${semester}/jobs`, { headers })).json() as Array<{ id: string; document_id: string; filename: string }>
  const targetJob = jobs.find((job) => job.filename === "target.pdf")!
  const readReview = async () => (await (await page.request.get(`${API}/semesters/${semester}/review`, { headers })).json()) as {
    semester: { review_completed_at: string | null }
    events: Array<{ id: string; document_id: string; title: string; review_status: string }>
  }
  const original = await readReview()
  for (const event of original.events) {
    const response = await page.request.patch(`${API}/extracted-events/${event.id}`, {
      headers, data: { title: event.document_id === targetJob.document_id ? "Manual target title" : "Manual sibling title", review_status: "confirmed" },
    })
    expect(response.ok()).toBe(true)
  }
  expect((await page.request.post(`${API}/semesters/${semester}/review/complete`, { headers })).ok()).toBe(true)
  const reviewed = await readReview()
  await page.reload()
  await page.getByRole("button", { name: "Run extraction again for target.pdf", exact: true }).click()
  const dialog = page.getByRole("dialog")
  await expect(dialog).toContainText("replace the extracted events and review decisions for this PDF")
  const reprocessUrl = `${API}/jobs/${targetJob.id}/reprocess`
  await page.route(reprocessUrl, (route) => route.fulfill({ status: 503, json: { detail: "Reprocessing temporarily unavailable" } }))
  await dialog.getByRole("button", { name: "Run extraction again", exact: true }).click()
  await expect(dialog.getByRole("alert")).toContainText("Reprocessing temporarily unavailable")
  expect(await readReview()).toEqual(reviewed)
  await expect(dialog.getByRole("button", { name: "Run extraction again", exact: true })).toBeEnabled()
  await page.unroute(reprocessUrl)
  const response = page.waitForResponse((res) => res.url() === reprocessUrl && res.request().method() === "POST")
  await dialog.getByRole("button", { name: "Run extraction again", exact: true }).click()
  expect((await response).ok()).toBe(true)
  await expect(dialog).toHaveCount(0)
  const after = await readReview()
  expect(after.semester.review_completed_at).toBeNull()
  expect(after.events.filter((event) => event.document_id !== targetJob.document_id)).toEqual(
    reviewed.events.filter((event) => event.document_id !== targetJob.document_id),
  )
  expect(after.events.filter((event) => event.document_id === targetJob.document_id)).toEqual([
    expect.objectContaining({ title: "Final project", review_status: "needs_review" }),
  ])
  expect(after.events.find((event) => event.document_id === targetJob.document_id)!.id).not.toBe(
    reviewed.events.find((event) => event.document_id === targetJob.document_id)!.id,
  )
})


test("uploads an empty-MIME PDF byte-for-byte and permits intentional repeat uploads", async ({ page }) => {
  const semester = await setup(page, "Empty MIME reliability")
  const payload = syllabus("same-name.PDF")
  const documentIds: string[] = []
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.goto("/upload")
    await page.getByLabel("Choose syllabus PDFs").evaluate((node, bytes) => {
      const transfer = new DataTransfer()
      transfer.items.add(new File([new Uint8Array(bytes)], "same-name.PDF", { type: "" }))
      const input = node as HTMLInputElement
      input.files = transfer.files
      node.dispatchEvent(new Event("change", { bubbles: true }))
    }, [...payload.buffer])
    const response = page.waitForResponse((res) => res.url().endsWith(`/semesters/${semester}/syllabi`) && res.request().method() === "POST")
    await page.getByRole("button", { name: "Process 1 syllabus", exact: true }).click()
    const uploaded = await response
    expect(uploaded.status()).toBe(202)
    const result = await uploaded.json() as { jobs: Array<{ document_id: string }> }
    expect(result.jobs).toHaveLength(1)
    const documentId = result.jobs[0].document_id
    documentIds.push(documentId)
    const original = await page.request.get(`${API}/syllabus-documents/${documentId}/file`, { headers })
    expect(original.ok()).toBe(true)
    expect(await original.body()).toEqual(payload.buffer)
    await expect(page.getByRole("button", { name: "Review details" })).toBeVisible({ timeout: 15_000 })
  }
  expect(new Set(documentIds).size).toBe(2)
  const jobs = await (await page.request.get(`${API}/semesters/${semester}/jobs`, { headers })).json() as unknown[]
  expect(jobs).toHaveLength(2)
})


test("reports a corrupt PDF and lets a failed retry request recover without duplicating jobs", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 375, height: 812 })
  const semester = await setup(page, "Failed PDF recovery")
  await page.getByLabel("Choose syllabus PDFs").setInputFiles({
    name: "broken.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-broken-document"),
  })
  await page.getByRole("button", { name: "Process 1 syllabus", exact: true }).click()
  const retryButton = page.getByRole("button", { name: "Retry broken.pdf", exact: true })
  await expect(retryButton).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole("heading", { name: "Some files need attention" })).toBeVisible()
  await expect(page.getByText("The uploaded file could not be opened as a PDF.", { exact: true })).toBeVisible()
  const jobsUrl = `${API}/semesters/${semester}/jobs`
  const before = await (await page.request.get(jobsUrl, { headers })).json() as Array<{ id: string; attempts: number }>
  expect(before).toHaveLength(1)
  const retryUrl = `${API}/jobs/${before[0].id}/retry`
  await page.route(retryUrl, (route) => route.fulfill({ status: 503, json: { detail: "Retry temporarily unavailable" } }))
  await retryButton.click()
  const alert = page.getByRole("alert").filter({ hasText: "Retry temporarily unavailable" })
  await expect(alert).toBeVisible()
  await expect(retryButton).toBeEnabled()
  await page.screenshot({ path: testInfo.outputPath("mobile-retry-error.png"), fullPage: true })
  await page.unroute(retryUrl)
  const retried = page.waitForResponse((res) => res.url() === retryUrl && res.request().method() === "POST")
  await alert.getByRole("button", { name: "Try again" }).click()
  expect((await retried).ok()).toBe(true)
  await expect(alert).toHaveCount(0)
  await expect(retryButton).toBeEnabled()
  await expect.poll(async () => {
    const jobs = await (await page.request.get(jobsUrl, { headers })).json() as Array<{ id: string; status: string; attempts: number }>
    return { count: jobs.length, id: jobs[0].id, status: jobs[0].status, attempts: jobs[0].attempts }
  }).toEqual({ count: 1, id: before[0].id, status: "failed", attempts: before[0].attempts + 1 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBe(375)
})
