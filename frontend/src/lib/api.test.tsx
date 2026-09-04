import { File as NativeFile } from "node:buffer"
import { useEffect } from "react"
import { render, waitFor } from "@testing-library/react"
import { afterEach } from "vitest"

import { useApi } from "./api"

const getAccessTokenMock = vi.hoisted(() => vi.fn(async () => "test-token"))

class NativeFormDataStub {
  private values = new Map<string, unknown[]>()

  append(name: string, value: FormDataEntryValue) {
    this.values.set(name, [...(this.values.get(name) ?? []), value])
  }

  getAll(name: string): FormDataEntryValue[] {
    return [...(this.values.get(name) ?? [])] as FormDataEntryValue[]
  }
}

vi.mock("./auth", () => ({
  useAuth: () => ({
    getAccessToken: getAccessTokenMock,
  }),
}))

function ApiHarness({ onReady }: { onReady: (api: ReturnType<typeof useApi>) => void }) {
  const api = useApi()

  useEffect(() => {
    onReady(api)
  }, [api, onReady])

  return null
}

afterEach(() => {
  vi.unstubAllGlobals()
})

test("deleteSemester accepts a 204 response with no body", async () => {
  const fetchMock = vi.fn(async () => new Response(null, { status: 204 }))
  vi.stubGlobal("fetch", fetchMock)
  let apiRef: ReturnType<typeof useApi> | null = null

  render(<ApiHarness onReady={(api) => { apiRef = api }} />)
  await waitFor(() => expect(apiRef).not.toBeNull())

  await expect(apiRef!.deleteSemester("semester-1")).resolves.toBeUndefined()
  expect(fetchMock).toHaveBeenCalledWith(
    "http://localhost:8000/api/semesters/semester-1",
    expect.objectContaining({
      method: "DELETE",
      headers: expect.objectContaining({
        Authorization: "Bearer test-token",
      }),
    }),
  )
})

test("updates a recurring series through the bulk review endpoint", async () => {
  const fetchMock = vi.fn(async () =>
    new Response(JSON.stringify({ id: "series-1", review_status: "confirmed" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  )
  vi.stubGlobal("fetch", fetchMock)
  let apiRef: ReturnType<typeof useApi> | null = null

  render(<ApiHarness onReady={(api) => { apiRef = api }} />)
  await waitFor(() => expect(apiRef).not.toBeNull())

  await expect(
    (apiRef as any).updateRecurringSeries("series-1", { review_status: "confirmed" }),
  ).resolves.toEqual(expect.objectContaining({ id: "series-1", review_status: "confirmed" }))
  expect(fetchMock).toHaveBeenCalledWith(
    "http://localhost:8000/api/recurring-series/series-1",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ review_status: "confirmed" }),
    }),
  )
})

test("starts an explicit reprocess without treating the response as empty", async () => {
  const responseBody = {
    id: "job-1",
    document_id: "doc-1",
    status: "queued",
    stage_detail: "Waiting to reprocess",
    error_message: null,
    attempts: 1,
    filename: "course.pdf",
  }
  const fetchMock = vi.fn(async () =>
    new Response(JSON.stringify(responseBody), {
      status: 202,
      headers: { "Content-Type": "application/json" },
    }),
  )
  vi.stubGlobal("fetch", fetchMock)
  let apiRef: ReturnType<typeof useApi> | null = null

  render(<ApiHarness onReady={(api) => { apiRef = api }} />)
  await waitFor(() => expect(apiRef).not.toBeNull())

  await expect((apiRef as any).reprocessJob("job-1")).resolves.toEqual(responseBody)
  expect(fetchMock).toHaveBeenCalledWith(
    "http://localhost:8000/api/jobs/job-1/reprocess",
    expect.objectContaining({ method: "POST" }),
  )
})

test("updateCourse accepts a partial color-only payload", async () => {
  const fetchMock = vi.fn(async () =>
    new Response(JSON.stringify({ id: "course-1", color: "#2563EB" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  )
  vi.stubGlobal("fetch", fetchMock)
  let apiRef: ReturnType<typeof useApi> | null = null

  render(<ApiHarness onReady={(api) => { apiRef = api }} />)
  await waitFor(() => expect(apiRef).not.toBeNull())

  await expect(apiRef!.updateCourse("course-1", { color: "#2563EB" })).resolves.toEqual(
    expect.objectContaining({ id: "course-1", color: "#2563EB" }),
  )
  expect(fetchMock).toHaveBeenCalledWith(
    "http://localhost:8000/api/courses/course-1",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ color: "#2563EB" }),
    }),
  )
})

test("uploadSyllabi marks empty-MIME PDF files as application/pdf before appending them to FormData", async () => {
  const fetchMock = vi.fn(async () =>
    new Response(JSON.stringify({ jobs: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  )
  vi.stubGlobal("File", NativeFile as unknown as typeof File)
  vi.stubGlobal("FormData", NativeFormDataStub as unknown as typeof FormData)
  vi.stubGlobal("fetch", fetchMock)
  let apiRef: ReturnType<typeof useApi> | null = null

  render(<ApiHarness onReady={(api) => { apiRef = api }} />)
  await waitFor(() => expect(apiRef).not.toBeNull())

  const binaryPdf = Uint8Array.from([0x25, 0x50, 0x44, 0x46, 0xff, 0x00, 0x41])
  const emptyMimePdf = new File([binaryPdf], "scan.PDF", { type: "" })
  const normalPdf = new File([Uint8Array.from([0x25, 0x50, 0x44, 0x46, 0x30])], "course.pdf", {
    type: "application/pdf",
  })

  await apiRef!.uploadSyllabi("semester-1", [emptyMimePdf, normalPdf])

  const firstCall = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
  const init = firstCall[1]
  const body = init.body as FormData
  const [uploadedEmptyMimePdf, uploadedNormalPdf] = body.getAll("files") as unknown as [File, File]

  expect(uploadedEmptyMimePdf.name).toBe("scan.PDF")
  expect(uploadedEmptyMimePdf.type).toBe("application/pdf")
  expect(uploadedEmptyMimePdf.size).toBe(emptyMimePdf.size)
  expect(uploadedEmptyMimePdf.lastModified).toBe(emptyMimePdf.lastModified)
  expect(Array.from(new Uint8Array(await uploadedEmptyMimePdf.arrayBuffer()))).toEqual(Array.from(binaryPdf))
  expect(uploadedNormalPdf.name).toBe("course.pdf")
  expect(uploadedNormalPdf.type).toBe("application/pdf")
  expect(uploadedNormalPdf.size).toBe(normalPdf.size)
  expect(uploadedNormalPdf.lastModified).toBe(normalPdf.lastModified)
  expect(Array.from(new Uint8Array(await uploadedNormalPdf.arrayBuffer()))).toEqual([0x25, 0x50, 0x44, 0x46, 0x30])
})
