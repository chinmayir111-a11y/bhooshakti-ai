import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, setSession } from '../api/client'

export default function Login() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('authority')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    // Prefill the shared demo password, and surface early if the API is down.
    api.demoLogins()
      .then((d) => { if (d[0]) setPassword(d[0].password) })
      .catch(() => setError('Cannot reach the API. Is the backend running on port 8000?'))
  }, [])

  async function submit(e: React.FormEvent, u = username, p = password) {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      const r = await api.login(u, p)
      setSession(r.access_token, {
        username: r.username, role: r.role, full_name: r.full_name, designation: r.designation,
      })
      navigate('/')
    } catch (err: any) {
      setError(err?.message ?? 'Sign-in failed')
    } finally { setBusy(false) }
  }

  return (
    <div style={{ minHeight: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
      <div style={{ width: '100%', maxWidth: 780 }}>
        <div style={{ background: 'var(--navy)', padding: '26px 30px' }}>
          <div style={{ color: '#fff', fontSize: 21, fontWeight: 700, letterSpacing: '.12em' }}>BHOOSHAKTI AI</div>
          <div style={{ color: '#A8BCD1', fontSize: 13, marginTop: 5 }}>
            Landslide early warning for North-East India
          </div>
        </div>

        <div className="card" style={{ borderTop: 0 }}>
          <div className="card-body">
            <div className="grid-2">
              <form onSubmit={submit}>
                <div className="field">
                  <label className="label" htmlFor="u">Username</label>
                  <input id="u" type="text" value={username} autoComplete="username"
                         onChange={(e) => setUsername(e.target.value)} />
                </div>
                <div className="field">
                  <label className="label" htmlFor="p">Password</label>
                  <input id="p" type="password" value={password} autoComplete="current-password"
                         onChange={(e) => setPassword(e.target.value)} />
                </div>
                {error && <p className="notice" style={{ marginBottom: 12 }}>{error}</p>}
                <button className="btn block" type="submit" disabled={busy}>
                  {busy ? 'Signing in…' : 'Sign in'}
                </button>
                <p className="tiny muted" style={{ marginTop: 12 }}>
                  Demo build. Weather data is real; landslide events and alerts are not.
                </p>
              </form>

              <div>
                <span className="label">Demo accounts</span>
                <p style={{ marginTop: 10, fontSize: 14.5, lineHeight: 1.65 }}>
                  Sign in as <strong>authority</strong> for the full dashboard,
                  <strong> field.officer</strong> for assigned zones and slope
                  verification, or <strong>citizen</strong> for the public view.
                  All three use the password <span className="mono">demo1234</span>.
                </p>
                <p style={{ marginTop: 12, fontSize: 14.5 }}>
                  Citizens can <a href="/report">report a hazard</a> without an account.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
