/**
 * Gaon Prahari: a trained village volunteer reads the manual rain gauge and
 * sends the millimetres. One screen: a big number pad and Send. The phone is
 * remembered after the first time. With no network the reading is queued
 * (offline/gaugeQueue) and sent on reconnect; with no data at all, `R 45` by
 * SMS does the same. The reply — saved / WATCH / ALERT — is shown in colour and
 * said out loud.
 */
import { useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../api/client'
import { IconCheck } from '../components/Pictograms'
import { useOnline } from '../hooks'
import { speak, useLang } from '../i18n'
import { gaugeQueue } from '../offline/gaugeQueue'
import { makeUuid } from '../offline/queue'
import Shell, { Speak } from './Shell'

const PHONE_KEY = 'bhooshakti.volunteer.phone'
type Result = { level: 'none' | 'watch' | 'alert' | 'queued' | 'unregistered'; reply?: string }

function storedPhone(): string {
  try { return localStorage.getItem(PHONE_KEY) ?? '' } catch { return '' }
}

export default function CitizenGauge() {
  const [lang, , t] = useLang()
  const online = useOnline()
  const [phone, setPhone] = useState(storedPhone)
  const [editingPhone, setEditingPhone] = useState(!storedPhone())
  const [mm, setMm] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<Result | null>(null)
  const uuid = useRef(makeUuid())

  function savePhone(e: React.FormEvent) {
    e.preventDefault()
    if (phone.replace(/\D/g, '').length < 10) return
    try { localStorage.setItem(PHONE_KEY, phone.trim()) } catch { /* private mode: keep for this visit */ }
    setEditingPhone(false)
  }

  function press(k: string) {
    setResult(null)
    setMm((v) => {
      if (k === 'del') return v.slice(0, -1)
      if (k === '.' && (v.includes('.') || !v)) return v
      const next = v + k
      return /^\d{0,3}(\.\d?)?$/.test(next) ? next : v
    })
  }

  async function send() {
    const value = Number(mm)
    if (!mm || !Number.isFinite(value)) return
    setBusy(true)
    const body = { client_uuid: uuid.current, phone: phone.trim(), mm: value, read_at: new Date().toISOString() }
    try {
      if (!online) throw new Error('offline')
      const r = await api.volunteerReading(body)
      setResult({ level: r.level ?? 'none', reply: r.reply })
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setResult({ level: 'unregistered' })
      else { await gaugeQueue.enqueue(body); setResult({ level: 'queued' }) }
    } finally {
      setBusy(false); setMm(''); uuid.current = makeUuid()
    }
  }

  const message = result ? t({ none: 'gauge_none', watch: 'gauge_watch', alert: 'gauge_alert', queued: 'gauge_queued', unregistered: 'gauge_not_registered' }[result.level]) : ''
  useEffect(() => { if (message) speak(message, lang) }, [message, lang])

  return (
    <Shell back title={t('gauge_title')}>
      <div className="step">
        <h2>{t('gauge_title')}<Speak text={`${t('gauge_title')}. ${t('gauge_intro')}`} lang={lang} dark /></h2>
        <p>{t('gauge_intro')}</p>
        {editingPhone ? (
          <form onSubmit={savePhone} style={{ marginTop: 10 }}>
            <label style={{ display: 'block', fontSize: 15, color: 'var(--text-muted)', marginBottom: 6 }} htmlFor="gphone">{t('gauge_phone')}</label>
            <input id="gphone" className="cz-input" type="tel" inputMode="tel" autoComplete="tel" value={phone}
                   onChange={(e) => setPhone(e.target.value)} placeholder="+91 98xxxxxxxx" />
            <button className="cz-linkbtn" style={{ marginTop: 10 }} type="submit" disabled={phone.replace(/\D/g, '').length < 10}>{t('gauge_continue')}</button>
          </form>
        ) : (
          <p className="tiny" style={{ margin: '6px 0 0', color: 'var(--text-muted)' }}>
            {phone} · <button className="linklike" onClick={() => setEditingPhone(true)}>{t('gauge_change_phone')}</button>
          </p>
        )}
      </div>

      {!editingPhone && (
        <div className="step">
          <div className="gauge-readout" aria-live="polite">
            <span className="gauge-num">{mm || '0'}</span><span className="gauge-unit">mm</span>
          </div>
          <p style={{ textAlign: 'center', margin: '4px 0 12px' }}>{t('gauge_mm')}</p>
          <div className="numpad">
            {['1', '2', '3', '4', '5', '6', '7', '8', '9', '.', '0', 'del'].map((k) => (
              <button key={k} type="button" onClick={() => press(k)} aria-label={k === 'del' ? 'Delete' : k}>
                {k === 'del' ? '⌫' : k}
              </button>
            ))}
          </div>
          <button className="cz-sendbtn" style={{ marginTop: 14 }} onClick={send} disabled={busy || !mm}>
            {busy ? t('report_sending') : t('gauge_send')}
          </button>
        </div>
      )}

      {result && (
        <div className={`gauge-result lv-${result.level}`} role="status">
          {result.level === 'none' && <IconCheck size={28} />}
          <p className="gauge-result-text">{message}</p>
          <Speak text={message} lang={lang} dark />
          {result.reply && <p className="tiny" style={{ margin: '8px 0 0', opacity: .85 }}>{result.reply}</p>}
        </div>
      )}

      <p className="cz-notice" style={{ marginTop: 12 }}>{t('gauge_sms_hint')}</p>
      <p className="cz-notice">{t('emergency_line')}</p>
    </Shell>
  )
}
