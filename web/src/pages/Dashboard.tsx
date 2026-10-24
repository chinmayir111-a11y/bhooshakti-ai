/**
 * Control room. One plain sentence of what needs attention, four live
 * counters, a ticker, the map (3D terrain by default, 2D/low-data on request
 * or automatically on a slow connection), the alert feed and the reports
 * waiting for a check. Every number can be labelled with its source ("Show
 * data sources"); labels are hidden until that switch is on.
 */
import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import MapView, { type Layers } from '../components/MapView'
import { rainColor, type Column, type Layers3D, type Pin, type Pulse, type ReportPoint, type View } from '../components/Map3D'
import {
  DeliveryChips, FactorList, SeverityChip, Sparkline, Src, TierChip, fmtTime, timeAgo,
} from '../components/common'
import { SEVERITY_FILL, SEVERITY_ORDER, SeverityShape, TIER_LABEL } from '../components/Severity'
import { IconAlert, IconCheck, IconChevron, IconCompass, IconExternal, IconLayers, IconPause, IconPlay } from '../components/Pictograms'
import { api, getUser, type Alert, type CitizenReport, type RainFrame, type Severity, type Summary, type WeatherStatus, type ZoneProvenance } from '../api/client'
import { useLive, type LiveMessage } from '../api/ws'
import { chime, countdown, notify, prefersReducedMotion, useCountUp, useLocalFlag, useNow } from '../hooks'
import { useControl } from '../control/context'
import { EscalationLine, scoreColour } from './Moderation'

const Map3D = lazy(() => import('../components/Map3D'))

interface Toast { id: number; step?: string; text: string }
interface Tick { id: number; text: string; kind: string; at: string }

/** 2D by default on connections that would struggle with vector + terrain tiles. */
function slowConnection(): boolean {
  const c = (navigator as any).connection
  return !!c && (c.saveData === true || /(^|-)(2g|3g)$/.test(String(c.effectiveType || '')))
}

const LAYER_LABELS: Array<[keyof Layers3D, string]> = [
  ['zones', 'Zones'], ['reports', 'Reports'], ['sensors', 'Sensors'], ['rain', 'Rain (24 h)'], ['roads', 'Roads & villages'],
]

function Counter({ value, label, tint, src, srcKind }: { value: number; label: string; tint?: string; src?: string; srcKind?: 'real' | 'live' | 'sim' }) {
  const shown = useCountUp(value)
  const [bump, setBump] = useState(false)
  const prev = useRef(value)
  useEffect(() => {
    if (prev.current !== value) { setBump(true); const id = setTimeout(() => setBump(false), 500); prev.current = value; return () => clearTimeout(id) }
  }, [value])
  return (
    <div className={`stat sev-tint${bump ? ' bump' : ''}`} style={{ borderLeftColor: tint ?? 'transparent' }}>
      <div className="stat-value">{shown}</div>
      <div className="stat-label">{label} {src && <Src kind={srcKind ?? 'sim'} label={src} />}</div>
    </div>
  )
}

