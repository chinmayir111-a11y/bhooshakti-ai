/**
 * Offline-first submission queue.
 *
 * A field officer on a hillside has no signal. Verifications are written to
 * local storage first and pushed later; the network is treated as an
 * optimisation, never a precondition.
 *
 * Deliberately free of React and React Native imports so it can be unit-tested
 * in plain Node — see queue.test.ts. Storage and transport are injected.
 *
 * Idempotence: every item carries a client-generated `client_uuid`. The API
 * upserts on it, so a flush interrupted halfway and retried cannot create
 * duplicate reports.
 */

export interface QueuedReport {
  client_uuid: string
  zone_id: number
  verdict: 'CONFIRMED' | 'DENIED' | 'UNCERTAIN'
  notes: string
  lat: number | null
  lon: number | null
  observed_at: string
  submitted_offline: boolean
  photo_base64?: string | null
  /** Failed attempts so far. Used for backoff and to surface stuck items. */
  attempts: number
  last_error?: string
}

export interface Storage {
  getItem(key: string): Promise<string | null>
  setItem(key: string, value: string): Promise<void>
}

/** Pushes a batch; resolves with the uuids the server accepted or already had. */
export type Transport = (batch: QueuedReport[]) => Promise<{ settled: string[] }>

export const QUEUE_KEY = 'bhooshakti.queue.v1'
export const MAX_ATTEMPTS = 8

export class OfflineQueue {
  private cache: QueuedReport[] | null = null
  private flushing = false

  constructor(private storage: Storage, private transport: Transport) {}

  async all(): Promise<QueuedReport[]> {
    if (this.cache) return this.cache
    try {
      const raw = await this.storage.getItem(QUEUE_KEY)
      this.cache = raw ? (JSON.parse(raw) as QueuedReport[]) : []
    } catch {
      // Corrupt or unreadable storage must not brick the app; start clean.
      this.cache = []
    }
    return this.cache
  }

  async count(): Promise<number> {
    return (await this.all()).length
  }

  private async persist(items: QueuedReport[]): Promise<void> {
    this.cache = items
    await this.storage.setItem(QUEUE_KEY, JSON.stringify(items))
  }

  /** Add a report. A repeat client_uuid replaces the pending copy, never appends. */
  async enqueue(report: Omit<QueuedReport, 'attempts'>): Promise<QueuedReport[]> {
    const items = await this.all()
    const next = items.filter((i) => i.client_uuid !== report.client_uuid)
    next.push({ ...report, attempts: 0 })
    await this.persist(next)
    return next
  }

  /**
   * Try to push everything pending.
   *
   * Returns what happened. Items the server settled are removed; the rest stay
   * queued with an incremented attempt count so nothing is silently lost.
   * Concurrent calls are collapsed — a reconnect event and a manual tap must
   * not double-send.
   */
  async flush(): Promise<{ synced: number; pending: number; error?: string }> {
    // The guard must be claimed synchronously, before the first await —
    // otherwise three concurrent callers all get past the check while the
    // first is still awaiting storage, and the batch goes out three times.
    if (this.flushing) return { synced: 0, pending: await this.count() }
    this.flushing = true
    try {
      const items = await this.all()
      if (items.length === 0) return { synced: 0, pending: 0 }

      const batch = items.filter((i) => i.attempts < MAX_ATTEMPTS)
      if (batch.length === 0) {
        return { synced: 0, pending: items.length, error: 'All queued items exceeded retry limit' }
      }

      const { settled } = await this.transport(batch)
      const done = new Set(settled)
      const remaining = items.filter((i) => !done.has(i.client_uuid))
      await this.persist(remaining)
      return { synced: items.length - remaining.length, pending: remaining.length }
    } catch (err: any) {
      const message = err?.message ?? String(err)
      // Still offline, or the server rejected the batch. Count the attempt and
      // keep everything — losing a field observation is the worst outcome here.
      const bumped = (await this.all()).map((i) => ({
        ...i, attempts: i.attempts + 1, last_error: message,
      }))
      await this.persist(bumped)
      return { synced: 0, pending: bumped.length, error: message }
    } finally {
      this.flushing = false
    }
  }

  async clear(): Promise<void> {
    await this.persist([])
  }
}

/** RFC4122-ish v4 id. Avoids a dependency for something this small. */
export function makeUuid(): string {
  const hex = '0123456789abcdef'
  let out = ''
  for (let i = 0; i < 36; i++) {
    if (i === 8 || i === 13 || i === 18 || i === 23) out += '-'
    else if (i === 14) out += '4'
    else out += hex[Math.floor(Math.random() * 16)]
  }
  return out
}
