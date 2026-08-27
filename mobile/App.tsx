/**
 * BHOOSHAKTI Field — the officer's app.
 *
 * Offline-first by design. Verifications are written to AsyncStorage first and
 * pushed when a connection is available; the banner always shows how many are
 * waiting. Turning the network off mid-demo is a supported path, not a failure.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ActivityIndicator, Alert as RNAlert, Image, Platform, Pressable, ScrollView,
  StyleSheet, Text, TextInput, View,
} from 'react-native'
import { StatusBar } from 'expo-status-bar'
import AsyncStorage from '@react-native-async-storage/async-storage'
import * as Location from 'expo-location'
import * as ImagePicker from 'expo-image-picker'

import { api, setToken } from './src/api'
import { OfflineQueue, makeUuid, type QueuedReport } from './src/offline/queue'
import { C, SEVERITY_BG, SEVERITY_FG } from './src/theme'

const TOKEN_KEY = 'bhooshakti.field.token'
const USER_KEY = 'bhooshakti.field.user'
const VERDICTS = ['CONFIRMED', 'DENIED', 'UNCERTAIN'] as const

const queue = new OfflineQueue(AsyncStorage, api.pushBatch)

export default function App() {
  const [booting, setBooting] = useState(true)
  const [user, setUser] = useState<any>(null)
  const [zones, setZones] = useState<any[]>([])
  const [selected, setSelected] = useState<any>(null)
  const [pending, setPending] = useState(0)
  const [onlineOk, setOnlineOk] = useState<boolean | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [banner, setBanner] = useState<string>('')

  const refreshPending = useCallback(async () => setPending(await queue.count()), [])

  // ---- boot: restore session, load work, drain anything left over --------
  useEffect(() => {
    (async () => {
      try {
        const [t, u] = await Promise.all([AsyncStorage.getItem(TOKEN_KEY), AsyncStorage.getItem(USER_KEY)])
        if (t && u) { setToken(t); setUser(JSON.parse(u)) }
      } catch { /* first run */ }
      await refreshPending()
      setBooting(false)
    })()
  }, [refreshPending])

  const loadZones = useCallback(async () => {
    try {
      setZones(await api.assignments())
      setOnlineOk(true)
    } catch {
      setOnlineOk(false)
    }
  }, [])

  useEffect(() => { if (user) loadZones() }, [user, loadZones])

  // ---- connectivity poll: when the network returns, drain the queue -------
  const wasOffline = useRef(false)
  useEffect(() => {
    if (!user) return
    let live = true
    const tick = async () => {
      let reachable = false
      try { await api.health(); reachable = true } catch { reachable = false }
      if (!live) return
      setOnlineOk(reachable)
      if (reachable && wasOffline.current) {
        wasOffline.current = false
        await sync(true)
        loadZones()
      }
      if (!reachable) wasOffline.current = true
    }
    tick()
    const id = setInterval(tick, 6000)
    return () => { live = false; clearInterval(id) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user])

  async function sync(auto = false) {
    setSyncing(true)
    try {
      const r = await queue.flush()
      await refreshPending()
      if (r.synced > 0) setBanner(`Synced ${r.synced} report${r.synced === 1 ? '' : 's'}.`)
      else if (r.error) setBanner(auto ? '' : `Still offline — ${r.pending} report(s) held locally.`)
      else if (!auto) setBanner('Nothing to sync.')
    } finally {
      setSyncing(false)
      setTimeout(() => setBanner(''), 4000)
    }
  }

  if (booting) {
    return <View style={[s.fill, s.center]}><ActivityIndicator color={C.navy} /></View>
  }

  if (!user) {
    return <LoginScreen onSignedIn={async (token, u) => {
      setToken(token)
      await AsyncStorage.multiSet([[TOKEN_KEY, token], [USER_KEY, JSON.stringify(u)]])
      setUser(u)
    }} />
  }

  return (
    <View style={s.fill}>
      <StatusBar style="light" />
      <View style={s.header}>
        <View style={s.rowBetween}>
          <Text style={s.brand}>BHOOSHAKTI FIELD</Text>
          <View style={s.demoBadge}><Text style={s.demoBadgeText}>DEMO DATA</Text></View>
        </View>
        <Text style={s.brandSub}>{user.full_name || user.username} · {user.designation || user.role}</Text>
      </View>

      {/* The banner the demo turns on by switching the network off. */}
      <Pressable
        style={[s.syncBar, pending > 0 ? s.syncBarPending : onlineOk === false ? s.syncBarOffline : s.syncBarOk]}
        onPress={() => sync(false)}>
        <View style={[s.dot, { backgroundColor: onlineOk === false ? C.faint : C.navy }]} />
        <Text style={s.syncText}>
          {pending > 0
            ? `${pending} report${pending === 1 ? '' : 's'} pending sync`
            : onlineOk === false ? 'Offline — reports will be held on this device'
            : 'All reports synced'}
        </Text>
        {syncing
          ? <ActivityIndicator size="small" color={C.navy} />
          : <Text style={s.syncAction}>{pending > 0 ? 'SYNC NOW' : ''}</Text>}
      </Pressable>

      {banner ? <View style={s.banner}><Text style={s.bannerText}>{banner}</Text></View> : null}

      {selected
        ? <VerifyScreen
            zone={selected}
            onCancel={() => setSelected(null)}
            onQueued={async (report) => {
              await queue.enqueue(report)
              await refreshPending()
              setSelected(null)
              setBanner('Saved on this device. It will sync automatically.')
              setTimeout(() => setBanner(''), 4000)
              sync(true)
            }} />
        : <ZoneList zones={zones} onlineOk={onlineOk} onPick={setSelected} onRefresh={loadZones} />}
    </View>
  )
}

