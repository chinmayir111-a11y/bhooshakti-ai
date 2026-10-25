/** Emergency help: two tap-to-call buttons, SMS keywords, the warning signs. */
import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { api } from '../api/client'
import { ISSUE_PICTOS, IconBell, IconMail, PictoEvacuate, PictoPhone, PictoShield } from '../components/Pictograms'
import { useLang } from '../i18n'
import Shell, { Speak } from './Shell'
import SmsButton from './SmsButton'

export default function CitizenHelp() {
  const [lang, , t] = useLang()
  const [sms, setSms] = useState<{ number: string; configured: boolean } | null>(null)
  useEffect(() => { api.smsNumber().then(setSms).catch(() => {}) }, [])
  const num = sms?.number || '<alert number>'
  // Footer "SMS" lands here (/help#sms): scroll to the buttons.
  const { hash } = useLocation()
  const smsRef = useRef<HTMLDivElement>(null)
  useEffect(() => { if (hash === '#sms') window.setTimeout(() => smsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80) }, [hash])

  return (
    <Shell back title={t('help_title')}>
      <a className="bigbtn red" href="tel:112">
        <span className="ico"><PictoPhone size={48} /></span>
        <span className="txt">{t('help_call_112')}</span>
        <Speak text={t('help_call_112')} lang={lang} />
      </a>
      <a className="bigbtn bamboo" href="tel:1078">
        <span className="ico"><PictoPhone size={48} /></span>
        <span className="txt">{t('help_call_1078')}</span>
        <Speak text={t('help_call_1078')} lang={lang} />
      </a>

      {/* No internet and no reading needed: one tap writes the SMS, the phone
          says what to do next, they press Send. */}
      <div className="step" id="sms" ref={smsRef}>
        <h2>{t('sms_buttons_title')}<Speak text={`${t('sms_buttons_title')}. ${t('sms_btn_report')}. ${t('sms_btn_safe')}. ${t('sms_btn_join')}`} lang={lang} dark /></h2>
        <SmsButton intent="report" className="bigbtn earth" label={t('sms_btn_report')} extra={t('issue_landslide')} icon={<ISSUE_PICTOS.landslide size={44} />} />
        <SmsButton intent="safe" className="bigbtn green" label={t('sms_btn_safe')} icon={<PictoShield size={44} />} />
        <SmsButton intent="join" className="bigbtn slate" label={t('sms_btn_join')} icon={<IconBell size={36} />} />
      </div>

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
        {sms?.configured && <a className="cz-linkbtn" href={`sms:${num}?body=SAFE%20`}><IconMail />SAFE …</a>}
      </div>
    </Shell>
  )
}
