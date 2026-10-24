/**
 * 3D terrain map: MapLibre GL JS on OpenFreeMap vector tiles (free, no key —
 * roads and labels stay crisp when tilted), AWS Terrain Tiles (terrarium DEM)
 * for elevation and hillshade, sky and fog at the horizon, zones draped on the
 * terrain in severity colours, and deck.gl on top for the 3D data layers —
 * extruded rainfall columns, glowing sensor pins and report ripples.
 *
 * Our own layers are spliced into the vector style just below its labels, so
 * place names stay readable over the zones. Satellite imagery (Esri) slots in
 * at the same point. If the vector style cannot be fetched (venue Wi-Fi), the
 * map falls back to OpenStreetMap raster tiles rather than a blank canvas.
 *
 * Only ever imported from the control room and the replay page, so the
 * citizen bundle never pays for it. The 2D fallback is components/MapView.tsx.
 */
import { useEffect, useRef } from 'react'
import maplibregl, { type Map as MLMap } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { MapboxOverlay } from '@deck.gl/mapbox'
import { ColumnLayer, ScatterplotLayer } from '@deck.gl/layers'
import { prefersReducedMotion } from '../hooks'
import { SEVERITY_FILL, asSeverity } from './Severity'

export interface Column { lon: number; lat: number; value: number; color?: [number, number, number, number?]; label?: string }
export interface Pin { lon: number; lat: number; live?: boolean; failed?: boolean; label?: string; source?: string }
export interface Pulse { lon: number; lat: number; at: number; big?: boolean; color?: [number, number, number] }
export interface View { lon: number; lat: number; zoom?: number }

interface Props {
  zones?: any
  roads?: any
  villages?: any
  columns?: Column[]
  pins?: Pin[]
  pulses?: Pulse[]
  selectedZoneId?: number | null
  onSelectZone?: (id: number) => void
  flyTo?: { lat: number; lon: number; zoom?: number } | null
  orbit?: { lat: number; lon: number; zoom?: number } | null
  dark?: boolean
  terrain?: boolean
  /** 'map' (OpenFreeMap vector) or 'satellite' (Esri World Imagery) */
  basemap?: 'map' | 'satellite'
  /** metres of column height per unit of `value` (mm of rain) */
  columnScale?: number
  columnRadius?: number
  center?: [number, number]
  zoom?: number
  /** Turn slowly after 20 s without input; any touch stops it. */
  idleRotate?: boolean
  /** Fly over these points once (bump `id` to start) so their tiles are cached. */
  tour?: { id: number; stops: View[]; onDone?: () => void } | null
}

const STYLE_URL = {
  light: 'https://tiles.openfreemap.org/styles/liberty',
  dark: 'https://tiles.openfreemap.org/styles/dark',
}
const DEM_TILES = ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png']
const SAT_TILES = ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}']
const OSM_TILES = ['https://tile.openstreetmap.org/{z}/{x}/{y}.png']
const TERRAIN_ATTRIB = 'Terrain: <a href="https://registry.opendata.aws/terrain-tiles/">AWS Terrain Tiles</a> (Mapzen)'
const SAT_ATTRIB = 'Imagery © Esri, Maxar, Earthstar Geographics'
const OSM_ATTRIB = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
// SRTM is ~30 m. 1.6x makes the ridges read as ridges on a laptop screen
// without turning the Khasi hills into the Alps.
const EXAGGERATION = 1.6
// The control room opens tilted over the hilliest demo district: the
// Darjeeling–Sikkim ridges, where the scripted storm lands.
const HOME = { center: [88.42, 27.12] as [number, number], zoom: 9.3, pitch: 60, bearing: -20 }
const IDLE_MS = 20000
const EMPTY = { type: 'FeatureCollection', features: [] as any[] }
const RISKY = ['in', ['get', 'severity'], ['literal', ['HIGH', 'CRITICAL']]]

const styleCache = new Map<string, Promise<any>>()
function fetchStyle(url: string): Promise<any> {
  if (!styleCache.has(url)) {
    styleCache.set(url, fetch(url).then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.json() })
      .catch((e) => { styleCache.delete(url); throw e }))
  }
  return styleCache.get(url)!
}