/* ------------------------------------------------------------------ login */

function LoginScreen({ onSignedIn }: { onSignedIn: (t: string, u: any) => void }) {
  const [username, setUsername] = useState('field.officer')
  const [password, setPassword] = useState('demo1234')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit() {
    setBusy(true); setError('')
    try {
      const r = await api.login(username.trim(), password)
      onSignedIn(r.access_token, r)
    } catch (e: any) {
      setError(e?.message ?? 'Sign-in failed')
    } finally { setBusy(false) }
  }

  return (
    <ScrollView style={s.fill} contentContainerStyle={{ padding: 0 }}>
      <StatusBar style="light" />
      <View style={[s.header, { paddingBottom: 26 }]}>
        <Text style={s.brand}>BHOOSHAKTI FIELD</Text>
        <Text style={s.brandSub}>Slope verification for district field officers</Text>
        <View style={[s.demoBadge, { alignSelf: 'flex-start', marginTop: 12 }]}>
          <Text style={s.demoBadgeText}>DEMO DATA</Text>
        </View>
      </View>

      <View style={{ padding: 18 }}>
        <View style={s.notice}>
          <Text style={s.noticeText}>
            Prototype — all data is simulated. Verifications you submit here reach the demo
            dashboard, not any real emergency service.
          </Text>
        </View>

        <Text style={s.label}>Username</Text>
        <TextInput style={s.input} value={username} onChangeText={setUsername}
                   autoCapitalize="none" autoCorrect={false} />
        <Text style={s.label}>Password</Text>
        <TextInput style={s.input} value={password} onChangeText={setPassword} secureTextEntry />

        {error ? <View style={s.notice}><Text style={s.noticeText}>{error}</Text></View> : null}

        <Pressable style={[s.btn, busy && s.btnDisabled]} onPress={submit} disabled={busy}>
          <Text style={s.btnText}>{busy ? 'Signing in…' : 'Sign in'}</Text>
        </Pressable>
        <Text style={s.hint}>Demo account: field.officer / demo1234</Text>
      </View>
    </ScrollView>
  )
}

/* ------------------------------------------------------------- zone list */

function ZoneList({ zones, onlineOk, onPick, onRefresh }: {
  zones: any[]; onlineOk: boolean | null; onPick: (z: any) => void; onRefresh: () => void
}) {
  return (
    <ScrollView style={s.fill} contentContainerStyle={{ padding: 14, paddingBottom: 40 }}>
      <View style={s.rowBetween}>
        <Text style={s.sectionTitle}>Assigned zones</Text>
        <Pressable onPress={onRefresh}><Text style={s.linkText}>Refresh</Text></Pressable>
      </View>
      <Text style={s.hint}>Worst first. Tap a zone to record what you can see on the slope.</Text>

      {zones.length === 0 && (
        <View style={s.card}>
          <Text style={s.cardBody}>
            {onlineOk === false
              ? 'Offline — assigned zones will load when a connection returns. You can still open a zone you have already seen and queue a report.'
              : 'No zones assigned to this account.'}
          </Text>
        </View>
      )}

      {zones.map((z) => (
        <Pressable key={z.zone_id} style={s.card} onPress={() => onPick(z)}>
          <View style={s.rowBetween}>
            <View style={[s.sev, { backgroundColor: SEVERITY_BG[z.severity] ?? SEVERITY_BG.LOW }]}>
              <Text style={[s.sevText, { color: SEVERITY_FG[z.severity] ?? C.navy }]}>{z.severity}</Text>
            </View>
            <Text style={s.mono}>{z.code}</Text>
          </View>
          <Text style={s.cardTitle}>{z.name}</Text>
          <Text style={s.cardMeta}>{z.district}, {z.state}</Text>
          {z.risk_score != null && (
            <Text style={s.cardMeta}>
              Risk {Math.round(z.risk_score)}/100 · confidence {Math.round((z.confidence ?? 0) * 100)}%
            </Text>
          )}
          {z.contributing_factors?.[0] && (
            <Text style={s.cardBody}>{z.contributing_factors[0].text}</Text>
          )}
        </Pressable>
      ))}
    </ScrollView>
  )
}

