/** Three calm, solid buttons: one bright main action, one quiet one, and the
 *  red SOS last, within thumb reach. Each speaks its label. On a desktop the
 *  card sits on the hero beside the risk (citizen.css). */
import { Link } from 'react-router-dom'
import { PictoCamera, PictoShield } from '../components/Pictograms'
import { useLang } from '../i18n'
import { useZoneState } from './rain'
import Shell, { Speak } from './Shell'
import SosButton from './Sos'

export default function CitizenHome() {
  const [lang, , t] = useLang()
  const zone = useZoneState()
  const hot = zone.state === 'watch' || zone.state === 'danger'
  const items = [
    { to: '/report', cls: `pri${hot ? ' hot' : ''}`, Icon: PictoCamera, key: 'report' },
    { to: '/safe', cls: 'sec', Icon: PictoShield, key: 'safe' },
  ]
  return (
    <Shell home>
      <div className="actions">
        {items.map(({ to, cls, Icon, key }, i) => (
          <Link key={key} to={to} className={`czbtn ${cls}`} style={{ animationDelay: `${i * 0.1}s` }}>
            <span className="ic"><Icon size={26} /></span>
            <span className="txt">{t(key)}</span>
            <Speak text={t(key)} lang={lang} size={36} />
          </Link>
        ))}
        <SosButton />
      </div>
    </Shell>
  )
}
