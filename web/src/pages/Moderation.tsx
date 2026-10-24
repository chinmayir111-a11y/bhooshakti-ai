/**
 * Citizen reports: scored, on a clock, one click to decide.
 *
 * Every card shows the corroboration score and why, the escalation state
 * (who was paged, what happens next and when), and three actions:
 * Acknowledge (stop the clock), CONFIRM (upgrade to a WARNING for the zone)
 * and DISMISS (false report — an all-clear goes to whoever got the advisory).
 */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { API_BASE, api, type CitizenReport } from '../api/client'
import { DemoBadge, PageTitle, Src, fmtTime, timeAgo } from '../components/common'
import { useLive } from '../api/ws'
import { countdown, useNow } from '../hooks'

const FILTERS = ['OPEN', 'PENDING', 'APPROVED', 'REJECTED', 'ESCALATED', 'ALL']

export function scoreColour(score: number): string {
  return score >= 85 ? 'var(--sev-critical)' : score >= 60 ? 'var(--sev-high)' : score >= 30 ? 'var(--sev-moderate)' : 'var(--sev-low)'
}

export function EscalationLine({ r, now }: { r: CitizenReport; now: number }) {
  const e = r.escalation
  if (!e) return null
  if (!e.open) {
    return <span className="tiny muted">{e.acknowledged_by ? `Seen by ${e.acknowledged_by} ${timeAgo(e.acknowledged_at)}` : 'Closed'}</span>
  }
  const parts: React.ReactNode[] = []
  parts.push(<span key="l" className="tiny muted">Level {e.level} paged</span>)
  if (e.next_step_at) {
    const c = countdown(e.next_step_at, now)
    parts.push(<span key="n" className={`countdown${c === 'now' ? ' now' : ''}`} title={e.next_step_label ?? ''}>⏱ {e.next_step_label?.replace('Escalate to ', '→ ') ?? 'escalate'} in {c}</span>)
  }
  if (e.advisory_alert_id) {
    parts.push(<Link key="a" to="/control/alerts" className="tier tier-ADVISORY" style={{ textDecoration: 'none' }}>ADVISORY #{e.advisory_alert_id} sent</Link>)
  } else if (e.advisory_at) {
    const c = countdown(e.advisory_at, now)
    parts.push(<span key="adv" className={`countdown${c === 'now' ? ' now' : ''}`}>📣 auto-ADVISORY in {c}</span>)
  }
  if (e.warning_alert_id) parts.push(<span key="w" className="tier tier-WARNING">WARNING #{e.warning_alert_id}</span>)
  return <div className="row" style={{ gap: 10 }}>{parts}</div>
}

export default function Moderation() {
  const [reports, setReports] = useState<CitizenReport[]>([])
  const [filter, setFilter] = useState('OPEN')
  const [notes, setNotes] = useState<Record<number, string>>({})
  const [busy, setBusy] = useState<number | null>(null)
  const now = useNow(1000)

  const load = useCallback(() => {
    const q = filter === 'ALL' ? undefined : filter === 'OPEN' ? 'PENDING' : filter
    api.reports(q).then((rs) => {
      const rows = filter === 'OPEN' ? rs.filter((r) => r.escalation?.open) : rs
      rows.sort((a, b) => (b.corroboration_score - a.corroboration_score) || (b.id - a.id))
      setReports(rows)
    }).catch(() => {})
  }, [filter])
  useEffect(load, [load])
  useLive((m) => { if (['report.new', 'report.moderated', 'report.escalation'].includes(m.event)) load() })

  async function act(id: number, fn: () => Promise<any>) {
    setBusy(id)
    try { await fn(); load() } finally { setBusy(null) }
  }

  return (
    <div className="page">
      <PageTitle title="Citizen reports"
                 subtitle="Scored for corroboration the moment they arrive, and escalated automatically until a human acts. CONFIRM upgrades to a WARNING; DISMISS sends the all-clear.">
        <DemoBadge dark />
      </PageTitle>
      <div className="page-body">
        <div className="page-narrow stack">
          <div className="row">
            <span className="label">Show</span>
            <div className="seg">
              {FILTERS.map((s) => <button key={s} className={filter === s ? 'on' : ''} onClick={() => setFilter(s)}>{s}</button>)}
            </div>
            <span className="muted tiny">{reports.length} report{reports.length === 1 ? '' : 's'}</span>
          </div>

          {reports.length === 0 && (
            <div className="card"><div className="empty">
              Nothing here. Reports arrive from the <Link to="/">citizen app</Link>, by SMS (<span className="mono">LS 734223 …</span>) and from the IVR.
            </div></div>
          )}

          {reports.map((r) => {
            const score = r.corroboration_score ?? 0
            const open = r.escalation?.open
            return (
              <div className="card lift" key={r.id} id={`report-${r.id}`}>
                <div className="card-head" style={{ gap: 14 }}>
                  <div style={{ textAlign: 'center', minWidth: 54 }}>
                    <div className="esc-score" style={{ color: scoreColour(score), fontSize: 24 }}>{Math.round(score)}</div>
                    <div className="label" style={{ fontSize: 9 }}>score</div>
                  </div>
                  <div style={{ flex: '1 1 auto', minWidth: 0 }}>
                    <strong>{r.issue_label || r.issue_type}</strong>
                    <span className="pill" style={{ marginLeft: 8 }}>{(r.channel || 'web').toUpperCase()}</span>
                    <span className={`pill${r.geo_valid ? ' on' : ''}`} style={{ marginLeft: 6 }}>{r.geo_valid ? 'INSIDE ZONE' : 'OUTSIDE ZONES'}</span>
                    <div style={{ marginTop: 4 }}><EscalationLine r={r} now={now} /></div>
                  </div>
                  <span className="pill">{r.status}</span>
                  <span className="tiny muted nowrap">#{r.id} · {timeAgo(r.created_at)}</span>
                </div>
                <div className="esc-bar" style={{ margin: 0, borderRadius: 0 }}><span style={{ width: `${score}%`, background: scoreColour(score) }} /></div>
                <div className="card-body">
                  <div className="grid-2">
                    <div>
                      <span className="label">Why this score</span>
                      <ul className="esc-reasons" style={{ fontSize: 13, marginTop: 6 }}>
                        {(r.corroboration_reasons ?? []).length === 0 && <li className="muted">No corroborating signal yet.</li>}
                        {(r.corroboration_reasons ?? []).map((x) => (
                          <li key={x.key}><b style={{ color: x.points < 0 ? 'var(--sev-critical-ink)' : 'var(--sev-low-ink)' }}>{x.points > 0 ? '+' : ''}{x.points}</b>{x.text}
                            {x.key === 'rain_above_threshold' && <> <Src kind="real" label="REAL · Open-Meteo" /></>}
                            {x.key === 'sensor_anomaly' && <> <Src kind="sim" label={x.text.includes('HW-') ? 'REAL · live sensor' : 'SIMULATED sensor'} /></>}
                          </li>
                        ))}
                      </ul>
                      {r.description && <p style={{ marginTop: 12, lineHeight: 1.6 }}>{r.description}</p>}
                      <dl className="kv" style={{ marginTop: 10 }}>
                        <dt>Zone</dt><dd>{r.zone_id ? <Link to={`/control?zone=${r.zone_id}`}>{r.zone_name}</Link> : '—'}</dd>
                        <dt>Coordinates</dt><dd className="mono">{r.lat.toFixed(4)}, {r.lon.toFixed(4)}</dd>
                        <dt>Phone</dt><dd className="mono">{r.phone || '—'}</dd>
                        <dt>Language</dt><dd>{r.language}</dd>
                      </dl>
                      <p className="notice tiny" style={{ marginTop: 12 }}>{r.geo_note}</p>
                    </div>
                    <div>
                      {r.photo_path && (
                        <img src={`${API_BASE}${r.photo_path}`} alt="Reported hazard"
                             style={{ maxWidth: '100%', borderRadius: 10, border: '1px solid var(--line)', display: 'block' }} />
                      )}
                      {r.voice_note_path && (
                        <div style={{ marginTop: 10 }}>
                          <span className="label">Voice note</span>
                          <audio controls src={`${API_BASE}${r.voice_note_path}`} style={{ width: '100%', marginTop: 4 }} />
                        </div>
                      )}
                      {open ? (
                        <>
                          <label className="label" htmlFor={`n${r.id}`} style={{ display: 'block', marginTop: 12 }}>Note (optional)</label>
                          <textarea id={`n${r.id}`} value={notes[r.id] ?? ''} placeholder="What did you decide, and why?"
                                    style={{ minHeight: 60 }}
                                    onChange={(e) => setNotes((n) => ({ ...n, [r.id]: e.target.value }))} />
                          <div className="esc-actions">
                            {!r.escalation.acknowledged_at && (
                              <button className="btn ghost sm" disabled={busy === r.id} onClick={() => act(r.id, () => api.acknowledgeReport(r.id))}>
                                ✓ Acknowledge (stop the clock)
                              </button>
                            )}
                            <button className="btn confirm sm" disabled={busy === r.id} onClick={() => act(r.id, () => api.confirmReport(r.id, notes[r.id] ?? ''))}>
                              CONFIRM → WARNING
                            </button>
                            <button className="btn dismiss sm" disabled={busy === r.id} onClick={() => act(r.id, () => api.dismissReport(r.id, notes[r.id] ?? ''))}>
                              DISMISS · all clear
                            </button>
                          </div>
                        </>
                      ) : (
                        <dl className="kv" style={{ marginTop: 12 }}>
                          <dt>Decision</dt><dd>{r.status}</dd>
                          <dt>By</dt><dd>{r.moderated_by || r.escalation?.acknowledged_by || '—'}</dd>
                          <dt>At</dt><dd>{fmtTime(r.moderated_at || r.escalation?.acknowledged_at)}</dd>
                          <dt>Note</dt><dd>{r.moderation_notes || '—'}</dd>
                        </dl>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
          <p className="notice tiny">
            Ladder: on arrival the on-duty moderator is paged (websocket + SMS + email). Every 10 unacknowledged minutes the
            next officer in the district roster is paged. At 20 minutes with a score of 60 or more — or at once with 85 — an
            ADVISORY goes to everyone registered in the zone, worded as unverified. Every automatic step is in the audit log with the score breakdown.
          </p>
        </div>
      </div>
    </div>
  )
}
