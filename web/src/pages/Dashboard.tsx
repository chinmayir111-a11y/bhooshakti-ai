/**
 * Control room. One plain sentence of what needs attention, four live
 * counters, a ticker, the map (3D terrain by default, 2D/low-data on request
 * or automatically on a slow connection), the alert feed and the reports
 * waiting for a check. Every number can be labelled with its source ("Show
 * data sources"); labels are hidden until that switch is on.
 */
import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import MapView, { type Layers } from '../components/MapView'
import { type Layers3D, type Pin, type Pulse, type RainPoint, type ReportPoint, type View, type VolunteerPoint, type QuakePoint } from '../components/Map3D'
import {
  DeliveryChips, FactorList, GaugeStrip, SeverityChip, Sparkline, Src, TierChip, fmtTime, timeAgo,
} from '../components/common'
import { SEVERITY_FILL, SEVERITY_ORDER, SeverityShape, TIER_LABEL } from '../components/Severity'
import { IconAlert, IconCheck, IconChevron, IconCompass, IconExternal, IconLayers, IconPause, IconPlay, SIGN_PICTOS, type SignKey } from '../components/Pictograms'
import { API_BASE, ApiError, api, getToken, getUser, type Alert, type CitizenReport, type RainFrame, type Severity, type Summary, type Volunteer, type WeatherStatus, type ZoneProvenance } from '../api/client'
import { useLive, type LiveMessage } from '../api/ws'
import { chime, countdown, notify, prefersReducedMotion, useCountUp, useLocalFlag, useNow } from '../hooks'
import { useControl } from '../control/context'
import { EscalationLine, scoreColour } from './Moderation'

const Map3D = lazy(() => import('../components/Map3D'))

interface Toast { id: number; step?: string; text: string }
interface Tick { id: number; text: string; kind: string; at: string }

/** Can this device draw WebGL at all? (Some office PCs, remote desktops and
 *  old drivers cannot; they get the flat map only.) */
function hasWebGL(): boolean {
  try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')) } catch { return false }
}

/** 2D by default on connections that would struggle with vector + terrain tiles. */
function slowConnection(): boolean {
  const c = (navigator as any).connection
  return !!c && (c.saveData === true || /(^|-)(2g|3g)$/.test(String(c.effectiveType || '')))
}

