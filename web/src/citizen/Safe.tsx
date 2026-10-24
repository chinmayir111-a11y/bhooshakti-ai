/** "Is it safe near me?" — one breathing traffic-light circle, a pictogram, a spoken line. */
import { useEffect, useState } from 'react'
import { api, type PublicRisk, type Severity } from '../api/client'
import { IconAlert, IconArrow, IconRefresh, PictoEvacuate, PictoLandslide, PictoShield } from '../components/Pictograms'
import { SeverityShape } from '../components/Severity'
import { useOnline } from '../hooks'
import { speak, useLang } from '../i18n'
import { rememberRisk } from './rain'
import Shell, { Speak } from './Shell'

export default function CitizenSafe() {
  const [lang, , t] = useLang()
  const online = useOnline()
  const [state, setState] = useState<'locating' | 'loading' | 'ok' | 'nolocation' | 'error'>('locating')
  const [risk, setRisk] = useState<PublicRisk | null>(null)
  const [pin, setPin] = useState('')

  function check() {
    setState('locating')
    if (!navigator.geolocation) { setState('nolocation'); return }
    navigator.geolocation.getCurrentPosition(
      (p) => load(() => api.publicRisk(p.coords.latitude, p.coords.longitude, lang)),
      () => setState('nolocation'),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 120000 },
    )
  }
  function load(fn: () => Promise<PublicRisk>) {
    setState('loading')
    fn().then((r) => { setRisk(r); rememberRisk(r); setState('ok') }).catch(() => setState('error'))
  }
  useEffect(check, [])       // eslint-disable-line react-hooks/exhaustive-deps

  const sev = (risk?.severity ?? null) as Severity | null
  const word = sev ? t(`sev_${sev}`) : '—'
  const line = !risk ? '' : risk.active_alert?.tier === 'WARNING' ? t('safe_warning')
    : risk.active_alert?.tier === 'ADVISORY' ? `${t('safe_advisory')} ${sev ? t(`line_${sev}`) : ''}`
    : sev ? t(`line_${sev}`) : t('safe_unknown')

  // Say it out loud as soon as we know — the point of this screen.
  useEffect(() => { if (state === 'ok' && line) speak(`${word}. ${line}`, lang) }, [state, line, word, lang])

  const Picto = sev === 'CRITICAL' || risk?.active_alert?.tier === 'WARNING' ? PictoEvacuate
    : sev === 'HIGH' ? PictoLandslide : PictoShield

  return (
    <Shell back title={t('safe_title')}>
      <div className="step" style={{ textAlign: 'center' }}>
        {(state === 'locating' || state === 'loading') && (
          <>
            <div className="light NONE skeleton" aria-hidden="true" />
            <p className="light-word" style={{ color: 'var(--text-muted)' }}>{t('safe_checking')}</p>
          </>
        )}
        {state === 'ok' && risk && (
          <>
            <div className={`light ${sev ?? 'NONE'}`} role="img" aria-label={word}>
              <div>
                <Picto size={88} />
                {sev && <div style={{ marginTop: -6 }}><SeverityShape value={sev} size={34} stroke="rgba(255,255,255,.7)" /></div>}
              </div>
            </div>
            <p className="light-word">{word}</p>
            <p className="light-line">{line}</p>
            <div style={{ display: 'flex', justifyContent: 'center', marginTop: 12 }}>
              <Speak text={`${word}. ${line}`} lang={lang} dark label={t('tap_to_hear')} />
            </div>
            <p className="light-meta">
              {risk.place}{risk.zone_name && risk.zone_name !== risk.place ? ` · ${risk.zone_name}` : ''}
              {!risk.inside_zone && <><br />{t('safe_outside')}</>}
              {risk.computed_at && <><br />{t('safe_updated')} {new Date(risk.computed_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</>}
              {!online && <><br /><IconAlert size={14} /> {t('offline_banner')}</>}
            </p>
          </>
        )}
        {state === 'nolocation' && <p className="light-line">{t('safe_no_location')}</p>}
        {state === 'error' && <p className="light-line">{t('safe_unknown')}</p>}

        <button className="cz-linkbtn" style={{ marginTop: 14 }} onClick={check}><IconRefresh />{t('safe_check_again')}</button>

        <form style={{ marginTop: 14 }} onSubmit={(e) => { e.preventDefault(); if (/^\d{6}$/.test(pin)) load(() => api.pincodeRisk(pin, lang)) }}>
          <label style={{ display: 'block', fontSize: 15, color: 'var(--text-muted)', marginBottom: 6 }}>{t('safe_pincode')}</label>
          <div style={{ display: 'flex', gap: 8 }}>
            <input className="cz-input" inputMode="numeric" pattern="\d{6}" maxLength={6} value={pin}
                   onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))} placeholder="734101" />
            <button className="cz-linkbtn" style={{ width: 'auto', padding: '0 18px' }} type="submit" aria-label={t('safe_pincode')}><IconArrow size={22} /></button>
          </div>
        </form>
      </div>
    </Shell>
  )
}
