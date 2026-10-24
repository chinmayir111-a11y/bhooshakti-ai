/** About: what this is, the demo notice, and the links that used to sit on
 *  the home screen (replay, control room) — out of the way of citizens. */
import { Link } from 'react-router-dom'
import { useLang } from '../i18n'
import Shell from './Shell'

export default function CitizenAbout() {
  const [, , t] = useLang()
  return (
    <Shell back title={t('about_title')}>
      <div className="step cz-about">
        <p style={{ fontSize: 17, color: 'var(--text)' }}>{t('about_body')}</p>
        <p className="cz-offline" style={{ marginBottom: 12 }}>{t('demo_notice')}</p>
        <ul className="cz-list">
          <li><Link to="/replay">{t('about_replay')}</Link></li>
          <li><Link to="/control">{t('about_control')}</Link></li>
        </ul>
      </div>
      <p className="cz-notice">{t('emergency_line')}</p>
    </Shell>
  )
}
