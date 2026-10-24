/**
 * Report a landslide with no typing: photo → location (automatic) → optional
 * hold-to-record voice note → send. Offline, the report is queued in
 * IndexedDB and sent on reconnect; an SMS fallback opens the phone's own
 * messaging app with `LS <pincode> <note>` already filled in.
 */
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { ISSUE_PICTOS, PictoCamera, PictoMic, PictoPin } from '../components/Pictograms'
import { useOnline } from '../hooks'
import { useLang } from '../i18n'
import { citizenQueue } from '../offline/citizenQueue'
import { makeUuid } from '../offline/queue'
import Shell, { Speak } from './Shell'

type Pos = { lat: number; lon: number; accuracy: number }
const ISSUES = ['landslide', 'road_blockage', 'crack', 'tilted_trees', 'muddy_water'] as const

function readAsDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(String(r.result)); r.onerror = reject
    r.readAsDataURL(blob)
  })
}

/** Downscale a phone photo so a 3G upload is seconds, not minutes. */
async function shrink(file: File, max = 1280, quality = 0.8): Promise<string> {
  const url = URL.createObjectURL(file)
  try {
    const img = await new Promise<HTMLImageElement>((res, rej) => {
      const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url
    })
    const scale = Math.min(1, max / Math.max(img.width, img.height))
    const c = document.createElement('canvas')
    c.width = Math.round(img.width * scale); c.height = Math.round(img.height * scale)
    c.getContext('2d')!.drawImage(img, 0, 0, c.width, c.height)
    return c.toDataURL('image/jpeg', quality)
  } catch {
    return readAsDataUrl(file)
  } finally { URL.revokeObjectURL(url) }
}

