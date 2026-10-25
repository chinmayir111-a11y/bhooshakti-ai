/**
 * Replay a REAL past landslide hour by hour through the risk pipeline — the
 * same timelines scripts/backtest.py scored. Public page; the 3D map loads
 * on demand and can be switched off for slow networks.
 */
import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type ReplayEvent, type ReplayTimeline } from '../api/client'
import { SEVERITY_FILL, SeverityChip } from '../components/Severity'
import { SettingsMenu } from '../components/common'
import { prefersReducedMotion, useLocalFlag } from '../hooks'
import { IconAlert, IconCheck, IconExternal, IconPause, IconPlay } from '../components/Pictograms'
import type { Pulse, RainPoint } from '../components/Map3D'
import { ControlCtx, useControl } from '../control/context'
import '../styles/theme.css'

const Map3D = lazy(() => import('../components/Map3D'))
const SPEEDS = [1, 4, 16] as const

function fmt(iso: string, opts: Intl.DateTimeFormatOptions = { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) {
  return new Date(iso).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', ...opts })
}

/** Rainfall bars + risk line with the HIGH threshold, cursor and event mark. */
function Chart({ tl, idx }: { tl: ReplayTimeline; idx: number }) {
  const W = 680, H = 210, L = 34, R = 34, T = 14, B = 26
  const hs = tl.hours
  const n = hs.length
  const x = (i: number) => L + (i / Math.max(1, n - 1)) * (W - L - R)
  const maxRain = Math.max(2, ...hs.map((h) => h.rain_mm))
  const yRain = (v: number) => T + (H - T - B) * (1 - v / maxRain)
  const yRisk = (v: number) => T + (H - T - B) * (1 - v / 100)
  const refIdx = hs.findIndex((h) => h.ts >= tl.event.reference)
  const faIdx = tl.verdict.first_alert ? hs.findIndex((h) => h.ts >= tl.verdict.first_alert!) : -1
  const path = hs.map((h, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${yRisk(h.risk_score).toFixed(1)}`).join(' ')
  const days = hs.map((h, i) => ({ i, d: new Date(h.ts) })).filter(({ d }) => d.getUTCHours() === 0)
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Hourly rainfall and risk score">
      <defs>
        {/* Risk line: mint when low, red when high — the colour follows the value. */}
        <linearGradient id="riskGrad" gradientUnits="userSpaceOnUse" x1="0" y1={yRisk(100)} x2="0" y2={yRisk(0)}>
          <stop offset="0" stopColor="#F87171" /><stop offset="0.45" stopColor="#FB923C" /><stop offset="0.7" stopColor="#FACC15" /><stop offset="1" stopColor="#7FD1AE" />
        </linearGradient>
        <filter id="rainGlow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="1.6" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>
      {[0, 25, 50, 75, 100].map((v) => <line key={v} className="grid" x1={L} x2={W - R} y1={yRisk(v)} y2={yRisk(v)} />)}
      {[0, 25, 50, 75, 100].map((v) => <text key={v} x={L - 6} y={yRisk(v) + 3} textAnchor="end">{v}</text>)}
      <text x={W - R + 6} y={yRain(maxRain) + 3}>{maxRain.toFixed(0)} mm</text>
      <text x={W - R + 6} y={yRain(0) + 3}>0</text>
      {hs.map((h, i) => i <= idx && h.rain_mm > 0 && (
        <rect key={i} className="rain" filter="url(#rainGlow)" x={x(i) - 1.2} width={2.4} y={yRain(h.rain_mm)} height={yRain(0) - yRain(h.rain_mm)} />
      ))}
      <line className="thr" x1={L} x2={W - R} y1={yRisk(tl.threshold)} y2={yRisk(tl.threshold)} />
      <text x={L + 4} y={yRisk(tl.threshold) - 4} style={{ fill: 'var(--sev-high-ink)', fontWeight: 700 }}>HIGH — alert fires</text>
      <path className="risk" d={path} stroke="url(#riskGrad)" pathLength={1000} strokeDasharray={`${(1000 * idx / Math.max(1, n - 1)).toFixed(1)} 9999`} />
      {refIdx >= 0 && <line className="evt" x1={x(refIdx)} x2={x(refIdx)} y1={T} y2={H - B} />}
      {refIdx >= 0 && <text x={x(refIdx) + 4} y={T + 10} style={{ fill: 'var(--sev-critical-ink)', fontWeight: 700 }}>landslide</text>}
      {faIdx >= 0 && faIdx <= idx && <circle cx={x(faIdx)} cy={yRisk(hs[faIdx].risk_score)} r={5} fill="var(--sev-high)" stroke="#fff" strokeWidth={2} />}
      <line className="cursor" x1={x(idx)} x2={x(idx)} y1={T} y2={H - B} />
      {days.map(({ i, d }) => <text key={i} x={x(i)} y={H - 8} textAnchor="middle">{d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: 'UTC' })}</text>)}
    </svg>
  )
}

export default function Replay() {
  const [dark, setDark] = useLocalFlag('bhooshakti.dark', true)
  const [sources, setSources] = useLocalFlag('bhooshakti.sources', false)
  const [sound, setSound] = useLocalFlag('bhooshakti.sound', false)
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light')
    return () => { document.documentElement.removeAttribute('data-theme') }
  }, [dark])
  return (
    <ControlCtx.Provider value={{ dark, setDark, sources, setSources, sound, setSound }}>
      <ReplayPage />
    </ControlCtx.Provider>
  )
}

function ReplayPage() {
  const { dark, sources } = useControl()
  const [toast, setToast] = useState<string | null>(null)
  const [events, setEvents] = useState<ReplayEvent[]>([])
  const [summary, setSummary] = useState<any>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [window_, setWindow] = useState<'event' | 'dry'>('event')
  const [tl, setTl] = useState<ReplayTimeline | null>(null)
  const [error, setError] = useState('')
  const [idx, setIdx] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<typeof SPEEDS[number]>(4)
  const [show3d, setShow3d] = useLocalFlag('bhooshakti.replay3d', true)
  // Satellite by default: real imagery suits a real event. (New key, so an
  // older "Map" choice saved in the browser does not override the default.)
  const [satellite, setSatellite] = useLocalFlag('bhooshakti.replay.sat', true)
  const [custom, setCustom] = useState({ pincode: '734223', lat: '', lon: '', date: '2024-05-28', time: '', label: '' })
  const [customBusy, setCustomBusy] = useState(false)
  const [customError, setCustomError] = useState('')
  const [customOpen, setCustomOpen] = useState(false)
  const shock = useRef<Pulse[]>([])

  useEffect(() => {
    api.replayEvents().then((e) => {
      setEvents(e)
      // Open on Aizawl, 28 May 2024 — a real slide the system warned about 3.5 h ahead.
      const first = e.find((x) => x.source_event_id === 'aizawl-melthum-2024') ?? e.find((x) => x.outcome === 'warned_before') ?? e[0]
      if (first) setSelected(first.id)
    }).catch(() => setError('The API is not reachable.'))
    api.replaySummary().then(setSummary).catch(() => {})
  }, [])

  async function runCustom(e: React.FormEvent) {
    e.preventDefault()
    setCustomBusy(true); setCustomError(''); setPlaying(false); shock.current = []
    try {
      const body: any = { date: custom.date, label: custom.label, time: custom.time || null }
      if (custom.lat && custom.lon) { body.lat = Number(custom.lat); body.lon = Number(custom.lon) }
      else body.pincode = custom.pincode
      const res = await fetch(`${import.meta.env.VITE_API_BASE || 'http://localhost:8000'}/replay/custom`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const data = await res.json()
      if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail))
      setSelected(null); setWindow('event'); setTl(data as ReplayTimeline); setIdx(0); setPlaying(true)
    } catch (err: any) {
      setCustomError(err?.message ?? 'Could not replay that place and date')
    } finally { setCustomBusy(false) }
  }

  useEffect(() => {
    if (selected == null) return
    setTl(null); setError(''); setPlaying(false); setIdx(0); shock.current = []
    api.replayEvent(selected, window_).then((t) => { setTl(t); setIdx(0); setPlaying(true) })
      .catch((e) => setError(e?.message ?? 'Could not load this replay'))
  }, [selected, window_])

  // Deep link: ?at=<ISO time> pauses the replay on that hour (demos, screenshots).
  useEffect(() => {
    const at = new URLSearchParams(window.location.search).get('at')
    if (!at || !tl) return
    const i = tl.hours.findIndex((x) => x.ts >= at)
    if (i >= 0) { setPlaying(false); setIdx(i) }
  }, [tl])

  useEffect(() => {
    if (!playing || !tl) return
    const ms = prefersReducedMotion() ? 600 : 520 / speed
    const id = setInterval(() => setIdx((i) => { if (i + 1 >= tl.hours.length) { setPlaying(false); return i } return i + 1 }), ms)
    return () => clearInterval(id)
  }, [playing, speed, tl])

  const ev = useMemo<ReplayEvent | null>(() => {
    const found = events.find((e) => e.id === selected)
    if (found) return found
    if (tl && tl.event.source === 'Your input') {
      return { id: 0, source: 'Your input', source_event_id: 'custom', date: tl.event.date, time_known: false,
               lat: tl.event.lat, lon: tl.event.lon, state: '', title: tl.event.title, trigger: '', fatalities: 0,
               source_url: '', location_accuracy: '', outcome: tl.verdict.outcome ?? null,
               lead_hours: tl.verdict.lead_hours ?? null, demo: false, real: true }
    }
    return null
  }, [events, selected, tl])
  const h = tl?.hours[idx]
  const refReached = !!(tl && h && window_ === 'event' && h.ts >= tl.event.reference)
  const firedReached = !!(tl && h && tl.verdict.first_alert && h.ts >= tl.verdict.first_alert)
  if (refReached && tl && !shock.current.length) shock.current = [{ lat: tl.event.lat, lon: tl.event.lon, at: performance.now(), big: true }]

  // The 24 h chip sits beside the landslide pin, not on top of it.
  const rainPoints: RainPoint[] = tl && h ? [{ lon: tl.event.lon, lat: tl.event.lat, mm: h.rain_mm, mm24: h.rainfall_24h, chipOffset: [7.4, -1.9] }] : []
  const marker = tl ? { lat: tl.event.lat, lon: tl.event.lon,
    label: `Landslide · ${new Date(`${tl.event.date}T00:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })}` } : null

  // The moment the line crosses HIGH while playing: one animated toast.
  const firedShown = useRef(false)
  useEffect(() => { firedShown.current = false; setToast(null) }, [tl])
  useEffect(() => {
    if (!tl || !firedReached || firedShown.current || window_ !== 'event') return
    firedShown.current = true
    const lead = tl.verdict.lead_hours
    setToast(lead != null && lead >= 0 ? `Alert would have fired — ${lead} hours before the landslide` : `Alert fires — ${fmt(tl.verdict.first_alert!)}`)
    const id = window.setTimeout(() => setToast(null), 6500)
    return () => window.clearTimeout(id)
  }, [firedReached, tl, window_])

  const lead = tl?.verdict.lead_hours
  let banner: { cls: string; text: string } | null = null
  if (tl && h) {
    if (window_ === 'dry') {
      banner = tl.verdict.false_alarm
        ? { cls: 'fired', text: `Dry week: risk reached HIGH for ${tl.verdict.hours_high} h — a false alarm (peak ${tl.verdict.peak_score}).` }
        : { cls: 'ok', text: `Dry week at the same place: risk stayed below HIGH (peak ${tl.verdict.peak_score}). No false alarm.` }
    } else if (refReached && tl.event.source === 'Your input') {
      const day = fmt(tl.event.reference, { day: '2-digit', month: 'short', year: 'numeric' })
      banner = tl.verdict.outcome === 'warned_before'
        ? { cls: 'fired', text: `By ${tl.event.time_known ? fmt(tl.event.reference) : `the start of ${day}`} the system had been at HIGH for ${lead} hours.` }
        : tl.verdict.outcome === 'same_day'
          ? { cls: 'fired', text: `Risk crossed HIGH at ${fmt(tl.verdict.first_alert!)} — during ${day}, after the day began. Enter the event time to see whether that was before it.` }
          : { cls: 'ok', text: `No alert: risk stayed below HIGH in the week before ${day} (peak ${tl.verdict.peak_score}).` }
    } else if (refReached) {
      banner = tl.verdict.outcome === 'warned_before'
        ? { cls: 'event', text: `Landslide reported ${fmt(tl.event.reference, { day: '2-digit', month: 'short', year: 'numeric' })}${tl.event.time_known ? ` at ${fmt(tl.event.reference, { hour: '2-digit', minute: '2-digit' })}` : ' (time not recorded)'} — the alert had been live for ${lead} hours.` }
        : tl.verdict.outcome === 'same_day'
          ? { cls: 'fired', text: `Landslide day. Risk crossed HIGH only during the day itself (${fmt(tl.verdict.first_alert!)}) — counted as same-day, not a warning.` }
          : { cls: 'miss', text: `MISSED. Risk never reached HIGH before this landslide (peak ${tl.verdict.peak_score}). Counted honestly as a miss.` }
    } else if (firedReached) {
      banner = { cls: 'fired', text: `Alert would have fired on ${fmt(tl.verdict.first_alert!)} — ${lead} hours before the landslide.` }
    }
  }

  return (
    <div className="app-shell" style={{ minHeight: '100%' }}>
      <header className="app-header">
        <div className="brand"><span className="brand-mark">BHOOSHAKTI</span><span className="brand-sub">Replay</span></div>
        <nav className="nav"><Link to="/control">Control room</Link><Link to="/">Citizen app</Link></nav>
        <div className="header-spacer" />
        <SettingsMenu />
      </header>
      {toast && <div className="toasts"><div className="toast fired"><div className="toast-step">Replay</div><div className="toast-text">{toast}</div></div></div>}
      <div className="page-body">
        <div className="page-narrow stack">
          <div>
            <h1 style={{ fontSize: 22 }}>Would we have warned?</h1>
            <p className="muted" style={{ margin: '3px 0 0', fontSize: 13 }}>
              Pick a <strong>real recorded landslide</strong> the model never saw in training and press Play: the real weather of
              the month before it runs hour by hour through the live risk pipeline.
            </p>
          </div>

          <div className="card">
            <div className="card-head replay-bar">
              <label className="label" htmlFor="ev">Landslide</label>
              <select id="ev" value={selected ?? ''} onChange={(e) => setSelected(Number(e.target.value))}>
                {selected == null && <option value="">Your own place and date</option>}
                {events.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.date} · {e.state} · {e.title.slice(0, 60)} — {e.outcome === 'warned_before' ? `warned ${e.lead_hours} h ahead` : e.outcome === 'same_day' ? 'same day' : e.outcome === 'missed' ? 'missed' : '—'}
                  </option>
                ))}
              </select>
              <button className="btn big" onClick={() => { if (tl && idx + 1 >= tl.hours.length) setIdx(0); setPlaying((p) => !p) }} disabled={!tl}>
                {playing ? <><IconPause size={18} /> Pause</> : <><IconPlay size={18} /> Play</>}
              </button>
              <button className="btn ghost sm" onClick={() => setCustomOpen((o) => !o)} aria-expanded={customOpen}>Try any place and date</button>
              <span style={{ flex: '1 1 auto' }} />
              <div className="seg">
                <button className={window_ === 'event' ? 'on' : ''} onClick={() => setWindow('event')}>Event week</button>
                <button className={window_ === 'dry' ? 'on' : ''} onClick={() => setWindow('dry')}>Dry week</button>
              </div>
              <div className="seg">{SPEEDS.map((s) => <button key={s} className={speed === s ? 'on' : ''} onClick={() => setSpeed(s)}>{s}×</button>)}</div>
              <label className="toggle-row" style={{ padding: 0 }}><input type="checkbox" checked={show3d} onChange={(e) => setShow3d(e.target.checked)} /> 3D</label>
            </div>

            {customOpen && (
              <form className="card-body row" style={{ gap: 10, alignItems: 'flex-end', borderBottom: '1px solid var(--line)', background: 'var(--surface-2)' }} onSubmit={runCustom}>
                <p className="tiny muted" style={{ flex: '1 1 100%', margin: 0 }}>Any pincode or point in the hills, any day since 1950. Real ERA5 weather for the 30 days before it is fetched and replayed; the first run for a new place takes 20–40 s.</p>
                <div style={{ flex: '0 1 130px' }}><label className="label" htmlFor="cpin">Pincode</label>
                  <input id="cpin" inputMode="numeric" maxLength={6} value={custom.pincode} onChange={(e) => setCustom({ ...custom, pincode: e.target.value.replace(/\D/g, ''), lat: '', lon: '' })} placeholder="734223" /></div>
                <span className="tiny muted" style={{ paddingBottom: 10 }}>or</span>
                <div style={{ flex: '0 1 120px' }}><label className="label" htmlFor="clat">Latitude</label>
                  <input id="clat" inputMode="decimal" value={custom.lat} onChange={(e) => setCustom({ ...custom, lat: e.target.value })} placeholder="24.782" /></div>
                <div style={{ flex: '0 1 120px' }}><label className="label" htmlFor="clon">Longitude</label>
                  <input id="clon" inputMode="decimal" value={custom.lon} onChange={(e) => setCustom({ ...custom, lon: e.target.value })} placeholder="93.663" /></div>
                <div style={{ flex: '0 1 170px' }}><label className="label" htmlFor="cdate">Date to test</label>
                  <input id="cdate" type="date" value={custom.date} onChange={(e) => setCustom({ ...custom, date: e.target.value })} /></div>
                <div style={{ flex: '0 1 120px' }}><label className="label" htmlFor="ctime">Time IST (optional)</label>
                  <input id="ctime" type="time" value={custom.time} onChange={(e) => setCustom({ ...custom, time: e.target.value })} /></div>
                <div style={{ flex: '1 1 160px' }}><label className="label" htmlFor="clabel">Label (optional)</label>
                  <input id="clabel" value={custom.label} onChange={(e) => setCustom({ ...custom, label: e.target.value })} placeholder="e.g. Kurseong slide I remember" /></div>
                <button className="btn" type="submit" disabled={customBusy}>{customBusy ? 'Fetching ERA5…' : 'Replay it'}</button>
                {customError && <p className="notice tiny" style={{ flex: '1 1 100%', margin: 0 }}>{customError}</p>}
              </form>
            )}

            {error && <p className="notice" style={{ margin: 16 }}>{error}</p>}
            {!tl && !error && <div className="card-body"><div className="skeleton" style={{ height: 220 }} /></div>}

            {tl && h && ev && (
              <div className="card-body">
                <div className="replay">
                  <div>
                    {show3d ? (
                      <div className="map-box">
                        <Suspense fallback={<div className="skeleton" style={{ position: 'absolute', inset: 0, borderRadius: 0 }} />}>
                          <Map3D orbit={{ lat: tl.event.lat, lon: tl.event.lon, zoom: 12, pitch: 55 }} orbitActive={playing} marker={marker} exaggeration={1.1} hillshade={0.15} rain={rainPoints} rainParticles={playing ? h.rain_mm : 0} pulses={refReached ? shock.current : []}
                                 terrain center={[tl.event.lon, tl.event.lat]} zoom={12} dark={dark}
                                 basemap={satellite ? 'satellite' : 'map'} />
                        </Suspense>
                        <div style={{ position: 'absolute', left: 10, top: 10, zIndex: 5 }} className="row">
                          <span className="seg" style={{ background: 'var(--surface)' }}>
                            <button className={!satellite ? 'on' : ''} onClick={() => setSatellite(false)}>Map</button>
                            <button className={satellite ? 'on' : ''} onClick={() => setSatellite(true)}>Satellite</button>
                          </span>
                        </div>
                      </div>
                    ) : (
                      <div className="map-box" style={{ height: 120, display: 'grid', placeItems: 'center' }}><span className="muted tiny">3D map off — point {tl.event.lat.toFixed(3)}, {tl.event.lon.toFixed(3)}</span></div>
                    )}
                    <div className="row" style={{ marginTop: 12, alignItems: 'flex-start' }}>
                      <div className="replay-disc" style={{ background: SEVERITY_FILL[h.severity] }}>{Math.round(h.risk_score)}</div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div className="row"><SeverityChip value={h.severity} size={16} /><span className="mono tiny">{fmt(h.ts)} IST</span></div>
                        <dl className="kv" style={{ marginTop: 6 }}>
                          <dt>Rain this hour</dt><dd>{h.rain_mm.toFixed(1)} mm</dd>
                          <dt>24 h rain</dt><dd>{h.rainfall_24h.toFixed(0)} mm</dd>
                          <dt>Soil saturation</dt><dd>{h.soil_moisture_pct.toFixed(0)} %</dd>
                        </dl>
                      </div>
                    </div>
                  </div>
                  <div>
                    <input type="range" min={0} max={tl.hours.length - 1} value={idx} onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)) }} style={{ width: '100%', accentColor: 'var(--brand)' }} aria-label="Timeline" />
                    <Chart tl={tl} idx={idx} />
                    {banner && <div className={`replay-banner ${banner.cls}`}>{banner.cls === 'ok' ? <IconCheck size={18} /> : <IconAlert size={18} />} {banner.text}</div>}
                    <div className="notice tiny" style={{ marginTop: 12 }}>
                      <strong>{ev.title}</strong><br />
                      {ev.date}{ev.time_known ? '' : ' (date only; time not recorded)'} · {ev.state} · trigger: {ev.trigger || '—'}{ev.fatalities ? ` · ${ev.fatalities} fatalities` : ''}
                      {ev.location_accuracy && <> · location ±{ev.location_accuracy}</>}<br />
                      {sources ? <span className="provbadge real">REAL · {ev.source}</span> : <span className="tiny muted">Source: {ev.source}</span>}{' '}
                      {ev.source_url && <a href={ev.source_url} target="_blank" rel="noreferrer" className="verify-link">source record <IconExternal size={12} /></a>}
                      <br /><span className="muted">Weather: {tl.provenance.weather}, grid cell {tl.provenance.grid.lat?.toFixed?.(2)}, {tl.provenance.grid.lon?.toFixed?.(2)}. {tl.provenance.forecast_input}. Map: AWS terrain; the blue–violet radar is this hour's rain, the chip its 24 h total.</span>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {summary && (
            <div className="card">
              <div className="card-head"><h3>The honest score on every held-out landslide</h3></div>
              <div className="card-body" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 14, alignItems: 'start' }}>
                {summary.earlier?.length > 0 && (() => {
                  // Every tested year together: each year scored by a model trained only on the years before it.
                  const all = [summary, ...summary.earlier]
                  const warned = all.reduce((n: number, r: any) => n + r.summary.warned_before, 0)
                  const events = all.reduce((n: number, r: any) => n + r.summary.events, 0)
                  return (
                    <div style={{ gridColumn: '1 / -1', fontSize: 18, fontWeight: 800 }}>
                      Warned before {warned} of {events} real landslides it had never seen, across {all.length} separate years.
                    </div>
                  )
                })()}
                <div style={{ gridColumn: '1 / -1', fontSize: 16, fontWeight: 700 }}>{summary.test_year}+ (shipped model): {summary.summary.headline}</div>
                {(summary.earlier ?? []).map((r: any) => (
                  <div key={r.test_year} style={{ gridColumn: '1 / -1', fontSize: 14.5, fontWeight: 600, color: 'var(--text-muted)' }}>
                    {r.test_year} (model trained on {r.trained_on.replace('NASA GLC events', 'landslides')}): {r.summary.headline}
                  </div>
                ))}
                <Stat n={summary.summary.warned_before} of={summary.summary.events} label="warned before" tint="var(--sev-low-ink)" />
                <Stat n={summary.summary.warned_same_day} of={summary.summary.events} label="same day only" tint="var(--sev-high-ink)" />
                <Stat n={summary.summary.missed} of={summary.summary.events} label="missed" tint="var(--sev-critical-ink)" />
                <Stat n={summary.summary.median_lead_hours ?? 0} label="median lead, hours" tint="var(--brand-ink)" />
                <Stat n={summary.summary.non_event_false_alarms} of={summary.summary.non_event_windows} label="false alarms, same-season non-event windows" tint="var(--earth)" />
                <Stat n={summary.summary.dry_false_alarms} of={summary.summary.dry_windows} label="false alarms, dry-season windows" tint="var(--earth)" />
                <p className="tiny muted" style={{ gridColumn: '1 / -1', margin: 0 }}>
                  Held out: every event from {summary.test_year} on, plus the curated 2022/2024 records. Alert = risk at or above {summary.threshold} (HIGH).
                  Reference = recorded time, else the start of the event day. Forecast input is a statistical nowcast only — no future data.
                  Model {summary.model_version}, run {fmt(summary.generated_at, { day: '2-digit', month: 'short', year: 'numeric' })}. Counts, not an accuracy claim.
                  {sources && <><span className="provbadge real" style={{ marginLeft: 6 }}>REAL · NASA GLC</span> <span className="provbadge real">REAL · ERA5 / Open-Meteo</span></>}
                </p>
              </div>
            </div>
          )}

          {summary?.demo_events?.length > 0 && (
            <div className="card">
              <div className="card-head"><h3>Demo events</h3></div>
              <table className="grid">
                <thead><tr><th>Date</th><th>Event</th><th>Outcome</th><th>Peak risk</th><th>First alert</th></tr></thead>
                <tbody>
                  {summary.demo_events.map((e: any) => (
                    <tr key={e.id} style={{ cursor: 'pointer' }} onClick={() => { setWindow('event'); setSelected(e.id) }}>
                      <td className="nowrap">{e.date}</td><td>{e.title}</td>
                      <td className="nowrap">{e.outcome === 'warned_before' ? <span className="pill on">warned {e.lead_hours} h ahead</span> : <span className="pill">{e.outcome}</span>}</td>
                      <td>{e.peak_score}</td><td className="nowrap tiny">{e.first_alert ? fmt(e.first_alert) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Stat({ n, of, label, tint }: { n: number; of?: number; label: string; tint: string }) {
  return (
    <div>
      <div style={{ fontSize: 26, fontWeight: 800, color: tint, lineHeight: 1 }}>{n}{of != null && <span style={{ fontSize: 14, color: 'var(--text-muted)', fontWeight: 600 }}> / {of}</span>}</div>
      <div className="label" style={{ marginTop: 4 }}>{label}</div>
    </div>
  )
}
