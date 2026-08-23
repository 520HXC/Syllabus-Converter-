import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  FileText,
  ListChecks,
  RefreshCw,
  Repeat,
  RotateCcw,
} from "lucide-react"
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom"

import { AppShell } from "../components/AppShell"
import { CourseReviewCard } from "../components/CourseReviewCard"
import { CourseRuleCard } from "../components/CourseRuleCard"
import { PdfViewer } from "../components/PdfViewer"
import { ErrorState, LoadingState } from "../components/QueryState"
import { ReviewCompletionState } from "../components/ReviewCompletionState"
import { ReviewEventCard } from "../components/ReviewEventCard"
import { RecurringSeriesCard } from "../components/RecurringSeriesCard"
import { Button } from "../components/ui/Button"
import { Card } from "../components/ui/Card"
import { useApi } from "../lib/api"
import { isAwaitingDate } from "../lib/awaitingDate"
import { resolveCourseDisplayColor } from "../lib/courseColors"
import { isCourseRule } from "../lib/courseRules"
import { useAuth } from "../lib/auth"
import { semesterQueryKey } from "../lib/queryKeys"
import { getReviewAttentionTarget } from "../lib/review"
import { useSemester } from "../lib/semester"
import type {
  Course,
  CourseUpdatePayload,
  EventUpdate,
  ExtractedEvent,
  ReviewBlockingDetail,
  ReviewPayload,
  ReviewStatus,
} from "../lib/types"
import { cn } from "../lib/utils"
import { useTheme } from "../theme/ThemeProvider"

function sortEvents(events: ExtractedEvent[]) {
  return [...events].sort((left, right) => {
    if (left.review_status === "needs_review" && right.review_status !== "needs_review") return -1
    if (left.review_status !== "needs_review" && right.review_status === "needs_review") return 1
    if (left.event_date && right.event_date) {
      return left.event_date.localeCompare(right.event_date) || left.title.localeCompare(right.title)
    }
    if (left.event_date) return -1
    if (right.event_date) return 1
    return left.title.localeCompare(right.title)
  })
}

function getBlockingDetail(error: unknown): ReviewBlockingDetail | null {
  if (error instanceof Error && typeof error === "object" && error && "blocking_event_ids" in error) {
    const detail = error as Error & {
      blocking_event_ids?: string[]
      blocking_document_ids?: string[]
      blocking_count?: number
    }
    if (!Array.isArray(detail.blocking_event_ids)) return null
    return {
      detail: detail.message,
      blocking_event_ids: detail.blocking_event_ids,
      blocking_document_ids: detail.blocking_document_ids ?? [],
      blocking_count: detail.blocking_count ?? detail.blocking_event_ids.length,
    }
  }
  return null
}

function groupEventsByCourse(events: ExtractedEvent[], courses: Course[]) {
  return courses
    .map((course) => ({
      course,
      events: events.filter((event) => event.course_id === course.id),
    }))
    .filter((group) => group.events.length > 0)
}

type ReviewPageMode = "active" | "editing" | "completed"

function getReviewPageMode({
  reviewCompletedAt,
  unresolvedCount,
  modeParam,
  eventId,
}: {
  reviewCompletedAt: string | null
  unresolvedCount: number
  modeParam: string | null
  eventId: string | null
}): ReviewPageMode {
  if (unresolvedCount > 0) return "active"
  if (modeParam === "edit" || Boolean(eventId)) return "editing"
  if (reviewCompletedAt) return "completed"
  return "active"
}

