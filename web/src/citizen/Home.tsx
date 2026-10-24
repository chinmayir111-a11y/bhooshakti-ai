/** Three giant icon buttons with audio labels. Nothing to read is required. */
import { Link } from 'react-router-dom'
import { PictoLandslide, PictoPhone, PictoShield } from '../components/Pictograms'
import { useLang } from '../i18n'
import Shell, { Speak } from './Shell'

export default function CitizenHome() {
  const [lang, , t] = useLang()
  const items = [
    { to: '/report', cls: 'earth', Icon: PictoLandslide, key: 'report', sub: t('tap_to_hear') },
    { to: '/safe', cls: 'green', Icon: PictoShield, key: 'safe', sub: t('tap_to_hear') },
    { to: '/help', cls: 'slate', Icon: PictoPhone, key: 'help', sub: '112 · 1078' },
  ]
  return (
    <Shell>
      {items.map(({ to, cls, Icon, key, sub }) => (
        <Link key={key} to={to} className={`bigbtn ${cls}`}>
          <span className="ico"><Icon size={52} /></span>
          <span className="txt">{t(key)}<span className="sub">{sub}</span></span>
          <Speak text={t(key)} lang={lang} />
        </Link>
      ))}
    </Shell>
  )
}