export default function Dashboard() {
  const [params, setParams] = useSearchParams()
  const user = getUser()
  const isAuthority = user?.role === 'authority'
  const { dark, sources, sound } = useControl()

  const [zones, setZones] = useState<any>(null)
  const [infrastructure, setInfrastructure] = useState<any>(null)
  const [sensors, setSensors] = useState<any>(null)
  const [historical, setHistorical] = useState<any>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [weather, setWeather] = useState<WeatherStatus | null>(null)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [escalations, setEscalations] = useState<CitizenReport[]>([])
  const [newAlertIds, setNewAlertIds] = useState<Set<number>>(new Set())
  const [ticks, setTicks] = useState<Tick[]>([])
  const [pulses, setPulses] = useState<Pulse[]>([])
  const tickSeq = useRef(0)

  const [mode, setMode] = useLocalFlag('bhooshakti.map2d', slowConnection())      // true = 2D / low data
  const [demoOpen, setDemoOpen] = useState(false)
  const [tour, setTour] = useState<{ id: number; stops: View[]; onDone?: () => void } | null>(null)
  const [drawerMore, setDrawerMore] = useState(false)
  const [satellite, setSatellite] = useLocalFlag('bhooshakti.satellite', false)
  const [railTab, setRailTab] = useState<'alerts' | 'reports'>('alerts')
  const [layersOpen, setLayersOpen] = useState(false)
  const [legendOpen, setLegendOpen] = useState(false)
  const [resetSignal, setResetSignal] = useState(0)
  const [layers, setLayers] = useState<Layers3D>({ zones: true, reports: true, sensors: true, rain: true, roads: true })
  // The 2D map keeps its own layer names.
  const layers2d: Layers = { risk: layers.zones, roads: layers.roads, villages: layers.roads, sensors: layers.sensors, historical: false }

  const [frames, setFrames] = useState<RainFrame[]>([])
  const [frameIdx, setFrameIdx] = useState<number | null>(null)       // null = live (latest observed)
  const [playing, setPlaying] = useState(false)

  const zoneParam = params.get('zone')
  const [selectedZoneId, setSelectedZoneId] = useState<number | null>(zoneParam ? Number(zoneParam) : null)
  const [zoneDetail, setZoneDetail] = useState<any>(null)
  const [provenance, setProvenance] = useState<ZoneProvenance | null>(null)
  const [flyTo, setFlyTo] = useState<{ lat: number; lon: number; zoom?: number } | null>(null)

  const [demo, setDemo] = useState<any>({ running: false, step: 0, total_steps: 8, label: 'Idle' })
  const [speed, setSpeed] = useState<1 | 4>(1)
  const [busy, setBusy] = useState<string | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])
  const toastSeq = useRef(0)
  const now = useNow(1000)

  const pushToast = useCallback((text: string, step?: string) => {
    const id = ++toastSeq.current
    setToasts((t) => [...t.slice(-5), { id, text, step }])
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 7000)
  }, [])
  const pushTick = useCallback((text: string, kind = 'info', at?: string) => {
    const id = ++tickSeq.current
    setTicks((t) => [{ id, text, kind, at: at ?? new Date().toISOString() }, ...t].slice(0, 12))
  }, [])

  // ---------------------------------------------------------------- loading
  const loadZones = useCallback(async () => { try { setZones(await api.zones()) } catch { /* offline */ } }, [])
  const loadSummary = useCallback(async () => { try { setSummary(await api.summary()) } catch { /* offline */ } }, [])
  const loadInfra = useCallback(async () => { try { setInfrastructure(await api.infrastructure()) } catch { /* offline */ } }, [])
  const loadSensors = useCallback(async () => { try { setSensors(await api.sensors()) } catch { /* offline */ } }, [])
  const loadAlerts = useCallback(async () => { try { setAlerts(await api.alerts(60)) } catch { /* offline */ } }, [])
  const loadEsc = useCallback(async () => { try { setEscalations(await api.escalations()) } catch { /* offline */ } }, [])

  useEffect(() => {
    loadZones(); loadSummary(); loadInfra(); loadSensors(); loadAlerts(); loadEsc()
    api.historical().then(setHistorical).catch(() => {})
    api.weatherStatus().then(setWeather).catch(() => {})
    api.demoState().then(setDemo).catch(() => {})
    api.rainFrames(48).then((r) => setFrames(r.frames)).catch(() => {})
    // Hardware LIVE dots need last-seen refreshed; cheap, every 15 s.
    const id = setInterval(loadSensors, 15000)
    return () => clearInterval(id)
  }, [loadZones, loadSummary, loadInfra, loadSensors, loadAlerts, loadEsc])

  // A zone named in the URL (deep link from an alert email) gets the camera too.
  const flownToParam = useRef(false)
  useEffect(() => {
    if (flownToParam.current || selectedZoneId == null || !zones?.features) return
    const f = zones.features.find((z: any) => z.properties.id === selectedZoneId)
    if (f) { setFlyTo({ lat: f.properties.centroid[0], lon: f.properties.centroid[1] }); flownToParam.current = true }
  }, [zones, selectedZoneId])

  useEffect(() => {
    if (selectedZoneId == null) { setZoneDetail(null); setProvenance(null); return }
    api.zone(selectedZoneId).then(setZoneDetail).catch(() => setZoneDetail(null))
    api.zoneProvenance(selectedZoneId).then(setProvenance).catch(() => setProvenance(null))
  }, [selectedZoneId, zones])

  // ------------------------------------------------------------------- live
  const connected = useLive((m: LiveMessage) => {
    switch (m.event) {
      case 'hello':
        for (const r of (m.payload.recent ?? []).slice(-8)) if (r.event === 'activity') pushTick(r.payload.text, r.payload.kind, r.payload.at)
        break
      case 'activity':
        pushTick(m.payload.text, m.payload.kind, m.payload.at)
        break
      case 'risk.update':
        loadZones()
        break
      case 'alert.new': {
        const a = m.payload as Alert
        setAlerts((prev) => (prev.some((x) => x.id === a.id) ? prev : [a, ...prev].slice(0, 80)))
        setNewAlertIds((s) => new Set(s).add(a.id))
        window.setTimeout(() => setNewAlertIds((s) => { const n = new Set(s); n.delete(a.id); return n }), 2000)
        const tier = a.tier ?? 'WARNING'
        pushToast(`${TIER_LABEL[tier] ?? tier} · ${a.severity} — ${a.zone_name}. ${a.title}`, tier === 'WARNING' ? 'Danger confirmed' : 'Be alert')
        if (tier === 'WARNING' && a.kind !== 'all_clear') {
          if (sound) { chime('warning'); notify(`WARNING — ${a.zone_name}`, a.title) }
          const f = zones?.features?.find((z: any) => z.properties.id === a.zone_id)
          if (f) setFlyTo({ lat: f.properties.centroid[0], lon: f.properties.centroid[1], zoom: 10.5 })
        } else if (sound && tier === 'ADVISORY') chime('advisory')
        loadEsc()
        break
      }
      case 'alert.delivery': case 'alert.update':
        loadAlerts()
        break
      case 'summary.update':
        setSummary(m.payload as Summary)
        break
      case 'infra.update':
        setInfrastructure((prev: any) => ({ ...(prev || {}), roads: m.payload.roads, villages: m.payload.villages }))
        break
      case 'sensor.status':
        loadSensors()
        break
      case 'report.new': {
        const r = m.payload
        setPulses((p) => [...p.filter((q) => Date.now() - q.at < 20000), { lat: r.lat, lon: r.lon, at: Date.now() }])
        pushToast(`${r.issue_label || r.issue_type}${r.zone_name ? ` in ${r.zone_name}` : ''} · corroboration ${Math.round(r.corroboration_score)}/100`, 'Citizen report')
        loadEsc()
        break
      }
      case 'report.escalation': case 'report.moderated':
        loadEsc()
        break
      case 'field.report':
        pushToast(`${m.payload.officer_name || 'Field officer'} — slope movement ${m.payload.verdict}.`, 'Field verification')
        loadZones()
        break
      case 'demo.state':
        setDemo(m.payload)
        break
      case 'demo.step':
        pushToast(m.payload.label, `Step ${m.payload.step} of ${m.payload.total_steps}`)
        break
      case 'response.plan':
        pushToast(`Response plan ready — ${m.payload.people_affected?.toLocaleString?.() ?? '—'} residents affected.`, 'Respond')
        break
    }
  })

  // --------------------------------------------------------------- rain play
  useEffect(() => {
    if (!playing || !frames.length) return
    const id = setInterval(() => setFrameIdx((i) => {
      const n = (i ?? frames.findIndex((f) => f.forecast)) + 1
      return n >= frames.length ? 0 : n
    }), prefersReducedMotion() ? 900 : 380)
    return () => clearInterval(id)
  }, [playing, frames])

  const liveIdx = useMemo(() => { const i = frames.findIndex((f) => f.forecast); return i < 0 ? frames.length - 1 : Math.max(0, i - 1) }, [frames])
  const frame = frames[frameIdx ?? liveIdx]
  const rainByZone = frame?.zones ?? null

  // ---------------------------------------------------------------- derived
  const selectZone = useCallback((id: number) => {
    setSelectedZoneId(id)
    const f = zones?.features?.find((z: any) => z.properties.id === id)
    if (f) setFlyTo({ lat: f.properties.centroid[0], lon: f.properties.centroid[1] })
    setParams((p) => { const n = new URLSearchParams(p); n.set('zone', String(id)); return n }, { replace: true })
  }, [setParams, zones])
  const closeDrawer = useCallback(() => {
    setSelectedZoneId(null)
    setParams((p) => { const n = new URLSearchParams(p); n.delete('zone'); return n }, { replace: true })
  }, [setParams])

  async function run(name: string, fn: () => Promise<any>, done?: string) {
    setBusy(name)
    try { const r = await fn(); if (done) pushToast(done); return r }
    catch (e: any) { pushToast(`${name} failed: ${e?.message ?? e}`) }
    finally { setBusy(null) }
  }

  const counts = summary?.severity_counts ?? {}
  const sortedAlerts = useMemo(() => [...alerts].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()), [alerts])

  // 24 h rain per zone: the 24 frames up to the one being shown (live = latest observed).
  const rain24ByZone = useMemo(() => {
    if (!frames.length) return null
    const end = (frameIdx ?? liveIdx) + 1
    const out: Record<string, number> = {}
    for (const f of frames.slice(Math.max(0, end - 24), end)) for (const [z, mm] of Object.entries(f.zones)) out[z] = (out[z] ?? 0) + mm
    return out
  }, [frames, frameIdx, liveIdx])

  // Zones carry their 24 h rain so the map tooltip can show it.
  const zonesForMap = useMemo(() => {
    if (!zones?.features) return zones
    return { ...zones, features: zones.features.map((f: any) => ({ ...f, properties: { ...f.properties, rain24: rain24ByZone?.[String(f.properties.id)] ?? null } })) }
  }, [zones, rain24ByZone])

  const columns: Column[] = useMemo(() => {
    if (!zones?.features || !rain24ByZone) return []
    return zones.features.map((f: any) => {
      const mm = rain24ByZone[String(f.properties.id)] ?? 0
      return { lon: f.properties.centroid[1], lat: f.properties.centroid[0], value: mm, color: rainColor(mm),
               label: `${f.properties.name}: ${mm.toFixed(0)} mm in 24 h (Open-Meteo)` }
    }).filter((c: Column) => c.value > 0.5)
  }, [zones, rain24ByZone])

  const pins: Pin[] = useMemo(() => {
    if (!sensors?.features) return []
    return sensors.features.map((f: any) => {
      const latest = f.properties.latest
      const anomalous = !!latest && ((latest.tilt_deg ?? 0) >= 1.5 || (latest.soil_moisture_pct ?? 0) >= 90)
      return {
        lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1],
        live: !!f.properties.live, failed: f.properties.status === 'FAILED', source: f.properties.source, anomalous,
        label: `${f.properties.node_id} · ${f.properties.source === 'hardware' ? (f.properties.live ? 'LIVE hardware' : 'hardware, offline') : 'simulated'}${latest ? ` · tilt ${latest.tilt_deg ?? '—'}° soil ${latest.soil_moisture_pct ?? '—'}%` : ''}`,
      }
    })
  }, [sensors])

  const reportPoints: ReportPoint[] = useMemo(() => escalations.filter((r) => r.lat && r.lon)
    .map((r) => ({ id: r.id, lat: r.lat, lon: r.lon, label: r.issue_label })), [escalations])

  const hardwareLive = sensors?.features?.filter((f: any) => f.properties.live) ?? []

  return (
    <div className="page">
      {/* -------------------------------------------------- status row: pill + counters + demo */}
      <div className="status-row">
        <RightNow summary={summary} escalations={escalations} zones={zones} alerts={alerts}
                  onZone={selectZone} onReports={() => setRailTab('reports')} />
        <div className="counters">
          <Counter value={summary?.zones_at_risk ?? 0} label="Zones at risk" tint={SEVERITY_FILL.HIGH} src="model on REAL weather" srcKind="real" />
          <Counter value={summary?.open_reports ?? 0} label="Reports waiting" tint="var(--earth-fill)" src="REAL · public" srcKind="real" />
          <Counter value={summary?.alerts_24h ?? 0} label="Alerts · 24h" tint={SEVERITY_FILL.CRITICAL} src={`${summary?.advisories_active ?? 0} be-alert active`} srcKind="sim" />
          <Counter value={summary?.sensors_online ?? 0} label="Sensors online" tint="var(--brand)" src={hardwareLive.length ? `${hardwareLive.length} LIVE hardware` : 'SIMULATED'} srcKind={hardwareLive.length ? 'live' : 'sim'} />
        </div>
        {isAuthority && (
          <div className="demo-menu">
            <button className="btn ghost sm" onClick={() => setDemoOpen((o) => !o)} aria-expanded={demoOpen}>
              Demo <IconChevron size={14} />
            </button>
            {demo.running && <span className="tiny muted nowrap">{demo.step}/{demo.total_steps}</span>}
            {demoOpen && (
              <div className="menu" onMouseLeave={() => setDemoOpen(false)}>
                <button disabled={demo.running || busy !== null} onClick={() => { setDemoOpen(false); run('Simulate', () => api.simulate(speed)) }}>
                  {demo.running ? 'Storm running…' : 'Simulate monsoon event'}
                </button>
                <div className="menu-row">Speed
                  <span className="seg">{([1, 4] as const).map((s) => <button key={s} className={speed === s ? 'on' : ''} onClick={() => setSpeed(s)} disabled={demo.running}>{s}×</button>)}</span>
                </div>
                <button disabled={busy !== null}
                        onClick={() => { setDemoOpen(false); run('Reset', async () => { await api.resetDemo(); await Promise.all([loadZones(), loadSummary(), loadInfra(), loadAlerts(), loadEsc()]) }, 'Demo reset to the seeded baseline.') }}>
                  Reset demo
                </button>
                <button disabled={busy !== null}
                        onClick={() => { setDemoOpen(false); run('Test alert', async () => {
                          const r = await api.testAlert({ zone_id: selectedZoneId ?? undefined })
                          const email = r.deliveries?.find((d: any) => d.channel === 'email')
                          pushToast(`Test alert for ${r.zone}: email ${email?.status ?? 'n/a'}${email?.status === 'SIMULATED' ? ' (set SMTP_HOST in .env to send for real)' : ` → ${email?.recipient}`}`)
                          await loadAlerts()
                        }) }}>
                  Send test alert
                </button>
                <button disabled={mode || !!tour} title="Fly over the demo districts once so map tiles are cached before judging"
                        onClick={() => {
                          setDemoOpen(false)
                          const stops: View[] = (zones?.features ?? []).map((f: any) => ({ lat: f.properties.centroid[0], lon: f.properties.centroid[1], zoom: 10.5 }))
                          pushToast(`Warming the map cache: ${stops.length} zones…`)
                          setTour({ id: Date.now(), stops, onDone: () => { setTour(null); pushToast('Map cache warm.') } })
                        }}>
                  {tour ? 'Warming map cache…' : 'Warm map cache'}
                </button>
                {demo.running && <div className="demo-progress"><span style={{ width: `${((demo.step ?? 0) / (demo.total_steps || 8)) * 100}%` }} /></div>}
              </div>
            )}
          </div>
        )}
      </div>

      {/* -------------------------------------------------- provenance (only with "Show data sources") */}
      {weather && sources && (
        <div className="provenance">
          <span className={`provbadge ${weather.using_real_weather ? 'real' : 'sim'}`}>{weather.using_real_weather ? 'REAL · Open-Meteo' : 'SIMULATED WEATHER'}</span>
          <span className="tiny">
            {weather.using_real_weather
              ? <>Rainfall and soil moisture are observed data (ERA5 reanalysis + forecast), cached locally. Latest observation {timeAgo(weather.latest_observation)}.</>
              : <>Rainfall and soil moisture are generated by the synthetic weather model.</>}
          </span>
          <span className="provbadge real">REAL · NASA GLC</span>
          <span className="tiny">past landslides</span>
          <span style={{ flex: 1 }} />
          <span className="tiny muted nowrap">
            <span className="provbadge sim">SIMULATED</span> zone boundaries, {hardwareLive.length ? 'all but the LIVE sensor' : 'sensors'}, the demo storm.
          </span>
        </div>
      )}

      {/* -------------------------------------------------- ticker */}
      <div className="ticker" aria-live="polite">
        <span className="ticker-label"><span className={`ws-dot${connected ? ' live' : ''}`} />{connected ? 'Live' : 'Offline'}</span>
        <div className="ticker-items">
          {ticks.length === 0 && <span className="tiny muted">Waiting for activity — reports, sensor changes and alerts appear here as they happen.</span>}
          {ticks.map((t) => (
            <span key={t.id} className={`ticker-item ${t.kind}`}><span className="dot" />{t.text}<span className="when">· {timeAgo(t.at)}</span></span>
          ))}
        </div>
      </div>

      {/* -------------------------------------------------- main */}
      <div className="dash">
        <aside className="rail">
          <div className="rail-tabs">
            <button className={railTab === 'alerts' ? 'on' : ''} onClick={() => setRailTab('alerts')}>Alerts</button>
            <button className={railTab === 'reports' ? 'on' : ''} onClick={() => setRailTab('reports')}>
              Waiting for check{escalations.length > 0 && <span className="count">{escalations.length}</span>}
            </button>
          </div>
          <div className="rail-scroll">
            {railTab === 'alerts' && (
              <>
                {sortedAlerts.length === 0 && (
                  <div className="empty">No alerts yet.<br />{isAuthority ? 'Run “Simulate monsoon event” from the Demo menu, or leave a citizen report unchecked.' : 'Alerts appear here as zones escalate.'}</div>
                )}
                {sortedAlerts.map((a) => (
                  <button key={a.id} className={`alert-item lv-${a.severity}${newAlertIds.has(a.id) ? ' is-new' : ''}`} onClick={() => selectZone(a.zone_id)}>
                    <div className="alert-row">
                      <span className="row" style={{ gap: 6 }}><TierChip tier={a.tier} status={a.status} /><SeverityChip value={a.severity} /></span>
                      <span className="tiny muted">{timeAgo(a.created_at)}</span>
                    </div>
                    <div className="alert-zone">{a.zone_name}</div>
                    <div className="alert-meta">Risk {Math.round(a.risk_score)}/100 · {Math.round(a.confidence * 100)}% sure{a.district ? ` · ${a.district}` : ''}</div>
                    <div className="alert-factor">{a.kind && a.kind !== 'risk' ? a.title : a.contributing_factors?.[0]?.text}</div>
                    <DeliveryChips deliveries={a.deliveries ?? []} />
                  </button>
                ))}
              </>
            )}
            {railTab === 'reports' && (
              <>
                {escalations.length === 0 && <div className="empty">No reports waiting. Nothing needs a human right now.</div>}
                {escalations.map((r) => (
                  <div key={r.id} className="esc-item">
                    <div className="esc-top">
                      <span className="esc-score" style={{ color: scoreColour(r.corroboration_score) }}>{Math.round(r.corroboration_score)}</span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <strong style={{ fontSize: 13 }}>{r.issue_label}</strong> <span className="tiny muted">#{r.id} · {r.zone_name ?? 'outside zones'} · {timeAgo(r.created_at)}</span>
                        <div className="esc-bar"><span style={{ width: `${r.corroboration_score}%`, background: scoreColour(r.corroboration_score) }} /></div>
                      </div>
                    </div>
                    <div style={{ marginTop: 6 }}><EscalationLine r={r} now={now} /></div>
                    <ul className="esc-reasons">{(r.corroboration_reasons ?? []).slice(0, 2).map((x) => <li key={x.key}><b>{x.points > 0 ? '+' : ''}{x.points}</b>{x.text}</li>)}</ul>
                    {isAuthority && (
                      <div className="esc-actions">
                        <button className="btn ghost sm" onClick={() => api.acknowledgeReport(r.id).then(loadEsc)}><IconCheck size={15} />I'm checking</button>
                        <button className="btn confirm sm" onClick={() => api.confirmReport(r.id).then(loadEsc)}>CONFIRM</button>
                        <button className="btn dismiss sm" onClick={() => api.dismissReport(r.id).then(loadEsc)}>DISMISS</button>
                        {r.lat && <button className="btn ghost sm" onClick={() => { setFlyTo({ lat: r.lat, lon: r.lon, zoom: 12 }); if (r.zone_id) setSelectedZoneId(r.zone_id) }}>Map</button>}
                      </div>
                    )}
                  </div>
                ))}
              </>
            )}
          </div>
        </aside>

        <div className={`map-wrap${zoneDetail ? ' has-drawer' : ''}`}>
          {mode ? (
            <MapView zones={zones} infrastructure={infrastructure} sensors={sensors} historical={historical}
                     layers={layers2d} selectedZoneId={selectedZoneId} onSelectZone={selectZone}
                     rain={rainByZone} pulses={pulses} />
          ) : (
            <Suspense fallback={<div className="skeleton" style={{ position: 'absolute', inset: 0, borderRadius: 0 }} />}>
              <Map3D zones={zonesForMap} roads={infrastructure?.roads} villages={infrastructure?.villages}
                     reports={reportPoints} columns={columns} pins={pins} pulses={pulses} layers={layers}
                     selectedZoneId={selectedZoneId} onSelectZone={selectZone} flyTo={flyTo} dark={dark}
                     basemap={satellite ? 'satellite' : 'map'} idleRotate tour={tour} resetSignal={resetSignal} />
            </Suspense>
          )}

          {/* One compact control group, top-right; MapLibre's zoom/compass sit under it. */}
          <div className="map-ctrl">
            <div className="seg">
              <button className={!mode ? 'on' : ''} onClick={() => setMode(false)} title="Vector tiles + terrain">3D</button>
              <button className={mode ? 'on' : ''} onClick={() => setMode(true)} title="Flat raster map — for slow networks and low-end devices">2D</button>
            </div>
            {!mode && (
              <div className="seg">
                <button className={!satellite ? 'on' : ''} onClick={() => setSatellite(false)}>Map</button>
                <button className={satellite ? 'on' : ''} onClick={() => setSatellite(true)} title="Esri World Imagery on the terrain">Satellite</button>
              </div>
            )}
            <div className="layers-menu" onMouseLeave={() => setLayersOpen(false)}>
              <button className={`iconbtn${layersOpen ? ' on' : ''}`} aria-label="Layers" aria-expanded={layersOpen} onClick={() => setLayersOpen((o) => !o)}><IconLayers size={16} /> Layers</button>
              {layersOpen && (
                <div className="menu">
                  {LAYER_LABELS.map(([key, label]) => (
                    <button key={key} role="menuitemcheckbox" aria-checked={layers[key]} onClick={() => setLayers((l) => ({ ...l, [key]: !l[key] }))}>
                      <span className={`check${layers[key] ? ' on' : ''}`} />{label}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {!mode && <button className="iconbtn" aria-label="Reset view" title="Reset view" onClick={() => setResetSignal((n) => n + 1)}><IconCompass size={16} /></button>}
          </div>

          {/* Legend, bottom-left, closed by default: just the four severity dots. */}
          <div className={`legend${legendOpen ? ' open' : ''}`}>
            <button className="legend-head" aria-expanded={legendOpen} onClick={() => setLegendOpen((o) => !o)}>
              {SEVERITY_ORDER.slice().reverse().map((sev) => <SeverityShape key={sev} value={sev} size={14} title={sev} />)}
              <span className="tiny muted" style={{ marginLeft: 4 }}>{legendOpen ? 'Legend' : ''}</span>
              <IconChevron size={14} style={{ transform: legendOpen ? 'rotate(180deg)' : 'none' }} />
            </button>
            {legendOpen && (
              <div className="legend-body">
                {SEVERITY_ORDER.slice().reverse().map((sev) => <div className="legend-row" key={sev}><SeverityShape value={sev} size={14} />{sev}</div>)}
                <div className="legend-row" style={{ marginTop: 6, borderTop: '1px solid var(--line)', paddingTop: 6 }}>
                  <span className="sw" style={{ background: 'linear-gradient(90deg,#4A90B8,#E3B23C,#DC2626)' }} /> Rain column: 24 h total {sources && <Src kind="real" label="REAL · Open-Meteo" />}
                </div>
                <div className="legend-row"><span className="sw dot-red" /> Citizen report (number = several)</div>
                <div className="legend-row"><span className="sw dia mint" /> LIVE hardware sensor</div>
                <div className="legend-row"><span className="sw dia" /> Simulated sensor · <span className="sw ring" /> anomaly</div>
                <div className="legend-row"><span className="sw" style={{ background: '#FB923C', height: 4 }} /> Blocked road · house + orange dot = cut-off village</div>
                {summary && (
                  <div className="mini-stats">
                    <div><span>{counts.CRITICAL ?? 0}</span> critical</div><div><span>{counts.HIGH ?? 0}</span> high</div>
                    <div><span>{counts.MODERATE ?? 0}</span> moderate</div><div><span>{counts.LOW ?? 0}</span> low</div>
                    <div><span>{summary.villages_cut_off}</span> villages cut off</div><div><span>{summary.roads_flagged}</span> roads flagged</div>
                  </div>
                )}
              </div>
            )}
          </div>

          {frames.length > 0 && (
            <div className="rain-slider" title="Hourly rainfall per zone from Open-Meteo (ERA5 + forecast). Drag or play.">
              <span className="label nowrap">Rain</span>
              <button className="play" onClick={() => setPlaying((p) => !p)} aria-label={playing ? 'Pause' : 'Play'}>{playing ? <IconPause size={14} /> : <IconPlay size={14} />}</button>
              <input type="range" min={0} max={frames.length - 1} value={frameIdx ?? liveIdx}
                     onChange={(e) => { setPlaying(false); setFrameIdx(Number(e.target.value)) }} />
              <span className="t">{frame ? new Date(frame.ts).toLocaleString(undefined, { day: '2-digit', month: 'short', hour: '2-digit' }) : ''}{frame?.forecast ? ' · forecast' : ''}</span>
              {frameIdx !== null && <button className="btn ghost sm" onClick={() => { setPlaying(false); setFrameIdx(null) }}>Live</button>}
              {sources && <span className="provbadge real">REAL · Open-Meteo</span>}
            </div>
          )}

          {zoneDetail && <ZoneDrawer detail={zoneDetail} weather={weather} provenance={provenance} onClose={closeDrawer} more={drawerMore} setMore={setDrawerMore} />}
        </div>
      </div>

      <div className="toasts">
        {toasts.map((t) => (
          <div className="toast" key={t.id}>{t.step && <div className="toast-step">{t.step}</div>}<div className="toast-text">{t.text}</div></div>
        ))}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ right now */

/** One sentence an officer can act on, and the button that takes them there. */
function RightNow({ summary, escalations, zones, alerts, onZone, onReports }: {
  summary: Summary | null; escalations: CitizenReport[]; zones: any; alerts: Alert[]
  onZone: (id: number) => void; onReports: () => void
}) {
  const atRisk = (zones?.features ?? []).filter((f: any) => ['HIGH', 'CRITICAL'].includes(f.properties.severity))
    .sort((x: any, y: any) => (y.properties.risk_score ?? 0) - (x.properties.risk_score ?? 0))
  const waiting = escalations.length
  const calm = atRisk.length === 0 && waiting === 0
  const parts: string[] = []
  if (atRisk.length) parts.push(`${atRisk.length} zone${atRisk.length > 1 ? 's' : ''} need${atRisk.length > 1 ? '' : 's'} attention`)
  if (waiting) parts.push(`${waiting} report${waiting > 1 ? 's' : ''} waiting for check`)
  const worst = atRisk[0]
  const danger = alerts.find((a) => a.status === 'ACTIVE' && a.tier === 'WARNING' && a.kind !== 'all_clear')
  // Most urgent: a confirmed danger, else the worst zone, else the oldest report.
  const go = danger ? () => onZone(danger.zone_id) : worst ? () => onZone(worst.properties.id) : waiting ? onReports : null
  const goLabel = danger ? `Open ${danger.zone_name}` : worst ? `Open ${worst.properties.name}` : waiting ? 'Open reports' : ''
  if (!summary) return null
  return (
    <div className={`status-pill${calm ? ' calm' : danger ? ' danger' : ''}`} role="status">
      {calm ? <IconCheck size={16} /> : <IconAlert size={16} />}
      <span className="status-text">{calm ? 'All zones calm · no reports waiting' : parts.join(' · ')}</span>
      {go && <button className="btn sm" onClick={go}>{goLabel.length > 22 ? 'Open' : goLabel}</button>}
    </div>
  )
}

/* ------------------------------------------------------------------ drawer */

const WHAT_TO_DO: Record<Severity, string> = {
  LOW: 'Nothing to do. Keep normal watch.',
  MODERATE: 'Watch this zone. Tell road crews and village heads to stay alert.',
  HIGH: 'Check the slope. Warn villages below it and restrict the exposed road if rain continues.',
  CRITICAL: 'Act now: move people away from the slope, close the road, confirm the warning so sirens and SMS go out.',
}

function ZoneDrawer({ detail, weather, provenance, onClose, more, setMore }: {
  detail: any; weather: WeatherStatus | null; provenance: ZoneProvenance | null; onClose: () => void
  more: boolean; setMore: (v: boolean) => void
}) {
  const r = detail.risk
  const t = detail.terrain
  const { sources } = useControl()
  const sensorsFailed = (detail.sensors ?? []).filter((s: any) => s.status !== 'ACTIVE')
  const sev = (r?.severity ?? 'LOW') as Severity

  return (
    <div className="drawer">
      <div className="drawer-head">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <span className="label">{detail.code} · {detail.district}, {detail.state}</span>
          <button className="btn ghost sm" onClick={onClose}>Close</button>
        </div>
        <h2 style={{ fontSize: 19, marginTop: 6 }}>{detail.name}</h2>
        <div style={{ marginTop: 8 }} className="row">
          <SeverityChip value={sev} size={18} />
          {r?.computed_at && <span className="tiny muted">updated {timeAgo(r.computed_at)}</span>}
        </div>
      </div>

      <div className="drawer-body">
        {r ? (
          <>
            <div className="score-pair">
              <div className="score-cell"><div className="label">Risk score</div><div className="score-num">{Math.round(r.risk_score)}<small>/100</small></div></div>
              <div className="score-cell"><div className="label">How sure</div><div className="score-num">{Math.round(r.confidence * 100)}<small>%</small></div></div>
            </div>
            <div className="drawer-section">
              <span className="label">Why</span>
              <FactorList factors={r.contributing_factors ?? []} limit={3} />
            </div>
            <div className="drawer-section">
              <span className="label">What to do</span>
              <p className={`todo lv-${sev}`}>{WHAT_TO_DO[sev]}</p>
              <p className="tiny muted" style={{ margin: '8px 0 0' }}>Decision support, not a guaranteed prediction. Model {r.model_version}.</p>
            </div>
          </>
        ) : <div className="empty">No risk computed for this zone yet.</div>}

        <button className="more-toggle" onClick={() => setMore(!more)} aria-expanded={more}>
          <span className="label">More details</span><span style={{ transform: more ? 'rotate(180deg)' : 'none', display: 'inline-flex' }}><IconChevron size={16} /></span>
        </button>

        {more && (
          <>
            {r && (
              <div className="drawer-section">
                <span className="label">Rainfall &amp; soil moisture — last 72 h {weather?.using_real_weather && <Src kind="real" label="REAL · Open-Meteo" />}</span>
                <Sparkline data={detail.sparkline ?? []} />
                <dl className="kv" style={{ marginTop: 10 }}>
                  <dt>24h rainfall</dt><dd>{r.rainfall_24h?.toFixed(0)} mm</dd>
                  <dt>72h rainfall</dt><dd>{r.rainfall_72h?.toFixed(0)} mm</dd>
                  <dt>15-day antecedent</dt><dd>{r.antecedent_rain_15d?.toFixed(0)} mm</dd>
                  <dt>Soil moisture</dt><dd>{r.soil_moisture_pct?.toFixed(0)} %</dd>
                  <dt>24h outlook</dt><dd>{r.forecast_24h_mm?.toFixed(0)} mm <span className="tiny muted">(forecast)</span></dd>
                </dl>
                {(r.contributing_factors ?? []).length > 3 && <><span className="label" style={{ display: 'block', marginTop: 12 }}>All reasons</span><FactorList factors={r.contributing_factors} /></>}
              </div>
            )}

            {provenance && (
              <div className="drawer-section">
                <span className="label">Where this data comes from <Src kind="real" /></span>
                {provenance.sources.map((s) => (
                  <div key={s.endpoint} style={{ marginTop: 8, fontSize: 12.5 }}>
                    <div><strong>{s.role}</strong></div>
                    <div className="tiny muted">{s.model}</div>
                    <div className="mono tiny">{s.endpoint}</div>
                    {s.grid && <div className="tiny">grid cell <span className="mono">{s.grid.lat.toFixed(3)}, {s.grid.lon.toFixed(3)}</span>{s.grid.elevation_m != null && <> · {Math.round(s.grid.elevation_m)} m</>} · fetched {timeAgo(s.grid.fetched_at)}</div>}
                  </div>
                ))}
                <div className="tiny" style={{ marginTop: 8 }}>Requested point <span className="mono">{provenance.requested_point.lat.toFixed(4)}, {provenance.requested_point.lon.toFixed(4)}</span></div>
                <div className="row" style={{ marginTop: 8, gap: 8 }}>
                  <a className="btn ghost sm" href={provenance.verify_live.forecast} target="_blank" rel="noreferrer">Verify live: forecast <IconExternal size={13} /></a>
                  <a className="btn ghost sm" href={provenance.verify_live.archive} target="_blank" rel="noreferrer">Verify live: ERA5 archive <IconExternal size={13} /></a>
                </div>
                <p className="tiny muted" style={{ marginTop: 8 }}>{provenance.attribution}</p>
              </div>
            )}

            <div className="drawer-section">
              <span className="label">Terrain {sources && <Src kind="sim" />}</span>
              <dl className="kv" style={{ marginTop: 8 }}>
                <dt>Slope</dt><dd>{t.slope_deg}°</dd><dt>Aspect</dt><dd>{t.aspect_deg}°</dd><dt>Elevation</dt><dd>{t.elevation_m} m</dd>
                <dt>Lithology</dt><dd>{t.lithology.replace(/_/g, ' ')}</dd><dt>Land cover</dt><dd>{t.land_cover.replace(/_/g, ' ')}</dd>
                <dt>Area</dt><dd>{t.area_km2} km²</dd><dt>Population</dt><dd>{t.population?.toLocaleString()}</dd>
              </dl>
            </div>

            <div className="drawer-section">
              <span className="label">Roads crossing this zone ({detail.roads?.length ?? 0}) {sources && <Src kind="sim" />}</span>
              {(detail.roads ?? []).length === 0 && <p className="muted tiny">None.</p>}
              {(detail.roads ?? []).map((road: any) => (
                <div key={road.id} className="row" style={{ justifyContent: 'space-between', padding: '6px 0', borderTop: '1px solid var(--line)' }}>
                  <span style={{ flex: '1 1 auto', minWidth: 0 }}>{road.name}<span className="tiny muted"> · {road.exposed_km} km exposed</span></span>
                  <span className={`pill${road.status !== 'OPEN' ? ' on' : ''}`}>{road.status}</span>
                </div>
              ))}
            </div>

            <div className="drawer-section">
              <span className="label">Settlements ({detail.villages?.length ?? 0}) {sources && <Src kind="sim" />}</span>
              {(detail.villages ?? []).map((v: any) => (
                <div key={v.id} className="row" style={{ justifyContent: 'space-between', padding: '6px 0', borderTop: '1px solid var(--line)' }}>
                  <span>{v.name} <span className="tiny muted">· pop {v.population.toLocaleString()}</span></span>
                  {v.is_cut_off && <span className="pill on">CUT OFF</span>}
                </div>
              ))}
            </div>

            <div className="drawer-section">
              <span className="label">Sensor nodes ({detail.sensors?.length ?? 0})</span>
              {(detail.sensors ?? []).map((s: any) => (
                <div key={s.node_id} className="row" style={{ justifyContent: 'space-between', padding: '6px 0', borderTop: '1px solid var(--line)' }}>
                  <span className="mono">{s.live && <span className="live-dot" />}{s.node_id}</span>
                  <span className="row" style={{ gap: 8 }}>
                    {sources && <Src kind={s.source === 'hardware' ? 'live' : 'sim'} label={s.source === 'hardware' ? 'REAL · hardware' : 'SIMULATED'} />}
                    <span className="tiny muted">{s.last_seen ? `${s.seconds_since_seen != null && s.seconds_since_seen < 120 ? `${s.seconds_since_seen}s ago` : timeAgo(s.last_seen)}` : 'no telemetry'}</span>
                    <span className={`pill${s.status !== 'ACTIVE' ? ' on' : ''}`}>{s.status}</span>
                  </span>
                </div>
              ))}
              {sensorsFailed.length > 0 && <p className="notice tiny" style={{ marginTop: 10 }}>{sensorsFailed.length} node(s) not reporting — confidence reduced, and listed in the reasons above.</p>}
            </div>

            <div className="drawer-section">
              <span className="label">Citizen reports ({detail.citizen_reports?.length ?? 0}) <Src kind="real" label="REAL · public" /></span>
              {(detail.citizen_reports ?? []).length === 0 && <p className="muted tiny">None.</p>}
              {(detail.citizen_reports ?? []).map((c: any) => (
                <div key={c.id} style={{ padding: '8px 0', borderTop: '1px solid var(--line)' }}>
                  <div className="row" style={{ justifyContent: 'space-between' }}>
                    <strong style={{ fontSize: 13 }}>{c.issue_type.replace(/_/g, ' ')}</strong><span className="pill">{c.status}</span>
                  </div>
                  <div className="tiny muted">{fmtTime(c.created_at)} · {c.geo_valid ? 'inside zone' : 'outside monitored zones'}</div>
                </div>
              ))}
            </div>

            <div className="drawer-section">
              <span className="label">Field verifications ({detail.field_reports?.length ?? 0})</span>
              {(detail.field_reports ?? []).length === 0 && <p className="muted tiny">No officer has reported from this zone.</p>}
              {(detail.field_reports ?? []).map((f: any) => (
                <div key={f.id} style={{ padding: '8px 0', borderTop: '1px solid var(--line)' }}>
                  <div className="row" style={{ justifyContent: 'space-between' }}><strong style={{ fontSize: 13 }}>{f.verdict}</strong><span className="tiny muted">{fmtTime(f.observed_at)}</span></div>
                  <div className="tiny muted">{f.officer_name}{f.submitted_offline ? ' · submitted offline, synced later' : ''}</div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