export function ReviewPage() {
  const api = useApi()
  const navigate = useNavigate()
  const { resolvedTheme } = useTheme()
  const { user } = useAuth()
  const [searchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const { semesterId } = useSemester()
  const [mobileTab, setMobileTab] = useState<"document" | "results">("results")
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null)
  const [showReviewed, setShowReviewed] = useState(false)
  const [showSavedForLater, setShowSavedForLater] = useState(false)
  const [showRemoved, setShowRemoved] = useState(false)
  const [deepLinkNotice, setDeepLinkNotice] = useState<string | null>(null)
  const [handledEventId, setHandledEventId] = useState<string | null>(null)
  const [removedNotice, setRemovedNotice] = useState<{ eventId: string; title: string } | null>(null)
  const [pendingFocusEventId, setPendingFocusEventId] = useState<string | null>(null)
  const [pendingFocusSeriesId, setPendingFocusSeriesId] = useState<string | null>(null)
  const [optimisticRemovedEventIds, setOptimisticRemovedEventIds] = useState<string[]>([])
  const [eventActionError, setEventActionError] = useState<string | null>(null)
  const reviewQuery = useQuery({
    queryKey: ["review", semesterId],
    queryFn: () => api.getReview(semesterId!),
    enabled: Boolean(semesterId),
  })
  const eventMutation = useMutation({
    mutationFn: ({ id, update }: { id: string; update: EventUpdate }) => api.updateEvent(id, update),
  })
  const courseMutation = useMutation({
    mutationFn: ({ id, values }: { id: string; values: CourseUpdatePayload }) =>
      api.updateCourse(id, values),
  })
  const recurringSeriesMutation = useMutation({
    mutationFn: ({ id, reviewStatus }: { id: string; reviewStatus: ReviewStatus }) =>
      api.updateRecurringSeries(id, { review_status: reviewStatus }),
  })
  const completeMutation = useMutation({
    mutationFn: () => api.completeReview(semesterId!),
  })

  const data = reviewQuery.data
  const modeParam = searchParams.get("mode")
  const eventId = searchParams.get("eventId")
  const recurringSeries = data?.recurring_series ?? []
  const recurringSeriesIds = useMemo(
    () => new Set(recurringSeries.map((series) => series.id)),
    [recurringSeries],
  )
  const belongsToKnownSeries = (event: ExtractedEvent) =>
    Boolean(event.recurring_series_id && recurringSeriesIds.has(event.recurring_series_id))
  const blockingEvents = useMemo(
    () =>
      (data?.events ?? []).filter(
        (event) =>
          event.review_status === "needs_review" &&
          !optimisticRemovedEventIds.includes(event.id),
      ),
    [data?.events, optimisticRemovedEventIds],
  )
  const unresolvedStandaloneEvents = blockingEvents.filter((event) => !belongsToKnownSeries(event))
  const unresolvedSeries = recurringSeries.filter((series) => series.review_status === "needs_review")
  const unresolvedCount = unresolvedStandaloneEvents.length + unresolvedSeries.length
  const documentStats = useMemo(() => {
    if (!data) return []
    return data.documents.map((document) => ({
      ...document,
      unresolvedCount:
        unresolvedStandaloneEvents.filter((event) => event.document_id === document.id).length +
        unresolvedSeries.filter((series) => series.document_id === document.id).length,
    }))
  }, [data, unresolvedSeries, unresolvedStandaloneEvents])
  const defaultDocumentId =
    documentStats.find((document) => document.unresolvedCount > 0)?.id ??
    documentStats[0]?.id ??
    null
  const reviewEvents = data?.events ?? []
  const currentDocumentId = selectedDocumentId ?? defaultDocumentId

  useEffect(() => {
    if (!selectedDocumentId && defaultDocumentId) setSelectedDocumentId(defaultDocumentId)
  }, [defaultDocumentId, selectedDocumentId])

  useEffect(() => {
    if (!pendingFocusEventId) return
    const card = document.querySelector<HTMLElement>(`[data-review-event-id="${pendingFocusEventId}"]`)
    if (!card) return
    const frame = requestAnimationFrame(() => {
      const focusEvent = reviewEvents.find((event) => event.id === pendingFocusEventId)
      const targetType =
        focusEvent && isAwaitingDate(focusEvent)
          ? "date"
          : getReviewAttentionTarget(focusEvent?.warning_codes ?? [])
      if (focusEvent && isCourseRule(focusEvent)) {
        const target =
          card.querySelector<HTMLElement>('button[aria-label^="Modify "]') ??
          card.querySelector<HTMLElement>("button, [tabindex='-1']") ??
          card
        target.scrollIntoView({ behavior: "smooth", block: "center" })
        target.focus()
        setPendingFocusEventId(null)
        return
      }
      const preferredDateField = card.querySelector<HTMLElement>('input[aria-label="Event date"]')
      const preferredNameField = card.querySelector<HTMLElement>('input[aria-label="Event name"]')
      const target =
        (targetType === "date"
          ? preferredDateField ?? card.querySelector<HTMLElement>('[data-focus-target="date"]')
          : targetType === "source"
            ? card.querySelector<HTMLElement>('[data-focus-target="source"]')
            : preferredNameField) ??
        preferredNameField ??
        preferredDateField ??
        card.querySelector<HTMLElement>('input, textarea, button, [tabindex="0"], [tabindex="-1"]') ??
        card
      target.scrollIntoView({ behavior: "smooth", block: "center" })
      target.focus()
      setPendingFocusEventId(null)
    })
    return () => cancelAnimationFrame(frame)
  }, [currentDocumentId, pendingFocusEventId, reviewEvents])

  useEffect(() => {
    if (!pendingFocusSeriesId) return
    const card = document.querySelector<HTMLElement>(
      `[data-recurring-series-id="${pendingFocusSeriesId}"]`,
    )
    if (!card) return
    card.scrollIntoView({ behavior: "smooth", block: "center" })
    card.focus()
    setPendingFocusSeriesId(null)
  }, [currentDocumentId, pendingFocusSeriesId])

  useEffect(() => {
    const eventId = searchParams.get("eventId")
    if (!eventId) {
      if (handledEventId !== null) setHandledEventId(null)
      return
    }
    if (!data || handledEventId === eventId) return
    const targetEvent = data.events.find((event) => event.id === eventId) ?? null
    if (targetEvent) {
      jumpToEvent(targetEvent)
      setDeepLinkNotice(null)
      setHandledEventId(eventId)
      return
    }
    setDeepLinkNotice("We could not find that calendar item.")
    jumpToEvent(sortEvents(blockingEvents)[0] ?? data.events[0] ?? null)
    setHandledEventId(eventId)
  }, [blockingEvents, data, handledEventId, searchParams])

  if (!semesterId) return <Navigate replace to="/setup" />
  if (reviewQuery.isLoading) {
    return (
      <AppShell currentStep={3}>
        <LoadingState label="Loading extracted details" />
      </AppShell>
    )
  }
  if (!data) {
    return (
      <AppShell currentStep={3}>
        <ErrorState
          message={reviewQuery.error?.message ?? "Review data is not available."}
          onRetry={() => reviewQuery.refetch()}
        />
      </AppShell>
    )
  }

  const reviewData = data
  const courseDisplayColors = new Map(
    reviewData.courses.map((course) => [
      course.id,
      resolveCourseDisplayColor(course.id, course.color, resolvedTheme),
    ]),
  )
  const courseById = new Map(reviewData.courses.map((course) => [course.id, course]))
  const countableReviewEvents = reviewData.events.filter(
    (event) => !(isCourseRule(event) && event.review_status === "confirmed"),
  )
  const totalEvents = countableReviewEvents.length
  const totalDecisionCount =
    countableReviewEvents.filter((event) => !belongsToKnownSeries(event)).length + recurringSeries.length
  const resolvedCount = totalDecisionCount - unresolvedCount
  const resolvedPercent = totalDecisionCount
    ? Math.round((resolvedCount / totalDecisionCount) * 100)
    : 0
  const currentDocument = reviewData.documents.find((item) => item.id === currentDocumentId) ?? null
  const courses = currentDocumentId
    ? reviewData.courses.filter((course) => course.document_id === currentDocumentId)
    : reviewData.courses
  const deepLinkedSavedRuleId =
    eventId && data.events.some((event) => event.id === eventId && isCourseRule(event) && event.review_status === "pending")
      ? eventId
      : null
  const eventsForDocument = currentDocumentId
    ? sortEvents(reviewData.events.filter((event) => event.document_id === currentDocumentId))
    : sortEvents(reviewData.events)
  const standaloneEvents = eventsForDocument.filter((event) => !belongsToKnownSeries(event))
  const courseRules = sortEvents(
    standaloneEvents.filter(
      (event) =>
        isCourseRule(event) &&
        (event.review_status === "needs_review" || event.id === deepLinkedSavedRuleId),
    ),
  )
  const standardStandaloneEvents = standaloneEvents.filter((event) => !isCourseRule(event))
  const seriesForDocument = recurringSeries.filter(
    (series) => !currentDocumentId || series.document_id === currentDocumentId,
  )
  const activeEvents = standardStandaloneEvents.filter(
    (event) =>
      event.review_status === "needs_review" && !optimisticRemovedEventIds.includes(event.id),
  )
  const activeGroups = groupEventsByCourse(activeEvents, courses)
  const reviewedEvents = standardStandaloneEvents.filter(
    (event) =>
      event.review_status === "confirmed" ||
      (event.review_status === "pending" && !isAwaitingDate(event)),
  )
  const savedForLaterEvents = standardStandaloneEvents.filter((event) => isAwaitingDate(event))
  const savedForLaterPanelId = "saved-for-later-panel"
  const removedEvents = standaloneEvents.filter((event) => event.review_status === "ignored")
  const unresolvedEvents = sortEvents(unresolvedStandaloneEvents)
  const nextUnresolvedEvent = unresolvedEvents[0] ?? null
  const nextUnresolvedSeries = unresolvedSeries[0] ?? null
  const hasPendingEventAction = eventMutation.isPending || optimisticRemovedEventIds.length > 0
  const confirmedCount = reviewData.events.filter(
    (event) => !isCourseRule(event) && event.review_status === "confirmed",
  ).length
  const savedForLaterCount = reviewData.events.filter(
    (event) => !isCourseRule(event) && event.review_status === "pending",
  ).length
  const awaitingDateCount = reviewData.events.filter((event) => isAwaitingDate(event)).length
  const savedRuleCount = reviewData.events.filter(
    (event) => isCourseRule(event) && event.review_status === "pending",
  ).length
  const removedCount = reviewData.events.filter((event) => event.review_status === "ignored").length
  const pageMode = getReviewPageMode({
    reviewCompletedAt: reviewData.semester.review_completed_at,
    unresolvedCount,
    modeParam,
    eventId,
  })

  async function saveEvent(id: string, update: EventUpdate) {
    const isOptimisticRemove = update.review_status === "ignored"
    if (isOptimisticRemove) {
      setOptimisticRemovedEventIds((current) => (current.includes(id) ? current : [...current, id]))
    }
    setEventActionError(null)

    let updated: ExtractedEvent
    try {
      updated = await eventMutation.mutateAsync({ id, update })
    } catch (caught) {
      if (isOptimisticRemove) {
        setOptimisticRemovedEventIds((current) => current.filter((eventId) => eventId !== id))
        setEventActionError(caught instanceof Error ? caught.message : "The event could not be saved.")
      }
      throw caught
    }

    queryClient.setQueryData<ReviewPayload>(["review", semesterId], (current) =>
      current
        ? {
            ...current,
            events: current.events.map((event) => (event.id === updated.id ? updated : event)),
          }
        : current,
    )
    queryClient.setQueryData<ExtractedEvent[] | undefined>(["events", semesterId], (current) => {
      if (typeof current === "undefined") return current
      if (updated.review_status !== "confirmed") {
        return current.filter((event) => event.id !== updated.id)
      }
      const existingIndex = current.findIndex((event) => event.id === updated.id)
      if (existingIndex === -1) return [...current, updated]
      return current.map((event) => (event.id === updated.id ? updated : event))
    })
    void queryClient.invalidateQueries({ queryKey: ["events", semesterId] })
    if (updated.review_status === "ignored") {
      setRemovedNotice({ eventId: updated.id, title: updated.title })
    } else if (removedNotice?.eventId === updated.id) {
      setRemovedNotice(null)
    }
    if (isOptimisticRemove) {
      setOptimisticRemovedEventIds((current) => current.filter((eventId) => eventId !== id))
    }

    try {
      await reviewQuery.refetch({ throwOnError: true })
    } catch {
      setEventActionError("Event saved, but the review list could not be refreshed.")
    }
  }

  async function saveCourse(id: string, values: CourseUpdatePayload) {
    const updatedCourse = await courseMutation.mutateAsync({ id, values })
    queryClient.setQueryData<ReviewPayload>(["review", semesterId], (current) =>
      current
        ? {
            ...current,
            courses: current.courses.map((course) => (course.id === updatedCourse.id ? updatedCourse : course)),
          }
        : current,
    )

    try {
      await reviewQuery.refetch({ throwOnError: true })
    } catch {
      throw new Error("Course saved, but the review list could not be refreshed.")
    }
  }

  async function saveRecurringSeries(id: string, reviewStatus: ReviewStatus) {
    setEventActionError(null)
    await recurringSeriesMutation.mutateAsync({ id, reviewStatus })
    try {
      await Promise.all([
        reviewQuery.refetch({ throwOnError: true }),
        queryClient.invalidateQueries({ queryKey: ["events", semesterId] }),
      ])
    } catch {
      setEventActionError("Series saved, but the review list could not be refreshed.")
    }
  }

  function jumpToEvent(event: ExtractedEvent | null) {
    if (!event) return
    if (event.document_id) setSelectedDocumentId(event.document_id)
    setShowSavedForLater(isAwaitingDate(event))
    setShowReviewed(event.review_status === "confirmed" || (event.review_status === "pending" && !isAwaitingDate(event)))
    setShowRemoved(event.review_status === "ignored")
    setMobileTab("results")
    setPendingFocusEventId(event.id)
  }

  function jumpToSeries(series: (typeof recurringSeries)[number] | null) {
    if (!series) return
    if (series.document_id) setSelectedDocumentId(series.document_id)
    setMobileTab("results")
    setPendingFocusSeriesId(series.id)
  }

  async function handleUndoRemove() {
    if (!removedNotice) return
    try {
      await saveEvent(removedNotice.eventId, { review_status: "needs_review" })
    } catch (caught) {
      setEventActionError(caught instanceof Error ? caught.message : "The event could not be restored.")
    }
  }

  async function handleRestoreEvent(eventId: string) {
    try {
      await saveEvent(eventId, { review_status: "needs_review" })
    } catch (caught) {
      setEventActionError(caught instanceof Error ? caught.message : "The event could not be restored.")
    }
  }

  async function handleCompleteReview() {
    try {
      const response = await completeMutation.mutateAsync()
      if (!("review_completed_at" in response)) {
        throw response
      }
      queryClient.setQueryData<ReviewPayload>(["review", semesterId], (current) =>
        current
          ? {
              ...current,
              semester: {
                ...current.semester,
                review_completed_at: response.review_completed_at,
              },
            }
          : current,
      )
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["review", semesterId] }),
        queryClient.invalidateQueries({ queryKey: ["events", semesterId] }),
        queryClient.invalidateQueries({ queryKey: semesterQueryKey(user?.id) }),
      ])
      navigate("/calendar")
    } catch (error) {
      const blockingDetail = getBlockingDetail(error)
      if (!blockingDetail) return
      const refreshedReview = await reviewQuery.refetch()
      const nextData = refreshedReview.data ?? reviewData
      const blockingEvent =
        nextData.events.find((event) => blockingDetail.blocking_event_ids.includes(event.id)) ?? null
      if (blockingEvent) jumpToEvent(blockingEvent)
    }
  }

  const resultsPanel = (
    <div className="grid gap-4 pb-44 sm:pb-32" data-testid="review-results-panel">
      {activeGroups.map(({ course, events }) => (
        <section key={course.id} className="grid gap-3" aria-labelledby={`course-group-${course.id}`}>
          <Card className="border-border/80 bg-panel/95 p-4 shadow-panel">
            <div className="flex items-start gap-3">
              <span
                className="mt-1 h-12 w-1.5 rounded-full"
                style={{ backgroundColor: courseDisplayColors.get(course.id) ?? course.color }}
              />
              <div className="min-w-0">
                <h2 className="text-lg font-semibold text-text" id={`course-group-${course.id}`}>
                  {course.code || course.name}
                </h2>
                <p className="mt-1 text-sm text-text-muted">{course.name}</p>
              </div>
            </div>
          </Card>
          <CourseReviewCard
            course={course}
            courseDisplayColor={courseDisplayColors.get(course.id) ?? course.color}
            onSave={saveCourse}
          />
          {events.map((event) => (
            <ReviewEventCard
              key={event.id}
              courseColor={courseDisplayColors.get(course.id) ?? course.color}
              courseLabel={course.code || course.name || "Course"}
              event={event}
              onSave={saveEvent}
              startEditing={pendingFocusEventId === event.id}
            />
          ))}
        </section>
      ))}

      {seriesForDocument.map((series) => {
        const course = courseById.get(series.course_id)
        const occurrences = sortEvents(
          reviewData.events.filter((event) => event.recurring_series_id === series.id),
        )
        return (
          <RecurringSeriesCard
            courseColor={
              courseDisplayColors.get(series.course_id) ??
              resolveCourseDisplayColor(series.course_id, course?.color, resolvedTheme)
            }
            courseLabel={course?.code || course?.name || "Course"}
            key={series.id}
            occurrences={occurrences}
            focusEventId={
              pendingFocusEventId && occurrences.some((event) => event.id === pendingFocusEventId)
                ? pendingFocusEventId
                : null
            }
            onSaveEvent={saveEvent}
            onSaveSeries={saveRecurringSeries}
            series={series}
          />
        )
      })}

      {courseRules.length ? (
        <section className="grid gap-3" data-testid="course-rules-section">
          <Card className="border-border/80 bg-panel/95 p-4 shadow-panel">
            <div className="flex items-start gap-3">
              <span className="mt-1 grid size-10 place-items-center rounded-2xl bg-accent/10 text-accent">
                <Repeat aria-hidden="true" className="size-4" />
              </span>
              <div className="min-w-0">
                <h2 className="text-lg font-semibold text-text">Course rules</h2>
                <p className="mt-1 text-sm text-text-muted">
                  Save recurring policies separately when the syllabus describes a pattern instead of exact dates.
                </p>
              </div>
            </div>
          </Card>
          {courseRules.map((event) => {
            const course = courseById.get(event.course_id)
            return (
              <CourseRuleCard
                courseColor={
                  courseDisplayColors.get(event.course_id) ??
                  resolveCourseDisplayColor(event.course_id, course?.color, resolvedTheme)
                }
                courseLabel={course?.code || course?.name || "Course"}
                event={event}
                key={event.id}
                onSave={saveEvent}
              />
            )
          })}
        </section>
      ) : null}

      {!activeEvents.length &&
      !reviewedEvents.length &&
      !savedForLaterEvents.length &&
      !removedEvents.length &&
      !seriesForDocument.length &&
      !courseRules.length ? (
        <Card className="border-warning-border bg-warning-soft p-5 text-sm text-warning">
          No calendar events were found in this file. Check the PDF before finishing review.
        </Card>
      ) : null}

      {savedForLaterEvents.length ? (
        <Card className="overflow-hidden border-border/80 bg-panel/95">
          <button
            aria-expanded={showSavedForLater}
            aria-controls={savedForLaterPanelId}
            className="flex min-h-11 w-full items-center justify-between px-4 py-3 text-left text-sm font-semibold text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-bg-app"
            onClick={() => setShowSavedForLater((current) => !current)}
            type="button"
          >
            <span>Saved for later ({savedForLaterEvents.length})</span>
            <ChevronDown
              aria-hidden="true"
              className={cn(
                "size-4 transition-transform motion-reduce:transition-none",
                showSavedForLater && "rotate-180",
              )}
            />
          </button>
          {showSavedForLater ? (
            <div className="grid gap-4 border-t border-border/80 p-4" id={savedForLaterPanelId}>
              {savedForLaterEvents.map((event) => {
                const course = courseById.get(event.course_id)
                return (
                  <ReviewEventCard
                    key={event.id}
                    courseColor={
                      courseDisplayColors.get(event.course_id) ??
                      resolveCourseDisplayColor(event.course_id, course?.color, resolvedTheme)
                    }
                    courseLabel={course?.code || course?.name || "Course"}
                    event={event}
                    onSave={saveEvent}
                    startEditing={pendingFocusEventId === event.id}
                  />
                )
              })}
            </div>
          ) : null}
        </Card>
      ) : null}

      {reviewedEvents.length ? (
        <Card className="overflow-hidden border-border/80 bg-panel/95">
          <button
            aria-expanded={showReviewed}
            className="flex min-h-11 w-full items-center justify-between px-4 py-3 text-left text-sm font-semibold text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-bg-app"
            onClick={() => setShowReviewed((current) => !current)}
            type="button"
          >
            <span>Reviewed events ({reviewedEvents.length})</span>
            <ChevronDown
              aria-hidden="true"
              className={cn("size-4 transition-transform motion-reduce:transition-none", showReviewed && "rotate-180")}
            />
          </button>
          {showReviewed ? (
            <div className="grid gap-4 border-t border-border/80 p-4">
              {reviewedEvents.map((event) => {
                const course = courseById.get(event.course_id)
                return (
                  <ReviewEventCard
                    key={event.id}
                    courseColor={
                      courseDisplayColors.get(event.course_id) ??
                      resolveCourseDisplayColor(event.course_id, course?.color, resolvedTheme)
                    }
                    courseLabel={course?.code || course?.name || "Course"}
                    event={event}
                    onSave={saveEvent}
                    startEditing={pendingFocusEventId === event.id}
                  />
                )
              })}
            </div>
          ) : null}
        </Card>
      ) : null}

      {removedEvents.length ? (
        <Card className="overflow-hidden border-border/80 bg-panel/95">
          <button
            aria-expanded={showRemoved}
            className="flex min-h-11 w-full items-center justify-between px-4 py-3 text-left text-sm font-semibold text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-bg-app"
            onClick={() => setShowRemoved((current) => !current)}
            type="button"
          >
            <span>Removed events ({removedEvents.length})</span>
            <ChevronDown
              aria-hidden="true"
              className={cn("size-4 transition-transform motion-reduce:transition-none", showRemoved && "rotate-180")}
            />
          </button>
          {showRemoved ? (
            <div className="grid gap-3 border-t border-border/80 p-4">
              {removedEvents.map((event) => {
                const course = courseById.get(event.course_id)
                return (
                  <div
                    key={event.id}
                    className="flex flex-col gap-3 rounded-2xl border border-border/80 bg-panel-muted/35 p-4 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="flex items-start gap-3">
                      <span
                        className="mt-1 h-8 w-1.5 rounded-full"
                        style={{
                          backgroundColor:
                            courseDisplayColors.get(event.course_id) ??
                            resolveCourseDisplayColor(event.course_id, course?.color, resolvedTheme),
                        }}
                      />
                      <div>
                        <p className="font-semibold text-text">{event.title}</p>
                        <p className="mt-1 text-sm text-text-muted">Removed from the active review list</p>
                      </div>
                    </div>
                    <Button onClick={() => handleRestoreEvent(event.id)} type="button" variant="secondary">
                      <RotateCcw aria-hidden="true" className="size-4" />
                      Restore
                    </Button>
                  </div>
                )
              })}
            </div>
          ) : null}
        </Card>
      ) : null}
    </div>
  )

  if (pageMode === "completed") {
    return (
      <AppShell>
        <ReviewCompletionState
          awaitingDateCount={awaitingDateCount}
          confirmedCount={confirmedCount}
          onOpenCalendar={() => navigate("/calendar")}
          onReviewDecisions={() => navigate("/review?mode=edit")}
          removedCount={removedCount}
          savedForLaterCount={savedForLaterCount}
          savedRuleCount={savedRuleCount}
          semesterName={reviewData.semester.name}
        />
      </AppShell>
    )
  }

  return (
    <AppShell currentStep={pageMode === "active" ? 3 : undefined}>
      {deepLinkNotice ? (
        <div className="mb-4 rounded-2xl border border-warning-border bg-warning-soft px-4 py-3 text-sm font-medium text-warning">
          {deepLinkNotice}
        </div>
      ) : null}

      <Card className="mb-5 border-border/80 bg-panel/95 p-4 shadow-panel sm:p-5" data-testid="review-progress-summary">
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex min-h-8 items-center rounded-full border border-border bg-panel-muted/50 px-3 text-xs font-semibold uppercase tracking-[0.16em] text-text-subtle">
                  Review progress
                </span>
                {currentDocument ? (
                  <span className="inline-flex min-h-8 items-center rounded-full border border-border bg-panel px-3 text-xs font-semibold text-text-muted">
                    {currentDocument.filename}
                  </span>
                ) : null}
              </div>
              <p className="text-sm font-semibold uppercase tracking-[0.16em] text-text-subtle">
                {reviewData.semester.name}
              </p>
              <h1 className="text-2xl font-bold tracking-[-0.03em] text-text sm:text-3xl">
                {`${unresolvedCount} of ${totalDecisionCount} decisions left`}
              </h1>
              <p className="text-sm text-text-muted">
                Review AI suggestions, save undated items for later, and publish only the events you trust.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3 text-sm font-medium text-text-muted">
              <span>{resolvedCount} resolved</span>
              <span>{unresolvedCount} unresolved</span>
              <span>{resolvedPercent}%</span>
              <Link
                className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-border bg-panel px-3 text-sm font-semibold text-text transition-colors hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-bg-app"
                to="/processing"
              >
                <RefreshCw aria-hidden="true" className="size-4" />
                Manage syllabus files
              </Link>
            </div>
          </div>
          <div className="space-y-2">
            <div className="h-2 overflow-hidden rounded-full bg-panel-muted/70">
              <div
                className="h-full rounded-full bg-accent transition-[width] duration-150 motion-reduce:transition-none"
                style={{ width: `${resolvedPercent}%` }}
              />
            </div>
            <div className="flex items-center justify-between gap-3 text-sm text-text-muted">
              <span>{totalEvents} extracted events</span>
              <span>{pageMode === "editing" ? "Saved decisions are open for changes" : `${unresolvedCount} decisions left`}</span>
            </div>
          </div>
        </div>
      </Card>

      {data.documents.length > 1 ? (
        <div className="mb-5 flex gap-2 overflow-x-auto pb-1">
          {documentStats.map((document) => (
            <button
              key={document.id}
              data-has-unresolved={document.unresolvedCount > 0 ? "true" : "false"}
              data-selected={currentDocumentId === document.id ? "true" : "false"}
              className={cn(
                "min-h-11 shrink-0 rounded-2xl border px-4 py-2.5 text-left text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-bg-app",
                currentDocumentId === document.id && document.unresolvedCount
                  ? "border-warning-border bg-accent text-accent-contrast"
                  : currentDocumentId === document.id
                    ? "border-accent bg-accent text-accent-contrast"
                    : document.unresolvedCount
                      ? "border-warning-border bg-warning-soft text-warning"
                      : "border-border bg-panel text-text-muted hover:border-accent hover:text-accent",
              )}
              onClick={() => setSelectedDocumentId(document.id)}
              type="button"
            >
              <span className="block">{document.filename}</span>
              <span
                className={cn(
                  "mt-1 flex items-center gap-1 text-xs font-medium",
                  currentDocumentId === document.id && document.unresolvedCount
                    ? "text-warning-soft"
                    : currentDocumentId === document.id
                      ? "text-accent-contrast/80"
                      : document.unresolvedCount
                        ? "text-warning"
                        : "text-text-subtle",
                )}
              >
                {document.unresolvedCount ? (
                  <AlertTriangle aria-hidden="true" className="size-3.5" />
                ) : null}
                {document.unresolvedCount} unresolved
              </span>
            </button>
          ))}
        </div>
      ) : null}

      <div
        aria-label="Review workspace"
        className="mb-5 grid grid-cols-2 gap-2 rounded-2xl border border-border/80 bg-panel-muted/60 p-1 lg:hidden"
        role="tablist"
      >
        <button
          aria-controls="review-document-panel"
          aria-selected={mobileTab === "document"}
          className={cn(
            "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-3 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-bg-app",
            mobileTab === "document" ? "bg-panel text-accent shadow-sm" : "text-text-muted",
          )}
          id="review-document-tab"
          onClick={() => setMobileTab("document")}
          role="tab"
          type="button"
        >
          <FileText aria-hidden="true" className="size-4" />
          PDF
        </button>
        <button
          aria-controls="review-results-panel"
          aria-selected={mobileTab === "results"}
          className={cn(
            "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-3 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-bg-app",
            mobileTab === "results" ? "bg-panel text-accent shadow-sm" : "text-text-muted",
          )}
          id="review-results-tab"
          onClick={() => setMobileTab("results")}
          role="tab"
          type="button"
        >
          <ListChecks aria-hidden="true" className="size-4" />
          Extracted details
        </button>
      </div>

      <div className="lg:grid lg:grid-cols-[minmax(0,0.92fr)_minmax(28rem,1.08fr)] lg:gap-6">
        <div
          className={cn(mobileTab !== "document" && "hidden", "lg:block")}
          id="review-document-panel"
          role="tabpanel"
          aria-labelledby="review-document-tab"
        >
          {currentDocument ? (
            <PdfViewer documentId={currentDocument.id} filename={currentDocument.filename} />
          ) : (
            <Card className="flex min-h-[32rem] items-center justify-center border-border/80 bg-panel/95 p-6 text-sm text-text-muted">
              Select a PDF to review its extracted events.
            </Card>
          )}
        </div>
        <div
          className={cn(mobileTab !== "results" && "hidden", "lg:block")}
          id="review-results-panel"
          role="tabpanel"
          aria-labelledby="review-results-tab"
        >
          {resultsPanel}
        </div>
      </div>

      {removedNotice ? (
        <div className="pointer-events-none fixed inset-x-4 bottom-28 z-20 mx-auto max-w-xl">
          <div
            aria-live="polite"
            className="pointer-events-auto rounded-2xl border border-border/80 bg-panel/95 p-4 shadow-panel backdrop-blur"
          >
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="font-semibold text-text">Event removed.</p>
                <p className="mt-1 text-sm text-text-muted">
                  {removedNotice.title} moved to Removed events.
                </p>
              </div>
              <Button onClick={handleUndoRemove} type="button" variant="secondary">
                Undo
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      <div
        className="sticky bottom-24 mt-6 rounded-2xl border border-border/80 bg-panel/95 p-2.5 shadow-panel backdrop-blur sm:bottom-28 sm:p-4 lg:bottom-3"
        data-testid="review-sticky-footer"
      >
        <div className="flex items-center justify-between gap-2 sm:gap-3">
          <div className="flex min-w-0 items-center gap-2 sm:items-start sm:gap-3">
            <CheckCircle2
              aria-hidden="true"
              className={cn(
                "size-4 shrink-0 sm:mt-0.5 sm:size-5",
                unresolvedCount ? "text-warning" : "text-accent",
              )}
            />
            <div className="min-w-0">
              <p className="text-sm font-semibold leading-5 text-text sm:text-base">
                {pageMode === "editing"
                  ? "Everything has a decision"
                  : unresolvedCount
                    ? `${unresolvedCount} items still need a decision`
                    : "Everything has a decision"}
              </p>
              <p className="mt-0.5 hidden text-sm text-text-muted sm:block">
                {pageMode === "editing"
                  ? "Saved decisions are open for changes until you return to the completed page."
                  : "Saved for later items stay off the calendar until you confirm them."}
              </p>
            </div>
          </div>
          {unresolvedCount ? (
            <Button
              className="w-auto shrink-0 px-3 sm:px-4"
              onClick={() =>
                nextUnresolvedEvent
                  ? jumpToEvent(nextUnresolvedEvent)
                  : jumpToSeries(nextUnresolvedSeries)
              }
              type="button"
            >
              Review next
              <ArrowRight aria-hidden="true" className="size-4" />
            </Button>
          ) : (
            <Button
              className="w-auto shrink-0 px-3 text-xs sm:px-4 sm:text-sm"
              disabled={hasPendingEventAction}
              loading={completeMutation.isPending}
              onClick={pageMode === "editing" ? () => navigate("/review") : handleCompleteReview}
              type="button"
            >
              {pageMode === "editing" ? "Done editing" : "Finish and open Calendar"}
              <ArrowRight aria-hidden="true" className="size-4" />
            </Button>
          )}
        </div>
        {completeMutation.error ? (
          <p
            className="mt-2 rounded-xl border border-danger/35 bg-danger/10 px-3 py-2 text-sm font-medium text-danger"
            role="alert"
          >
            {completeMutation.error.message}
          </p>
        ) : null}
      </div>
      {eventActionError ? (
        <p className="mt-3 text-sm font-medium text-danger" role="status">
          {eventActionError}
        </p>
      ) : null}
    </AppShell>
  )
}
