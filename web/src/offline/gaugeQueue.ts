/** Village-volunteer gauge readings written with no network: kept in IndexedDB
 *  and sent on reconnect, like reports (citizenQueue). A reading the server
 *  refuses outright (number not registered) is dropped, not retried forever. */
import { ApiError, api } from '../api/client'
import { idbStore } from './idb'

const KEY = 'bhooshakti.gauge.queue'
export interface QueuedReading { client_uuid: string; phone: string; mm: number; read_at: string }

async function all(): Promise<QueuedReading[]> {
  try { return JSON.parse((await idbStore.getItem(KEY)) ?? '[]') } catch { return [] }
}
async function save(items: QueuedReading[]) { await idbStore.setItem(KEY, JSON.stringify(items)) }

export const gaugeQueue = {
  count: async () => (await all()).length,
  async enqueue(r: QueuedReading) { await save([...(await all()).filter((x) => x.client_uuid !== r.client_uuid), r]) },
  async flush(): Promise<number> {
    let sent = 0
    for (const r of await all()) {
      try {
        await api.volunteerReading({ ...r, channel: 'app-offline' })
      } catch (err) {
        if (!(err instanceof ApiError && err.status >= 400 && err.status < 500)) break   // network: try later
      }
      sent++
      await save((await all()).filter((x) => x.client_uuid !== r.client_uuid))
    }
    return sent
  },
}