/** Offline-ish fallback: raster OSM, no glyphs needed (our layers have no labels). */
function fallbackStyle(): any {
  return {
    version: 8,
    sources: { osm: { type: 'raster', tiles: OSM_TILES, tileSize: 256, attribution: OSM_ATTRIB, maxzoom: 19 } },
    layers: [{ id: 'osm', type: 'raster', source: 'osm', paint: { 'raster-saturation': -0.35 } }],
  }
}

function sky(dark: boolean): any {
  return dark
    ? { 'sky-color': '#0E1512', 'horizon-color': '#1F2A24', 'fog-color': '#141815', 'sky-horizon-blend': 0.6, 'horizon-fog-blend': 0.7, 'fog-ground-blend': 0.35, 'atmosphere-blend': 0.4 }
    : { 'sky-color': '#BFD3DE', 'horizon-color': '#EDEBE4', 'fog-color': '#F4F1EA', 'sky-horizon-blend': 0.55, 'horizon-fog-blend': 0.75, 'fog-ground-blend': 0.3, 'atmosphere-blend': 0.6 }
}

function ourSources(): Record<string, any> {
  return {
    sat: { type: 'raster', tiles: SAT_TILES, tileSize: 256, attribution: SAT_ATTRIB, maxzoom: 18 },
    // Two DEM sources: MapLibre recommends not sharing one between terrain and hillshade.
    dem: { type: 'raster-dem', tiles: DEM_TILES, tileSize: 256, encoding: 'terrarium', maxzoom: 15, attribution: TERRAIN_ATTRIB },
    'dem-hs': { type: 'raster-dem', tiles: DEM_TILES, tileSize: 256, encoding: 'terrarium', maxzoom: 15 },
    zones: { type: 'geojson', data: EMPTY },
    roads: { type: 'geojson', data: EMPTY },
    villages: { type: 'geojson', data: EMPTY },
  }
}

function ourLayers(satellite: boolean, dark: boolean): any[] {
  return [
    { id: 'sat', type: 'raster', source: 'sat', layout: { visibility: satellite ? 'visible' : 'none' },
      paint: dark ? { 'raster-saturation': -0.2, 'raster-brightness-max': 0.75 } : { 'raster-saturation': 0.05 } },
    { id: 'hillshade', type: 'hillshade', source: 'dem-hs',
      paint: { 'hillshade-exaggeration': satellite ? 0.18 : 0.5, 'hillshade-shadow-color': dark ? '#000000' : '#33403A',
               'hillshade-highlight-color': dark ? '#3A463E' : '#FFFFFF', 'hillshade-accent-color': dark ? '#000000' : '#5A6B5E' } },
    // LOW zones sit back; the eye goes to danger.
    { id: 'zone-fill', type: 'fill', source: 'zones',
      paint: { 'fill-color': ['to-color', ['get', 'color']],
               'fill-opacity': ['match', ['get', 'severity'], 'LOW', 0.2, 'MODERATE', 0.4, 0.58] } },
    // Soft glow: a wide, blurred line under the outline of HIGH/CRITICAL zones.
    { id: 'zone-glow', type: 'line', source: 'zones', filter: RISKY,
      paint: { 'line-color': ['to-color', ['get', 'color']], 'line-width': 14, 'line-blur': 10, 'line-opacity': 0.5 } },
    { id: 'zone-line', type: 'line', source: 'zones',
      paint: { 'line-color': ['case', ['boolean', ['get', 'selected'], false], dark ? '#FFFFFF' : '#1F2A33',
                              RISKY, ['to-color', ['get', 'color']], dark ? 'rgba(236,232,223,.35)' : 'rgba(40,52,60,.45)'],
               'line-width': ['case', ['boolean', ['get', 'selected'], false], 3.5, RISKY, 2.2, 1] } },
    { id: 'roads', type: 'line', source: 'roads',
      paint: { 'line-color': ['case', ['==', ['get', 'status'], 'BLOCKED'], '#DC2626', ['==', ['get', 'status'], 'RESTRICTED'], '#F97316', dark ? '#9DA196' : '#5B6670'],
               'line-width': ['case', ['==', ['get', 'status'], 'BLOCKED'], 4.5, ['==', ['get', 'criticality'], 'lifeline'], 2.6, 1.8],
               'line-opacity': 0.9 } },
    { id: 'roads-blocked', type: 'line', source: 'roads', filter: ['==', ['get', 'status'], 'BLOCKED'],
      paint: { 'line-color': '#ffffff', 'line-width': 1.5, 'line-dasharray': [2, 2] } },
    { id: 'villages', type: 'circle', source: 'villages',
      paint: { 'circle-radius': ['case', ['boolean', ['get', 'is_cut_off'], false], 7, 4],
               'circle-color': ['case', ['boolean', ['get', 'is_cut_off'], false], '#DC2626', '#ffffff'],
               'circle-stroke-color': '#3E4C59', 'circle-stroke-width': 1.2 } },
  ]
}

