/** Frame for every citizen screen: hills header, language pills, back link,
 *  offline banner, demo notice. Big text, one action per screen. */
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { HillsHeader, PictoSpeaker } from '../components/Pictograms'
import { LANGS, canSpeak, langName, needsReview, speak, useLang, type Lang } from '../i18n'
import { useOnline } from '../hooks'
import '../styles/citizen.css'

const NO_VOICE: Record<Lang, string> = {
  en: 'No voice installed for this language on this device',
  hi: 'इस डिवाइस पर इस भाषा की आवाज़ उपलब्ध नहीं है',
  as: 'এই ডিভাইচত এই ভাষাৰ কণ্ঠ উপলব্ধ নহয় (No Assamese voice on this device)',
  bn: 'এই ডিভাইসে এই ভাষার কণ্ঠ নেই (No Bengali voice on this device)',
  ne: 'यो उपकरणमा यस भाषाको आवाज छैन (No Nepali voice on this device)',
}

export function Speak({ text, lang, dark = false, label }: { text: string; lang: Lang; dark?: boolean; label?: string }) {
  const [state, setState] = useState<'idle' | 'speaking' | 'none'>('idle')
  if (!canSpeak()) return null
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, position: 'relative' }}>
      <button type="button" className={`speakbtn${dark ? ' dark' : ''}${state === 'speaking' ? ' speaking' : ''}`} aria-label={label ?? text}
              onClick={(e) => {
                e.preventDefault(); e.stopPropagation()
                const r = speak(text, lang)
                setState(r === 'none' ? 'none' : 'speaking')
                window.setTimeout(() => setState('idle'), r === 'none' ? 3500 : 1500)
              }}>
        <PictoSpeaker size={26} />
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
