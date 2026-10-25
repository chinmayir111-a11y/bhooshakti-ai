/** Typed REST client. One place that knows the base URL and the token. */

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string) || 'http://localhost:8000'

const TOKEN_KEY = 'bhooshakti.token'
const USER_KEY = 'bhooshakti.user'

export type Severity = 'LOW' | 'MODERATE' | 'HIGH' | 'CRITICAL'
export type Tier = 'ADVISORY' | 'WARNING'
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
  sensors_online: number; sensors_hardware_live: number
  zones_at_risk: number; open_reports: number; advisories_active: number
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
  tier?: Tier; status?: string; report_id?: number | null; parent_alert_id?: number | null
  kind?: string; siren?: boolean | null
}

export interface CorroborationReason { key: string; points: number; text: string }
export interface EscalationState {
  open: boolean; level: number
  next_step_at: string | null; next_step_label: string | null
  advisory_at: string | null; advisory_alert_id: number | null; warning_alert_id: number | null
  acknowledged_at: string | null; acknowledged_by: string
}

export interface CitizenReport {
  id: number; issue_type: string; issue_label: string; description: string
  photo_path: string; voice_note_path: string; lat: number; lon: number; phone: string; language: string
  channel: string
  zone_id: number | null; zone_name: string | null
  geo_valid: boolean; geo_note: string; status: string
  corroboration_score: number; corroboration_reasons: CorroborationReason[]
  escalation: EscalationState
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

export interface ZoneProvenance {
  zone_id: number; zone_code: string; zone_name: string
  requested_point: { lat: number; lon: number }
  sources: Array<{ endpoint: string; role: string; model: string
    grid: { lat: number; lon: number; elevation_m: number | null; fetched_at: string | null } | null }>
  last_24h_by_source: Array<{ source: string; hours: number; mm: number }>
  fetched_at: Record<string, string>
  verify_live: { forecast: string; archive: string }
  real: boolean; attribution: string
}

export interface RainFrame { ts: string; forecast: boolean; zones: Record<string, number> }

export interface PublicRisk {
  inside_zone: boolean; zone_id: number | null; zone_name: string | null; place: string
  severity: Severity | null; message: string
  active_alert: { tier: Tier; title: string; created_at: string } | null
  computed_at: string | null; distance_km?: number | null
  pincode?: string; lat?: number; lon?: number
  rain_last_hour_mm?: number | null
}

export interface ReplayEvent {
  id: number; source: string; source_event_id: string; date: string; time_known: boolean
  lat: number; lon: number; state: string; title: string; trigger: string; fatalities: number
  source_url: string; location_accuracy: string
  outcome: string | null; lead_hours: number | null; demo: boolean; real: true
}

export interface ReplayHour {
  ts: string; rain_mm: number; rainfall_24h: number; soil_moisture_pct: number
  risk_score: number; severity: Severity
}

export interface ReplayTimeline {
  event: { id: number; source: string; source_event_id: string; time_known: boolean; lat: number; lon: number
    state: string; title: string; fatalities: number; source_url: string; date: string; reference: string; day_end: string }
  window: 'event' | 'dry'
  threshold: number
  verdict: { outcome?: string; lead_hours?: number | null; first_alert: string | null; peak_score: number
    false_alarm?: boolean; hours_high?: number }
  hours: ReplayHour[]
  provenance: { events: string; weather: string; grid: { lat: number; lon: number }; forecast_input: string; real: boolean }
}

export interface StoredUser {
  username: string; role: Role; full_name: string; designation: string
}

/** The stored token, or null when it is missing or past its expiry (a
 *  12-hour token left over from yesterday would otherwise look signed in
 *  while every action comes back 401). */
export function getToken(): string | null {
  let token: string | null = null
  try { token = localStorage.getItem(TOKEN_KEY) } catch { return null }
  if (token && tokenExpired(token)) { clearSession(); return null }
  return token
}
function tokenExpired(token: string): boolean {
  try {
    const exp = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))).exp
    return typeof exp === 'number' && exp * 1000 <= Date.now()
  } catch { return false }
}
/** A random id kept on this device, so the server can tell two people apart
 *  when neither gives a phone number (SOS groups, the hourly report limit).
 *  Not linked to the person; clearing site data makes a new one. */
