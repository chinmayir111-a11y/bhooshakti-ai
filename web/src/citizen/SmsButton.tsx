/**
 * SMS for people who cannot read or type: one tap writes the whole message.
 *
 * On tap: find where the person is (the pincode if we know it; otherwise the
 * phone's GPS, which works with no internet), say out loud "Your message is
 * ready. On the next screen, press the send button.", show the same in big
 * type, then open the SMS app with the message filled in. They only press
 * Send. The server reads "LS 26.95300,88.32100 …" as well as "LS 734223 …".
 */
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { IconMail } from '../components/Pictograms'
import { speak, useLang, type Lang } from '../i18n'

export type SmsIntent = 'report' | 'safe' | 'join'
const KEYWORD: Record<SmsIntent, string> = { report: 'LS', safe: 'SAFE', join: 'JOIN' }

export function useSmsNumber() {
  const [sms, setSms] = useState<{ number: string; configured: boolean } | null>(null)
  useEffect(() => { api.smsNumber().then(setSms).catch(() => {}) }, [])
  return sms
}

/** GPS without the network: a cached fix is fine, give up after 10 s. */
function gps(): Promise<string | null> {
  return new Promise((res) => {
    if (!navigator.geolocation) return res(null)
    navigator.geolocation.getCurrentPosition(
      (p) => res(`${p.coords.latitude.toFixed(5)},${p.coords.longitude.toFixed(5)}`),
      () => res(null), { enableHighAccuracy: true, timeout: 10000, maximumAge: 10 * 60000 })
  })
}

export function smsHref(number: string, body: string): string {
  return `sms:${number}${/iPhone|iPad/.test(navigator.userAgent) ? '&' : '?'}body=${encodeURIComponent(body)}`
}

/** Speak, and call `then` when the voice has finished (or at once with no voice). */
function speakThen(text: string, lang: Lang, then: () => void) {
  const r = speak(text, lang)
  if (r === 'none') { window.setTimeout(then, 1800); return }       // no voice: let them read the card
  const t0 = Date.now()
  const wait = () => {
    const done = !window.speechSynthesis.speaking && Date.now() - t0 > 400
    if (done || Date.now() - t0 > 7000) then(); else window.setTimeout(wait, 150)
  }
  window.setTimeout(wait, 300)
}

export default function SmsButton({ intent, label, where, extra = '', className = 'bigbtn', icon }: {
  intent: SmsIntent
  label: string
  /** Pincode or "lat,lon" if the page already knows it; otherwise GPS is asked. */
  where?: string | null
  /** Words after the location: what they saw, or the language for JOIN. */
  extra?: string
  className?: string
  icon?: React.ReactNode
}) {
  const [lang, , t] = useLang()
  const sms = useSmsNumber()
  const [stage, setStage] = useState<null | 'locating' | 'ready'>(null)

  async function go() {
    setStage('locating')
    const loc = where || (await gps()) || ''
    const tail = intent === 'join' ? `${extra} ${lang.toUpperCase()}` : extra
    const body = `${KEYWORD[intent]} ${loc} ${tail}`.replace(/\s+/g, ' ').trim()
    setStage('ready')
    speakThen(t('sms_ready_say'), lang, () => {
      setStage(null)
      const href = smsHref(sms?.number ?? '', body)
      if (import.meta.env.DEV) (window as any).__lastSms = href      // for the browser test scripts
      window.location.href = href
    })
  }

  return (
    <>
      <button type="button" className={className} onClick={go} disabled={stage !== null}>
        <span className="ico">{icon ?? <IconMail size={40} />}</span>
        <span className="txt">{label}</span>
      </button>
      {stage && (
        <div className="cz sms-ready" role="alert" onClick={() => setStage(null)}>
          {stage === 'locating' ? <p className="sms-ready-text">{t('sms_finding_location')}</p> : (
            <>
              <svg className="sms-ready-send" viewBox="0 0 64 64" aria-hidden="true">
                <circle cx="32" cy="32" r="30" fill="#2F6B3A" />
                <path d="M18 32 L46 20 L38 46 L32 35 Z" fill="#fff" />
              </svg>
              <p className="sms-ready-text">{t('sms_ready_show')}</p>
            </>
          )}
          {sms && !sms.configured && <p className="sms-ready-note">{t('sms_no_number')}</p>}
        </div>
      )}
    </>
  )
}

