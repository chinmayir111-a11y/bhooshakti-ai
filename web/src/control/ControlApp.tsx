/** The officer dashboard. Lazy-loaded; this is where the map stacks live. */
import { useEffect } from 'react'
import { Route, Routes } from 'react-router-dom'
import { AppHeader } from '../components/common'
import { useLocalFlag } from '../hooks'
import Alerts from '../pages/Alerts'
import Audit from '../pages/Audit'
import Dashboard from '../pages/Dashboard'
import Moderation from '../pages/Moderation'
import '../styles/theme.css'
import { ControlCtx } from './context'

export default function ControlApp() {
  const [dark, setDark] = useLocalFlag('bhooshakti.dark', true)
  const [sources, setSources] = useLocalFlag('bhooshakti.sources', false)
  const [sound, setSound] = useLocalFlag('bhooshakti.sound', false)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light')
    return () => { document.documentElement.removeAttribute('data-theme') }
  }, [dark])

  return (
    <ControlCtx.Provider value={{ dark, setDark, sources, setSources, sound, setSound }}>
      <div className="app-shell">
        <AppHeader />
        <Routes>
          <Route index element={<Dashboard />} />
          <Route path="alerts" element={<Alerts />} />
          <Route path="moderation" element={<Moderation />} />
          <Route path="audit" element={<Audit />} />
        </Routes>
      </div>
    </ControlCtx.Provider>
  )
}