export function deviceId(): string {
  try {
    let id = localStorage.getItem('bhooshakti.device')
    if (!id) { id = crypto.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`; localStorage.setItem('bhooshakti.device', id) }
    return id
  } catch { return '' }
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
  // Signed in but refused: the session ended server-side. Say so and go to
  // sign-in rather than leaving buttons that silently do nothing.
  if (res.status === 401 && token) {
    clearSession()
    if (!location.pathname.startsWith('/login')) location.assign(`/login?expired=1&next=${encodeURIComponent(location.pathname + location.search)}`)
  }
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

const post = (path: string, body?: unknown) =>
  request<any>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  login: (username: string, password: string) =>
    request<{ access_token: string } & StoredUser>('/auth/login', {
      method: 'POST', body: JSON.stringify({ username, password }),
    }),
  demoLogins: () => request<Array<{ username: string; password: string; role: Role; label: string; description: string }>>('/auth/demo-logins'),

  zones: () => request<{ features: Array<{ id: number; geometry: any; properties: ZoneProps }> }>('/zones'),
  zone: (id: number) => request<any>(`/zones/${id}`),
  summary: () => request<Summary>('/zones/summary'),
  recompute: () => post('/risk/recompute', { raise_alerts: true }),
  modelInfo: () => request<any>('/risk/model'),

  infrastructure: () => request<any>('/infrastructure'),
  sensors: () => request<any>('/sensors'),
  historical: () => request<any>('/historical'),

  alerts: (limit = 100) => request<Alert[]>(`/alerts?limit=${limit}`),
  testAlert: (body: { zone_id?: number; email?: string; language?: string }) => post('/alerts/test', body),
  acknowledge: (id: number) => post(`/alerts/${id}/acknowledge`),

  reports: (status?: string) =>
    request<CitizenReport[]>(`/reports${status ? `?status=${status}` : ''}`),
  escalations: (includeChecking = false) => request<CitizenReport[]>(`/reports/escalations${includeChecking ? '?include_checking=true' : ''}`),
  createReport: (body: Record<string, unknown>) => post('/reports', { device_id: deviceId(), ...body }),
  moderate: (id: number, decision: string, notes: string) => post(`/reports/${id}/moderate`, { decision, notes }),
  acknowledgeReport: (id: number) => post(`/reports/${id}/acknowledge`),
  confirmReport: (id: number, notes = '') => post(`/reports/${id}/confirm`, { notes }),
  dismissReport: (id: number, notes = '') => post(`/reports/${id}/dismiss`, { notes }),
  geoCheck: (lat: number, lon: number) => request<any>(`/reports/geo-check?lat=${lat}&lon=${lon}`),

  publicRisk: (lat: number, lon: number, lang = 'en') =>
    request<PublicRisk>(`/public/risk?lat=${lat}&lon=${lon}&lang=${lang}`),
  pincodeRisk: (pin: string, lang = 'en') => request<PublicRisk>(`/public/pincode/${pin}?lang=${lang}`),
  smsNumber: () => request<{ number: string; configured: boolean; keywords: string[] }>('/public/sms-number'),

  audit: (limit = 200) => request<any>(`/audit?limit=${limit}`),

  demoState: () => request<any>('/demo/state'),
  demoSteps: () => request<any>('/demo/steps'),
  simulate: (speed: 1 | 4) => post('/demo/simulate', { speed }),
  resetDemo: () => post('/demo/reset'),
  responsePlan: () => request<any>('/demo/response-plan'),

  health: () => request<any>('/health'),

  weatherStatus: () => request<WeatherStatus>('/weather/status'),
  refreshWeather: () => post('/weather/refresh'),
  zoneProvenance: (id: number) => request<ZoneProvenance>(`/weather/zone/${id}/provenance`),
  rainFrames: (hours = 48) => request<{ frames: RainFrame[]; source: string; real: boolean }>(`/weather/rain-frames?hours=${hours}`),

  replaySummary: () => request<any>('/replay/summary'),
  replayEvents: () => request<ReplayEvent[]>('/replay/events'),
  replayEvent: (id: number, window: 'event' | 'dry' = 'event') =>
    request<ReplayTimeline>(`/replay/events/${id}?window=${window}`),
}