/** The base style with our sources added and our layers spliced in under its labels. */
function compose(base: any, satellite: boolean, dark: boolean): any {
  const layers: any[] = base.layers ?? []
  let cut = layers.length
  while (cut > 0 && layers[cut - 1].type === 'symbol') cut--
  return {
    ...base,
    sources: { ...base.sources, ...ourSources() },
    layers: [...layers.slice(0, cut), ...ourLayers(satellite, dark), ...layers.slice(cut)],
    sky: sky(dark),
  }
}

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

export default function Map3D(p: Props) {
  const host = useRef<HTMLDivElement | null>(null)
  const map = useRef<MLMap | null>(null)
  const overlay = useRef<MapboxOverlay | null>(null)
  const ready = useRef(false)
  const props = useRef(p)
  props.current = p
  const select = useRef(p.onSelectZone)
  select.current = p.onSelectZone
  const prevColors = useRef<Record<number, string>>({})
  const raf = useRef(0)
  const orbitBearing = useRef(-20)
  const lastPulseRender = useRef(0)
  const lastInput = useRef(performance.now())
  const touring = useRef(false)
  const styleSeq = useRef(0)

  // ----------------------------------------------------------------- style
  async function loadStyle() {
    const m = map.current
    if (!m) return
    const seq = ++styleSeq.current
    const { dark, basemap } = props.current
    let style: any
    try { style = compose(await fetchStyle(dark ? STYLE_URL.dark : STYLE_URL.light), basemap === 'satellite', !!dark) }
    catch { style = compose(fallbackStyle(), basemap === 'satellite', !!dark) }
    if (seq !== styleSeq.current || !map.current) return
    ready.current = false
    m.setStyle(style, { diff: false })
  }

  // ----------------------------------------------------------------- init
  useEffect(() => {
    if (!host.current || map.current) return
    const home = p.center ? { center: p.center, zoom: p.zoom ?? 9, pitch: p.orbit ? 62 : 55, bearing: -18 } : HOME
    const m = new maplibregl.Map({
      container: host.current,
      ...home,
      maxPitch: 78,
      attributionControl: false,
      style: { version: 8, sources: {}, layers: [{ id: 'bg', type: 'background', paint: { 'background-color': p.dark ? '#141815' : '#EAE6DD' } }] },
    })
    m.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')
    m.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right')
    const ov = new MapboxOverlay({
      interleaved: false,
      layers: [],
      getTooltip: ({ object }: any) => object?.label ? { text: object.label } : null,
    })
    m.addControl(ov as any)
    overlay.current = ov
    map.current = m

    m.on('style.load', () => {
      if (!m.getSource('zones')) return          // the placeholder style
      ready.current = true
      if (props.current.terrain !== false) m.setTerrain({ source: 'dem', exaggeration: EXAGGERATION })
      prevColors.current = {}
      syncAll()
    })
    m.on('click', 'zone-fill', (e) => {
      const f = e.features?.[0]
      if (f && select.current) select.current(Number(f.properties?.id))
    })
    m.on('mouseenter', 'zone-fill', () => { m.getCanvas().style.cursor = 'pointer' })
    m.on('mouseleave', 'zone-fill', () => { m.getCanvas().style.cursor = '' })
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 })
    m.on('mousemove', 'zone-fill', (e) => {
      const q = e.features?.[0]?.properties
      if (!q) return
      popup.setLngLat(e.lngLat).setHTML(
        `<strong>${q.code} — ${q.name}</strong><br>${q.severity}${q.risk_score != null ? ` · ${Number(q.risk_score).toFixed(0)}/100` : ''}`
      ).addTo(m)
    })
    m.on('mouseleave', 'zone-fill', () => popup.remove())

    // Any real input stops the idle rotation and restarts the 20 s clock.
    const touched = () => { lastInput.current = performance.now() }
    const el = host.current
    for (const ev of ['pointerdown', 'wheel', 'keydown', 'touchstart'] as const) el.addEventListener(ev, touched, { passive: true })

    loadStyle()
    startLoop()

    const ro = new ResizeObserver(() => m.resize())
    ro.observe(el)
    return () => {
      cancelAnimationFrame(raf.current)
      ro.disconnect()
      for (const ev of ['pointerdown', 'wheel', 'keydown', 'touchstart'] as const) el.removeEventListener(ev, touched)
      m.remove()
      map.current = null
      ready.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ------------------------------------------------------------- data sync
  function zonesWithColor(): any {
    const z = props.current.zones
    if (!z?.features) return EMPTY
    return {
      type: 'FeatureCollection',
      features: z.features.map((f: any) => {
        const sev = asSeverity(f.properties.severity)
        const color = SEVERITY_FILL[sev]
        return {
          ...f,
          properties: {
            ...f.properties, severity: sev, color,
            prevColor: prevColors.current[f.properties.id] ?? color,
            selected: f.properties.id === props.current.selectedZoneId,
          },
        }
      }),
    }
  }

  function animateZoneColours(fc: any) {
    const m = map.current
    if (!m || prefersReducedMotion()) return
    const changed = fc.features.some((f: any) => f.properties.prevColor !== f.properties.color)
    if (!changed) return
    const t0 = performance.now(), ms = 900
    const step = () => {
      const k = Math.min(1, (performance.now() - t0) / ms)
      const e = 1 - Math.pow(1 - k, 3)
      try {
        m.setPaintProperty('zone-fill', 'fill-color',
          ['interpolate', ['linear'], e, 0, ['to-color', ['get', 'prevColor']], 1, ['to-color', ['get', 'color']]] as any)
      } catch { /* style not ready */ }
      if (k < 1) requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  }

  function syncZones() {
    const m = map.current
    if (!m || !ready.current) return
    const fc = zonesWithColor()
    ;(m.getSource('zones') as any)?.setData(fc)
    animateZoneColours(fc)
    for (const f of fc.features) prevColors.current[f.properties.id] = f.properties.color
  }

  function deckLayers(now: number) {
    const { columns = [], pins = [], pulses = [], columnScale = 60, columnRadius = 1800 } = props.current
    const m = map.current
    const elev = (lon: number, lat: number) => {
      try { return (m?.queryTerrainElevation([lon, lat]) ?? 0) || 0 } catch { return 0 }
    }
    const layers: any[] = []
    if (columns.length) {
      layers.push(new ColumnLayer({
        id: 'rain-columns', data: columns, diskResolution: 14, radius: columnRadius, extruded: true,
        elevationScale: columnScale, pickable: true,
        getPosition: (d: Column) => [d.lon, d.lat, elev(d.lon, d.lat)],
        getElevation: (d: Column) => Math.max(0.05, d.value),
        getFillColor: (d: Column) => (d.color as any) ?? [14, 165, 233, 190],
        getLineColor: [255, 255, 255, 80], lineWidthMinPixels: 1,
        transitions: { getElevation: 500 },
        updateTriggers: { getPosition: [props.current.terrain] },
      }))
    }
    if (pins.length) {
      const color = (d: Pin): [number, number, number, number] =>
        d.failed ? [120, 128, 124, 200] : d.live ? [34, 197, 94, 255] : d.source === 'hardware' ? [250, 204, 21, 255] : [47, 107, 58, 255]
      const pos = (d: Pin): [number, number, number] => [d.lon, d.lat, elev(d.lon, d.lat) + 30]
      layers.push(new ScatterplotLayer({
        id: 'pins-glow', data: pins, radiusUnits: 'pixels', getRadius: (d: Pin) => (d.live ? 16 + 4 * Math.sin(now / 250) : 11),
        getPosition: pos, getFillColor: (d: Pin) => [...color(d).slice(0, 3), 70] as any, stroked: false,
        updateTriggers: { getRadius: [Math.round(now / 60)] },
      }))
      layers.push(new ScatterplotLayer({
        id: 'pins', data: pins, radiusUnits: 'pixels', getRadius: 5.5, pickable: true,
        getPosition: pos, getFillColor: color as any, stroked: true, getLineColor: [255, 255, 255, 230], lineWidthMinPixels: 1.5,
      }))
    }
    // A new report ripples out once; the replay's landslide moment keeps pulsing.
    const life = (q: Pulse) => (q.big ? 20000 : 2200)
    const live = pulses.filter((q) => now - q.at < life(q))
    if (live.length) {
      const ring = (q: Pulse) => {
        const period = q.big ? 2600 : 2200
        const k = ((now - q.at) % period) / period
        return { r: k * (q.big ? 9000 : 3200), a: 1 - k }
      }
      layers.push(new ScatterplotLayer({
        id: 'pulses', data: live, radiusUnits: 'meters', stroked: true, filled: true,
        getPosition: (q: Pulse) => [q.lon, q.lat, elev(q.lon, q.lat) + 20],
        getRadius: (q: Pulse) => ring(q).r,
        getFillColor: (q: Pulse) => [...(q.color ?? [220, 38, 38]), Math.round(40 * ring(q).a)] as any,
        getLineColor: (q: Pulse) => [...(q.color ?? [220, 38, 38]), Math.round(230 * ring(q).a)] as any,
        lineWidthMinPixels: 2,
        updateTriggers: { getRadius: now, getFillColor: now, getLineColor: now },
      }))
    }
    // The dot stays for 20 s after the ring has gone, so the place is findable.
    const dots = pulses.filter((q) => now - q.at < 20000)
    if (dots.length) {
      layers.push(new ScatterplotLayer({
        id: 'pulse-dots', data: dots, radiusUnits: 'pixels', getRadius: (q: Pulse) => (q.big ? 9 : 6),
        getPosition: (q: Pulse) => [q.lon, q.lat, elev(q.lon, q.lat) + 20],
        getFillColor: (q: Pulse) => [...(q.color ?? [220, 38, 38]), 255] as any, stroked: true, getLineColor: [255, 255, 255, 255], lineWidthMinPixels: 2,
      }))
    }
    return layers
  }

  function syncDeck(now = performance.now()) {
    overlay.current?.setProps({ layers: deckLayers(now) })
  }

  function syncAll() {
    const m = map.current
    if (!m || !ready.current) return
    syncZones()
    ;(m.getSource('roads') as any)?.setData(props.current.roads ?? EMPTY)
    ;(m.getSource('villages') as any)?.setData(props.current.villages ?? EMPTY)
    syncDeck()
  }

  // Animation loop: glow breathing on at-risk zones, live pins, ripples,
  // the replay orbit, and the control room's idle rotation.
  function startLoop() {
    cancelAnimationFrame(raf.current)
    const reduced = prefersReducedMotion()
    const tick = () => {
      const m = map.current
      if (!m) return
      const now = performance.now()
      const { pulses = [], pins = [], orbit, idleRotate } = props.current
      const hasPulse = pulses.some((q) => now - q.at < 20000)
      const hasLive = pins.some((q) => q.live)
      if (!reduced && ready.current) {
        try { m.setPaintProperty('zone-glow', 'line-opacity', 0.3 + 0.3 * (0.5 + 0.5 * Math.sin(now / 520))) } catch { /* not ready */ }
        if (orbit) {
          orbitBearing.current = (orbitBearing.current + 0.05) % 360
          m.setBearing(orbitBearing.current)
        } else if (idleRotate && !touring.current && now - lastInput.current > IDLE_MS && !m.isMoving()) {
          m.setBearing((m.getBearing() + 0.03) % 360)
        }
      }
      if ((hasPulse || hasLive) && now - lastPulseRender.current > 40) {
        lastPulseRender.current = now
        syncDeck(now)
      }
      raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
  }

  useEffect(() => { syncZones() }, [p.zones, p.selectedZoneId])            // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (ready.current) (map.current?.getSource('roads') as any)?.setData(p.roads ?? EMPTY) }, [p.roads])
  useEffect(() => { if (ready.current) (map.current?.getSource('villages') as any)?.setData(p.villages ?? EMPTY) }, [p.villages])
  useEffect(() => { if (ready.current) syncDeck() }, [p.columns, p.pins, p.pulses, p.columnScale])  // eslint-disable-line react-hooks/exhaustive-deps

  // Dark mode swaps the whole vector style (labels, water, land colours).
  const firstDark = useRef(true)
  useEffect(() => {
    if (firstDark.current) { firstDark.current = false; return }
    loadStyle()
  }, [p.dark])                                                             // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const m = map.current
    if (!m || !ready.current) return
    const sat = p.basemap === 'satellite'
    try {
      m.setLayoutProperty('sat', 'visibility', sat ? 'visible' : 'none')
      // Hillshade on top of imagery double-shades the slopes; keep it light.
      m.setPaintProperty('hillshade', 'hillshade-exaggeration', sat ? 0.18 : 0.5)
    } catch { /* style not ready */ }
  }, [p.basemap])

  useEffect(() => {
    const m = map.current
    if (!m || !ready.current) return
    m.setTerrain(p.terrain === false ? null : { source: 'dem', exaggeration: EXAGGERATION })
  }, [p.terrain])

  useEffect(() => {
    const m = map.current
    if (!m || !p.flyTo) return
    lastInput.current = performance.now()
    m.flyTo({ center: [p.flyTo.lon, p.flyTo.lat], zoom: p.flyTo.zoom ?? 11, pitch: 62, bearing: -25,
              duration: prefersReducedMotion() ? 0 : 1800, essential: true })
  }, [p.flyTo])

  useEffect(() => {
    const m = map.current
    if (!m || !p.orbit) return
    m.jumpTo({ center: [p.orbit.lon, p.orbit.lat], zoom: p.orbit.zoom ?? 11.8, pitch: 64, bearing: orbitBearing.current })
  }, [p.orbit?.lat, p.orbit?.lon])  // eslint-disable-line react-hooks/exhaustive-deps

  // Warm the tile cache: visit each stop, wait for its tiles, come home.
  useEffect(() => {
    const m = map.current
    const tour = p.tour
    if (!m || !tour?.stops.length) return
    let cancelled = false
    touring.current = true
    const settle = () => new Promise<void>((res) => {
      const t = window.setTimeout(res, 9000)
      m.once('idle', () => { window.clearTimeout(t); res() })
    })
    ;(async () => {
      for (const s of tour.stops) {
        if (cancelled) return
        m.flyTo({ center: [s.lon, s.lat], zoom: s.zoom ?? 11, pitch: 60, bearing: -20, duration: 2200, essential: true })
        await new Promise((r) => window.setTimeout(r, 2300))
        await settle()
      }
      if (cancelled) return
      m.flyTo({ ...HOME, duration: 2200, essential: true })
      touring.current = false
      lastInput.current = performance.now()
      tour.onDone?.()
    })()
    return () => { cancelled = true; touring.current = false }
  }, [p.tour?.id])  // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={host} className="map-host" />
}

export const rgb = hexToRgb
