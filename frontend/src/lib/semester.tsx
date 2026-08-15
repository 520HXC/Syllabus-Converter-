import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react"

import { useAuth } from "./auth"
import { clearStoredSemester, getStoredSemester, setStoredSemester } from "./semesterStorage"

interface SemesterState {
  semesterId: string | null
  ready: boolean
  setSemesterId: (semesterId: string | null) => void
  clearSemesterId: () => void
}

const SemesterContext = createContext<SemesterState | null>(null)

export function SemesterProvider({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const [semesterId, setSemesterIdState] = useState<string | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (loading) {
      setReady(false)
      return
    }
    setSemesterIdState(user ? getStoredSemester(user.id) : null)
    setReady(true)
  }, [loading, user])

  const value = useMemo(
    () => ({
      semesterId,
      ready,
      setSemesterId: (next: string | null) => {
        setSemesterIdState(next)
        if (!user) return
        if (next) setStoredSemester(user.id, next)
        else clearStoredSemester(user.id)
      },
      clearSemesterId: () => {
        setSemesterIdState(null)
        if (user) clearStoredSemester(user.id)
      },
    }),
    [ready, semesterId, user],
  )
  return <SemesterContext.Provider value={value}>{children}</SemesterContext.Provider>
}

export function useSemester() {
  const value = useContext(SemesterContext)
  if (!value) throw new Error("useSemester must be used inside SemesterProvider")
  return value
}