const LAYER_LABELS: Array<[keyof Layers3D, string]> = [
  ['zones', 'Zones'], ['reports', 'Reports'], ['sensors', 'Sensors'], ['rain', 'Rain'], ['roads', 'Roads & villages'], ['volunteers', 'Village volunteers'], ['quakes', 'Earthquakes (USGS)'],
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

/** Officer-facing names for the villager warning signs (backend services/signs.py). */
const SIGN_LABELS: Record<SignKey, string> = {
  crack: 'Cracks in ground or walls', spring: 'Muddy or new springs / water stopped', tilt: 'Tilted trees, poles or walls',
  sound: 'Rumbling or cracking sounds', stones: 'Falling stones', sinking: 'Road or ground sinking',
}

export default function Dashboard() {
  const [params, setParams] = useSearchParams()
  const user = getUser()
  const isAuthority = user?.role === 'authority'
  const { dark, sources, sound } = useControl()

  const [zones, setZones] = useState<any>(null)
  const [infrastructure, setInfrastructure] = useState<any>(null)
  const [sensors, setSensors] = useState<any>(null)
  const [volunteers, setVolunteers] = useState<Volunteer[]>([])
  // Recent M4.5+ earthquakes (USGS), refreshed every 15 min like the server's feed.
  const [quakeList, setQuakeList] = useState<any[]>([])
  useEffect(() => {
    const load = () => api.quakes().then((r) => setQuakeList(r.quakes ?? [])).catch(() => {})
    load(); const id = setInterval(load, 15 * 60000); return () => clearInterval(id)
  }, [])
  const quakePoints: QuakePoint[] = useMemo(() => quakeList.map((q) => ({
    lat: q.lat, lon: q.lon, mag: q.mag, place: q.place, ago: timeAgo(q.occurred_at), depth_km: q.depth_km,
  })), [quakeList])
  // Critical services that are down (System health): a banner, checked every minute.
  const [healthRed, setHealthRed] = useState<string[]>([])
  useEffect(() => {
    const check = () => api.healthStatus().then((h) => setHealthRed(h.critical_red ?? []))
      .catch((e) => { if (!(e instanceof ApiError)) setHealthRed(['API unreachable']) })
    check(); const id = setInterval(check, 60000); return () => clearInterval(id)
  }, [])
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
  // The flat map shows at once on every device; the 3D map loads behind it
  // and fades in only when it has actually drawn. No WebGL or a failure: the
  // flat map stays.
  const webgl = useMemo(hasWebGL, [])
  const [failed3d, setFailed3d] = useState<string | null>(null)
  const [ready3d, setReady3d] = useState(false)
  const [hide2d, setHide2d] = useState(false)
  const want3d = !mode && webgl && !failed3d
  useEffect(() => { if (!want3d) { setReady3d(false); setHide2d(false) } }, [want3d])
  useEffect(() => { if (!ready3d) return; const id = window.setTimeout(() => setHide2d(true), 900); return () => window.clearTimeout(id) }, [ready3d])
  const [demoOpen, setDemoOpen] = useState(false)
  const [tour, setTour] = useState<{ id: number; stops: View[]; onDone?: () => void } | null>(null)
  const [drawerMore, setDrawerMore] = useState(false)
  const [satellite, setSatellite] = useLocalFlag('bhooshakti.satellite', false)
  const [railTab, setRailTab] = useState<'alerts' | 'reports'>('alerts')
  const [layersOpen, setLayersOpen] = useState(false)
  const [legendOpen, setLegendOpen] = useState(false)
  const [resetSignal, setResetSignal] = useState(0)
  const [layers, setLayers] = useState<Layers3D>({ zones: true, reports: true, sensors: true, rain: true, roads: true, volunteers: true, quakes: true })
  // The 2D map keeps its own layer names.
  const layers2d: Layers = { risk: layers.zones, roads: layers.roads, villages: layers.roads, sensors: layers.sensors, historical: false, volunteers: layers.volunteers, quakes: layers.quakes }

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
  // When the server is unreachable the last data stays on screen, labelled with its age.
  const [lastData, setLastData] = useState<string | null>(null)
  const loadZones = useCallback(async () => { try { setZones(await api.zones()); setLastData(new Date().toISOString()) } catch { /* offline */ } }, [])
  const loadSummary = useCallback(async () => { try { setSummary(await api.summary()) } catch { /* offline */ } }, [])
  const loadInfra = useCallback(async () => { try { setInfrastructure(await api.infrastructure()) } catch { /* offline */ } }, [])
  const loadSensors = useCallback(async () => { try { setSensors(await api.sensors()) } catch { /* offline */ } }, [])
  // Village volunteers (Gaon Prahari) are officer-only data: names and phones.
  const loadVolunteers = useCallback(async () => { try { setVolunteers(await api.volunteers()) } catch { /* not an officer, or offline */ } }, [])
  const loadAlerts = useCallback(async () => { try { setAlerts(await api.alerts(60)) } catch { /* offline */ } }, [])
  // Pending reports, including ones someone is already checking: they keep their
  // card (and CONFIRM / DISMISS) until a decision is made.
  const loadEsc = useCallback(async () => { try { setEscalations(await api.escalations(true)) } catch { /* offline */ } }, [])

  useEffect(() => {
    loadZones(); loadSummary(); loadInfra(); loadSensors(); loadAlerts(); loadEsc()
    api.historical().then(setHistorical).catch(() => {})
    api.weatherStatus().then(setWeather).catch(() => {})
    api.demoState().then(setDemo).catch(() => {})
    api.rainFrames(48).then((r) => setFrames(r.frames)).catch(() => {})
    loadVolunteers()
    // Hardware LIVE dots need last-seen refreshed; cheap, every 15 s. Volunteer
    // "2 h ago" and stale flags every minute.
    const id = setInterval(loadSensors, 15000)
    const vid = setInterval(loadVolunteers, 60000)
    return () => { clearInterval(id); clearInterval(vid) }
  }, [loadZones, loadSummary, loadInfra, loadSensors, loadAlerts, loadEsc, loadVolunteers])

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
        if (String(m.payload.text).startsWith('Village gauge')) {
          loadVolunteers()
          if (String(m.payload.text).includes('ALERT')) pushToast(m.payload.text, 'Village volunteer')
        }
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
  // Deep link for demos and screenshots: ?frame=dry | heavy pins the slider to
  // the driest / wettest observed hour; ?frame=<n> to an index.
  const frameParam = params.get('frame')
  useEffect(() => {
    if (!frameParam || !frames.length) return
    const observed = frames.map((f, i) => ({ i, total: Object.values(f.zones).reduce((a, b) => a + b, 0), fc: f.forecast })).filter((x) => !x.fc)
    if (!observed.length) return
    const pick = frameParam === 'heavy' ? observed.reduce((m, x) => (x.total > m.total ? x : m)) : frameParam === 'dry' ? observed.reduce((m, x) => (x.total < m.total ? x : m)) : { i: Number(frameParam) }
    if (Number.isFinite(pick.i)) { setPlaying(false); setFrameIdx(pick.i) }
  }, [frameParam, frames])
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
    catch (e: any) { pushToast(`Not done: ${e?.message ?? e}`, 'Error') }
    finally { setBusy(null) }
  }

  // Report buttons: a spinner while it runs, then a toast either way.
  const [openReportId, setOpenReportId] = useState<number | null>(null)
  // A CONFIRM release or a DISMISS waits 10 s with an Undo bar, then goes out.
  const [pending, setPending] = useState<{ r: CitizenReport; kind: 'confirm' | 'dismiss'; note: string; until: number } | null>(null)
  const [, setPendingTick] = useState(0)
  useEffect(() => {
    if (!pending) return
    const id = setInterval(() => {
      if (Date.now() >= pending.until) { clearInterval(id); setPending(null); executeAction(pending.r, pending.kind, pending.note) }
      else setPendingTick((n) => n + 1)
    }, 250)
    return () => clearInterval(id)
  }, [pending])   // eslint-disable-line react-hooks/exhaustive-deps

  // Two-person rule: CONFIRM first shows who the WARNING reaches; a second
  // officer releases it at once, the same officer after 30 s (server-enforced).
  const [release, setRelease] = useState<{ r: CitizenReport; reach: any; by: string; at: number } | null>(null)
  async function startConfirm(r: CitizenReport) {
    const me = user?.username
    if (r.confirm_prepared && r.confirm_prepared.by !== me) {
      setRelease({ r, reach: null, by: r.confirm_prepared.by, at: new Date(r.confirm_prepared.at).getTime() }); return
    }
    const reach = await run(`confirm-${r.id}`, () => api.prepareConfirm(r.id))
    if (reach) setRelease({ r, reach, by: reach.prepared_by, at: Date.now() })
  }
  async function reportAction(r: CitizenReport, kind: 'ack' | 'confirm' | 'dismiss') {
    if (kind === 'confirm' && release?.r.id !== r.id) { await startConfirm(r); return }
    if (kind === 'confirm') setRelease(null)
    // Closing an SOS either way needs a note (server-enforced).
    let note = ''
    if (r.issue_type === 'sos' && kind !== 'ack') {
      note = window.prompt(`Closing an SOS needs a note: what happened? (${kind === 'confirm' ? 'confirming danger' : 'not real'})`)?.trim() ?? ''
      if (!note) return
    }
    if (kind !== 'ack') {
      // Ten seconds to change your mind before anything leaves the building.
      if (pending) await executeAction(pending.r, pending.kind, pending.note)
      setPending({ r, kind, note, until: Date.now() + 10000 })
      return
    }
    await executeAction(r, kind, note)
  }
  async function executeAction(r: CitizenReport, kind: 'ack' | 'confirm' | 'dismiss', note = '') {
    const res: any = await run(`${kind}-${r.id}`,
      () => (kind === 'ack' ? api.acknowledgeReport(r.id) : kind === 'confirm' ? api.confirmReport(r.id, note) : api.dismissReport(r.id, note)))
    if (res === undefined) return
    pushToast(kind === 'ack' ? 'Marked as checking — the next officer will not be paged'
      : kind === 'confirm' ? (res.warning_alert_id ? 'Danger confirmed — alerts sent' : 'Confirmed — outside every zone, so no zone alert was sent')
      : (res.all_clear_alert_id ? 'Marked not real — all-clear sent' : 'Marked not real — nobody had been alerted'))
    await Promise.all([loadEsc(), loadAlerts(), loadZones(), loadSummary()])
  }
  // A report dot on the map: show its card in "Waiting for check".
  const selectReport = useCallback((id: number) => {
    setRailTab('reports'); setOpenReportId(id)
    window.setTimeout(() => document.getElementById(`esc-${id}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }), 60)
  }, [])

  // Keyboard: J/K move through the list, C confirm, D dismiss, M show on map, ? help.
  const [kbdHelp, setKbdHelp] = useState(false)
  const [selAlertId, setSelAlertId] = useState<number | null>(null)
  const keyHandler = useRef<(e: KeyboardEvent) => void>()
  keyHandler.current = (e: KeyboardEvent) => {
    const t = e.target as HTMLElement
    if (e.metaKey || e.ctrlKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable || release) return
    const k = e.key.toLowerCase()
    if (k === '?') { setKbdHelp((h) => !h); return }
    if (k === 'escape') { setKbdHelp(false); return }
    const step = k === 'j' ? 1 : k === 'k' ? -1 : 0
    if (railTab === 'reports') {
      const i = escalations.findIndex((r) => r.id === openReportId)
      if (step) { const n = escalations[i < 0 ? 0 : Math.max(0, Math.min(escalations.length - 1, i + step))]; if (n) selectReport(n.id); return }
      const cur = escalations[i]
      if (!cur) return
      if (k === 'c' && isAuthority) reportAction(cur, 'confirm')
      else if (k === 'd' && isAuthority) reportAction(cur, 'dismiss')
      else if (k === 'm' && cur.lat) { setFlyTo({ lat: cur.lat, lon: cur.lon, zoom: 12 }); if (cur.zone_id) setSelectedZoneId(cur.zone_id) }
    } else {
      const i = sortedAlerts.findIndex((a) => a.id === selAlertId)
      if (step) {
        const n = sortedAlerts[i < 0 ? 0 : Math.max(0, Math.min(sortedAlerts.length - 1, i + step))]
        if (n) { setSelAlertId(n.id); window.setTimeout(() => document.getElementById(`alert-${n.id}`)?.scrollIntoView({ block: 'nearest' }), 30) }
        return
      }
      const cur = sortedAlerts[i]
      if (cur && k === 'm') selectZone(cur.zone_id)
    }
  }
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => keyHandler.current?.(e)
    const onHelp = () => setKbdHelp(true)
    window.addEventListener('keydown', onKey); window.addEventListener('bh-kbd-help', onHelp)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('bh-kbd-help', onHelp) }
  }, [])

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

  // Rain radar input: this hour's rain per zone (surface) + the 24 h total (chip).
  const rainPoints: RainPoint[] = useMemo(() => {
    if (!zones?.features || !rainByZone) return []
    return zones.features.map((f: any) => ({
      lat: f.properties.centroid[0], lon: f.properties.centroid[1],
      mm: rainByZone[String(f.properties.id)] ?? 0, mm24: rain24ByZone?.[String(f.properties.id)] ?? 0,
    }))
  }, [zones, rainByZone, rain24ByZone])

  const pins: Pin[] = useMemo(() => {
    if (!sensors?.features) return []
    return sensors.features.map((f: any) => {
      const latest = f.properties.latest
      const anomalous = !!latest && ((latest.tilt_deg ?? 0) >= 1.5 || (latest.soil_moisture_pct ?? 0) >= 90)
      return {
        lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1],
        live: !!f.properties.live, failed: f.properties.status === 'FAILED', source: f.properties.source, anomalous,
        label: `${f.properties.node_id} · ${f.properties.source === 'hardware' ? (f.properties.live ? 'LIVE hardware' : 'hardware, offline') : 'simulated'}${latest ? ` · tilt ${latest.tilt_deg ?? '—'}° soil ${latest.soil_moisture_pct ?? '—'}%` : ''}`,
        node: f.properties.node_id, tilt: latest?.tilt_deg ?? null, soil: latest?.soil_moisture_pct ?? null,
        seen: `${f.properties.source === 'hardware' ? (f.properties.live ? 'Live hardware' : 'Hardware, offline') : 'Simulated node'}${f.properties.last_seen ? ` · last reading ${timeAgo(f.properties.last_seen)}` : ''}`,
      }
    })
  }, [sensors])

  const volunteerPoints: VolunteerPoint[] = useMemo(() => volunteers.map((v) => ({
    id: v.id, lat: v.lat, lon: v.lon, name: v.name, place: v.place, simulated: v.simulated,
    last_mm: v.last_mm, ago: timeAgo(v.last_at), total_24h: v.total_24h, level: v.level, stale: v.stale,
  })), [volunteers])
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

      {healthRed.length > 0 && (
        <p className="notice health-banner" role="alert">
          <IconAlert size={15} />
          {healthRed.includes('API unreachable')
            ? <>Cannot reach the server — showing data last updated {lastData ? timeAgo(lastData) : 'earlier'}. It will refresh when the connection returns.</>
            : <>System problem: {healthRed.join(', ')} — warnings may not go out.</>}
          {' '}<Link to="/control/health">Details</Link>
        </p>
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
                  <button key={a.id} id={`alert-${a.id}`} className={`alert-item lv-${a.severity}${newAlertIds.has(a.id) ? ' is-new' : ''}${selAlertId === a.id ? ' open' : ''}`} onClick={() => { setSelAlertId(a.id); selectZone(a.zone_id) }}>
                    <div className="alert-row">
                      <span className="row" style={{ gap: 6 }}><TierChip tier={a.tier} status={a.status} /><SeverityChip value={a.severity} /></span>
                      <span className="tiny muted">{timeAgo(a.created_at)}</span>
                    </div>
                    <div className="alert-zone">{a.zone_name}</div>
                    <div className="alert-meta">Risk {Math.round(a.risk_score)}/100 · {Math.round(a.confidence * 100)}% sure{a.district ? ` · ${a.district}` : ''}</div>
                    <div className="alert-factor">{a.kind && a.kind !== 'risk' ? a.title : a.contributing_factors?.[0]?.text}</div>
                    <DeliveryChips deliveries={a.deliveries ?? []} />
                    {isAuthority && (a.deliveries ?? []).some((d: any) => d.status === 'FAILED') && (
                      <span role="button" tabIndex={0} className="retry-chip"
                            onClick={(e) => { e.stopPropagation(); run(`retry-${a.id}`, () => api.retryAlert(a.id)).then((r) => { if (r) { pushToast(`Retried ${r.retried} failed deliver${r.retried === 1 ? 'y' : 'ies'}: ${r.results.map((x: any) => x.status).join(', ') || 'none'}`); loadAlerts() } }) }}
                            onKeyDown={(e) => { if (e.key === 'Enter') (e.currentTarget as HTMLElement).click() }}>
                        {busy === `retry-${a.id}` && <span className="spinner" />}Retry failed
                      </span>
                    )}
                  </button>
                ))}
              </>
            )}
            {railTab === 'reports' && (
              <>
                {escalations.length === 0 && <div className="empty">No reports waiting. Nothing needs a human right now.</div>}
                {escalations.map((r) => (
                  <div key={r.id} id={`esc-${r.id}`} className={`esc-item${r.zone_id ? '' : ' outside'}${openReportId === r.id ? ' open' : ''}`}>
                    <div className="esc-top">
                      <span className="esc-score term" title={TERMS.corroboration} style={{ color: r.zone_id ? scoreColour(r.corroboration_score) : 'var(--text-muted)' }}>{Math.round(r.corroboration_score)}</span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <strong style={{ fontSize: 13 }}>{r.issue_label}</strong> <span className="tiny muted">#{r.id} · {r.zone_name ?? 'Outside monitored area'} · {timeAgo(r.created_at)}</span>
                        <div className="esc-bar"><span style={{ width: `${r.corroboration_score}%`, background: r.zone_id ? scoreColour(r.corroboration_score) : 'var(--text-muted)' }} /></div>
                      </div>
                    </div>
                    {(r.signs?.length ?? 0) > 0 && (
                      <div className="esc-signs" aria-label="Warning signs seen">
                        {(r.signs as SignKey[]).filter((k) => k in SIGN_PICTOS).map((k) => {
                          const P = SIGN_PICTOS[k]
                          return <span key={k} title={SIGN_LABELS[k]}><P size={22} /></span>
                        })}
                      </div>
                    )}
                    {(r.sender_reports_1h ?? 0) >= 3 && (
                      <p className="tiny sender-flag"><IconAlert size={13} /> {r.sender_reports_1h} reports from this sender in the last hour — check before acting</p>
                    )}
                    <div style={{ marginTop: 6 }}><EscalationLine r={r} now={now} /></div>
                    <ul className="esc-reasons">{(r.corroboration_reasons ?? []).slice(0, 2).map((x) => <li key={x.key}><b>{x.points > 0 ? '+' : ''}{x.points}</b>{x.text}</li>)}</ul>
                    {isAuthority && (
                      <div className="esc-actions">
                        {!r.escalation?.acknowledged_at && <button className="btn ghost sm" disabled={busy !== null} onClick={() => reportAction(r, 'ack')}>{busy === `ack-${r.id}` ? <span className="spinner" /> : <IconCheck size={15} />}I'm checking</button>}
                        <button className="btn confirm sm" disabled={busy !== null} onClick={() => reportAction(r, 'confirm')}
                                title={r.confirm_prepared ? `Prepared by ${r.confirm_prepared.by} — a second officer can release it now` : 'Step 1 of 2: shows who the WARNING reaches'}>
                          {busy === `confirm-${r.id}` && <span className="spinner" />}{r.confirm_prepared && r.confirm_prepared.by !== user?.username ? 'RELEASE' : 'CONFIRM'}</button>
                        <button className="btn dismiss sm" disabled={busy !== null} onClick={() => reportAction(r, 'dismiss')}>{busy === `dismiss-${r.id}` && <span className="spinner" />}DISMISS</button>
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
          {!(want3d && hide2d) && (
            <MapView zones={zones} infrastructure={infrastructure} sensors={sensors} historical={historical}
                     layers={layers2d} selectedZoneId={selectedZoneId} onSelectZone={selectZone}
                     rain={rainByZone} pulses={pulses} volunteers={volunteerPoints} quakes={quakePoints} />
          )}
          {want3d && (
            <div className={`map3d-layer${ready3d ? ' ready' : ''}`}>
              <Suspense fallback={null}>
                <Map3D zones={zonesForMap} roads={infrastructure?.roads} villages={infrastructure?.villages}
                       reports={reportPoints} rain={rainPoints} pins={pins} pulses={pulses} layers={layers} volunteers={volunteerPoints} quakes={quakePoints}
                       selectedZoneId={selectedZoneId} onSelectZone={selectZone} onSelectReport={selectReport} flyTo={flyTo} dark={dark}
                       basemap={satellite ? 'satellite' : 'map'} idleRotate tour={tour} resetSignal={resetSignal}
                       onReady={() => setReady3d(true)}
                       onFail={(why) => { setFailed3d(why); pushToast(`3D map unavailable here (${why}) — showing the flat map.`) }} />
              </Suspense>
            </div>
          )}
          {want3d && !ready3d && <div className="map-loading-chip" role="status"><span className="spin" />Loading 3D map…</div>}

          {/* One compact control group, top-right; MapLibre's zoom/compass sit under it. */}
          <div className="map-ctrl">
            <div className="seg">
              <button className={want3d ? 'on' : ''} disabled={!webgl} onClick={() => { setFailed3d(null); setMode(false) }}
                      title={webgl ? 'Vector tiles + terrain' : 'This device cannot draw the 3D map (no WebGL)'}>3D</button>
              <button className={!want3d ? 'on' : ''} onClick={() => setMode(true)} title="Flat map — works on every device">2D</button>
            </div>
            {want3d && (
              <div className="seg">
                <button className={!satellite ? 'on' : ''} onClick={() => setSatellite(false)}>Map</button>
                <button className={satellite ? 'on' : ''} onClick={() => setSatellite(true)} title="Esri World Imagery on the terrain">Satellite</button>
              </div>
            )}
            <div className="layers-menu" onMouseLeave={() => setLayersOpen(false)}>
              <button className={`iconbtn${layersOpen ? ' on' : ''}`} aria-label="Layers" aria-expanded={layersOpen} onClick={() => setLayersOpen((o) => !o)}><IconLayers size={16} /><span className="lbl">Layers</span></button>
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
            {want3d && <button className="iconbtn" title="Fit every monitored zone in view" aria-label="Show all zones" onClick={() => setResetSignal((n) => n + 1)}><IconCompass size={16} /><span className="lbl">Show all zones</span></button>}
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
                <div className="legend-rain">
                  <div className="legend-row" style={{ marginTop: 6, borderTop: '1px solid var(--line)', paddingTop: 6 }}>Rain this hour (radar) {sources && <Src kind="real" label="REAL · Open-Meteo" />}</div>
                  <div className="ramp" />
                  <div className="ramp-labels"><span>0</span><span>2</span><span>10</span><span>30</span><span>60+ mm</span></div>
                  <div className="tiny muted">Chips from zoom 10 show each zone's 24 h total.</div>
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

          {zoneDetail && <ZoneDrawer detail={zoneDetail} weather={weather} provenance={provenance} onClose={closeDrawer} more={drawerMore} setMore={setDrawerMore}
                                     volunteers={volunteers.filter((v) => v.zone_id === zoneDetail.id)} />}
        </div>
      </div>

      {kbdHelp && (
        <div className="release-backdrop" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts" onClick={() => setKbdHelp(false)}>
          <div className="card release-card" onClick={(e) => e.stopPropagation()}>
            <div className="card-body">
              <h3 style={{ margin: 0 }}>Keyboard shortcuts</h3>
              <dl className="kv kbd-list" style={{ marginTop: 12 }}>
                <dt><kbd>J</kbd> / <kbd>K</kbd></dt><dd>Next / previous in the list</dd>
                <dt><kbd>C</kbd></dt><dd>Confirm the selected report (then release, with 10 s to undo)</dd>
                <dt><kbd>D</kbd></dt><dd>Dismiss the selected report (10 s to undo)</dd>
                <dt><kbd>M</kbd></dt><dd>Show it on the map</dd>
                <dt><kbd>?</kbd></dt><dd>This help · <kbd>Esc</kbd> closes it</dd>
              </dl>
              <div className="row" style={{ justifyContent: 'flex-end', marginTop: 12 }}><button className="btn ghost" onClick={() => setKbdHelp(false)}>Close</button></div>
            </div>
          </div>
        </div>
      )}

      {pending && (
        <div className="undo-bar" role="status" aria-live="polite">
          <span>{pending.kind === 'confirm' ? `Releasing the WARNING${pending.r.zone_name ? ` for ${pending.r.zone_name}` : ''}` : `Marking report #${pending.r.id} not real`} in {Math.max(0, Math.ceil((pending.until - Date.now()) / 1000))} s</span>
          <button className="btn sm" onClick={() => { setPending(null); pushToast('Undone — nothing was sent') }}>Undo</button>
        </div>
      )}

      {release && <ReleaseDialog release={release} me={user?.username ?? ''} busy={busy !== null}
                                 onCancel={() => setRelease(null)} onRelease={() => reportAction(release.r, 'confirm')} />}

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
  const waiting = escalations.filter((r) => !r.escalation?.acknowledged_at).length
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

/** Plain words for the technical terms on this screen (hover or long-press). */
const TERMS = {
  confidence: 'Confidence: how much the system trusts this risk number right now. It drops when sensors are silent, weather data is old or the signals disagree.',
  corroboration: 'Corroboration (trust score, 0-100): how much independent evidence backs this report up — rain, sensors, the zone\'s state, other people. Not the chance it is true.',
  cap: 'CAP 1.2: the international alert format that NDMA\'s SACHET and mobile cell broadcast read.',
}

/** "What to do now": 3-5 steps from the zone's own roads, villages, shelters,
 *  volunteers and open reports. Each tick is written to the audit log. */
function TodoList({ zoneId }: { zoneId: number }) {
  const [items, setItems] = useState<any[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState('')
  const canTick = getUser()?.role === 'authority'
  useEffect(() => { setItems(null); api.zoneTodo(zoneId).then(setItems).catch(() => setItems([])) }, [zoneId])
  if (!items?.length) return null
  async function tick(key: string) {
    setBusy(key); setErr('')
    try { const r = await api.tickTodo(zoneId, key); setItems((xs) => xs!.map((x) => x.key === key ? { ...x, done: r.done } : x)) }
    catch (e: any) { setErr(`Not saved: ${e?.message ?? 'error'}`) }
    finally { setBusy(null) }
  }
  return (
    <div className="todo-list">
      <span className="label">What to do now</span>
      {items.map((s) => (
        <div key={s.key} className={`todo-step${s.done ? ' done' : ''}`}>
          <span className="todo-text">{s.text}{s.done && <span className="tiny muted"> · done by {s.done.by}, {timeAgo(s.done.at)}</span>}</span>
          {!s.done && canTick && (
            <button className="btn ghost sm" disabled={busy !== null} onClick={() => tick(s.key)}>
              {busy === s.key ? <span className="spinner" /> : <IconCheck size={14} />}Done
            </button>
          )}
          {s.done && <IconCheck size={16} />}
        </div>
      ))}
      {err && <p className="notice tiny" role="alert">{err}</p>}
    </div>
  )
}

/** One click: a PDF for the DM / SDMA (time, risk, why, rain, reports, roads, shelters, actions). */
function SitrepButton({ zoneId, code }: { zoneId: number; code: string }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  async function download() {
    setBusy(true); setErr('')
    try {
      const res = await fetch(`${API_BASE}/zones/${zoneId}/sitrep.pdf`, { headers: { Authorization: `Bearer ${getToken() ?? ''}` } })
      if (!res.ok) throw new Error(`${res.status}`)
      const url = URL.createObjectURL(await res.blob())
      const a = document.createElement('a'); a.href = url; a.download = `sitrep-${code}.pdf`; a.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 2000)
    } catch (e: any) { setErr(`Could not make the report (${e?.message ?? 'error'})`) }
    finally { setBusy(false) }
  }
  return (
    <>
      <button className="btn ghost sm" style={{ marginTop: 10 }} onClick={download} disabled={busy}>
        {busy && <span className="spinner" />}Download situation report (PDF)
      </button>
      {err && <p className="notice tiny" role="alert">{err}</p>}
    </>
  )
}

/** Step 2 of CONFIRM: what the WARNING will do, and the release button. */
function ReleaseDialog({ release, me, busy, onCancel, onRelease }: {
  release: { r: CitizenReport; reach: any; by: string; at: number }; me: string; busy: boolean
  onCancel: () => void; onRelease: () => void
}) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(id) }, [])
  const second = release.by !== me
  const left = second ? 0 : Math.max(0, Math.ceil(30 - (now - release.at) / 1000))
  const reach = release.reach
  return (
    <div className="release-backdrop" role="dialog" aria-modal="true" aria-labelledby="release-title">
      <div className="card release-card">
        <div className="card-body">
          <h3 id="release-title" style={{ margin: 0 }}>Release the WARNING{release.r.zone_name ? ` for ${release.r.zone_name}` : ''}?</h3>
          {reach ? (
            <p style={{ margin: '10px 0 0' }}>
              This alerts <strong>{reach.phones} registered phone{reach.phones === 1 ? '' : 's'}</strong> by SMS and voice call
              and sounds the zone siren. About <strong>{Number(reach.population).toLocaleString()}</strong> people live in the zone.
            </p>
          ) : (
            <p style={{ margin: '10px 0 0' }}>Prepared by <strong>{release.by}</strong>. As the second officer you can release it now.</p>
          )}
          <p className="tiny muted" style={{ margin: '8px 0 0' }}>
            Two-person rule: a second officer releases at once; the officer who prepared it can release after 30 seconds.
          </p>
          <div className="row" style={{ gap: 8, marginTop: 14, justifyContent: 'flex-end' }}>
            <button className="btn ghost" onClick={onCancel} disabled={busy}>Cancel</button>
            <button className="btn confirm" onClick={onRelease} disabled={busy || left > 0}>
              {busy && <span className="spinner" />}{left > 0 ? `Release in ${left} s` : 'Release WARNING'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

/** Safe places near the zone (OpenStreetMap). An officer can mark one unsafe —
 *  it is on the slope, flooded, locked — and it is never suggested to anyone. */
function ShelterList({ shelters }: { shelters: any[] }) {
  const { sources } = useControl()
  const user = getUser()
  const [marks, setMarks] = useState<Record<number, boolean>>({})
  const [busy, setBusy] = useState<number | null>(null)
  const [err, setErr] = useState('')
  async function toggle(s: any, unsafe: boolean) {
    setBusy(s.id); setErr('')
    try { await api.markShelter(s.id, unsafe); setMarks((m) => ({ ...m, [s.id]: unsafe })) }
    catch (e: any) { setErr(`Not saved: ${e?.message ?? 'error'}`) }
    finally { setBusy(null) }
  }
  return (
    <div className="drawer-section">
      <span className="label">Safe places ({shelters.length}) {sources && <Src kind="real" label="REAL · OpenStreetMap" />}</span>
      {shelters.length === 0 && <p className="muted tiny">No schools, halls or hospitals mapped within 3 km.</p>}
      {shelters.slice(0, 12).map((s) => {
        const unsafe = marks[s.id] ?? s.unsafe
        return (
          <div key={s.id} className="row" style={{ justifyContent: 'space-between', padding: '6px 0', borderTop: '1px solid var(--line)', gap: 8 }}>
            <span style={{ flex: '1 1 auto', minWidth: 0, textDecoration: unsafe ? 'line-through' : 'none', opacity: unsafe ? 0.6 : 1 }}>
              {s.name}<span className="tiny muted"> · {s.kind_label}{s.inside_zone ? ' · inside zone' : ''}</span>
            </span>
            {user?.role === 'authority'
              ? <button className="btn ghost sm" disabled={busy !== null} onClick={() => toggle(s, !unsafe)}>
                  {busy === s.id && <span className="spinner" />}{unsafe ? 'Mark safe' : 'Mark unsafe'}
                </button>
              : unsafe && <span className="pill on">UNSAFE</span>}
          </div>
        )
      })}
      {err && <p className="notice tiny" role="alert">{err}</p>}
    </div>
  )
}

function ZoneDrawer({ detail, weather, provenance, onClose, more, setMore, volunteers }: {
  detail: any; weather: WeatherStatus | null; provenance: ZoneProvenance | null; onClose: () => void
  more: boolean; setMore: (v: boolean) => void; volunteers: Volunteer[]
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
            {(r.contributing_factors ?? []).some((f: any) => /^stale_|^no_sensors$|^sensor_failure$/.test(f.key ?? '')) && (
              <p className="notice stale-banner" role="status">
                <IconAlert size={15} /> Data is stale — treat this as uncertain.{' '}
                <span className="tiny">{(r.contributing_factors ?? []).filter((f: any) => /^stale_|^no_sensors$|^sensor_failure$/.test(f.key ?? '')).map((f: any) => f.text).join(' · ')}</span>
              </p>
            )}
            <div className="score-pair">
              <div className="score-cell"><div className="label">Risk score</div><div className="score-num">{Math.round(r.risk_score)}<small>/100</small></div></div>
              <div className="score-cell"><div className="label"><span className="term" title={TERMS.confidence}>How sure</span></div><div className="score-num">{Math.round(r.confidence * 100)}<small>%</small></div></div>
            </div>
            <div className="drawer-section">
              <span className="label">Why</span>
              <FactorList factors={r.contributing_factors ?? []} limit={3} />
            </div>
            <div className="drawer-section">
              <span className="label">What to do</span>
              <p className={`todo lv-${sev}`}>{WHAT_TO_DO[sev]}</p>
              {(sev === 'HIGH' || sev === 'CRITICAL') && <TodoList zoneId={detail.id} />}
              <SitrepButton zoneId={detail.id} code={detail.code} />
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
                {(detail.volunteer_gauge ?? []).length > 0 && (detail.sparkline ?? []).length > 0 && (
                  <>
                    <GaugeStrip data={detail.volunteer_gauge} from={detail.sparkline[0].ts} to={detail.sparkline[detail.sparkline.length - 1].ts} />
                    <p className="tiny muted" style={{ margin: '2px 0 0' }}>
                      <span className="legend-key bars" /> Open-Meteo, hourly · <span className="legend-key dot" /> Village gauge (volunteer), mm since the previous reading
                    </p>
                  </>
                )}
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

            <ShelterList shelters={detail.shelters ?? []} />

            <div className="drawer-section">
              <span className="label">Village volunteers ({volunteers.length})</span>
              {volunteers.length === 0 && <p className="muted tiny">None registered in this zone.</p>}
              {volunteers.map((v) => (
                <div key={v.id} className="row" style={{ justifyContent: 'space-between', padding: '6px 0', borderTop: '1px solid var(--line)' }}>
                  <span style={{ flex: '1 1 auto', minWidth: 0 }}>{v.name}<span className="tiny muted"> · gauge at {v.place} · ···{v.phone_last4}</span></span>
                  <span className="row" style={{ gap: 8 }}>
                    {v.simulated && sources && <Src kind="sim" />}
                    <span className="tiny muted">{v.total_24h.toFixed(0)} mm / 24 h · {v.last_at ? timeAgo(v.last_at) : 'no reading'}</span>
                    {v.stale ? <span className="pill">QUIET</span> : v.level !== 'none' && <span className="pill on">{v.level.toUpperCase()}</span>}
                  </span>
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
