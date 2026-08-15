import { lazy, Suspense, type ReactNode } from "react"
import { Navigate, Route, Routes } from "react-router-dom"

import { LoadingState } from "./components/QueryState"
import { SemesterGuard } from "./components/SemesterGuard"
import { useAuth } from "./lib/auth"
import { useSemester } from "./lib/semester"
import { LandingPage } from "./pages/LandingPage"

const SemesterSetupPage = lazy(() =>
  import("./pages/SemesterSetupPage").then((module) => ({ default: module.SemesterSetupPage })),
)
const SemestersPage = lazy(() =>
  import("./pages/SemestersPage").then((module) => ({ default: module.SemestersPage })),
)
const UploadPage = lazy(() =>
  import("./pages/UploadPage").then((module) => ({ default: module.UploadPage })),
)
const ProcessingPage = lazy(() =>
  import("./pages/ProcessingPage").then((module) => ({ default: module.ProcessingPage })),
)
const ReviewPage = lazy(() =>
  import("./pages/ReviewPage").then((module) => ({ default: module.ReviewPage })),
)
const CalendarPage = lazy(() =>
  import("./pages/CalendarPage").then((module) => ({ default: module.CalendarPage })),
)

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const { ready } = useSemester()
  if (loading) return <LoadingState label="Checking your session" />
  if (!user) return <Navigate replace to="/" />
  if (!ready) return <LoadingState label="Restoring your semester" />
  return children
}

function LandingRoute() {
  const { user, loading } = useAuth()
  if (loading) return <LoadingState label="Checking your session" />
  if (user) return <Navigate replace to="/semesters" />
  return <LandingPage />
}

export default function App() {
  return (
    <Suspense fallback={<LoadingState label="Opening this step" />}>
      <Routes>
        <Route path="/" element={<LandingRoute />} />
        <Route path="/semesters" element={<ProtectedRoute><SemestersPage /></ProtectedRoute>} />
        <Route path="/setup" element={<ProtectedRoute><SemesterSetupPage /></ProtectedRoute>} />
        <Route path="/upload" element={<ProtectedRoute><UploadPage /></ProtectedRoute>} />
        <Route path="/processing" element={<ProtectedRoute><SemesterGuard><ProcessingPage /></SemesterGuard></ProtectedRoute>} />
        <Route path="/review" element={<ProtectedRoute><SemesterGuard><ReviewPage /></SemesterGuard></ProtectedRoute>} />
        <Route path="/calendar" element={<ProtectedRoute><SemesterGuard><CalendarPage /></SemesterGuard></ProtectedRoute>} />
        <Route path="*" element={<Navigate replace to="/" />} />
      </Routes>
    </Suspense>
  )
}
