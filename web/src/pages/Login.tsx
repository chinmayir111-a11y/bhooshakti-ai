import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, setSession } from '../api/client'
import { DemoBadge } from '../components/common'

export default function Login() {
  const navigate = useNavigate()
  const [demos, setDemos] = useState<any[]>([])
  const [username, setUsername] = useState('authority')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.demoLogins().then((d) => {
      setDemos(d)
      if (d[0]) setPassword(d[0].password)
    }).catch(() => setError('Cannot reach the API. Is the backend running on port 8000?'))
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
            AI landslide early warning &amp; risk monitoring — North-East India
          </div>
          <div style={{ marginTop: 14 }}><DemoBadge /></div>
        </div>

        <div className="card" style={{ borderTop: 0 }}>
          <div className="card-body">
            <p className="notice">
              <strong>Demo system — not connected to any live service.</strong> Rainfall and
              soil moisture are real observed data; landslide events, sensor readings and
              alerts are simulated. Risk output is decision support with a confidence
              score, never a guaranteed prediction.
            </p>

            <div className="grid-2" style={{ marginTop: 18 }}>
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
                <p className="tiny muted" style={{ marginTop: 12, textAlign: 'center' }}>
                  Citizens can <a href="/report">report a hazard</a> without an account.
                </p>
              </form>

              <div>
                <span className="label">Demo accounts</span>
                <div className="stack" style={{ marginTop: 10 }}>
                  {demos.map((d) => (
                    <button key={d.username} className="card" type="button"
                            style={{ display: 'block', width: '100%', textAlign: 'left', cursor: 'pointer', font: 'inherit', padding: 0 }}
                            onClick={(e) => { setUsername(d.username); setPassword(d.password); submit(e as any, d.username, d.password) }}>
                      <div className="card-body" style={{ padding: 12 }}>
                        <div className="row" style={{ justifyContent: 'space-between' }}>
                          <strong style={{ color: 'var(--navy)', fontSize: 13.5 }}>{d.label}</strong>
                          <span className="pill">{d.role}</span>
                        </div>
                        <div className="tiny muted" style={{ marginTop: 4 }}>{d.description}</div>
                        <div className="mono tiny" style={{ marginTop: 6 }}>{d.username} / {d.password}</div>
                      </div>
                    </button>
                  ))}
                  {demos.length === 0 && <p className="muted tiny">Loading demo accounts…</p>}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
