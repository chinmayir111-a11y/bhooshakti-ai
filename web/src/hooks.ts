/** Small shared hooks: online state, reduced motion, count-up, a chime. */
import { useEffect, useRef, useState } from 'react'

export function useOnline(): boolean {
  const [on, setOn] = useState(typeof navigator === 'undefined' ? true : navigator.onLine)
  useEffect(() => {
    const up = () => setOn(true), down = () => setOn(false)
    window.addEventListener('online', up); window.addEventListener('offline', down)
    return () => { window.removeEventListener('online', up); window.removeEventListener('offline', down) }
  }, [])
  return on
}

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

/** Animates towards `target` over ~600 ms; jumps straight there under reduced motion. */
export function useCountUp(target: number, ms = 600): number {
  const [value, setValue] = useState(target)
  const from = useRef(target)
  useEffect(() => {
    if (prefersReducedMotion() || !Number.isFinite(target)) { setValue(target); from.current = target; return }
    const start = performance.now(), a = from.current, b = target
    if (a === b) return
    let raf = 0
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / ms)
      const e = 1 - Math.pow(1 - p, 3)
      setValue(Math.round(a + (b - a) * e))
      if (p < 1) raf = requestAnimationFrame(tick)
      else from.current = b
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, ms])
  return value
}

/** A two-note chime from the Web Audio API — no asset to load. Browsers
 *  require a user gesture before audio plays; the control room's "Sound"
 *  toggle is that gesture. */
let ctx: AudioContext | null = null
export function chime(kind: 'warning' | 'advisory' = 'warning') {
  try {
    ctx = ctx ?? new (window.AudioContext || (window as any).webkitAudioContext)()
    const t0 = ctx.currentTime
    const notes = kind === 'warning' ? [880, 1174.7, 880] : [659.3, 880]
    notes.forEach((f, i) => {
      const o = ctx!.createOscillator(), g = ctx!.createGain()
      o.type = 'sine'; o.frequency.value = f
      g.gain.setValueAtTime(0.0001, t0 + i * 0.18)
      g.gain.exponentialRampToValueAtTime(0.25, t0 + i * 0.18 + 0.02)
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + i * 0.18 + 0.17)
      o.connect(g).connect(ctx!.destination)
      o.start(t0 + i * 0.18); o.stop(t0 + i * 0.18 + 0.2)
    })
  } catch { /* no audio */ }
}

export function notify(title: string, body: string) {
  try {
    if (!('Notification' in window) || Notification.permission !== 'granted') return
    new Notification(title, { body, icon: '/icon.svg', tag: title })
  } catch { /* ignore */ }
}

export function useLocalFlag(key: string, initial = false): [boolean, (v: boolean) => void] {
  const [v, setV] = useState<boolean>(() => {
    try { const s = localStorage.getItem(key); return s == null ? initial : s === '1' } catch { return initial }
  })
  return [v, (n) => { setV(n); try { localStorage.setItem(key, n ? '1' : '0') } catch { /* ignore */ } }]
}

export function useNow(everyMs = 1000): number {
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), everyMs); return () => clearInterval(id) }, [everyMs])
  return now
}

export function countdown(iso: string | null | undefined, now: number): string {
  if (!iso) return '—'
  const secs = Math.round((new Date(iso).getTime() - now) / 1000)
  if (secs <= 0) return 'now'
  const m = Math.floor(secs / 60), s = secs % 60
  return m ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`
}
