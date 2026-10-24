/** Frame for every citizen screen: hills header, language pills, back link,
 *  offline banner, demo notice. Big text, one action per screen. */
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { HillsHeader, PictoSpeaker } from '../components/Pictograms'
import { LANGS, canSpeak, langName, needsReview, speak, useLang, type Lang } from '../i18n'
import { useOnline } from '../hooks'
import '../styles/citizen.css'

export function Speak({ text, lang, dark = false, label }: { text: string; lang: Lang; dark?: boolean; label?: string }) {
  if (!canSpeak()) return null
  return (
    <button type="button" className={`speakbtn${dark ? ' dark' : ''}`} aria-label={label ?? text}
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); speak(text, lang) }}>
      <PictoSpeaker size={26} />
    </button>
  )
}

export default function Shell({ title, back = false, children }: { title?: string; back?: boolean; children: ReactNode }) {
  const [lang, setLang, t] = useLang()
  const online = useOnline()
  return (
    <div className="cz">
      <header className="cz-head">
        <HillsHeader className="cz-hills" />
        <div className="cz-head-inner">
          <div>
            {back ? (
              <Link to="/" className="cz-back">‹ {t('home')}</Link>
            ) : (
              <>
                <div className="cz-brand">{t('app_name')}</div>
                <div className="cz-tag">{t('tagline')}</div>
              </>
            )}
            {title && <div style={{ fontSize: 22, fontWeight: 800, marginTop: 4 }}>{title}</div>}
          </div>
          <div className="cz-langs" role="group" aria-label="Language">
            {LANGS.map((l) => (
              <button key={l} className={lang === l ? 'on' : ''} onClick={() => setLang(l)} lang={l}>{langName(l)}</button>
            ))}
          </div>
        </div>
      </header>
      <main className="cz-body">
        {!online && <div className="cz-offline" role="status">⚠ {t('offline_banner')}</div>}
        {children}
        {needsReview(lang) && <p className="cz-review">{t('review_note')}</p>}
        <p className="cz-notice">{t('demo_notice')}</p>
      </main>
    </div>
  )
}
