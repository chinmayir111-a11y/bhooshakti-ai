import { describe, expect, it } from 'vitest'
import { MAX_ATTEMPTS, OfflineQueue, QUEUE_KEY, makeUuid, type QueuedReport, type Storage } from './queue'

class MemoryStorage implements Storage {
  data = new Map<string, string>()
  async getItem(k: string) { return this.data.get(k) ?? null }
  async setItem(k: string, v: string) { this.data.set(k, v) }
}

function report(uuid: string, zone = 1): Omit<QueuedReport, 'attempts'> {
  return {
    client_uuid: uuid, zone_id: zone, verdict: 'CONFIRMED',
    notes: 'Tension cracks across the cut slope', lat: 26.95, lon: 88.32,
    observed_at: '2026-08-26T10:00:00Z', submitted_offline: true,
  }
}

const online = async (batch: QueuedReport[]) => ({ settled: batch.map((b) => b.client_uuid) })
const offline = async () => { throw new Error('Network request failed') }

describe('OfflineQueue', () => {
  it('holds submissions while offline and reports how many are pending', async () => {
    const q = new OfflineQueue(new MemoryStorage(), offline)
    await q.enqueue(report('a'))
    await q.enqueue(report('b'))
    await q.enqueue(report('c'))
    expect(await q.count()).toBe(3)

    const result = await q.flush()
    expect(result.synced).toBe(0)
    expect(result.pending).toBe(3)
    expect(result.error).toContain('Network')
    // Nothing may be dropped just because the network was down.
    expect(await q.count()).toBe(3)
  })

  it('flushes everything once the network returns, and empties the queue', async () => {
    const storage = new MemoryStorage()
    const down = new OfflineQueue(storage, offline)
    await down.enqueue(report('a'))
    await down.enqueue(report('b'))
    await down.flush()

    const up = new OfflineQueue(storage, online)
    const result = await up.flush()
    expect(result.synced).toBe(2)
    expect(result.pending).toBe(0)
    expect(await up.count()).toBe(0)
  })

  it('survives an app restart — the queue lives in storage, not memory', async () => {
    const storage = new MemoryStorage()
    const first = new OfflineQueue(storage, offline)
    await first.enqueue(report('a'))
    await first.enqueue(report('b'))

    const afterRestart = new OfflineQueue(storage, online)
    expect(await afterRestart.count()).toBe(2)
    expect((await afterRestart.flush()).synced).toBe(2)
  })

  it('never queues the same client_uuid twice', async () => {
    const q = new OfflineQueue(new MemoryStorage(), offline)
    await q.enqueue(report('same'))
    await q.enqueue({ ...report('same'), notes: 'edited before sync' })
    expect(await q.count()).toBe(1)
    expect((await q.all())[0].notes).toBe('edited before sync')
  })

  it('keeps only the items the server did not settle', async () => {
    const q = new OfflineQueue(new MemoryStorage(), async (batch) => ({
      settled: batch.filter((b) => b.zone_id === 1).map((b) => b.client_uuid),
    }))
    await q.enqueue(report('a', 1))
    await q.enqueue(report('b', 2))
    await q.enqueue(report('c', 1))

    const result = await q.flush()
    expect(result.synced).toBe(2)
    expect(result.pending).toBe(1)
    expect((await q.all()).map((i) => i.client_uuid)).toEqual(['b'])
  })

  it('counts failed attempts and stops retrying past the limit', async () => {
    const q = new OfflineQueue(new MemoryStorage(), offline)
    await q.enqueue(report('a'))
    for (let i = 0; i < MAX_ATTEMPTS; i++) await q.flush()

    expect((await q.all())[0].attempts).toBeGreaterThanOrEqual(MAX_ATTEMPTS)
    const result = await q.flush()
    expect(result.error).toContain('retry limit')
    // Still retained — a stuck item is surfaced to the officer, not discarded.
    expect(await q.count()).toBe(1)
  })

  it('collapses concurrent flushes so a reconnect and a tap cannot double-send', async () => {
    let calls = 0
    const q = new OfflineQueue(new MemoryStorage(), async (batch) => {
      calls++
      await new Promise((r) => setTimeout(r, 20))
      return { settled: batch.map((b) => b.client_uuid) }
    })
    await q.enqueue(report('a'))
    await Promise.all([q.flush(), q.flush(), q.flush()])
    expect(calls).toBe(1)
  })

  it('recovers from corrupt storage instead of crashing', async () => {
    const storage = new MemoryStorage()
    storage.data.set(QUEUE_KEY, '{ this is not json')
    const q = new OfflineQueue(storage, online)
    expect(await q.count()).toBe(0)
    await q.enqueue(report('a'))
    expect(await q.count()).toBe(1)
  })

  it('generates unique client uuids', () => {
    const ids = new Set(Array.from({ length: 500 }, makeUuid))
    expect(ids.size).toBe(500)
    expect([...ids][0]).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$/)
  })
})
