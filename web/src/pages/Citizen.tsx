/**
 * Public hazard reporting. Mobile-first, no login.
 * UI strings come from src/i18n/strings.json — English / Hindi / Assamese.
 */
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { DemoBadge } from '../components/common'
import strings from '../i18n/strings.json'

type Lang = 'en' | 'hi' | 'as'
const LANGS: Lang[] = ['en', 'hi', 'as']
const ISSUES = ['crack', 'slope_movement', 'road_blockage', 'water_seepage'] as const

export default function Citizen() {
  const [lang, setLang] = useState<Lang>('en')
  const t = (strings as Record<Lang, Record<string, string>>)[lang]

  const [issue, setIssue] = useState<typeof ISSUES[number]>('crack')
  const [description, setDescription] = useState('')
  const [phone, setPhone] = useState('')
  const [lat, setLat] = useState<string>('')
  const [lon, setLon] = useState<string>('')
  const [photo, setPhoto] = useState<string | null>(null)
  const [photoName, setPhotoName] = useState('')
  const [locating, setLocating] = useState(false)
  const [geo, setGeo] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState<any>(null)

  // Tell the reporter, before they submit, whether their point falls inside a
  // monitored zone — that check is a PostGIS ST_Contains on the server.
  useEffect(() => {
    const la = Number(lat), lo = Number(lon)
    if (!lat || !lon || Number.isNaN(la) || Number.isNaN(lo)) { setGeo(null); return }
    const id = window.setTimeout(() => { api.geoCheck(la, lo).then(setGeo).catch(() => setGeo(null)) }, 400)
    return () => clearTimeout(id)
  }, [lat, lon])

  function locate() {
    if (!navigator.geolocation) { setError('This browser cannot report a location.'); return }
    setLocating(true); setError('')
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLat(pos.coords.latitude.toFixed(5))
        setLon(pos.coords.longitude.toFixed(5))
        setLocating(false)
      },
      () => {
        setLocating(false)
        setError('Location permission denied — enter coordinates below instead.')
      },
      { enableHighAccuracy: true, timeout: 10000 },
    )
  }

  function readPhoto(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setPhotoName(file.name)
    const reader = new FileReader()
    reader.onload = () => setPhoto(String(reader.result))
    reader.readAsDataURL(file)
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    const la = Number(lat), lo = Number(lon)
    if (!lat || !lon || Number.isNaN(la) || Number.isNaN(lo)) { setError(t.need_location); return }
    setBusy(true); setError('')
    try {
      const r = await api.createReport({
        issue_type: issue, description, lat: la, lon: lo,
        phone, language: lang, photo_base64: photo,
      })
      setDone(r)
    } catch (err: any) {
      setError(err?.message ?? 'Submission failed')
    } finally { setBusy(false) }
  }

  function reset() {
    setDone(null); setDescription(''); setPhone(''); setPhoto(null); setPhotoName('')
  }

  return (
    <div style={{ minHeight: '100%', background: 'var(--panel)', padding: '0 0 40px' }}>
      <div style={{ background: 'var(--navy)', padding: '20px 18px' }}>
        <div style={{ maxWidth: 620, margin: '0 auto' }}>
          <div style={{ color: '#fff', fontSize: 17, fontWeight: 700, letterSpacing: '.12em' }}>BHOOSHAKTI AI</div>
          <div style={{ color: '#A8BCD1', fontSize: 12.5, marginTop: 4 }}>{t.subtitle}</div>
          <div className="row" style={{ marginTop: 12, justifyContent: 'space-between' }}>
            <DemoBadge />
            <div className="seg">
              {LANGS.map((l) => (
                <button key={l} className={lang === l ? 'on' : ''} onClick={() => setLang(l)}>
                  {(strings as any)[l].lang_name}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div style={{ maxWidth: 620, margin: '0 auto', padding: '18px' }}>
        <p className="notice" style={{ marginBottom: 16 }}>{t.demo_notice}</p>

        {done ? (
          <div className="card">
            <div className="card-body">
              <h2 style={{ fontSize: 18 }}>{t.thanks_title}</h2>
              <p style={{ marginTop: 8, lineHeight: 1.6 }}>{t.thanks_body}</p>
              <dl className="kv" style={{ marginTop: 16 }}>
                <dt>Reference</dt><dd className="mono">#{done.id}</dd>
                <dt>Status</dt><dd>{done.status}</dd>
                <dt>Location check</dt>
                <dd>{done.geo_valid ? t.inside_zone : t.outside_zone}</dd>
                {done.zone_name && (<><dt>Zone</dt><dd>{done.zone_name}</dd></>)}
              </dl>
              <button className="btn block" style={{ marginTop: 18 }} onClick={reset}>{t.another}</button>
            </div>
          </div>
        ) : (
          <form className="card" onSubmit={submit}>
            <div className="card-body">
              <h2 style={{ fontSize: 18, marginBottom: 14 }}>{t.title}</h2>

              <div className="field">
                <label className="label">{t.issue_label}</label>
                <div style={{ display: 'grid', gap: 8 }}>
                  {ISSUES.map((key) => (
                    <label key={key} className="toggle-row" style={{ border: '1px solid var(--line)', padding: '10px 12px', margin: 0 }}>
                      <input type="radio" name="issue" checked={issue === key} onChange={() => setIssue(key)} />
                      {t[key]}
                    </label>
                  ))}
                </div>
              </div>

              <div className="field">
                <label className="label" htmlFor="d">{t.description_label}</label>
                <textarea id="d" value={description} placeholder={t.description_hint}
                          onChange={(e) => setDescription(e.target.value)} />
              </div>

              <div className="field">
                <label className="label" htmlFor="ph">{t.photo_label}</label>
                <input id="ph" type="file" accept="image/*" capture="environment" onChange={readPhoto}
                       style={{ border: 0, padding: 0 }} />
                {photoName && <div className="tiny muted" style={{ marginTop: 5 }}>{photoName}</div>}
              </div>

              <div className="field">
                <label className="label">{t.location_label}</label>
                <button type="button" className="btn ghost block" onClick={locate} disabled={locating}>
                  {locating ? t.locating : t.locate}
                </button>
                <div className="row" style={{ marginTop: 10, gap: 8 }}>
                  <div style={{ flex: 1 }}>
                    <label className="label tiny" htmlFor="la">{t.lat}</label>
                    <input id="la" type="text" inputMode="decimal" value={lat} onChange={(e) => setLat(e.target.value)} />
                  </div>
                  <div style={{ flex: 1 }}>
                    <label className="label tiny" htmlFor="lo">{t.lon}</label>
                    <input id="lo" type="text" inputMode="decimal" value={lon} onChange={(e) => setLon(e.target.value)} />
                  </div>
                </div>
                {geo && (
                  <p className="notice tiny" style={{ marginTop: 10 }}>
                    {geo.geo_valid ? `✓ ${t.inside_zone} — ${geo.zone_name}` : `${t.outside_zone}`}
                  </p>
                )}
              </div>

              <div className="field">
                <label className="label" htmlFor="tel">{t.phone_label}</label>
                <input id="tel" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} />
                <div className="tiny muted" style={{ marginTop: 4 }}>{t.phone_hint}</div>
              </div>

              {error && <p className="notice" style={{ marginBottom: 12 }}>{error}</p>}

              <button className="btn block" type="submit" disabled={busy}>
                {busy ? t.submitting : t.submit}
              </button>
              <p className="tiny muted" style={{ marginTop: 12, textAlign: 'center' }}>{t.emergency}</p>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
