import { NavLink, useNavigate } from 'react-router-dom'
import { clearSession, getUser, type Severity } from '../api/client'

export const SEVERITY_ORDER: Severity[] = ['CRITICAL', 'HIGH', 'MODERATE', 'LOW']

export const SEVERITY_FILL: Record<Severity, string> = {
  LOW: '#D6DFEA', MODERATE: '#A8BCD1', HIGH: '#5C7EA4', CRITICAL: '#1F3864',
}

export function SeverityChip({ value }: { value: Severity | string }) {
  return <span className={`sev sev-${value}`}>{value}</span>
}

export function DemoBadge({ dark = false }: { dark?: boolean }) {
  return (
    <span className={`demo-badge${dark ? ' dark' : ''}`} title="Every figure on this screen is simulated. No live government feed or physical sensor is connected.">
      DEMO DATA
    </span>
  )
}

/** Every page carries the product name, a one-line subtitle and the badge. */
export function AppHeader() {
  const user = getUser()
  const navigate = useNavigate()
  const authority = user?.role === 'authority'

  return (
    <header className="app-header">
      <div className="brand">
        <span className="brand-mark">BHOOSHAKTI AI</span>
        <span className="brand-sub">Landslide early warning &amp; risk monitoring — North-East India</span>
      </div>
      <div className="header-spacer" />
      <nav className="nav">
        <NavLink to="/" end>Dashboard</NavLink>
        <NavLink to="/alerts">Alerts</NavLink>
        {authority && <NavLink to="/moderation">Moderation</NavLink>}
        <NavLink to="/report">Report</NavLink>
        {authority && <NavLink to="/audit">Audit</NavLink>}
      </nav>
      <DemoBadge />
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

export function DeliveryChips({ deliveries }: { deliveries: Array<{ channel: string; status: string; detail?: string }> }) {
  return (
    <div className="alert-chans">
      {deliveries.map((d, i) => (
        <span
          key={i}
          className={`chan ${d.status === 'SENT' ? 'ok' : d.status === 'FAILED' ? 'fail' : 'sim'}`}
          title={`${d.status}${d.detail ? ` — ${d.detail}` : ''}`}
        >
          {d.channel}{d.status === 'SIMULATED' ? ' · sim' : ''}
        </span>
      ))}
    </div>
  )
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
