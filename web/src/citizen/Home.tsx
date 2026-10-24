/** Three calm, solid buttons under the scene: one bright main action, two
 *  quiet ones. Each speaks its label; nothing to read is required. */
import { Link } from 'react-router-dom'
import { IconArrow, PictoCamera, PictoPhone, PictoShield } from '../components/Pictograms'
import { useLang } from '../i18n'
import { useZoneState } from './rain'
import Shell, { Speak } from './Shell'

export default function CitizenHome() {
  const [lang, , t] = useLang()
  const zone = useZoneState()
  const hot = zone.state === 'watch' || zone.state === 'danger'
  const items = [
    { to: '/report', cls: `pri${hot ? ' hot' : ''}`, Icon: PictoCamera, key: 'report' },
    { to: '/safe', cls: 'sec', Icon: PictoShield, key: 'safe' },
    { to: '/help', cls: 'sec', Icon: PictoPhone, key: 'help' },
  ]
  return (
    <Shell>
      {items.map(({ to, cls, Icon, key }, i) => (
        <Link key={key} to={to} className={`czbtn ${cls}`} style={{ animationDelay: `${i * 0.1}s` }}>
          <span className="ic"><Icon size={26} /></span>
          <span className="txt">{t(key)}</span>
          <Speak text={t(key)} lang={lang} />
          <IconArrow size={18} className="arr" />
        </Link>
      ))}
    </Shell>
  )
}
