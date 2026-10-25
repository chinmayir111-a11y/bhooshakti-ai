/** System health: every dependency green / amber / red with the last time it
 *  worked, refreshed every 30 s. Officers only (the API checks the role). */
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { DemoBadge, PageTitle, fmtTime, timeAgo } from '../components/common'

export default function Health() {
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const load = () => api.healthStatus().then((d) => { setData(d); setError('') })
      .catch((e) => setError(`Cannot reach the API (${e?.message ?? 'offline'}) — showing the last check below.`))
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="page">
      <PageTitle title="System health" subtitle="Each service the warning chain depends on. Red on a critical one shows a banner in the control room.">
        <DemoBadge dark />
      </PageTitle>
      <div className="page-body">
        <div className="page-narrow stack">
          {error && <p className="notice">{error}</p>}
          {data && (
            <>
              <p className="muted tiny">Checked {fmtTime(data.checked_at)}{data.critical_red.length ? ` · critical problem: ${data.critical_red.join(', ')}` : ' · no critical problems'}</p>
              <div className="card">
                <table className="grid">
                  <thead><tr><th>Service</th><th>Status</th><th>Detail</th><th>Last worked</th></tr></thead>
                  <tbody>
                    {data.checks.map((c: any) => (
                      <tr key={c.key}>
                        <td className="nowrap">{c.label}{c.critical && <span className="tiny muted"> · critical</span>}</td>
                        <td className="nowrap"><span className={`health-dot ${c.status}`} aria-hidden="true" /> {c.status === 'green' ? 'OK' : c.status === 'amber' ? 'Degraded' : 'Down'}</td>
                        <td>{c.detail}</td>
                        <td className="nowrap tiny muted">{c.last_ok ? timeAgo(c.last_ok) : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
