import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import MapView, { type Layers } from '../components/MapView'
import {
  DeliveryChips, FactorList, SeverityChip, Sparkline,
  SEVERITY_FILL, SEVERITY_ORDER, fmtTime, timeAgo,
} from '../components/common'
import { api, getUser, type Alert, type Severity, type Summary, type WeatherStatus } from '../api/client'
import { useLive, type LiveMessage } from '../api/ws'

interface Toast { id: number; step?: string; text: string }

const LAYER_LABELS: Array<[keyof Layers, string]> = [
  ['risk', 'Zone risk'],
  ['roads', 'Roads'],
  ['villages', 'Villages'],
  ['sensors', 'Sensors'],
  ['historical', 'Historical events'],
]

export default function Dashboard() {
  const [params, setParams] = useSearchParams()
  const user = getUser()
  const isAuthority = user?.role === 'authority'

  const [zones, setZones] = useState<any>(null)
  const [infrastructure, setInfrastructure] = useState<any>(null)
  const [sensors, setSensors] = useState<any>(null)
  const [historical, setHistorical] = useState<any>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [weather, setWeather] = useState<WeatherStatus | null>(null)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [newAlertIds, setNewAlertIds] = useState<Set<number>>(new Set())

  const [layers, setLayers] = useState<Layers>({
    risk: true, roads: true, villages: true, sensors: true, historical: false,
  })

  const zoneParam = params.get('zone')
  const [selectedZoneId, setSelectedZoneId] = useState<number | null>(zoneParam ? Number(zoneParam) : null)
  const [zoneDetail, setZoneDetail] = useState<any>(null)

  const [demo, setDemo] = useState<any>({ running: false, step: 0, total_steps: 8, label: 'Idle' })
  const [speed, setSpeed] = useState<1 | 4>(1)
  const [busy, setBusy] = useState<string | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])
  const toastSeq = useRef(0)

  const pushToast = useCallback((text: string, step?: string) => {
    const id = ++toastSeq.current
    setToasts((t) => [...t.slice(-5), { id, text, step }])
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 7000)
  }, [])

  // ---------------------------------------------------------------- loading
  const loadZones = useCallback(async () => { try { setZones(await api.zones()) } catch { /* offline */ } }, [])
  const loadSummary = useCallback(async () => { try { setSummary(await api.summary()) } catch { /* offline */ } }, [])
  const loadInfra = useCallback(async () => { try { setInfrastructure(await api.infrastructure()) } catch { /* offline */ } }, [])
  const loadSensors = useCallback(async () => { try { setSensors(await api.sensors()) } catch { /* offline */ } }, [])
  const loadAlerts = useCallback(async () => { try { setAlerts(await api.alerts(60)) } catch { /* offline */ } }, [])

  useEffect(() => {
    loadZones(); loadSummary(); loadInfra(); loadSensors(); loadAlerts()
    api.historical().then(setHistorical).catch(() => {})
    api.weatherStatus().then(setWeather).catch(() => {})
    api.demoState().then(setDemo).catch(() => {})
  }, [loadZones, loadSummary, loadInfra, loadSensors, loadAlerts])

  useEffect(() => {
    if (selectedZoneId == null) { setZoneDetail(null); return }
    api.zone(selectedZoneId).then(setZoneDetail).catch(() => setZoneDetail(null))
  }, [selectedZoneId, zones])

  // ------------------------------------------------------------------- live
  const connected = useLive((m: LiveMessage) => {
    switch (m.event) {
      case 'risk.update':
        loadZones()
        break
      case 'alert.new': {
        const a = m.payload as Alert
        setAlerts((prev) => (prev.some((x) => x.id === a.id) ? prev : [a, ...prev].slice(0, 80)))
        setNewAlertIds((s) => new Set(s).add(a.id))
        window.setTimeout(() => setNewAlertIds((s) => {
          const next = new Set(s); next.delete(a.id); return next
        }), 2000)
        pushToast(`${a.severity} — ${a.zone_name}. Risk ${Math.round(a.risk_score)}/100, confidence ${Math.round(a.confidence * 100)}%.`, 'Alert raised')
        break
      }
      case 'alert.delivery':
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
      case 'report.new':
        pushToast(`Citizen report: ${String(m.payload.issue_type || '').replace(/_/g, ' ')}${m.payload.zone_name ? ` in ${m.payload.zone_name}` : ''}.`, 'Public report')
        break
      case 'field.report': {
        const e = m.payload.escalation
        pushToast(
          `${m.payload.officer_name || 'Field officer'} — slope movement ${m.payload.verdict}.` +
          (e && e.severity_after !== e.severity_before
            ? ` ${e.zone_code} escalated ${e.severity_before} → ${e.severity_after}.` : ''),
          'Field verification',
        )
        loadZones()
        break
      }
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

  // ---------------------------------------------------------------- actions
  const selectZone = useCallback((id: number) => {
    setSelectedZoneId(id)
    setParams((p) => { const n = new URLSearchParams(p); n.set('zone', String(id)); return n }, { replace: true })
  }, [setParams])

  const closeDrawer = useCallback(() => {
    setSelectedZoneId(null)
    setParams((p) => { const n = new URLSearchParams(p); n.delete('zone'); return n }, { replace: true })
  }, [setParams])

  async function run(name: string, fn: () => Promise<any>, done?: string) {
    setBusy(name)
    try {
      const r = await fn()
      if (done) pushToast(done)
      return r
    } catch (e: any) {
      pushToast(`${name} failed: ${e?.message ?? e}`)
    } finally { setBusy(null) }
  }

  const counts = summary?.severity_counts ?? {}

  const sortedAlerts = useMemo(
    () => [...alerts].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()),
    [alerts],
  )

  return (
    <div className="page">
      {/* -------------------------------------------------- top strip */}
      <div className="top-strip">
        {SEVERITY_ORDER.map((sev) => (
          <div className="stat sev-tint" key={sev} style={{ borderLeftColor: SEVERITY_FILL[sev] }}>
            <div className="stat-value">{counts[sev] ?? 0}</div>
            <div className="stat-label">{sev.toLowerCase()} zones</div>
          </div>
        ))}
        <div className="stat"><div className="stat-value">{summary?.active_alerts ?? 0}</div><div className="stat-label">Active alerts</div></div>
        <div className="stat"><div className="stat-value">{summary?.unverified_reports ?? 0}</div><div className="stat-label">Unverified reports</div></div>
        <div className="stat"><div className="stat-value">{summary?.roads_flagged ?? 0}</div><div className="stat-label">Roads flagged</div></div>
        <div className="stat"><div className="stat-value">{summary?.villages_cut_off ?? 0}</div><div className="stat-label">Villages cut off</div></div>
        <div className="stat">
          <div className="stat-value">{(summary?.sensors_total ?? 0) - (summary?.sensors_failed ?? 0)}<span style={{ fontSize: 14, color: 'var(--text-muted)' }}>/{summary?.sensors_total ?? 0}</span></div>
          <div className="stat-label">Sensors reporting</div>
        </div>
      </div>

      {/* -------------------------------------------- data provenance */}
      {weather && (
        <div className="provenance">
          <span className={`pill${weather.using_real_weather ? ' on' : ''}`}>
            {weather.using_real_weather ? 'REAL WEATHER' : 'SIMULATED WEATHER'}
          </span>
          <span className="tiny">
            {weather.using_real_weather
              ? <>Rainfall and soil moisture are observed data from <strong>Open-Meteo</strong> (ERA5
                  reanalysis + forecast), cached locally. Latest observation {timeAgo(weather.latest_observation)}.</>
              : <>Rainfall and soil moisture are generated by the synthetic weather model.</>}
          </span>
          <span style={{ flex: 1 }} />
          <span className="tiny muted nowrap">
            Hazard events, sensors and zone boundaries remain simulated.
          </span>
        </div>
      )}

      {/* -------------------------------------------------- demo bar */}
      {isAuthority && (
        <div className="demo-bar">
          <button className="btn" disabled={demo.running || busy !== null}
                  onClick={() => run('Simulate', () => api.simulate(speed))}>
            {demo.running ? 'Running…' : 'Simulate Monsoon Event'}
          </button>
          <div className="seg">
            {([1, 4] as const).map((s) => (
              <button key={s} className={speed === s ? 'on' : ''} onClick={() => setSpeed(s)} disabled={demo.running}>
                {s}×
              </button>
            ))}
          </div>
          <button className="btn ghost" disabled={busy !== null}
                  onClick={() => run('Reset', async () => {
                    await api.resetDemo()
                    await Promise.all([loadZones(), loadSummary(), loadInfra(), loadAlerts()])
                  }, 'Demo reset to the seeded baseline.')}>
            Reset Demo
          </button>
          <button className="btn ghost" disabled={busy !== null}
                  onClick={() => run('Test alert', async () => {
                    const r = await api.testAlert({ zone_id: selectedZoneId ?? undefined })
                    const email = r.deliveries?.find((d: any) => d.channel === 'email')
                    pushToast(`Test alert for ${r.zone}: email ${email?.status ?? 'n/a'}${email?.status === 'SIMULATED' ? ' (set SMTP_HOST in .env to send for real)' : ` → ${email?.recipient}`}`)
                    await loadAlerts()
                  })}>
            Send test alert
          </button>
          <div className="demo-progress" title={demo.label}>
            <span style={{ width: `${((demo.step ?? 0) / (demo.total_steps || 8)) * 100}%` }} />
          </div>
          <div className="demo-step-label">
            {demo.step ? `${demo.step}/${demo.total_steps} · ${demo.label}` : demo.label}
          </div>
        </div>
      )}

      {/* -------------------------------------------------- main */}
      <div className="dash">
        {/* left rail: live alert feed */}
        <aside className="rail">
          <div className="rail-head">
            <h3 style={{ fontSize: 12, letterSpacing: '.05em', textTransform: 'uppercase', color: 'var(--text-muted)' }}>
              Live alert feed
            </h3>
            <span className="row tiny muted" style={{ gap: 6 }}>
              <span className={`ws-dot${connected ? ' live' : ''}`} />
              {connected ? 'live' : 'offline'}
            </span>
          </div>
          <div className="rail-scroll">
            {sortedAlerts.length === 0 && (
              <div className="empty">
                No alerts yet.<br />
                {isAuthority ? 'Run “Simulate Monsoon Event” to see the system escalate.' : 'Alerts appear here as zones escalate.'}
              </div>
            )}
            {sortedAlerts.map((a) => (
              <button key={a.id}
                      className={`alert-item lv-${a.severity}${newAlertIds.has(a.id) ? ' is-new' : ''}`}
                      onClick={() => selectZone(a.zone_id)}>
                <div className="alert-row">
                  <SeverityChip value={a.severity} />
                  <span className="tiny muted">{timeAgo(a.created_at)}</span>
                </div>
                <div className="alert-zone">{a.zone_name}</div>
                <div className="alert-meta">
                  Risk {Math.round(a.risk_score)}/100 · confidence {Math.round(a.confidence * 100)}%
                  {a.district ? ` · ${a.district}` : ''}
                </div>
                {a.contributing_factors?.[0] && (
                  <div className="alert-factor">{a.contributing_factors[0].text}</div>
                )}
                <DeliveryChips deliveries={a.deliveries ?? []} />
              </button>
            ))}
          </div>
        </aside>

        {/* map + overlays */}
        <div className="map-wrap">
          <MapView
            zones={zones} infrastructure={infrastructure} sensors={sensors}
            historical={historical} layers={layers}
            selectedZoneId={selectedZoneId} onSelectZone={selectZone}
          />

          <div className="map-panel tl">
            <div className="map-panel-head"><span className="label">Layers</span></div>
            <div className="map-panel-body">
              {LAYER_LABELS.map(([key, label]) => (
                <label className="toggle-row" key={key}>
                  <input type="checkbox" checked={layers[key]}
                         onChange={(e) => setLayers((l) => ({ ...l, [key]: e.target.checked }))} />
                  {label}
                </label>
              ))}
            </div>
          </div>

          <div className="map-panel bl">
            <div className="map-panel-head"><span className="label">Risk severity</span></div>
            <div className="map-panel-body">
              {SEVERITY_ORDER.slice().reverse().map((sev) => (
                <div className="legend-row" key={sev}>
                  <span className="legend-swatch" style={{ background: SEVERITY_FILL[sev] }} />
                  {sev}
                </div>
              ))}
              <div className="legend-row" style={{ marginTop: 6, borderTop: '1px solid var(--line)', paddingTop: 6 }}>
                <svg width="22" height="11"><line x1="0" y1="5.5" x2="22" y2="5.5" stroke="#1F3864" strokeWidth="3" strokeDasharray="6 3" /></svg>
                Road blocked
              </div>
              <div className="legend-row">
                <span style={{ width: 22, display: 'inline-flex', justifyContent: 'center' }}>
                  <span style={{ width: 9, height: 9, border: '1.5px solid #1F3864', transform: 'rotate(45deg)', display: 'inline-block' }} />
                </span>
                Sensor (hollow = failed)
              </div>
            </div>
          </div>

          {/* zone drawer */}
          {zoneDetail && (
            <ZoneDrawer detail={zoneDetail} weather={weather} onClose={closeDrawer} />
          )}
        </div>
      </div>

      {/* -------------------------------------------------- toasts */}
      <div className="toasts">
        {toasts.map((t) => (
          <div className="toast" key={t.id}>
            {t.step && <div className="toast-step">{t.step}</div>}
            <div className="toast-text">{t.text}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ drawer */

function ZoneDrawer({ detail, weather, onClose }: {
  detail: any; weather: WeatherStatus | null; onClose: () => void
}) {
  const r = detail.risk
  const t = detail.terrain
  const sensorsFailed = (detail.sensors ?? []).filter((s: any) => s.status !== 'ACTIVE')

  return (
    <div className="drawer">
      <div className="drawer-head">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <span className="label">{detail.code} · {detail.district}, {detail.state}</span>
          <button className="btn ghost sm" onClick={onClose}>Close</button>
        </div>
        <h2 style={{ fontSize: 17, marginTop: 6 }}>{detail.name}</h2>
        <div style={{ marginTop: 8 }}>
          <SeverityChip value={(r?.severity ?? 'LOW') as Severity} />
          {r?.computed_at && <span className="tiny muted" style={{ marginLeft: 10 }}>computed {timeAgo(r.computed_at)}</span>}
        </div>
      </div>

      <div className="drawer-body">
        {r ? (
          <>
            <div className="score-pair">
              <div className="score-cell">
                <div className="label">Risk score</div>
                <div className="score-num">{Math.round(r.risk_score)}<small>/100</small></div>
              </div>
              <div className="score-cell">
                <div className="label">Confidence</div>
                <div className="score-num">{Math.round(r.confidence * 100)}<small>%</small></div>
              </div>
            </div>

            <div className="drawer-section">
              <span className="label">Why this score</span>
              <FactorList factors={r.contributing_factors ?? []} />
              <p className="notice tiny" style={{ marginTop: 12 }}>
                Decision support, not a guaranteed prediction. The score is an estimate carrying
                the confidence shown above.
              </p>
            </div>

            <div className="drawer-section">
              <span className="label">
                Rainfall &amp; soil moisture — last 72 h
                {weather?.using_real_weather && <span className="muted"> · observed, Open-Meteo</span>}
              </span>
              <Sparkline data={detail.sparkline ?? []} />
              <dl className="kv" style={{ marginTop: 10 }}>
                <dt>24h rainfall</dt><dd>{r.rainfall_24h?.toFixed(0)} mm</dd>
                <dt>72h rainfall</dt><dd>{r.rainfall_72h?.toFixed(0)} mm</dd>
                <dt>15-day antecedent</dt><dd>{r.antecedent_rain_15d?.toFixed(0)} mm</dd>
                <dt>Soil moisture</dt><dd>{r.soil_moisture_pct?.toFixed(0)} %</dd>
                <dt>24h outlook</dt>
                <dd>{r.forecast_24h_mm?.toFixed(0)} mm
                  {weather?.using_real_weather && <span className="tiny muted"> (forecast)</span>}
                </dd>
              </dl>
            </div>
          </>
        ) : (
          <div className="empty">No risk computed for this zone yet.</div>
        )}

        <div className="drawer-section">
          <span className="label">Terrain</span>
          <dl className="kv" style={{ marginTop: 8 }}>
            <dt>Slope</dt><dd>{t.slope_deg}°</dd>
            <dt>Aspect</dt><dd>{t.aspect_deg}°</dd>
            <dt>Elevation</dt><dd>{t.elevation_m} m</dd>
            <dt>Lithology</dt><dd>{t.lithology.replace(/_/g, ' ')}</dd>
            <dt>Land cover</dt><dd>{t.land_cover.replace(/_/g, ' ')}</dd>
            <dt>Area</dt><dd>{t.area_km2} km²</dd>
            <dt>Population</dt><dd>{t.population?.toLocaleString()}</dd>
          </dl>
        </div>

        <div className="drawer-section">
          <span className="label">Roads crossing this zone ({detail.roads?.length ?? 0})</span>
          {(detail.roads ?? []).length === 0 && <p className="muted tiny">None.</p>}
          {(detail.roads ?? []).map((road: any) => (
            <div key={road.id} className="row" style={{ justifyContent: 'space-between', padding: '6px 0', borderTop: '1px solid var(--line)' }}>
              <span style={{ flex: '1 1 auto', minWidth: 0 }}>
                {road.name}
                <span className="tiny muted"> · {road.exposed_km} km exposed</span>
              </span>
              <span className={`pill${road.status !== 'OPEN' ? ' on' : ''}`}>{road.status}</span>
            </div>
          ))}
        </div>

        <div className="drawer-section">
          <span className="label">Settlements in this zone ({detail.villages?.length ?? 0})</span>
          {(detail.villages ?? []).length === 0 && <p className="muted tiny">None inside the zone boundary.</p>}
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
              <span className="mono">{s.node_id}</span>
              <span className="row" style={{ gap: 8 }}>
                <span className="tiny muted">{s.last_seen ? timeAgo(s.last_seen) : 'no telemetry'}</span>
                <span className={`pill${s.status !== 'ACTIVE' ? ' on' : ''}`}>{s.status}</span>
              </span>
            </div>
          ))}
          {sensorsFailed.length > 0 && (
            <p className="notice tiny" style={{ marginTop: 10 }}>
              {sensorsFailed.length} node(s) not reporting. Confidence in this zone's estimate is
              reduced accordingly, and the reduction is listed in the contributing factors.
            </p>
          )}
        </div>

        <div className="drawer-section">
          <span className="label">Field verifications ({detail.field_reports?.length ?? 0})</span>
          {(detail.field_reports ?? []).length === 0 && <p className="muted tiny">No officer has reported from this zone.</p>}
          {(detail.field_reports ?? []).map((f: any) => (
            <div key={f.id} style={{ padding: '8px 0', borderTop: '1px solid var(--line)' }}>
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <strong style={{ fontSize: 13 }}>{f.verdict}</strong>
                <span className="tiny muted">{fmtTime(f.observed_at)}</span>
              </div>
              <div className="tiny muted">{f.officer_name}{f.submitted_offline ? ' · submitted offline, synced later' : ''}</div>
              {f.notes && <div className="tiny" style={{ marginTop: 4 }}>{f.notes}</div>}
            </div>
          ))}
        </div>

        <div className="drawer-section">
          <span className="label">Citizen reports ({detail.citizen_reports?.length ?? 0})</span>
          {(detail.citizen_reports ?? []).length === 0 && <p className="muted tiny">None.</p>}
          {(detail.citizen_reports ?? []).map((c: any) => (
            <div key={c.id} style={{ padding: '8px 0', borderTop: '1px solid var(--line)' }}>
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <strong style={{ fontSize: 13 }}>{c.issue_type.replace(/_/g, ' ')}</strong>
                <span className="pill">{c.status}</span>
              </div>
              <div className="tiny muted">{fmtTime(c.created_at)} · {c.geo_valid ? 'inside zone' : 'outside monitored zones'}</div>
              {c.description && <div className="tiny" style={{ marginTop: 4 }}>{c.description}</div>}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
