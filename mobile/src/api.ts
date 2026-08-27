/** Thin API layer for the field app. */
import Constants from 'expo-constants'
import type { QueuedReport } from './offline/queue'

const configured = (Constants.expoConfig?.extra as any)?.apiBase as string | undefined
export const API_BASE = configured || 'http://localhost:8000'

let token: string | null = null
export function setToken(t: string | null) { token = t }
export function getStoredToken() { return token }

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as any) }
  if (init.body) headers['Content-Type'] = 'application/json'
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (!res.ok) {
    let detail = res.statusText
    try { const b = await res.json(); detail = b.detail ?? detail } catch { /* non-JSON */ }
    throw new Error(String(detail))
  }
  return (await res.json()) as T
}

export const api = {
  login: (username: string, password: string) =>
    req<any>('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  assignments: () => req<any[]>('/field/assignments'),
  health: () => req<any>('/health'),

  /** Flush the offline queue. Idempotent server-side on client_uuid. */
  async pushBatch(batch: QueuedReport[]): Promise<{ settled: string[] }> {
    const body = {
      reports: batch.map(({ attempts, last_error, ...r }) => ({
        ...r, observed_at: r.observed_at,
      })),
    }
    const r = await req<any>('/field/verify/batch', { method: 'POST', body: JSON.stringify(body) })
    // Both newly accepted and already-known items count as settled: a replay
    // that the server recognised is done, not stuck.
    return {
      settled: [
        ...(r.accepted ?? []).map((x: any) => x.client_uuid),
        ...(r.duplicates ?? []).map((x: any) => x.client_uuid),
      ],
    }
  },
}
