import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type CitizenReport } from '../api/client'
import { DemoBadge, PageTitle, fmtTime } from '../components/common'
import { API_BASE } from '../api/client'
import { useLive } from '../api/ws'

const DECISIONS = [
  ['APPROVED', 'Approve'],
  ['ESCALATED', 'Escalate to field officer'],
  ['REJECTED', 'Reject'],
] as const

export default function Moderation() {
  const [reports, setReports] = useState<CitizenReport[]>([])
  const [filter, setFilter] = useState('PENDING')
  const [notes, setNotes] = useState<Record<number, string>>({})
  const [busy, setBusy] = useState<number | null>(null)

  const load = useCallback(() => {
    api.reports(filter === 'ALL' ? undefined : filter).then(setReports).catch(() => {})
  }, [filter])
  useEffect(load, [load])
  useLive((m) => { if (m.event === 'report.new' || m.event === 'report.moderated') load() })

  async function decide(id: number, decision: string) {
    setBusy(id)
    try { await api.moderate(id, decision, notes[id] ?? ''); load() }
    finally { setBusy(null) }
  }

  return (
    <div className="page">
      <PageTitle title="Moderation queue"
                 subtitle="Citizen reports, each geo-validated against the monitored zones by PostGIS before it reaches you.">
        <DemoBadge dark />
      </PageTitle>
      <div className="page-body">
        <div className="page-narrow stack">
          <div className="row">
            <span className="label">Status</span>
            <div className="seg">
              {['PENDING', 'APPROVED', 'ESCALATED', 'REJECTED', 'ALL'].map((s) => (
                <button key={s} className={filter === s ? 'on' : ''} onClick={() => setFilter(s)}>{s}</button>
              ))}
            </div>
            <span className="muted tiny">{reports.length} report{reports.length === 1 ? '' : 's'}</span>
          </div>

          {reports.length === 0 && (
            <div className="card"><div className="empty">
              Nothing in this queue. Reports submitted at <Link to="/report">/report</Link> land here.
            </div></div>
          )}

          {reports.map((r) => (
            <div className="card" key={r.id}>
              <div className="card-head">
                <strong style={{ color: 'var(--navy)' }}>{r.issue_label || r.issue_type}</strong>
                <span className={`pill${r.geo_valid ? ' on' : ''}`}>
                  {r.geo_valid ? 'INSIDE MONITORED ZONE' : 'OUTSIDE ZONES'}
                </span>
                <div style={{ flex: 1 }} />
                <span className="pill">{r.status}</span>
                <span className="tiny muted">{fmtTime(r.created_at)}</span>
              </div>
              <div className="card-body">
                <div className="grid-2">
                  <div>
                    {r.description && <p style={{ marginTop: 0, lineHeight: 1.6 }}>{r.description}</p>}
                    <dl className="kv" style={{ marginTop: 10 }}>
                      <dt>Coordinates</dt><dd className="mono">{r.lat.toFixed(4)}, {r.lon.toFixed(4)}</dd>
                      <dt>Zone</dt>
                      <dd>{r.zone_id ? <Link to={`/?zone=${r.zone_id}`}>{r.zone_name}</Link> : '—'}</dd>
                      <dt>Language</dt><dd>{r.language}</dd>
                      <dt>Phone</dt><dd className="mono">{r.phone || '—'}</dd>
                    </dl>
                    <p className="notice tiny" style={{ marginTop: 12 }}>{r.geo_note}</p>
                    {r.photo_path && (
                      <img src={`${API_BASE}${r.photo_path}`} alt="Reported hazard"
                           style={{ marginTop: 12, maxWidth: '100%', border: '1px solid var(--line)' }} />
                    )}
                  </div>
                  <div>
                    {r.status === 'PENDING' ? (
                      <>
                        <label className="label" htmlFor={`n${r.id}`}>Moderator note</label>
                        <textarea id={`n${r.id}`} value={notes[r.id] ?? ''}
                                  placeholder="What did you decide, and why?"
                                  onChange={(e) => setNotes((n) => ({ ...n, [r.id]: e.target.value }))} />
                        <div className="row" style={{ marginTop: 10 }}>
                          {DECISIONS.map(([value, label]) => (
                            <button key={value}
                                    className={`btn sm${value === 'APPROVED' ? '' : ' ghost'}`}
                                    disabled={busy === r.id}
                                    onClick={() => decide(r.id, value)}>
                              {label}
                            </button>
                          ))}
                        </div>
                      </>
                    ) : (
                      <dl className="kv">
                        <dt>Decision</dt><dd>{r.status}</dd>
                        <dt>By</dt><dd>{r.moderated_by || '—'}</dd>
                        <dt>At</dt><dd>{fmtTime(r.moderated_at)}</dd>
                        <dt>Note</dt><dd>{r.moderation_notes || '—'}</dd>
                      </dl>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