/* ------------------------------------------------------------ verify form */

function VerifyScreen({ zone, onCancel, onQueued }: {
  zone: any
  onCancel: () => void
  onQueued: (r: Omit<QueuedReport, 'attempts'>) => void
}) {
  const [verdict, setVerdict] = useState<typeof VERDICTS[number]>('CONFIRMED')
  const [notes, setNotes] = useState('')
  const [coords, setCoords] = useState<{ lat: number; lon: number } | null>(null)
  const [locating, setLocating] = useState(false)
  const [photo, setPhoto] = useState<string | null>(null)

  // Auto geo-tag on open; fall back to the zone centroid if permission is denied.
  useEffect(() => {
    (async () => {
      setLocating(true)
      try {
        const { status } = await Location.requestForegroundPermissionsAsync()
        if (status === 'granted') {
          const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced })
          setCoords({ lat: pos.coords.latitude, lon: pos.coords.longitude })
        } else if (zone.centroid) {
          setCoords({ lat: zone.centroid[0], lon: zone.centroid[1] })
        }
      } catch {
        if (zone.centroid) setCoords({ lat: zone.centroid[0], lon: zone.centroid[1] })
      } finally { setLocating(false) }
    })()
  }, [zone])

  async function attachPhoto() {
    try {
      const perm = await ImagePicker.requestCameraPermissionsAsync()
      const picker = perm.granted
        ? ImagePicker.launchCameraAsync
        : ImagePicker.launchImageLibraryAsync
      const r = await picker({ quality: 0.5, base64: true, mediaTypes: ImagePicker.MediaTypeOptions.Images })
      if (!r.canceled && r.assets?.[0]?.base64) {
        setPhoto(`data:image/jpeg;base64,${r.assets[0].base64}`)
      }
    } catch {
      RNAlert.alert('Camera unavailable', 'Attach a photo from the library instead, or submit without one.')
    }
  }

  function submit() {
    onQueued({
      client_uuid: makeUuid(),
      zone_id: zone.zone_id,
      verdict,
      notes: notes.trim(),
      lat: coords?.lat ?? null,
      lon: coords?.lon ?? null,
      observed_at: new Date().toISOString(),
      submitted_offline: true,
      photo_base64: photo,
    })
  }

  return (
    <ScrollView style={s.fill} contentContainerStyle={{ padding: 14, paddingBottom: 44 }}>
      <Pressable onPress={onCancel}><Text style={s.linkText}>‹ Back to zones</Text></Pressable>

      <Text style={s.sectionTitle}>{zone.name}</Text>
      <Text style={s.hint}>{zone.code} · {zone.district}, {zone.state}</Text>

      <Text style={s.label}>What did you find on the slope?</Text>
      {VERDICTS.map((v) => (
        <Pressable key={v} style={[s.choice, verdict === v && s.choiceOn]} onPress={() => setVerdict(v)}>
          <View style={[s.radio, verdict === v && s.radioOn]} />
          <Text style={s.choiceText}>
            {v === 'CONFIRMED' ? 'Confirmed — active slope movement'
              : v === 'DENIED' ? 'Denied — no movement visible'
              : 'Uncertain — needs a second look'}
          </Text>
        </Pressable>
      ))}

      <Text style={s.label}>Notes</Text>
      <TextInput style={[s.input, { height: 110, textAlignVertical: 'top' }]} multiline
                 placeholder="Cracks, displacement, seepage, who is at risk…"
                 placeholderTextColor={C.faint}
                 value={notes} onChangeText={setNotes} />

      <Text style={s.label}>Photograph</Text>
      <Pressable style={[s.btn, s.btnGhost]} onPress={attachPhoto}>
        <Text style={[s.btnText, s.btnGhostText]}>{photo ? 'Replace photo' : 'Take / attach photo'}</Text>
      </Pressable>
      {photo && <Image source={{ uri: photo }} style={s.preview} resizeMode="cover" />}

      <Text style={s.label}>Location</Text>
      <View style={s.notice}>
        <Text style={s.noticeText}>
          {locating ? 'Reading GPS…'
            : coords ? `Auto geo-tagged: ${coords.lat.toFixed(5)}, ${coords.lon.toFixed(5)}`
            : 'No location available — the report will be tied to the zone only.'}
        </Text>
      </View>

      <Pressable style={s.btn} onPress={submit}>
        <Text style={s.btnText}>Submit verification</Text>
      </Pressable>
      <Text style={s.hint}>
        Saved to this device immediately. If you are offline it stays queued and syncs by itself
        when a connection returns — you can close the app in between.
      </Text>
    </ScrollView>
  )
}

