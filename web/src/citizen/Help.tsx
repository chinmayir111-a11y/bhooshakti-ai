/** Emergency help: two tap-to-call buttons, SMS keywords, the warning signs. */
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { ISSUE_PICTOS, PictoEvacuate, PictoPhone } from '../components/Pictograms'
import { useLang } from '../i18n'
import Shell, { Speak } from './Shell'

export default function CitizenHelp() {
  const [lang, , t] = useLang()
  const [sms, setSms] = useState<{ number: string; configured: boolean } | null>(null)
  useEffect(() => { api.smsNumber().then(setSms).catch(() => {}) }, [])
  const num = sms?.number || '<alert number>'

  return (
    <Shell back title={t('help_title')}>
      <a className="bigbtn red" href="tel:112">
        <span className="ico"><PictoPhone size={48} /></span>
        <span className="txt">{t('help_call_112')}</span>
        <Speak text={t('help_call_112')} lang={lang} />
      </a>
      <a className="bigbtn earth" href="tel:1078">
        <span className="ico"><PictoPhone size={48} /></span>
        <span className="txt">{t('help_call_1078')}</span>
        <Speak text={t('help_call_1078')} lang={lang} />
      </a>

      <div className="step">
        <h2>{t('help_what_to_do')}<Speak text={`${t('help_what_to_do')}. ${t('help_tip_1')} ${t('help_tip_2')} ${t('help_tip_3')}`} lang={lang} dark /></h2>
        <ul className="cz-list">
          <li><PictoEvacuate size={44} />{t('help_tip_1')}</li>
          <li><ISSUE_PICTOS.road_blockage size={44} />{t('help_tip_2')}</li>
          <li><ISSUE_PICTOS.tilted_trees size={44} />{t('help_tip_3')}</li>
        </ul>
      </div>

      <div className="step">
        <h2>{t('signs_title')}</h2>
        <div className="picto-grid">
          {(['landslide', 'crack', 'road_blockage', 'tilted_trees', 'muddy_water', 'evacuate'] as const).map((k) => {
            const P = ISSUE_PICTOS[k]
            return <div key={k} role="img" aria-label={t(`issue_${k}`)} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 700, textAlign: 'center' }}><P size={48} style={{ color: 'var(--earth)' }} />{t(`issue_${k}`)}</div>
          })}
        </div>
      </div>

      <div className="step">
        <h2>{t('help_sms_title')}<Speak text={`${t('help_sms_title')}. ${t('help_sms_report')}. ${t('help_sms_safe')}. ${t('help_sms_join')}`} lang={lang} dark /></h2>
        <ul className="cz-list">
          <li><span className="cz-kbd">LS 734101</span>{t('help_sms_report')}</li>
          <li><span className="cz-kbd">SAFE 734101</span>{t('help_sms_safe')}</li>
          <li><span className="cz-kbd">JOIN 734101</span>{t('help_sms_join')}</li>
        </ul>
        <p style={{ fontSize: 15, color: 'var(--text-muted)', marginTop: 10 }}>
          {t('help_missed_call')} {sms?.configured ? <a href={`tel:${num}`}>{num}</a> : <em>(SMS gateway not configured in this demo)</em>}
        </p>
        {sms?.configured && <a className="cz-linkbtn" href={`sms:${num}?body=SAFE%20`}>✉ SAFE …</a>}
      </div>
    </Shell>
  )
}
