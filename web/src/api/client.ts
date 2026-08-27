/** Typed REST client. One place that knows the base URL and the token. */

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string) || 'http://localhost:8000'

const TOKEN_KEY = 'bhooshakti.token'
const USER_KEY = 'bhooshakti.user'

export type Severity = 'LOW' | 'MODERATE' | 'HIGH' | 'CRITICAL'
export type Role = 'authority' | 'field_officer' | 'citizen'

export interface Factor { key: string; text: string; weight: number; direction: string }

export interface ZoneProps {
  id: number; code: string; name: string; district: string; state: string
  slope_deg: number; aspect_deg: number; elevation_m: number
  lithology: string; land_cover: string; population: number; area_km2: number
  centroid: [number, number]
  risk_score: number | null; severity: Severity; confidence: number | null
  contributing_factors: Factor[]; computed_at: string | null
}

export interface Summary {
  severity_counts: Record<string, number>
  active_alerts: number; alerts_24h: number; unverified_reports: number
  roads_flagged: number; villages_cut_off: number
  sensors_total: number; sensors_failed: number; field_reports_24h: number
}

export interface Delivery {
  channel: string; recipient: string; status: string; detail: string
  language: string; sent_at: string | null
}

export interface Alert {
  id: number; zone_id: number; zone_name: string; zone_code?: string
  district?: string; state?: string
  severity: Severity; risk_score: number; confidence: number
  title: string; message: string; contributing_factors: Factor[]
  language: string; created_at: string; acknowledged: boolean
  source: string; deliveries: Delivery[]
}

export interface CitizenReport {
  id: number; issue_type: string; issue_label: string; description: string
  photo_path: string; lat: number; lon: number; phone: string; language: string
  zone_id: number | null; zone_name: string | null
  geo_valid: boolean; geo_note: string; status: string
  moderated_by: string; moderated_at: string | null; moderation_notes: string
  created_at: string
}

export interface WeatherStatus {
  provider: string
  using_real_weather: boolean
  latest_observation: string | null
  coverage: Array<{ source: string; observed_hours: number; forecast_hours: number; from: string | null; to: string | null }>
  recent_fetches: Array<{ endpoint: string; fetched_at: string | null; ok: boolean; hours_written: number; detail: string }>
  attribution: string
}

export interface StoredUser {
  username: string; role: Role; full_name: string; designation: string
}

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}
export function getUser(): StoredUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as StoredUser) : null
  } catch { return null }
}
export function setSession(token: string, user: StoredUser) {
  try {
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  } catch { /* private-mode browsers: session simply won't persist */ }
}
export function clearSession() {
  try { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY) } catch { /* ignore */ }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) }
  if (init.body) headers['Content-Type'] = 'application/json'
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  login: (username: string, password: string) =>
    request<{ access_token: string } & StoredUser>('/auth/login', {
      method: 'POST', body: JSON.stringify({ username, password }),
    }),
  demoLogins: () => request<Array<{ username: string; password: string; role: Role; label: string; description: string }>>('/auth/demo-logins'),

  zones: () => request<{ features: Array<{ id: number; geometry: any; properties: ZoneProps }> }>('/zones'),
  zone: (id: number) => request<any>(`/zones/${id}`),
  summary: () => request<Summary>('/zones/summary'),
  recompute: () => request<any>('/risk/recompute', { method: 'POST', body: JSON.stringify({ raise_alerts: true }) }),
  modelInfo: () => request<any>('/risk/model'),

  infrastructure: () => request<any>('/infrastructure'),
  sensors: () => request<any>('/sensors'),
  historical: () => request<any>('/historical'),

  alerts: (limit = 100) => request<Alert[]>(`/alerts?limit=${limit}`),
  testAlert: (body: { zone_id?: number; email?: string; language?: string }) =>
    request<any>('/alerts/test', { method: 'POST', body: JSON.stringify(body) }),
  acknowledge: (id: number) => request<any>(`/alerts/${id}/acknowledge`, { method: 'POST' }),

  reports: (status?: string) =>
    request<CitizenReport[]>(`/reports${status ? `?status=${status}` : ''}`),
  createReport: (body: Record<string, unknown>) =>
    request<any>('/reports', { method: 'POST', body: JSON.stringify(body) }),
  moderate: (id: number, decision: string, notes: string) =>
    request<any>(`/reports/${id}/moderate`, { method: 'POST', body: JSON.stringify({ decision, notes }) }),
  geoCheck: (lat: number, lon: number) => request<any>(`/reports/geo-check?lat=${lat}&lon=${lon}`),

  audit: (limit = 200) => request<any>(`/audit?limit=${limit}`),

  demoState: () => request<any>('/demo/state'),
  demoSteps: () => request<any>('/demo/steps'),
  simulate: (speed: 1 | 4) => request<any>('/demo/simulate', { method: 'POST', body: JSON.stringify({ speed }) }),
  resetDemo: () => request<any>('/demo/reset', { method: 'POST' }),
  responsePlan: () => request<any>('/demo/response-plan'),

  health: () => request<any>('/health'),

  weatherStatus: () => request<WeatherStatus>('/weather/status'),
  refreshWeather: () => request<any>('/weather/refresh', { method: 'POST' }),
}
