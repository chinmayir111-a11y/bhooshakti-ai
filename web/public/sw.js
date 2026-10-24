/* BHOOSHAKTI service worker — app shell offline, network for the API.
 *
 * Strategy
 *   navigation      network first, fall back to the cached shell (index.html)
 *   built assets    cache first (hashed filenames never change)
 *   /public/*, /pincode risk   stale-while-revalidate, so "Am I safe?" shows
 *                   the last known answer with no signal
 *   everything else network only (reports are queued in IndexedDB by the app)
 */
const VERSION = 'bhooshakti-v3'
const SHELL = ['/', '/index.html', '/manifest.webmanifest', '/icon.svg']

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()))
})

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('message', (e) => {
  if (e.data === 'skipWaiting') self.skipWaiting()
})

self.addEventListener('fetch', (e) => {
  const req = e.request
  if (req.method !== 'GET') return
  const url = new URL(req.url)
  const sameOrigin = url.origin === self.location.origin

  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).then((r) => {
      caches.open(VERSION).then((c) => c.put('/index.html', r.clone()))
      return r
    }).catch(() => caches.match('/index.html')))
    return
  }

  if (sameOrigin && url.pathname.startsWith('/assets/')) {
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((r) => {
      caches.open(VERSION).then((c) => c.put(req, r.clone()))
      return r
    })))
    return
  }

  if (/\/public\/(risk|pincode)|\/manifest\.webmanifest|\/icon/.test(url.pathname)) {
    e.respondWith(caches.open(VERSION).then(async (c) => {
      const cached = await c.match(req)
      const net = fetch(req).then((r) => { if (r.ok) c.put(req, r.clone()); return r }).catch(() => cached)
      return cached || net
    }))
  }
})
