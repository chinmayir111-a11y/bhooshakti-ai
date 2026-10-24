/**
 * Offline-first citizen report queue for the PWA.
 *
 * Mirrors mobile/src/offline/queue.ts: storage and transport are injected so
 * the class is unit-testable in Node, every item carries a client_uuid the
 * API upserts on (a replay interrupted halfway cannot double-post), and a
 * concurrent flush is collapsed into one. Storage here is IndexedDB
 * (offline/idb.ts) because a photo + voice note can exceed localStorage.
 */

export interface QueuedCitizenReport {
  client_uuid: string
  issue_type: string
  lat: number
  lon: number
  description: string
  phone: string
  language: string
  photo_base64: string | null
  voice_base64: string | null
  channel: 'pwa-offline'
  queued_at: string
  attempts: number
  last_error?: string
}

export interface KeyValueStore {
  getItem(key: string): Promise<string | null>
  setItem(key: string, value: string): Promise<void>
}

/** Posts one report; resolves when the server has it (or already had it). */
export type Transport = (report: QueuedCitizenReport) => Promise<void>

export const QUEUE_KEY = 'bhooshakti.citizen.queue.v1'
export const MAX_ATTEMPTS = 12

export class CitizenQueue {
  private cache: QueuedCitizenReport[] | null = null
  private flushing = false

  constructor(private store: KeyValueStore, private transport: Transport) {}

  async all(): Promise<QueuedCitizenReport[]> {
    if (this.cache) return this.cache
    try {
      const raw = await this.store.getItem(QUEUE_KEY)
      this.cache = raw ? (JSON.parse(raw) as QueuedCitizenReport[]) : []
    } catch {
      this.cache = []
    }
    return this.cache
  }

  async count(): Promise<number> { return (await this.all()).length }

  private async persist(items: QueuedCitizenReport[]) {
    this.cache = items
    await this.store.setItem(QUEUE_KEY, JSON.stringify(items))
  }

  async enqueue(report: Omit<QueuedCitizenReport, 'attempts' | 'queued_at' | 'channel'>): Promise<QueuedCitizenReport> {
    const items = await this.all()
    const item: QueuedCitizenReport = {
      ...report, channel: 'pwa-offline', queued_at: new Date().toISOString(), attempts: 0,
    }
    await this.persist([...items.filter((i) => i.client_uuid !== item.client_uuid), item])
    return item
  }

  /** Send everything pending, oldest first. Stops at the first failure so a
   *  dead network costs one attempt per flush, not one per item. */
  async flush(): Promise<{ synced: number; pending: number; error?: string }> {
    if (this.flushing) return { synced: 0, pending: await this.count() }
    this.flushing = true
    try {
      const items = await this.all()
      let synced = 0
      let error: string | undefined
      for (const item of items) {
        if (item.attempts >= MAX_ATTEMPTS) continue
        try {
          await this.transport(item)
          synced++
          await this.persist((await this.all()).filter((i) => i.client_uuid !== item.client_uuid))
        } catch (err: any) {
          error = err?.message ?? String(err)
          await this.persist((await this.all()).map((i) =>
            i.client_uuid === item.client_uuid ? { ...i, attempts: i.attempts + 1, last_error: error } : i))
          break
        }
      }
      return { synced, pending: await this.count(), error }
    } finally {
      this.flushing = false
    }
  }

  async clear() { await this.persist([]) }
}

export function makeUuid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  const hex = '0123456789abcdef'
  let out = ''
  for (let i = 0; i < 36; i++) {
    if (i === 8 || i === 13 || i === 18 || i === 23) out += '-'
    else if (i === 14) out += '4'
    else out += hex[Math.floor(Math.random() * 16)]
  }
  return out
}
