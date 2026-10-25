/** About: what this is. No links to the control room or replay: those are
 *  for officials, who sign in at /login. */
import { useLang } from '../i18n'
import Shell from './Shell'

export default function CitizenAbout() {
  const [, , t] = useLang()
  return (
    <Shell back title={t('about_title')}>
      <div className="step cz-about">
        <p style={{ fontSize: 17, color: 'var(--text)' }}>{t('about_body')}</p>
        <p style={{ fontSize: 14, color: 'var(--text-muted)', marginTop: 10 }}>{t('about_integrations')}</p>
      </div>
      <p className="cz-notice">{t('emergency_line')}</p>
    </Shell>
  )
}
