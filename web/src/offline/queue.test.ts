import { describe, expect, it } from 'vitest'
import { CitizenQueue, MAX_ATTEMPTS, QUEUE_KEY, type KeyValueStore, type QueuedCitizenReport } from './queue'

function memStore(): KeyValueStore & { data: Map<string, string> } {
  const data = new Map<string, string>()
  return { data, async getItem(k) { return data.get(k) ?? null }, async setItem(k, v) { data.set(k, v) } }
}

const report = (id: string) => ({
  client_uuid: id, issue_type: 'landslide', lat: 26.95, lon: 88.32, description: '',
  phone: '', language: 'en', photo_base64: null, voice_base64: null,
})

describe('CitizenQueue', () => {
  it('persists queued reports across instances', async () => {
    const store = memStore()
    await new CitizenQueue(store, async () => {}).enqueue(report('a'))
    const again = new CitizenQueue(store, async () => {})
    expect(await again.count()).toBe(1)
    expect(JSON.parse(store.data.get(QUEUE_KEY)!)[0].channel).toBe('pwa-offline')
  })

  it('re-enqueueing the same uuid replaces, never duplicates', async () => {
    const q = new CitizenQueue(memStore(), async () => {})
    await q.enqueue(report('a'))
    await q.enqueue({ ...report('a'), description: 'edited' })
    const all = await q.all()
    expect(all).toHaveLength(1)
    expect(all[0].description).toBe('edited')
  })

  it('flush sends oldest first and removes what the server took', async () => {
    const sent: string[] = []
    const q = new CitizenQueue(memStore(), async (r) => { sent.push(r.client_uuid) })
    await q.enqueue(report('a')); await q.enqueue(report('b'))
    expect(await q.flush()).toEqual({ synced: 2, pending: 0, error: undefined })
    expect(sent).toEqual(['a', 'b'])
  })

  it('a dead network keeps everything and costs one attempt', async () => {
    const q = new CitizenQueue(memStore(), async () => { throw new Error('offline') })
    await q.enqueue(report('a')); await q.enqueue(report('b'))
    const r = await q.flush()
    expect(r).toMatchObject({ synced: 0, pending: 2, error: 'offline' })
    const all = await q.all()
    expect(all.map((i) => i.attempts)).toEqual([1, 0])
    expect(all[0].last_error).toBe('offline')
  })

  it('an item past the retry limit is skipped, not lost', async () => {
    const store = memStore()
    const stuck: QueuedCitizenReport = { ...report('x'), channel: 'pwa-offline', queued_at: '', attempts: MAX_ATTEMPTS }
    await store.setItem(QUEUE_KEY, JSON.stringify([stuck]))
    const q = new CitizenQueue(store, async () => { throw new Error('should not be called') })
    expect(await q.flush()).toEqual({ synced: 0, pending: 1, error: undefined })
  })

  it('concurrent flushes collapse into one send', async () => {
    let calls = 0
    const q = new CitizenQueue(memStore(), async () => { calls++; await new Promise((r) => setTimeout(r, 5)) })
    await q.enqueue(report('a'))
    await Promise.all([q.flush(), q.flush(), q.flush()])
    expect(calls).toBe(1)
  })

  it('corrupt storage starts clean instead of crashing', async () => {
    const store = memStore()
    store.data.set(QUEUE_KEY, '{not json')
    expect(await new CitizenQueue(store, async () => {}).count()).toBe(0)
  })
})
