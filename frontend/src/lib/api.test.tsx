import { useEffect } from "react"
import { render, waitFor } from "@testing-library/react"

import { useApi } from "./api"

const getAccessTokenMock = vi.hoisted(() => vi.fn(async () => "test-token"))

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
