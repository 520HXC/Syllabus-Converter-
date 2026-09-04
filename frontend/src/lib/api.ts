import { useMemo } from "react"

import { useAuth } from "./auth"
import type {
  Course,
  CourseUpdatePayload,
  EventUpdate,
  ExtractedEvent,
  ProcessingJob,
  ReviewPayload,
  ReviewBlockingDetail,
  ReviewCompleteResponse,
  RecurringEventSeries,
  RecurringSeriesUpdate,
  Semester,
} from "./types"

const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000/api"

interface ApiErrorPayload {
  detail?: string | Array<{ msg?: string }>
  blocking_event_ids?: string[]
  blocking_document_ids?: string[]
  blocking_count?: number
}

type SemesterCreatePayload = Omit<
  Semester,
  "id" | "review_completed_at" | "course_count" | "document_count" | "event_count" | "needs_review_count"
>

export class ApiError extends Error {
  status: number
  blocking_event_ids: string[]
  blocking_document_ids: string[]
  blocking_count: number

  constructor(status: number, payload: ApiErrorPayload | null, fallbackMessage: string) {
    super(getErrorMessage(payload, status, fallbackMessage))
    this.name = "ApiError"
    this.status = status
    this.blocking_event_ids = payload?.blocking_event_ids ?? []
    this.blocking_document_ids = payload?.blocking_document_ids ?? []
    this.blocking_count = payload?.blocking_count ?? 0
  }
}

function getErrorMessage(payload: ApiErrorPayload | null, status: number, fallbackMessage?: string) {
  if (typeof payload?.detail === "string") return payload.detail
  if (Array.isArray(payload?.detail)) return payload.detail.map((item) => item.msg).filter(Boolean).join(" ")
  return fallbackMessage ?? `Request failed with status ${status}.`
}

async function getErrorPayload(response: Response) {
  try {
    return (await response.json()) as ApiErrorPayload
  } catch {
    return null
  }
}

function normalizeUploadFile(file: File) {
  if (file.type || !file.name.toLowerCase().endsWith(".pdf")) return file
  return new File([file], file.name, {
    type: "application/pdf",
    lastModified: file.lastModified,
  })
}

export function useApi() {
  const { getAccessToken } = useAuth()

  return useMemo(() => {
    async function authorizedFetch(path: string, init?: RequestInit) {
      const token = await getAccessToken()
      if (!token) throw new Error("Sign in is required.")
      return fetch(`${API_URL}${path}`, {
        ...init,
        headers: {
          Authorization: `Bearer ${token}`,
          ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
          ...init?.headers,
        },
      })
    }

    async function request<T>(path: string, init?: RequestInit): Promise<T> {
      const response = await authorizedFetch(path, init)
      if (!response.ok) {
        throw new ApiError(response.status, await getErrorPayload(response), `Request failed with status ${response.status}.`)
      }
      return response.json() as Promise<T>
    }

    async function requestVoid(path: string, init?: RequestInit): Promise<void> {
      const response = await authorizedFetch(path, init)
      if (!response.ok) {
        throw new ApiError(response.status, await getErrorPayload(response), `Request failed with status ${response.status}.`)
      }
    }

    async function requestBlob(path: string): Promise<Blob> {
      const token = await getAccessToken()
      if (!token) throw new Error("Sign in is required.")
      const response = await fetch(`${API_URL}${path}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!response.ok) {
        throw new ApiError(response.status, await getErrorPayload(response), `Request failed with status ${response.status}.`)
      }
      return response.blob()
    }

    return {
      createSemester: (payload: SemesterCreatePayload) =>
        request<Semester>("/semesters", { method: "POST", body: JSON.stringify(payload) }),
      listSemesters: () => request<Semester[]>("/semesters"),
      deleteSemester: (semesterId: string) =>
        requestVoid(`/semesters/${semesterId}`, { method: "DELETE" }),
      uploadSyllabi: async (semesterId: string, files: File[]) => {
        const body = new FormData()
        files.forEach((file) => body.append("files", normalizeUploadFile(file)))
        return request<{ jobs: ProcessingJob[] }>(`/semesters/${semesterId}/syllabi`, {
          method: "POST",
          body,
        })
      },
      listJobs: (semesterId: string) => request<ProcessingJob[]>(`/semesters/${semesterId}/jobs`),
      retryJob: (jobId: string) =>
        request<ProcessingJob>(`/jobs/${jobId}/retry`, { method: "POST" }),
      reprocessJob: (jobId: string) =>
        request<ProcessingJob>(`/jobs/${jobId}/reprocess`, { method: "POST" }),
      getReview: (semesterId: string) => request<ReviewPayload>(`/semesters/${semesterId}/review`),
      updateEvent: (eventId: string, payload: EventUpdate) =>
        request<ExtractedEvent>(`/extracted-events/${eventId}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        }),
      updateRecurringSeries: (seriesId: string, payload: RecurringSeriesUpdate) =>
        request<RecurringEventSeries>(`/recurring-series/${seriesId}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        }),
      updateCourse: (courseId: string, payload: CourseUpdatePayload) =>
        request<Course>(`/courses/${courseId}`, { method: "PATCH", body: JSON.stringify(payload) }),
      completeReview: (semesterId: string) =>
        request<ReviewCompleteResponse | ReviewBlockingDetail>(
          `/semesters/${semesterId}/review/complete`,
          {
            method: "POST",
          },
        ),
      listEvents: (semesterId: string) => request<ExtractedEvent[]>(`/semesters/${semesterId}/events`),
      getDocument: (documentId: string) => requestBlob(`/syllabus-documents/${documentId}/file`),
      getCalendar: (semesterId: string, courseIds: string[] = []) => {
        const params = new URLSearchParams()
        courseIds.forEach((courseId) => params.append("course_id", courseId))
        const search = params.size ? `?${params.toString()}` : ""
        return requestBlob(`/semesters/${semesterId}/calendar.ics${search}`)
      },
    }
  }, [getAccessToken])
}
