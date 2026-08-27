import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, getUser, type Alert } from '../api/client'
import { DeliveryChips, PageTitle, SeverityChip, DemoBadge, fmtTime } from '../components/common'
import { useLive } from '../api/ws'

export default function Alerts() {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [filter, setFilter] = useState<string>('ALL')
  const [expanded, setExpanded] = useState<number | null>(null)
  const isAuthority = getUser()?.role === 'authority'

  const load = useCallback(() => { api.alerts(300).then(setAlerts).catch(() => {}) }, [])
  useEffect(load, [load])
  useLive((m) => { if (m.event === 'alert.new' || m.event === 'alert.delivery') load() })

  const rows = filter === 'ALL' ? alerts : alerts.filter((a) => a.severity === filter)

  return (
    <div className="page">
      <PageTitle title="Alerts"
                 subtitle="Every alert raised, with the channel it went out on and its delivery status.">
        <DemoBadge dark />
      </PageTitle>
      <div className="page-body">
        <div className="page-narrow stack">
          <div className="row">
            <span className="label">Severity</span>
            <div className="seg">
              {['ALL', 'CRITICAL', 'HIGH', 'MODERATE', 'LOW'].map((s) => (
                <button key={s} className={filter === s ? 'on' : ''} onClick={() => setFilter(s)}>{s}</button>
              ))}
            </div>
            <span className="muted tiny">{rows.length} alert{rows.length === 1 ? '' : 's'}</span>
          </div>

          <div className="card">
            <table className="grid">
              <thead>
                <tr>
                  <th>Severity</th><th>Zone</th><th>Risk</th><th>Confidence</th>
                  <th>Language</th><th>Raised</th><th>Source</th><th>Delivery</th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && (
                  <tr><td colSpan={8}><div className="empty">
                    No alerts. Run the monsoon simulation from the dashboard to see the system escalate.
                  </div></td></tr>
                )}
                {rows.map((a) => (
                  <>
                    <tr key={a.id} onClick={() => setExpanded(expanded === a.id ? null : a.id)} style={{ cursor: 'pointer' }}>
                      <td><SeverityChip value={a.severity} /></td>
                      <td>
                        <Link to={`/?zone=${a.zone_id}`} onClick={(e) => e.stopPropagation()}>{a.zone_name}</Link>
                        <div className="tiny muted">{a.district ?? ''}{a.state ? `, ${a.state}` : ''}</div>
                      </td>
                      <td className="nowrap">{Math.round(a.risk_score)}/100</td>
                      <td className="nowrap">{Math.round(a.confidence * 100)}%</td>
                      <td className="nowrap">{a.language}</td>
                      <td className="nowrap">{fmtTime(a.created_at)}</td>
                      <td className="nowrap tiny muted">{a.source}</td>
                      <td><DeliveryChips deliveries={a.deliveries ?? []} /></td>
                    </tr>
                    {expanded === a.id && (
                      <tr key={`${a.id}-x`}>
                        <td colSpan={8} style={{ background: 'var(--panel)' }}>
                          <span className="label">Contributing factors</span>
                          <ol style={{ margin: '8px 0 14px', paddingLeft: 20, fontSize: 13, lineHeight: 1.6 }}>
                            {(a.contributing_factors ?? []).map((f, i) => <li key={i}>{f.text}</li>)}
                          </ol>
                          <span className="label">Delivery detail</span>
                          <table className="grid" style={{ marginTop: 6 }}>
                            <thead><tr><th>Channel</th><th>Recipient</th><th>Status</th><th>Detail</th><th>Sent</th></tr></thead>
                            <tbody>
                              {(a.deliveries ?? []).map((d, i) => (
                                <tr key={i}>
                                  <td className="nowrap">{d.channel}</td>
                                  <td className="mono">{d.recipient || '—'}</td>
                                  <td className="nowrap"><span className={`pill${d.status === 'SENT' ? ' on' : ''}`}>{d.status}</span></td>
                                  <td className="tiny">{d.detail}</td>
                                  <td className="nowrap tiny">{fmtTime(d.sent_at)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          {isAuthority && !a.acknowledged && (
                            <button className="btn sm" style={{ marginTop: 12 }}
                                    onClick={(e) => { e.stopPropagation(); api.acknowledge(a.id).then(load) }}>
                              Acknowledge
                            </button>
                          )}
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>

          <p className="notice">
            Channels marked <strong>sim</strong> are simulated: the SMS gateway defaults to a stub
            so the demo needs no paid account, and email reports SIMULATED until SMTP credentials
            are set in <span className="mono">.env</span>. Console and WebSocket deliveries are real.
          </p>
        </div>
      </div>
    </div>
  )
}
