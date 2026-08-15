import { useEffect, type ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import { Navigate } from "react-router-dom"

import { useApi } from "../lib/api"
import { useAuth } from "../lib/auth"
import { semesterQueryKey } from "../lib/queryKeys"
import { useSemester } from "../lib/semester"
import { ErrorState, LoadingState } from "./QueryState"

export function SemesterGuard({ children }: { children: ReactNode }) {
  const api = useApi()
  const { user } = useAuth()
  const { semesterId, setSemesterId } = useSemester()
  const semestersQuery = useQuery({
    queryKey: semesterQueryKey(user?.id),
    queryFn: api.listSemesters,
    enabled: Boolean(user),
  })
  const semesters = semestersQuery.data ?? []
  const validSemester = semesters.some((semester) => semester.id === semesterId)

  useEffect(() => {
    if (semestersQuery.isSuccess && semesters.length && !validSemester) {
      setSemesterId(semesters[0].id)
    }
  }, [semesters, semestersQuery.isSuccess, setSemesterId, validSemester])

  if (!user) return <Navigate replace to="/" />
  if (semestersQuery.isPending) return <LoadingState label="Checking your semester" />
  if (semestersQuery.isError) {
    return <ErrorState message={semestersQuery.error.message} onRetry={() => semestersQuery.refetch()} />
  }
  if (!semesters.length) return <Navigate replace to="/setup" />
  if (!validSemester) return <LoadingState label="Opening your semester" />

  return children
}
