/** "Is it safe near me?" — one breathing traffic-light circle, a pictogram, a spoken line. */
import { useEffect, useState } from 'react'
import { api, type PublicRisk, type Severity, type Shelter } from '../api/client'
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

  const goLine = risk?.shelter ? shelterLine(risk.shelter, t) : ''
  // Say it out loud as soon as we know — the point of this screen — and where to go.
  useEffect(() => { if (state === 'ok' && line) speak(`${word}. ${line} ${goLine}`, lang) }, [state, line, word, lang, goLine])

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
            {risk.shelter && <ShelterCard s={risk.shelter} line={goLine} />}
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

/** "Go to Government School Tindharia, 800 metres north-east." in the chosen language. */
function shelterLine(s: Shelter, t: (k: string) => string): string {
  const dist = s.distance_m < 1000 ? `${s.distance_m} ${t('unit_m')}` : `${(s.distance_m / 1000).toFixed(1)} ${t('unit_km')}`
  return t('shelter_go').replace('{name}', s.name).replace('{dist}', dist).replace('{dir}', t(`dir_${s.direction.replace('-', '_')}`))
}

/** Where to go: name, distance, an arrow pointing that way on a compass, and
 *  the phone's own maps app for the route. */
function ShelterCard({ s, line }: { s: Shelter; line: string }) {
  const [lang, , t] = useLang()
  const ios = /iPhone|iPad/.test(navigator.userAgent)
  const href = ios ? `https://maps.apple.com/?daddr=${s.lat},${s.lon}&q=${encodeURIComponent(s.name)}`
    : `geo:${s.lat},${s.lon}?q=${s.lat},${s.lon}(${encodeURIComponent(s.name)})`
  return (
    <div className="shelter-card" role="status">
      <div className="shelter-compass" aria-hidden="true">
        <span className="shelter-n">N</span>
        <svg viewBox="0 0 48 48" width="56" height="56" style={{ transform: `rotate(${s.bearing_deg}deg)` }}>
          <path d="M24 5 L35 34 L24 28 L13 34 Z" fill="currentColor" />
        </svg>
      </div>
      <div className="shelter-text">
        <span className="shelter-title">{t('shelter_title')}</span>
        <strong>{s.name}</strong>
        <span>{line}</span>
      </div>
      <div className="shelter-actions">
        <Speak text={line} lang={lang} dark />
        <a className="cz-linkbtn" href={href}>{t('shelter_open_maps')}</a>
      </div>
      <p className="shelter-src">{t('shelter_source')}</p>
    </div>
  )
}
