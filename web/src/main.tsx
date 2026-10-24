import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './styles/base.css'
import { citizenQueue } from './offline/citizenQueue'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
)

// The citizen app is an installable PWA: the shell is cached, and a report
// written while offline is queued in IndexedDB and sent on reconnect.
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => { navigator.serviceWorker.register('/sw.js').catch(() => {}) })
}
window.addEventListener('online', () => { citizenQueue.flush().catch(() => {}) })
citizenQueue.flush().catch(() => {})
