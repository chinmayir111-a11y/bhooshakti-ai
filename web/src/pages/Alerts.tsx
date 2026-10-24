import { TIER_SHORT } from '../components/Severity'
import { Fragment, useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, getUser, type Alert } from '../api/client'
import { DeliveryChips, DemoBadge, PageTitle, SeverityChip, Src, TierChip, fmtTime } from '../components/common'
import { useLive } from '../api/ws'

export default function Alerts() {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [filter, setFilter] = useState<string>('ALL')
  const [tier, setTier] = useState<string>('ALL')
  const [expanded, setExpanded] = useState<number | null>(null)
  const isAuthority = getUser()?.role === 'authority'

  const load = useCallback(() => { api.alerts(300).then(setAlerts).catch(() => {}) }, [])
  useEffect(load, [load])
  useLive((m) => { if (m.event === 'alert.new' || m.event === 'alert.delivery' || m.event === 'alert.update') load() })

  const rows = alerts
    .filter((a) => filter === 'ALL' || a.severity === filter)
    .filter((a) => tier === 'ALL' || (a.tier ?? 'WARNING') === tier)

  return (
    <div className="page">
      <PageTitle title="Alerts"
                 subtitle="Every notice raised — Be alert (unconfirmed) and Danger (confirmed) — with the channel it went out on and its delivery status.">
        <DemoBadge dark />
      </PageTitle>
      <div className="page-body">
        <div className="page-narrow stack">
          <div className="row">
            <span className="label">Kind</span>
            <div className="seg">
              {['ALL', 'WARNING', 'ADVISORY'].map((s) => (
                <button key={s} className={tier === s ? 'on' : ''} onClick={() => setTier(s)}>{s === 'ALL' ? 'All' : TIER_SHORT[s]}</button>
              ))}
            </div>
            <span className="label">Severity</span>
            <div className="seg">
              {['ALL', 'CRITICAL', 'HIGH', 'MODERATE', 'LOW'].map((s) => (
                <button key={s} className={filter === s ? 'on' : ''} onClick={() => setFilter(s)}>{s}</button>
              ))}
            </div>
            <span className="muted tiny">{rows.length} alert{rows.length === 1 ? '' : 's'}</span>
          </div>

          <div className="card" style={{ overflowX: 'auto' }}>
            <table className="grid">
              <thead>
                <tr>
                  <th>Kind</th><th>Severity</th><th>Zone</th><th>Risk</th><th>How sure</th>
                  <th>Raised</th><th>Source</th><th>Delivery</th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && (
                  <tr><td colSpan={8}><div className="empty">
                    No alerts. Run the monsoon simulation from the dashboard, or submit a citizen report and leave it unacknowledged.
                  </div></td></tr>
                )}
                {rows.map((a) => (
                  <Fragment key={a.id}>
                    <tr onClick={() => setExpanded(expanded === a.id ? null : a.id)} style={{ cursor: 'pointer' }}>
                      <td><TierChip tier={a.tier} status={a.status} /></td>
                      <td><SeverityChip value={a.severity} /></td>
                      <td>
                        <Link to={`/control?zone=${a.zone_id}`} onClick={(e) => e.stopPropagation()}>{a.zone_name}</Link>
                        <div className="tiny muted">{a.title}</div>
                      </td>
                      <td className="nowrap">{Math.round(a.risk_score)}/100 <Src kind={a.source === 'auto-advisory' || a.source === 'moderator-confirmed' ? 'real' : 'sim'} label={a.source === 'auto-advisory' ? 'REAL · public reports' : a.source === 'moderator-confirmed' ? 'REAL · human' : 'SIMULATED storm'} /></td>
                      <td className="nowrap">{Math.round(a.confidence * 100)}%</td>
                      <td className="nowrap">{fmtTime(a.created_at)}</td>
                      <td className="nowrap tiny muted">{a.source}</td>
                      <td><DeliveryChips deliveries={a.deliveries ?? []} /></td>
                    </tr>
                    {expanded === a.id && (
                      <tr>
                        <td colSpan={8} style={{ background: 'var(--panel)' }}>
                          <span className="label">Message as sent</span>
                          <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, margin: '6px 0 14px', fontFamily: 'var(--mono)' }}>{a.message}</pre>
                          <span className="label">Delivery detail</span>
                          <table className="grid" style={{ marginTop: 6 }}>
                            <thead><tr><th>Channel</th><th>Recipient</th><th>Lang</th><th>Status</th><th>Detail</th><th>Sent</th></tr></thead>
                            <tbody>
                              {(a.deliveries ?? []).map((d, i) => (
                                <tr key={i}>
                                  <td className="nowrap">{d.channel}</td>
                                  <td className="mono">{d.recipient || '—'}</td>
                                  <td className="nowrap">{d.language}</td>
                                  <td className="nowrap"><span className={`pill${d.status === 'SENT' ? ' on' : ''}`}>{d.status}</span></td>
                                  <td className="tiny">{d.detail}</td>
                                  <td className="nowrap tiny">{fmtTime(d.sent_at)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          <div className="row" style={{ marginTop: 12 }}>
                            <a className="btn ghost sm" href={`${import.meta.env.VITE_API_BASE || 'http://localhost:8000'}/api/cap/alerts/${a.id}.xml`} target="_blank" rel="noreferrer"
                               onClick={(e) => e.stopPropagation()}>CAP 1.2 XML</a>
                            {isAuthority && !a.acknowledged && (
                              <button className="btn sm" onClick={(e) => { e.stopPropagation(); api.acknowledge(a.id).then(load) }}>
                                I'm checking
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>

          <p className="notice">
            <strong>Be alert (unconfirmed)</strong> is issued by the system from unverified evidence and says so in its wording.
            <strong> Danger (confirmed)</strong> needs an officer's confirmation or a model CRITICAL, and also sounds the siren relay.
            Channels marked <em>simulated</em> run on stub gateways; email turns real once SMTP is set in <span className="mono">.env</span>.
            The same alerts are published as CAP 1.2 at <span className="mono">/api/cap/alerts.xml</span>.
          </p>
        </div>
      </div>
    </div>
  )
}
