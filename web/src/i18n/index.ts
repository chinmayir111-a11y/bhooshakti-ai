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

export function speak(text: string, lang: Lang): boolean {
  if (!canSpeak() || !text) return false
  const locale = tables._meta.voice_locale[lang] ?? 'en-IN'
  const u = new SpeechSynthesisUtterance(text)
  u.lang = locale
  u.rate = 0.92
  const voices = window.speechSynthesis.getVoices()
  const match = voices.find((v) => v.lang.replace('_', '-').toLowerCase() === locale.toLowerCase())
    ?? voices.find((v) => v.lang.toLowerCase().startsWith(locale.slice(0, 2)))
  if (match) u.voice = match
  window.speechSynthesis.cancel()
  window.speechSynthesis.speak(u)
  return true
}
