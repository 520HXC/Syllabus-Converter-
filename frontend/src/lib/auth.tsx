import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import type { User } from "@supabase/supabase-js"
import { useQueryClient } from "@tanstack/react-query"

import { clearStoredSemester } from "./semesterStorage"
import { authMode, supabase } from "./supabase"

const DEMO_USER_ID = "11111111-1111-4111-8111-111111111111"
const DEMO_KEY = "syllabus-calendar-demo-session"

interface AuthState {
  user: Pick<User, "id" | "email"> | null
  loading: boolean
  isDemo: boolean
  signIn: () => Promise<void>
  signOut: () => Promise<void>
  getAccessToken: () => Promise<string | null>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [user, setUser] = useState<Pick<User, "id" | "email"> | null>(null)
  const [loading, setLoading] = useState(true)
  const previousUserId = useRef<string | null>(null)
  const isDemo = authMode === "demo"

  const applyUser = useCallback((nextUser: Pick<User, "id" | "email"> | null) => {
    const nextUserId = nextUser?.id ?? null
    if (previousUserId.current && previousUserId.current !== nextUserId) queryClient.clear()
    previousUserId.current = nextUserId
    setUser(nextUser)
  }, [queryClient])

  useEffect(() => {
    if (isDemo) {
      if (localStorage.getItem(DEMO_KEY) === "active") {
        applyUser({ id: DEMO_USER_ID, email: "demo@example.com" })
      }
      setLoading(false)
      return
    }
    if (!supabase) {
      setLoading(false)
      return
    }
    supabase.auth.getSession().then(({ data }) => {
      applyUser(data.session?.user ?? null)
      setLoading(false)
    })
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      applyUser(session?.user ?? null)
      setLoading(false)
    })
    return () => data.subscription.unsubscribe()
  }, [applyUser, isDemo])

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      isDemo,
      signIn: async () => {
        if (isDemo) {
          localStorage.setItem(DEMO_KEY, "active")
          applyUser({ id: DEMO_USER_ID, email: "demo@example.com" })
          return
        }
        if (!supabase) throw new Error("Supabase authentication is not configured.")
        const { error } = await supabase.auth.signInWithOAuth({
          provider: "google",
          options: { redirectTo: `${window.location.origin}/semesters` },
        })
        if (error) throw error
      },
      signOut: async () => {
        const currentUserId = user?.id
        if (isDemo) {
          localStorage.removeItem(DEMO_KEY)
          if (currentUserId) clearStoredSemester(currentUserId)
          queryClient.clear()
          applyUser(null)
          return
        }
        if (!supabase) throw new Error("Supabase authentication is not configured.")
        const { error } = await supabase.auth.signOut()
        if (error) throw error
        if (currentUserId) clearStoredSemester(currentUserId)
        queryClient.clear()
      },
      getAccessToken: async () => {
        if (isDemo) return user ? DEMO_USER_ID : null
        const { data } = await supabase!.auth.getSession()
        return data.session?.access_token ?? null
      },
    }),
    [applyUser, isDemo, loading, queryClient, user],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error("useAuth must be used inside AuthProvider")
  return value
}