/* ---------------------------------------------------------------- styles */

const s = StyleSheet.create({
  fill: { flex: 1, backgroundColor: C.panel },
  center: { alignItems: 'center', justifyContent: 'center' },
  rowBetween: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },

  header: { backgroundColor: C.navy, paddingTop: Platform.OS === 'web' ? 18 : 52, paddingBottom: 14, paddingHorizontal: 16 },
  brand: { color: C.white, fontSize: 15, fontWeight: '700', letterSpacing: 2 },
  brandSub: { color: '#A8BCD1', fontSize: 12, marginTop: 4 },
  demoBadge: { borderWidth: 1, borderColor: 'rgba(255,255,255,.45)', paddingHorizontal: 8, paddingVertical: 3 },
  demoBadgeText: { color: C.white, fontSize: 9, fontWeight: '700', letterSpacing: 1.6 },

  syncBar: { flexDirection: 'row', alignItems: 'center', gap: 9, paddingHorizontal: 16, paddingVertical: 11, borderBottomWidth: 1, borderBottomColor: C.line },
  syncBarOk: { backgroundColor: C.white },
  syncBarPending: { backgroundColor: C.panelDeep },
  syncBarOffline: { backgroundColor: C.panelDeep },
  syncText: { flex: 1, fontSize: 13, color: C.text, fontWeight: '600' },
  syncAction: { fontSize: 11, letterSpacing: 1, color: C.navy, fontWeight: '700' },
  dot: { width: 8, height: 8, borderRadius: 4 },

  banner: { backgroundColor: C.navy, paddingHorizontal: 16, paddingVertical: 9 },
  bannerText: { color: C.white, fontSize: 12.5 },

  sectionTitle: { fontSize: 17, fontWeight: '700', color: C.navy, marginTop: 10 },
  hint: { fontSize: 12, color: C.muted, marginTop: 5, lineHeight: 17 },
  label: { fontSize: 10.5, letterSpacing: 1, textTransform: 'uppercase', color: C.muted, fontWeight: '700', marginTop: 18, marginBottom: 6 },
  linkText: { color: C.navy, fontWeight: '600', fontSize: 13 },
  mono: { fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace', fontSize: 11, color: C.muted },

  card: { backgroundColor: C.white, borderWidth: 1, borderColor: C.line, padding: 13, marginTop: 10 },
  cardTitle: { fontSize: 15, fontWeight: '700', color: C.navy, marginTop: 8 },
  cardMeta: { fontSize: 12, color: C.muted, marginTop: 3 },
  cardBody: { fontSize: 12.5, color: C.text, marginTop: 7, lineHeight: 18 },

  sev: { paddingHorizontal: 8, paddingVertical: 3 },
  sevText: { fontSize: 10, fontWeight: '700', letterSpacing: 1.2 },

  input: { backgroundColor: C.white, borderWidth: 1, borderColor: C.lineStrong, paddingHorizontal: 11, paddingVertical: 10, fontSize: 14, color: C.text },

  choice: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: C.white, borderWidth: 1, borderColor: C.line, padding: 12, marginBottom: 8 },
  choiceOn: { borderColor: C.navy },
  choiceText: { fontSize: 13.5, color: C.text, flex: 1 },
  radio: { width: 16, height: 16, borderRadius: 8, borderWidth: 2, borderColor: C.lineStrong },
  radioOn: { borderColor: C.navy, backgroundColor: C.navy },

  btn: { backgroundColor: C.navy, paddingVertical: 13, alignItems: 'center', marginTop: 16 },
  btnDisabled: { opacity: 0.5 },
  btnText: { color: C.white, fontSize: 14, fontWeight: '700' },
  btnGhost: { backgroundColor: C.white, borderWidth: 1, borderColor: C.navy, marginTop: 0 },
  btnGhostText: { color: C.navy },

  preview: { width: '100%', height: 190, marginTop: 10, borderWidth: 1, borderColor: C.line },

  notice: { backgroundColor: C.panelDeep, borderLeftWidth: 3, borderLeftColor: C.navy, padding: 11, marginTop: 10 },
  noticeText: { fontSize: 12.5, color: C.text, lineHeight: 18 },
})
