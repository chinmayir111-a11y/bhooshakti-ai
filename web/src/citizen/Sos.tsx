/**
 * The SOS button. Hold for two seconds (a progress bar fills; letting go early
 * cancels), then: the phone's position and the time go to the district officer
 * as a top-priority report (issue_type "sos"), a call to 112 is opened, and
 * with no network the report is queued and the SMS app opens with the location
 * already typed. Ends on a full-screen confirmation that is also spoken.
 */
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { IconAlert, PictoPhone } from '../components/Pictograms'
import { speak, useLang } from '../i18n'
import { citizenQueue } from '../offline/citizenQueue'
import { makeUuid } from '../offline/queue'
import { Speak } from './Shell'

const HOLD_MS = 2000

type Done = { queued: boolean; noLocation?: boolean; sms?: string }

export default function SosButton() {
  const [lang, , t] = useLang()
  const [progress, setProgress] = useState(0)        // 0..1 while holding
  const [sending, setSending] = useState(false)
  const [done, setDone] = useState<Done | null>(null)
  const timer = useRef(0)
  const t0 = useRef(0)
  const [smsNumber, setSmsNumber] = useState('')
  useEffect(() => { api.smsNumber().then((r) => setSmsNumber(r.number)).catch(() => {}) }, [])

  function start(e: React.PointerEvent) {
    if (sending || done) return
    e.preventDefault()
    ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
    t0.current = performance.now()
    const tick = () => {
      const k = Math.min(1, (performance.now() - t0.current) / HOLD_MS)
      setProgress(k)
      if (k >= 1) { timer.current = 0; send(); return }
      timer.current = requestAnimationFrame(tick)
    }
    timer.current = requestAnimationFrame(tick)
  }
  function cancel() {
    if (timer.current) cancelAnimationFrame(timer.current)
    timer.current = 0
    setProgress(0)
  }
  useEffect(() => () => { if (timer.current) cancelAnimationFrame(timer.current) }, [])

  function locate(): Promise<{ lat: number; lon: number } | null> {
    return new Promise((res) => {
      if (!navigator.geolocation) return res(null)
      navigator.geolocation.getCurrentPosition(
        (p) => res({ lat: p.coords.latitude, lon: p.coords.longitude }),
        () => res(null), { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 })
    })
  }

  async function send() {
    setSending(true)
    try { navigator.vibrate?.([80, 40, 80]) } catch { /* no haptics */ }
    const pos = await locate()
    const when = new Date()
    if (!pos) { setDone({ queued: false, noLocation: true }); setSending(false); return }
    const body = { client_uuid: makeUuid(), issue_type: 'sos', lat: pos.lat, lon: pos.lon,
                   description: `SOS at ${when.toISOString()}`, language: lang, phone: '', photo_base64: null, voice_base64: null }
    const sms = `sms:${smsNumber || ''}${/iPhone|iPad/.test(navigator.userAgent) ? '&' : '?'}body=${encodeURIComponent(`SOS ${pos.lat.toFixed(5)},${pos.lon.toFixed(5)} ${when.toLocaleTimeString()}`)}`
    let queued = false
    try {
      if (!navigator.onLine) throw new Error('offline')
      await api.createReport({ ...body, channel: 'pwa' })
    } catch {
      await citizenQueue.enqueue(body)
      queued = true
    }
    setDone({ queued, sms: queued ? sms : undefined })
    setSending(false)
    // Open the call (or, offline, the SMS with the location) once the screen has changed.
    window.setTimeout(() => { window.location.href = queued ? sms : 'tel:112' }, 900)
  }

  if (done) {
    const head = done.noLocation ? t('sos_no_location') : t('sos_sent')
    const body = done.noLocation ? '' : done.queued ? t('sos_queued_body') : t('sos_sent_body')
    return <SosDone head={head} body={body} lang={lang} t={t} sms={done.sms} />
  }

  const label = sending ? t('sos_sending') : progress > 0 ? t('sos_holding') : t('sos_hold')
  // A div, not a <button>: the speaker inside is itself a button. Keyboard:
  // hold Space/Enter for two seconds, release early to cancel.
  return (
    <div role="button" tabIndex={0} className={`czbtn sos${progress > 0 ? ' holding' : ''}${sending ? ' busy' : ''}`}
         aria-label={`SOS. ${t('help')}. ${t('sos_hold')}`} aria-disabled={sending}
         onPointerDown={start} onPointerUp={cancel} onPointerLeave={cancel} onPointerCancel={cancel} onContextMenu={(e) => e.preventDefault()}
         onKeyDown={(e) => { if ((e.key === ' ' || e.key === 'Enter') && !timer.current && !sending) { e.preventDefault(); t0.current = performance.now(); timer.current = requestAnimationFrame(function tick() { const k = Math.min(1, (performance.now() - t0.current) / HOLD_MS); setProgress(k); if (k >= 1) { timer.current = 0; send(); return } timer.current = requestAnimationFrame(tick) }) } }}
         onKeyUp={cancel}>
      <span className="sos-badge">SOS</span>
      <span className="txt">{t('help')}<span className="sub">{label}</span></span>
      <span className="sos-bar" aria-hidden="true"><span style={{ width: `${Math.round(progress * 100)}%` }} /></span>
      <span onPointerDown={(e) => e.stopPropagation()}><Speak text={`${t('help')}. ${t('sos_hold')}`} lang={lang} size={36} /></span>
    </div>
  )
}

function SosDone({ head, body, lang, t, sms }: { head: string; body: string; lang: any; t: (k: string) => string; sms?: string }) {
  useEffect(() => { speak(`${head}. ${body}`, lang) }, [head, body, lang])
  return (
    <div className="cz cz-done sos" role="alert">
      <IconAlert size={64} />
      <h1>{head}</h1>
      {body && <p>{body}</p>}
      <div className="actions">
        <a className="cz-linkbtn" href="tel:112"><PictoPhone size={22} /> {t('call_112')}</a>
        {sms && <a className="cz-linkbtn" href={sms}>SMS</a>}
        <a className="cz-linkbtn" href="/">{t('done_home')}</a>
      </div>
    </div>
  )
}
