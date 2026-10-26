/** The one queue instance the citizen app uses, wired to IndexedDB and the API. */
import { api } from '../api/client'
import { idbStore } from './idb'
import { CitizenQueue } from './queue'

export const citizenQueue = new CitizenQueue(idbStore, async (r) => {
  await api.createReport({
    client_uuid: r.client_uuid, issue_type: r.issue_type, lat: r.lat, lon: r.lon,
    description: r.description, phone: r.phone, language: r.language,
    photo_base64: r.photo_base64, voice_base64: r.voice_base64, signs: r.signs ?? [], channel: 'pwa-offline',
  })
})
