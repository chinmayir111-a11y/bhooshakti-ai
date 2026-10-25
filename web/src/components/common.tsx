import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { clearSession, getUser } from '../api/client'
import { useControl } from '../control/context'
import { SeverityChip } from './Severity'

export { SEVERITY_FILL, SEVERITY_ORDER, SeverityChip, TierChip } from './Severity'
import { IconGear, IconMoon, IconSun } from './Pictograms'

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

/** One settings menu (gear): Show data sources, Sound, Light/Dark. Used by
 *  the control-room header and the replay page. */
export function SettingsMenu() {
  const { dark, setDark, sources, setSources, sound, setSound } = useControl()
  const [open, setOpen] = useState(false)
  async function toggleSound() {
    const next = !sound
    setSound(next)
    if (next && 'Notification' in window && Notification.permission === 'default') {
      try { await Notification.requestPermission() } catch { /* ignore */ }
    }
  }
  return (
    <div className="settings" onMouseLeave={() => setOpen(false)}>
      <button className="iconbtn" aria-label="Settings" aria-expanded={open} onClick={() => setOpen((o) => !o)}><IconGear size={18} /></button>
      {open && (
        <div className="menu" role="menu">
          <button role="menuitemcheckbox" aria-checked={sources} onClick={() => setSources(!sources)}>
            <span className={`check${sources ? ' on' : ''}`} /> Show data sources
            <span className="tiny muted" style={{ marginLeft: 'auto' }}>REAL / SIMULATED</span>
          </button>
          <button role="menuitemcheckbox" aria-checked={sound} onClick={toggleSound}>
            <span className={`check${sound ? ' on' : ''}`} /> Sound on new danger
          </button>
          <button role="menuitemcheckbox" aria-checked={!dark} onClick={() => setDark(!dark)}>
            {dark ? <IconSun size={15} /> : <IconMoon size={15} />} {dark ? 'Light mode' : 'Dark mode'}
          </button>
          <button role="menuitem" onClick={() => { window.location.assign('/control/health') }}>System health</button>
        </div>
      )}
    </div>
  )
}

/** Control-room header: brand + "Control room", nav tabs, one settings menu, identity. */
export function AppHeader() {
  const user = getUser()
  const navigate = useNavigate()
  const authority = user?.role === 'authority'

  return (
    <header className="app-header">
      <div className="brand">
        <span className="brand-mark">BHOOSHAKTI</span>
        <span className="brand-sub">Control room</span>
      </div>
      <nav className="nav">
        <NavLink to="/control" end>Dashboard</NavLink>
        <NavLink to="/control/alerts">Alerts</NavLink>
        {authority && <NavLink to="/control/moderation">Reports</NavLink>}
        <NavLink to="/replay">Replay</NavLink>
        {authority && <NavLink to="/control/audit">Audit</NavLink>}
        <NavLink to="/">Citizen app</NavLink>
      </nav>
      <div className="header-spacer" />
      <SettingsMenu />
      {user ? (
        <>
          <div className="who">
            <strong>{user.full_name || user.username}</strong>
            <span>{user.designation || user.role}</span>
          </div>
          <button className="btn ghost sm" onClick={() => { clearSession(); navigate('/login') }}>Sign out</button>
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

/** Village-gauge readings (volunteer, mm since the previous reading) on the same
 *  time axis as the hourly Open-Meteo bars above them: one dot per reading. */
export function GaugeStrip({ data, from, to }: { data: Array<{ read_at: string; mm: number; level: string }>; from: string; to: string }) {
  const t0 = new Date(from).getTime(), t1 = new Date(to).getTime()
  const W = 380, H = 26
  const pts = data.map((d) => ({ ...d, t: new Date(d.read_at).getTime() })).filter((d) => d.t >= t0 && d.t <= t1 + 3600e3)
  if (!pts.length || t1 <= t0) return null
  const x = (t: number) => Math.min(W - 8, Math.max(8, ((t - t0) / (t1 - t0)) * W))
  return (
    <svg className="gauge-strip" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Village gauge readings">
      <line x1="0" y1={H - 6} x2={W} y2={H - 6} className="gauge-axis" />
      {pts.map((d, i) => (
        <g key={i} className={`gauge-dot lv-${d.level}`}>
          <circle cx={x(d.t)} cy={H - 6} r="4" />
          <text x={x(d.t)} y={H - 12} textAnchor="middle">{Math.round(d.mm)}</text>
        </g>
      ))}
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
