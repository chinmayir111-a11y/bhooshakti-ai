import { NavLink, useNavigate } from 'react-router-dom'
import { clearSession, getUser } from '../api/client'
import { useControl } from '../control/context'
import { SeverityChip } from './Severity'

export { SEVERITY_FILL, SEVERITY_ORDER, SeverityChip, TierChip } from './Severity'

export function DemoBadge({ dark = false }: { dark?: boolean }) {
  return (
    <span className={`demo-badge${dark ? ' dark' : ''}`} title="Hazard events, sensors and zone boundaries on this screen are simulated. Weather and the historical landslide record are real.">
      DEMO
    </span>
  )
}

/** Provenance badge next to a number: REAL · Open-Meteo, REAL · live sensor, SIMULATED. */
export function Src({ kind, label }: { kind: 'real' | 'live' | 'sim'; label?: string }) {
  const { sources } = useControl()
  if (!sources) return null
  const text = label ?? (kind === 'real' ? 'REAL' : kind === 'live' ? 'REAL · live sensor' : 'SIMULATED')
  return <span className={`provbadge ${kind}`}>{text}</span>
}

/** Control-room header: brand, nav, the three global toggles, identity. */
export function AppHeader() {
  const user = getUser()
  const navigate = useNavigate()
  const authority = user?.role === 'authority'
  const { dark, setDark, sources, setSources, sound, setSound } = useControl()

  async function toggleSound() {
    const next = !sound
    setSound(next)
    if (next && 'Notification' in window && Notification.permission === 'default') {
      try { await Notification.requestPermission() } catch { /* ignore */ }
    }
  }

  return (
    <header className="app-header">
      <div className="brand">
        <span className="brand-mark">BHOOSHAKTI AI</span>
        <span className="brand-sub">Control room — landslide early warning, North-East India</span>
      </div>
      <div className="header-spacer" />
      <nav className="nav">
        <NavLink to="/control" end>Dashboard</NavLink>
        <NavLink to="/control/alerts">Alerts</NavLink>
        {authority && <NavLink to="/control/moderation">Reports</NavLink>}
        <NavLink to="/replay">Replay</NavLink>
        {authority && <NavLink to="/control/audit">Audit</NavLink>}
        <NavLink to="/">Citizen app</NavLink>
      </nav>
      <div className="hdr-controls">
        <button className={`hdr-toggle${sources ? ' on' : ''}`} onClick={() => setSources(!sources)}
                title="Label every number with where it comes from">Show data sources</button>
        <button className={`hdr-toggle${sound ? ' on' : ''}`} onClick={toggleSound}
                title="Chime and browser notification on a new WARNING">{sound ? '🔔 Sound on' : '🔕 Sound off'}</button>
        <button className={`hdr-toggle${dark ? ' on' : ''}`} onClick={() => setDark(!dark)} title="Dark mode">
          {dark ? '☀' : '☾'}
        </button>
      </div>
      {user ? (
        <>
          <div className="who">
            <strong>{user.full_name || user.username}</strong>
            {user.designation || user.role}
          </div>
          <button className="btn ghost sm" onClick={() => { clearSession(); navigate('/login') }}>
            Sign out
          </button>
        </>
      ) : (
        <button className="btn ghost sm" onClick={() => navigate('/login')}>Sign in</button>
      )}
    </header>
  )
}

export function PageTitle({ title, subtitle, children }: {
  title: string; subtitle: string; children?: React.ReactNode
}) {
  return (
    <div className="page-title-row">
      <div style={{ flex: '1 1 auto', minWidth: 0 }}>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      {children}
    </div>
  )
}

/** Ranked contributing factors. Factors that argue against risk read muted. */
export function FactorList({ factors, limit }: { factors: Array<{ text: string; weight: number; direction: string }>; limit?: number }) {
  const shown = limit ? factors.slice(0, limit) : factors
  if (!shown.length) return <p className="muted tiny" style={{ marginTop: 8 }}>No contributing factors recorded.</p>
  return (
    <ol className="factor-list">
      {shown.map((f, i) => (
        <li key={i}>
          <span className="factor-rank">{i + 1}</span>
          <span style={{ flex: '1 1 auto' }}>
            <span className={`factor-text${f.direction !== 'increases' ? ' down' : ''}`}>{f.text}</span>
            {f.weight > 0 && (
              <span className="factor-bar" style={{ width: `${Math.max(4, Math.round(f.weight * 100))}%` }} />
            )}
          </span>
        </li>
      ))}
    </ol>
  )
}

const CHANNEL_NAMES: Record<string, string> = {
  email: 'Email', sms: 'SMS', push: 'Push', voice: 'Voice call',
  websocket: 'WebSocket', console: 'Console',
}

/** One line per alert, deduplicated by channel. */
export function DeliveryChips({ deliveries }: {
  deliveries: Array<{ channel: string; status: string; detail?: string }>
}) {
  if (!deliveries?.length) return null
  const byChannel = new Map<string, Set<string>>()
  for (const d of deliveries) {
    if (!byChannel.has(d.channel)) byChannel.set(d.channel, new Set())
    byChannel.get(d.channel)!.add(d.status)
  }
  const sent: string[] = [], simulated: string[] = [], failed: string[] = []
  for (const [channel, statuses] of byChannel) {
    const name = CHANNEL_NAMES[channel] ?? channel
    if (statuses.has('SENT')) sent.push(name)
    else if (statuses.has('SIMULATED')) simulated.push(name)
    else failed.push(name)
  }
  const parts: string[] = []
  if (sent.length) parts.push(`${sent.join(', ')} sent`)
  if (simulated.length) parts.push(`${simulated.join(', ')} — simulated`)
  if (failed.length) parts.push(`${failed.join(', ')} failed`)
  return <div className="chan-line">{parts.join('  ·  ')}</div>
}

/** Rainfall bars with the soil-moisture trace over the top. */
export function Sparkline({ data }: { data: Array<{ rainfall_mm: number; soil_moisture_pct: number | null }> }) {
  if (!data.length) return <p className="muted tiny">No recent readings.</p>
  const W = 380, H = 62
  const maxRain = Math.max(1, ...data.map((d) => d.rainfall_mm))
  const bw = W / data.length
  const soilPts = data
    .map((d, i) => (d.soil_moisture_pct == null ? null : `${i * bw + bw / 2},${H - (d.soil_moisture_pct / 100) * H}`))
    .filter(Boolean).join(' ')
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
         aria-label="Hourly rainfall with soil moisture trace">
      {data.map((d, i) => {
        const h = (d.rainfall_mm / maxRain) * H
        return <rect key={i} className="spark-rain" x={i * bw} y={H - h} width={Math.max(bw - 0.6, 0.6)} height={h} />
      })}
      {soilPts && <polyline className="spark-soil" points={soilPts} vectorEffect="non-scaling-stroke" />}
    </svg>
  )
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const secs = Math.max(0, Math.floor((Date.now() - then) / 1000))
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString(undefined, {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}

export { SeverityChip as Sev }
