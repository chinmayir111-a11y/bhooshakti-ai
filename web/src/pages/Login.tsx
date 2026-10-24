import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { api, setSession } from '../api/client'
import { HillsHeader } from '../components/Pictograms'
import '../styles/theme.css'

export default function Login() {
  const navigate = useNavigate()
  const location = useLocation() as { state?: { from?: { pathname: string } } }
  const [username, setUsername] = useState('authority')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.demoLogins()
      .then((d) => { if (d[0]) setPassword(d[0].password) })
      .catch(() => setError('Cannot reach the API. Is the backend running on port 8000?'))
  }, [])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      const r = await api.login(username, password)
      setSession(r.access_token, { username: r.username, role: r.role, full_name: r.full_name, designation: r.designation })
      navigate(location.state?.from?.pathname ?? '/control')
    } catch (err: any) {
      setError(err?.message ?? 'Sign-in failed')
    } finally { setBusy(false) }
  }

  return (
    <div className="app-shell" style={{ minHeight: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
      <div className="card" style={{ width: '100%', maxWidth: 780 }}>
        <div style={{ position: 'relative', height: 110, overflow: 'hidden' }}>
          <HillsHeader className="login-hills" />
          <div style={{ position: 'relative', padding: '26px 30px', color: '#fff' }}>
            <div style={{ fontSize: 21, fontWeight: 800, letterSpacing: '.12em' }}>BHOOSHAKTI AI</div>
            <div style={{ fontSize: 13, marginTop: 5, opacity: .9 }}>Control room sign-in</div>
          </div>
        </div>
        <div className="card-body">
          <div className="grid-2">
            <form onSubmit={submit}>
              <div className="field">
                <label className="label" htmlFor="u">Username</label>
                <input id="u" type="text" value={username} autoComplete="username" onChange={(e) => setUsername(e.target.value)} />
              </div>
              <div className="field">
                <label className="label" htmlFor="p">Password</label>
                <input id="p" type="password" value={password} autoComplete="current-password" onChange={(e) => setPassword(e.target.value)} />
              </div>
              {error && <p className="notice" style={{ marginBottom: 12 }}>{error}</p>}
              <button className="btn block" type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
              <p className="tiny muted" style={{ marginTop: 12 }}>Demo build. Weather and the historical landslide record are real; the storm, sensors and alerts are not.</p>
            </form>
            <div>
              <span className="label">Demo accounts</span>
              <p style={{ marginTop: 10, fontSize: 14.5, lineHeight: 1.65 }}>
                <strong>authority</strong> for the full control room, <strong>field.officer</strong> for assigned zones,
                <strong> citizen</strong> for the public view. Password <span className="mono">demo1234</span>.
              </p>
              <p style={{ marginTop: 12, fontSize: 14.5 }}>
                The public app needs no account: <Link to="/">report a landslide, check if you are safe</Link>.
                The backtest on real landslides is at <Link to="/replay">/replay</Link>.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
