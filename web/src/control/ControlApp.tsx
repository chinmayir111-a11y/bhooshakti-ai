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

// Open the connections to the map tile servers while the dashboard is still
// loading, so the first terrain and base-map tiles do not pay for DNS + TLS.
// Done here, not in index.html, so the citizen app never makes them.
for (const href of ['https://s3.amazonaws.com', 'https://tiles.openfreemap.org', 'https://tile.openstreetmap.org', 'https://server.arcgisonline.com']) {
  if (!document.querySelector(`link[rel="preconnect"][href="${href}"]`)) {
    const l = document.createElement('link'); l.rel = 'preconnect'; l.href = href; l.crossOrigin = 'anonymous'
    document.head.appendChild(l)
  }
}

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
