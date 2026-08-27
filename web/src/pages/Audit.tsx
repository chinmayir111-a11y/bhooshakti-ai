import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { DemoBadge, PageTitle, fmtTime } from '../components/common'

export default function Audit() {
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.audit(300).then(setData).catch((e) => setError(e?.message ?? 'Cannot load the audit log'))
  }, [])

  return (
    <div className="page">
      <PageTitle title="Audit log"
                 subtitle="Every data access, moderation decision and alert dispatch, with who did it and when.">
        <DemoBadge dark />
      </PageTitle>
      <div className="page-body">
        <div className="page-narrow stack">
          {error && <p className="notice">{error}</p>}
          {data && (
            <>
              <div className="row">
                <span className="muted tiny">
                  Showing {data.entries.length} of {data.total.toLocaleString()} entries, newest first.
                </span>
              </div>
              <div className="card">
                <table className="grid">
                  <thead>
                    <tr><th>When</th><th>User</th><th>Role</th><th>Action</th><th>Resource</th><th>Path</th><th>Detail</th></tr>
                  </thead>
                  <tbody>
                    {data.entries.map((e: any) => (
                      <tr key={e.id}>
                        <td className="nowrap tiny">{fmtTime(e.ts)}</td>
                        <td className="nowrap">{e.username}</td>
                        <td className="nowrap tiny muted">{e.role}</td>
                        <td className="nowrap"><span className="pill">{e.action}</span></td>
                        <td className="nowrap">{e.resource}{e.resource_id ? ` #${e.resource_id}` : ''}</td>
                        <td className="mono tiny">{e.method} {e.path}</td>
                        <td className="mono tiny">{Object.keys(e.detail ?? {}).length ? JSON.stringify(e.detail) : '—'}</td>
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
