/**
 * What the header scene needs to know about the person's own place, without
 * ever prompting for location: the Safe and Report screens remember the last
 * answer, and if location is already granted we refresh it quietly.
 * `state` drives sky, fog, rain and lightning; nothing here is a prompt.
 */
import { useEffect, useState } from 'react'
import { api, type PublicRisk, type Severity } from '../api/client'

const KEY = 'bhooshakti.lastRisk'
const FRESH_MS = 60 * 60 * 1000

export type SceneState = 'unknown' | 'safe' | 'watch' | 'danger'
export interface ZoneState { state: SceneState; rainMm: number; place: string | null; severity: Severity | null }

interface Stored { sev: Severity | null; tier: string | null; mm: number; place: string | null; at: number }

function toState(sev: Severity | null, tier: string | null): SceneState {
  if (tier === 'WARNING' || sev === 'CRITICAL') return 'danger'
  if (sev === 'HIGH' || sev === 'MODERATE' || tier === 'ADVISORY') return 'watch'
  if (sev === 'LOW') return 'safe'
  return 'unknown'
}

export function rememberRisk(r: PublicRisk) {
  const s: Stored = { sev: r.severity, tier: r.active_alert?.tier ?? null, mm: r.rain_last_hour_mm ?? 0, place: r.place, at: Date.now() }
  try { localStorage.setItem(KEY, JSON.stringify(s)) } catch { /* private mode */ }
  listeners.forEach((fn) => fn(s))
}

const listeners = new Set<(s: Stored) => void>()

function cached(): Stored | null {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || 'null') as Stored | null
    return v && Date.now() - v.at < FRESH_MS ? v : null
  } catch { return null }
}

export function useZoneState(): ZoneState {
  const [s, setS] = useState<Stored | null>(cached)
  useEffect(() => {
    listeners.add(setS)
    return () => { listeners.delete(setS) }
  }, [])
  useEffect(() => {
    if (s || !navigator.onLine || !navigator.permissions || !navigator.geolocation) return
    let gone = false
    navigator.permissions.query({ name: 'geolocation' as PermissionName }).then((p) => {
      if (p.state !== 'granted' || gone) return
      navigator.geolocation.getCurrentPosition((pos) => {
        api.publicRisk(pos.coords.latitude, pos.coords.longitude).then((r) => { if (!gone) rememberRisk(r) }).catch(() => {})
      }, () => {}, { maximumAge: 10 * 60 * 1000, timeout: 8000 })
    }).catch(() => {})
    return () => { gone = true }
  }, [s])
  return { state: s ? toState(s.sev, s.tier) : 'unknown', rainMm: s?.mm ?? 0, place: s?.place ?? null, severity: s?.sev ?? null }
}
