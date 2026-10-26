/** Minimal IndexedDB key-value store. Falls back to memory when IndexedDB is
 *  blocked (private mode on some browsers) so the queue still works for the
 *  life of the page. */
import type { KeyValueStore } from './queue'

const DB = 'bhooshakti', STORE = 'kv'

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1)
    req.onupgradeneeded = () => req.result.createObjectStore(STORE)
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

function tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return open().then((db) => new Promise<T>((resolve, reject) => {
    const t = db.transaction(STORE, mode)
    const req = fn(t.objectStore(STORE))
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
    t.oncomplete = () => db.close()
  }))
}

const memory = new Map<string, string>()

export const idbStore: KeyValueStore = {
  async getItem(key) {
    try { return (await tx<string | undefined>('readonly', (s) => s.get(key))) ?? null }
    catch { return memory.get(key) ?? null }
  },
  async setItem(key, value) {
    try { await tx('readwrite', (s) => s.put(value, key)) }
    catch { memory.set(key, value) }
  },
}