export default function CitizenReport() {
  const [lang, , t] = useLang()
  const online = useOnline()
  const [photo, setPhoto] = useState<string | null>(null)
  const [pos, setPos] = useState<Pos | null>(null)
  const [locState, setLocState] = useState<'idle' | 'finding' | 'ok' | 'failed'>('idle')
  const [geo, setGeo] = useState<any>(null)
  const [issue, setIssue] = useState<typeof ISSUES[number]>('landslide')
  const [voice, setVoice] = useState<string | null>(null)
  const [recording, setRecording] = useState(false)
  const [note, setNote] = useState('')
  const [phone, setPhone] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<{ queued: boolean; id?: number; zone?: string | null } | null>(null)
  const [error, setError] = useState('')
  const recorder = useRef<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const uuid = useRef(makeUuid())

  // Location is captured automatically — the reporter never types a coordinate.
  function locate() {
    if (!navigator.geolocation) { setLocState('failed'); return }
    setLocState('finding')
    navigator.geolocation.getCurrentPosition(
      (p) => { setPos({ lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy }); setLocState('ok') },
      () => setLocState('failed'),
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 },
    )
  }
  useEffect(locate, [])
  useEffect(() => {
    if (!pos || !online) return
    api.geoCheck(pos.lat, pos.lon).then(setGeo).catch(() => setGeo(null))
  }, [pos, online])

  async function onPhoto(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (f) setPhoto(await shrink(f))
  }

  async function startRec() {
    if (recording) return
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mr = new MediaRecorder(stream)
      chunks.current = []
      mr.ondataavailable = (ev) => { if (ev.data.size) chunks.current.push(ev.data) }
      mr.onstop = async () => {
        stream.getTracks().forEach((tr) => tr.stop())
        const blob = new Blob(chunks.current, { type: mr.mimeType || 'audio/webm' })
        if (blob.size) setVoice(await readAsDataUrl(blob))
        setRecording(false)
      }
      recorder.current = mr
      mr.start()
      setRecording(true)
      window.setTimeout(() => { if (mr.state === 'recording') mr.stop() }, 20000)   // 20 s cap
    } catch { setError('Microphone not available') }
  }
  function stopRec() { if (recorder.current?.state === 'recording') recorder.current.stop() }

  // `LS <pincode> <what you see>` — the keyword format the SMS gateway parses.
  // The nearest pincode comes from the geo-check; with no network the person
  // types it themselves (the help screen shows the format).
  const smsBody = encodeURIComponent(`LS ${geo?.nearest_pincode ?? ''} ${t(`issue_${issue}`)} ${note}`.replace(/\s+/g, ' ').trim())
  const [smsNumber, setSmsNumber] = useState('')
  useEffect(() => { api.smsNumber().then((r) => setSmsNumber(r.number)).catch(() => {}) }, [])

  async function send() {
    if (!pos) { setError(t('report_location_failed')); return }
    setBusy(true); setError('')
    const body = {
      client_uuid: uuid.current, issue_type: issue, lat: pos.lat, lon: pos.lon,
      description: note, phone, language: lang, photo_base64: photo, voice_base64: voice,
    }
    try {
      if (!online) throw new Error('offline')
      const r = await api.createReport({ ...body, channel: 'pwa' })
      setDone({ queued: false, id: r.id, zone: r.zone_name })
    } catch {
      await citizenQueue.enqueue(body)
      setDone({ queued: true })
    } finally { setBusy(false) }
  }

  if (done) {
    const head = done.queued ? t('report_queued') : t('report_sent')
    const body = done.queued ? t('report_queued_body') : t('report_sent_body')
    return (
      <Shell back>
        <div className="step" style={{ textAlign: 'center' }}>
          <svg className="tick" viewBox="0 0 100 100"><circle cx="50" cy="50" r="45" /><path d="M30 52l13 13 27-30" /></svg>
          <h2 style={{ justifyContent: 'center' }}>{head}<Speak text={`${head}. ${body}`} lang={lang} dark /></h2>
          <p>{body}</p>
          {done.id && <p className="light-meta">{t('report_ref')} #{done.id}{done.zone ? ` · ${done.zone}` : ''}</p>}
          <button className="cz-linkbtn" style={{ marginTop: 8 }} onClick={() => window.location.reload()}>{t('report_another')}</button>
        </div>
      </Shell>
    )
  }

  const Picto = ISSUE_PICTOS[issue as keyof typeof ISSUE_PICTOS] ?? ISSUE_PICTOS.landslide

  return (
    <Shell back title={t('report')}>
      {/* 1 photo */}
      <div className={`step${photo ? ' done' : ''}`}>
        <h2><span className="n">1</span>{t('report_take_photo')}<Speak text={`${t('report_take_photo')}. ${t('report_photo_hint')}`} lang={lang} dark />{photo && <span className="okmark">✓</span>}</h2>
        <p>{t('report_photo_hint')}</p>
        {photo ? (
          <>
            <img className="photo-preview" src={photo} alt="" />
            <label className="cz-linkbtn" style={{ marginTop: 10 }}>
              {t('report_retake')}<input type="file" accept="image/*" capture="environment" onChange={onPhoto} hidden />
            </label>
          </>
        ) : (
          <label className="photo-btn">
            <PictoCamera size={64} />{t('report_take_photo')}
            <input type="file" accept="image/*" capture="environment" onChange={onPhoto} hidden />
          </label>
        )}
      </div>

      {/* 2 location — automatic */}
      <div className={`step${locState === 'ok' ? ' done' : ''}`}>
        <h2><span className="n">2</span>{locState === 'ok' ? t('report_located') : t('report_locating')}
          <Speak text={locState === 'ok' ? t('report_located') : t('report_locating')} lang={lang} dark />
          {locState === 'ok' && <span className="okmark">✓</span>}
        </h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <PictoPin size={44} style={{ color: locState === 'ok' ? 'var(--sev-low-ink)' : 'var(--text-faint)' }} />
          <div style={{ fontSize: 15, color: 'var(--text-muted)' }}>
            {locState === 'finding' && <span className="skeleton" style={{ display: 'inline-block', width: 160, height: 16 }} />}
            {locState === 'ok' && pos && <>{geo?.zone_name ?? `${pos.lat.toFixed(4)}, ${pos.lon.toFixed(4)}`}<br /><span style={{ fontSize: 13 }}>± {Math.round(pos.accuracy)} m</span></>}
            {locState === 'failed' && <>{t('report_location_failed')}<br /><button className="cz-linkbtn" style={{ marginTop: 8, minHeight: 44 }} onClick={locate}>{t('report_retry_location')}</button></>}
          </div>
        </div>
      </div>

      {/* 3 what do you see — pictograms, optional */}
      <div className="step">
        <h2><span className="n">3</span>{t('report_what')}<Speak text={t('report_what')} lang={lang} dark /></h2>
        <div className="picto-grid" role="radiogroup">
          {ISSUES.map((k) => {
            const P = ISSUE_PICTOS[k as keyof typeof ISSUE_PICTOS]
            return (
              <button key={k} type="button" role="radio" aria-checked={issue === k} className={issue === k ? 'on' : ''}
                      onClick={() => setIssue(k)}>
                <P size={44} />{t(`issue_${k}`)}
              </button>
            )
          })}
          <button type="button" className={`holdbtn${recording ? ' rec' : ''}`} style={{ minHeight: 104, borderRadius: 'var(--radius-sm)', flexDirection: 'column', gap: 6, fontSize: 13 }}
                  onPointerDown={startRec} onPointerUp={stopRec} onPointerLeave={stopRec} onPointerCancel={stopRec}
                  aria-label={t('report_hold_record')}>
            <PictoMic size={40} />
            {recording ? t('report_recording') : voice ? `✓ ${t('report_recorded')}` : t('report_hold_record')}
          </button>
        </div>
        <details style={{ marginTop: 12 }}>
          <summary style={{ cursor: 'pointer', color: 'var(--text-muted)', fontSize: 15 }}>{t('report_describe_optional')}</summary>
          <input className="cz-input" style={{ marginTop: 8 }} value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('report_describe_optional')} />
          <input className="cz-input" style={{ marginTop: 8 }} type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder={t('report_phone_optional')} />
        </details>
      </div>

      {error && <p className="cz-offline" role="alert">{error}</p>}

      <button className="cz-sendbtn" onClick={send} disabled={busy || locState === 'finding'}>
        {busy ? t('report_sending') : <><Picto size={28} style={{ verticalAlign: 'middle', marginRight: 8 }} />{t('report_send')}</>}
      </button>

      <a className="cz-linkbtn" style={{ marginTop: 12 }}
         href={`sms:${smsNumber || ''}${/iPhone|iPad/.test(navigator.userAgent) ? '&' : '?'}body=${smsBody}`}>
        ✉ {t('report_send_sms')}
      </a>
      <p className="cz-notice" style={{ marginTop: 6 }}>{t('report_sms_hint')}</p>
      <p className="cz-notice">{t('emergency_line')}</p>
    </Shell>
  )
}
