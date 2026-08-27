import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AppHeader } from './components/common'
import { getToken } from './api/client'
import Dashboard from './pages/Dashboard'
import Alerts from './pages/Alerts'
import Moderation from './pages/Moderation'
import Citizen from './pages/Citizen'
import Audit from './pages/Audit'
import Login from './pages/Login'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  if (!getToken()) return <Navigate to="/login" state={{ from: location }} replace />
  return <>{children}</>
}

export default function App() {
  const location = useLocation()
  // The citizen form and the login screen carry their own headers: both are
  // reachable without an account and must not imply a signed-in session.
  const bare = location.pathname === '/report' || location.pathname === '/login'

  return (
    <div className="app-shell">
      {!bare && <AppHeader />}
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/report" element={<Citizen />} />
        <Route path="/" element={<RequireAuth><Dashboard /></RequireAuth>} />
        <Route path="/alerts" element={<RequireAuth><Alerts /></RequireAuth>} />
        <Route path="/moderation" element={<RequireAuth><Moderation /></RequireAuth>} />
        <Route path="/audit" element={<RequireAuth><Audit /></RequireAuth>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  )
}
