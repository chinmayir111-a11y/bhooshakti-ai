/**
 * Language + speech for the citizen app.
 *
 * `useLang` persists the choice. `speak` reads a string aloud with the
 * browser's own TTS in the language's locale — no network, no provider key.
 * Assamese has no mainstream voice yet, so it falls back to Bengali, the
 * nearest script and sound; the strings file records which languages are
 * machine translations awaiting native review.
 */
import { useCallback, useEffect, useState } from 'react'
import strings from './strings.json'

export type Lang = 'en' | 'hi' | 'as' | 'bn' | 'ne'
export const LANGS: Lang[] = ['en', 'hi', 'as', 'bn', 'ne']
const KEY = 'bhooshakti.lang'

type Table = Record<string, string>
const tables = strings as unknown as Record<Lang, Table> & { _meta: { needs_native_review: string[]; voice_locale: Record<string, string> } }

export function needsReview(lang: Lang): boolean {
  return tables._meta.needs_native_review.includes(lang)
}

export function langName(lang: Lang): string {
  return tables[lang].lang_name
}

export function t(lang: Lang, key: string): string {
  return tables[lang]?.[key] ?? tables.en[key] ?? key
}

function stored(): Lang {
  try {
    const v = localStorage.getItem(KEY) as Lang | null
    if (v && LANGS.includes(v)) return v
  } catch { /* private mode */ }
  const nav = (navigator.language || 'en').slice(0, 2) as Lang
  return LANGS.includes(nav) ? nav : 'en'
}

const listeners = new Set<(l: Lang) => void>()
let current: Lang = stored()

export function setLang(l: Lang) {
  current = l
  try { localStorage.setItem(KEY, l) } catch { /* ignore */ }
  document.documentElement.lang = l
  listeners.forEach((fn) => fn(l))
}

export function useLang(): [Lang, (l: Lang) => void, (key: string) => string] {
  const [lang, set] = useState<Lang>(current)
  useEffect(() => {
    listeners.add(set)
    document.documentElement.lang = current
    return () => { listeners.delete(set) }
  }, [])
  const tr = useCallback((key: string) => t(lang, key), [lang])
  return [lang, setLang, tr]
}

export function canSpeak(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window
}

// Voices load asynchronously in Chrome; ask early and refresh when they arrive.
let voices: SpeechSynthesisVoice[] = []
function loadVoices() {
  if (!canSpeak()) return
  voices = window.speechSynthesis.getVoices()
  window.speechSynthesis.onvoiceschanged = () => { voices = window.speechSynthesis.getVoices() }
}
loadVoices()

// What to try, in order, when the device has no voice for the language.
// Nepali is Devanagari, so a Hindi voice reads it intelligibly; Assamese
// script is Bengali's, so a Bengali voice is the closest thing available.
const VOICE_CHAIN: Record<Lang, string[]> = {
  en: ['en-IN', 'en-GB', 'en'],
  hi: ['hi-IN', 'hi'],
  ne: ['ne-NP', 'ne', 'hi-IN', 'hi'],
  bn: ['bn-IN', 'bn-BD', 'bn'],
  as: ['as-IN', 'as', 'bn-IN', 'bn-BD', 'bn'],
}

function findVoice(lang: Lang): { voice: SpeechSynthesisVoice; exact: boolean } | null {
  if (!voices.length) voices = window.speechSynthesis.getVoices()
  const norm = (v: string) => v.replace('_', '-').toLowerCase()
  for (const [i, tag] of VOICE_CHAIN[lang].entries()) {
    const want = norm(tag)
    const v = voices.find((x) => norm(x.lang) === want) ?? voices.find((x) => norm(x.lang).startsWith(want.split('-')[0] + '-'))
    if (v) return { voice: v, exact: i === 0 || norm(v.lang).split('-')[0] === norm(VOICE_CHAIN[lang][0]).split('-')[0] }
  }
  return null
}

export type SpeakResult = 'ok' | 'fallback' | 'none'

let speaking: SpeechSynthesisUtterance | null = null

/** Speak `text` in `lang`. 'fallback' means a related language's voice was
 *  used; 'none' means the device has no usable voice (the caller should say so). */
export function speak(text: string, lang: Lang): SpeakResult {
  if (!canSpeak() || !text) return 'none'
  const found = findVoice(lang)
  if (!found && lang !== 'en') return 'none'
  const u = new SpeechSynthesisUtterance(text)
  u.lang = found?.voice.lang ?? tables._meta.voice_locale[lang] ?? 'en-IN'
  if (found) u.voice = found.voice
  u.rate = 0.9
  // Chrome bugs worked around here: an utterance that gets garbage-collected
  // goes silent, a speak() straight after cancel() is sometimes dropped, and a
  // tab can stay "paused" after speech was cut off by a page change. So keep a
  // reference, speak a moment after cancelling, and retry once if it never starts.
  const s = window.speechSynthesis
  speaking = u
  let started = false
  u.onstart = () => { started = true }
  if (import.meta.env.DEV) u.onerror = (e) => console.warn('speech error:', e.error)
  s.cancel(); s.resume()
  window.setTimeout(() => {
    if (speaking !== u) return
    s.speak(u)
    window.setTimeout(() => { if (speaking === u && !started) { s.cancel(); s.resume(); s.speak(u) } }, 1200)
  }, 60)
  return found && !found.exact ? 'fallback' : 'ok'
}

/** Human-readable list of installed voices for the language, for the hint. */
export function voiceFor(lang: Lang): string | null {
  const f = findVoice(lang)
  return f ? `${f.voice.name} (${f.voice.lang})` : null
}
