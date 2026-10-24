/**
 * "Is it raining where I am?" for the header animation, without ever
 * prompting for location: the Safe and Report screens remember the last
 * answer, and if the person has already granted location we refresh it
 * quietly. Rain shows only when the zone had rain in the last observed hour.
 */
import { useEffect, useState } from 'react'
import { api, type PublicRisk } from '../api/client'

const KEY = 'bhooshakti.lastRain'
const FRESH_MS = 60 * 60 * 1000

export function rememberRisk(r: PublicRisk) {
  try { localStorage.setItem(KEY, JSON.stringify({ mm: r.rain_last_hour_mm ?? 0, at: Date.now() })) } catch { /* private mode */ }
}

function cached(): number | null {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || 'null')
    return v && Date.now() - v.at < FRESH_MS ? Number(v.mm) || 0 : null
  } catch { return null }
}

export function useZoneRain(): boolean {
  const [mm, setMm] = useState<number | null>(cached)
  useEffect(() => {
    if (mm != null || !navigator.onLine || !navigator.permissions || !navigator.geolocation) return
    let gone = false
    navigator.permissions.query({ name: 'geolocation' as PermissionName }).then((p) => {
      if (p.state !== 'granted' || gone) return
      navigator.geolocation.getCurrentPosition((pos) => {
        api.publicRisk(pos.coords.latitude, pos.coords.longitude).then((r) => {
          rememberRisk(r)
          if (!gone) setMm(r.rain_last_hour_mm ?? 0)
        }).catch(() => {})
      }, () => {}, { maximumAge: 10 * 60 * 1000, timeout: 8000 })
    }).catch(() => {})
    return () => { gone = true }
  }, [mm])
  return (mm ?? 0) > 0.1
}
