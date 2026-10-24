/**
 * Two apps, one bundle split in two.
 *
 *   /            citizen app — public, tiny, no map libraries
 *   /control/*   officer dashboard — login; MapLibre + deck.gl load here only
 *   /replay      backtest replay — public, loads the 3D map on demand
 */
import { Suspense, lazy } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { getToken } from './api/client'
import CitizenHome from './citizen/Home'
import CitizenReport from './citizen/Report'
import CitizenSafe from './citizen/Safe'
import CitizenHelp from './citizen/Help'

const Control = lazy(() => import('./control/ControlApp'))
const Replay = lazy(() => import('./pages/Replay'))
const Login = lazy(() => import('./pages/Login'))

function RequireAuth({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  if (!getToken()) return <Navigate to="/login" state={{ from: location }} replace />
  return <>{children}</>
}

function Loading() {
  return (
    <div style={{ padding: 24, maxWidth: 720, margin: '0 auto' }}>
      <div className="skeleton" style={{ height: 28, width: '40%', marginBottom: 14 }} />
      <div className="skeleton" style={{ height: 120, marginBottom: 10 }} />
      <div className="skeleton" style={{ height: 120 }} />
    </div>
  )
}

export default function App() {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route path="/" element={<CitizenHome />} />
        <Route path="/report" element={<CitizenReport />} />
        <Route path="/safe" element={<CitizenSafe />} />
        <Route path="/help" element={<CitizenHelp />} />
        <Route path="/login" element={<Login />} />
        <Route path="/replay" element={<Replay />} />
        <Route path="/control/*" element={<RequireAuth><Control /></RequireAuth>} />
        {/* Old bookmarks from the first prototype. */}
        <Route path="/alerts" element={<Navigate to="/control/alerts" replace />} />
        <Route path="/moderation" element={<Navigate to="/control/moderation" replace />} />
        <Route path="/audit" element={<Navigate to="/control/audit" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  )
}
