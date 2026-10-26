/** Frame for every citizen screen: the ridge scene (sky, fog, rain and
 *  lightning follow the risk where the person is), the risk as one big word,
 *  a language dropdown top-right, back link, offline banner, quiet footer.
 *
 *  Layout is by screen width only (CSS media queries in citizen.css):
 *  phones stack everything; on desktop the home page's actions sit on the
 *  hero beside the risk, in an 1100 px container. */
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { IconAlert, IconBack, IconPin, PictoSpeaker } from '../components/Pictograms'
import { LANGS, canSpeak, langName, needsReview, speak, useLang, type Lang } from '../i18n'
import { useOnline } from '../hooks'
import Scene, { Dot } from './Scene'
import { useZoneState } from './rain'
import '../styles/citizen.css'

const NO_VOICE: Record<Lang, string> = {
  en: 'No voice installed for this language on this device',
  hi: 'इस डिवाइस पर इस भाषा की आवाज़ उपलब्ध नहीं है',
  as: 'এই ডিভাইচত এই ভাষাৰ কণ্ঠ উপলব্ধ নহয় (No Assamese voice on this device)',
  bn: 'এই ডিভাইসে এই ভাষার কণ্ঠ নেই (No Bengali voice on this device)',
  ne: 'यो उपकरणमा यस भाषाको आवाज छैन (No Nepali voice on this device)',
}

export function Speak({ text, lang, dark = false, label, size = 48 }: { text: string; lang: Lang; dark?: boolean; label?: string; size?: number }) {
  const [state, setState] = useState<'idle' | 'speaking' | 'none'>('idle')
  if (!canSpeak()) return null
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, position: 'relative' }}>
      <button type="button" className={`speakbtn${dark ? ' dark' : ''}${state === 'speaking' ? ' speaking' : ''}`} aria-label={label ?? text}
              style={size !== 48 ? { width: size, height: size, minWidth: size } : undefined}
              onClick={(e) => {
                e.preventDefault(); e.stopPropagation()
                const r = speak(text, lang)
                setState(r === 'none' ? 'none' : 'speaking')
                window.setTimeout(() => setState('idle'), r === 'none' ? 3500 : 1500)
              }}>
        <PictoSpeaker size={Math.round(size / 2)} />
      </button>
      {state === 'none' && (
        <span role="status" style={{ position: 'absolute', top: '100%', right: 0, marginTop: 6, zIndex: 5, background: 'var(--text)', color: 'var(--bg)',
                                      fontSize: 12, lineHeight: 1.35, padding: '6px 10px', borderRadius: 8, width: 220, textAlign: 'left', boxShadow: 'var(--shadow-md)' }}>
          {NO_VOICE[lang]}
        </span>
      )}
    </span>
  )
}

export default function Shell({ title, back = false, home = false, children }: { title?: string; back?: boolean; home?: boolean; children: ReactNode }) {
  const [lang, setLang, t] = useLang()
  const online = useOnline()
  const zone = useZoneState()
  const raining = zone.rainMm > 0.1 || zone.state === 'danger'
  const weather = zone.state === 'danger' ? t('scene_storm') : zone.rainMm > 0.1 ? t('scene_rain').replace('{mm}', zone.rainMm.toFixed(0)) : zone.state === 'unknown' ? '' : t('scene_clear')
  const word = t(`scene_${zone.state}`)
  const sub = t(`scene_sub_${zone.state}`)

  return (
    <div className={`cz${home ? ' home' : ''}`}>
      <Scene state={zone.state} raining={raining} compact={back}>
        <div className="scene-top">
          <div className="cz-brandblock">
            {back ? (
              <Link to="/" className="cz-back"><IconBack size={20} />{t('home')}</Link>
            ) : (
              <>
                <div className="cz-brand">{t('app_name')}</div>
                <div className="cz-tagline">{t('tagline')}</div>
              </>
            )}
          </div>
          <select className="cz-lang" value={lang} onChange={(e) => setLang(e.target.value as Lang)} aria-label="Language">
            {LANGS.map((l) => <option key={l} value={l} lang={l}>{langName(l)}</option>)}
          </select>
        </div>
        <div className="scene-big">
          {back ? (
            <h1 className="cz-title">{title}</h1>
          ) : zone.state === 'unknown' ? (
            <Link to="/safe" className="cz-check"><IconPin size={20} />{t('check_area')}</Link>
          ) : (
            <Link to="/safe" className="cz-level" aria-label={`${word}. ${sub}`}>
              <div className="lvl"><Dot state={zone.state} /><span>{word}</span></div>
              <div className="sub">{sub}</div>
            </Link>
          )}
          {(zone.place || weather) && <div className="cz-loc">{[zone.place, weather].filter(Boolean).join(' · ')}</div>}
        </div>
      </Scene>
      <main className="cz-body">
        {!online && <div className="cz-offline" role="status"><IconAlert />{t('offline_banner')}</div>}
        {children}
        {needsReview(lang) && <p className="cz-review">{t('review_note')}</p>}
      </main>
      <footer className="cz-foot">
        <Link to="/about">{t('about')}</Link>
        <span aria-hidden="true"> · </span>
        <Link to="/help#sms">SMS</Link>
      </footer>
    </div>
  )
}
