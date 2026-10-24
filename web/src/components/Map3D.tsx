/**
 * 3D terrain map: MapLibre GL JS (free, no key) + AWS Terrain Tiles
 * (terrarium DEM) for elevation and hillshade, zones draped on the terrain in
 * severity colours, and deck.gl on top for the 3D data layers — extruded
 * rainfall columns, glowing sensor pins and expanding report ripples.
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
  /** metres of column height per unit of `value` (mm of rain) */
  columnScale?: number
  columnRadius?: number
  center?: [number, number]
  zoom?: number
}

const DEM_TILES = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'
// OpenStreetMap raster tiles: free, no key. Dark mode is a raster treatment
// of the same tiles, so there is one tile cache and no second provider.
const BASE_TILES = ['https://tile.openstreetmap.org/{z}/{x}/{y}.png']
const ATTRIB = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors · Terrain: <a href="https://registry.opendata.aws/terrain-tiles/">AWS Terrain Tiles</a> (Mapzen)'
const EMPTY = { type: 'FeatureCollection', features: [] as any[] }

function basePaint(dark: boolean): any {
  return dark
    ? { 'raster-saturation': -0.85, 'raster-brightness-min': 0.05, 'raster-brightness-max': 0.38, 'raster-contrast': 0.15, 'raster-opacity': 1 }
    : { 'raster-saturation': -0.35, 'raster-brightness-max': 0.96, 'raster-opacity': 1 }
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

  // ----------------------------------------------------------------- init
  useEffect(() => {
    if (!host.current || map.current) return
    const m = new maplibregl.Map({
      container: host.current,
      center: p.center ?? [91.8, 26.2],
      zoom: p.zoom ?? 6.6,
      pitch: p.orbit ? 62 : 52,
      bearing: -18,
      maxPitch: 75,
      attributionControl: false,
      style: {
        version: 8,
        sources: {
          base: { type: 'raster', tiles: BASE_TILES, tileSize: 256, attribution: ATTRIB, maxzoom: 19 },
          dem: { type: 'raster-dem', tiles: [DEM_TILES], tileSize: 256, encoding: 'terrarium', maxzoom: 15 },
          zones: { type: 'geojson', data: EMPTY as any },
          roads: { type: 'geojson', data: EMPTY as any },
          villages: { type: 'geojson', data: EMPTY as any },
        },
        layers: [
          { id: 'base', type: 'raster', source: 'base', paint: basePaint(!!p.dark) },
          { id: 'hillshade', type: 'hillshade', source: 'dem',
            paint: { 'hillshade-exaggeration': 0.42, 'hillshade-shadow-color': '#2f3b36', 'hillshade-highlight-color': '#ffffff' } },
          { id: 'zone-fill', type: 'fill', source: 'zones',
            paint: { 'fill-color': ['to-color', ['get', 'color']],
                     'fill-opacity': ['case', ['==', ['get', 'severity'], 'LOW'], 0.55, 0.72] } },
          { id: 'zone-glow', type: 'fill', source: 'zones',
            filter: ['in', ['get', 'severity'], ['literal', ['HIGH', 'CRITICAL']]],
            paint: { 'fill-color': ['to-color', ['get', 'color']], 'fill-opacity': 0.0 } },
          { id: 'zone-line', type: 'line', source: 'zones',
            paint: { 'line-color': ['case', ['boolean', ['get', 'selected'], false], '#0F766E', 'rgba(20,40,36,.75)'],
                     'line-width': ['case', ['boolean', ['get', 'selected'], false], 3.5, 1.6] } },
          { id: 'roads', type: 'line', source: 'roads',
            paint: { 'line-color': ['case', ['==', ['get', 'status'], 'BLOCKED'], '#DC2626', ['==', ['get', 'status'], 'RESTRICTED'], '#F97316', '#5B6B66'],
                     'line-width': ['case', ['==', ['get', 'status'], 'BLOCKED'], 4.5, ['==', ['get', 'criticality'], 'lifeline'], 2.6, 1.8],
                     'line-opacity': 0.85 } },
          { id: 'roads-blocked', type: 'line', source: 'roads', filter: ['==', ['get', 'status'], 'BLOCKED'],
            paint: { 'line-color': '#ffffff', 'line-width': 1.5, 'line-dasharray': [2, 2] } },
          { id: 'villages', type: 'circle', source: 'villages',
            paint: { 'circle-radius': ['case', ['boolean', ['get', 'is_cut_off'], false], 7, 4],
                     'circle-color': ['case', ['boolean', ['get', 'is_cut_off'], false], '#DC2626', '#ffffff'],
                     'circle-stroke-color': '#1C2B27', 'circle-stroke-width': 1.2 } },
        ],
      },
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

    m.on('load', () => {
      ready.current = true
      if (props.current.terrain !== false) m.setTerrain({ source: 'dem', exaggeration: 1.6 })
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
      syncAll()
      startLoop()
    })

    const ro = new ResizeObserver(() => m.resize())
    ro.observe(host.current)
    return () => {
      cancelAnimationFrame(raf.current)
      ro.disconnect()
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
        d.failed ? [120, 128, 124, 200] : d.live ? [34, 197, 94, 255] : d.source === 'hardware' ? [250, 204, 21, 255] : [15, 118, 110, 255]
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
    const live = pulses.filter((q) => now - q.at < (q.big ? 20000 : 12000))
    if (live.length) {
      const ring = (q: Pulse) => {
        const period = q.big ? 2600 : 1600
        const k = ((now - q.at) % period) / period
        return { r: k * (q.big ? 9000 : 2600), a: 1 - k }
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
      layers.push(new ScatterplotLayer({
        id: 'pulse-dots', data: live, radiusUnits: 'pixels', getRadius: (q: Pulse) => (q.big ? 9 : 6),
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

  // Animation loop: glow for at-risk zones, live pin breathing, ripples, orbit.
  function startLoop() {
    cancelAnimationFrame(raf.current)
    const reduced = prefersReducedMotion()
    const tick = () => {
      const m = map.current
      if (!m) return
      const now = performance.now()
      const { pulses = [], pins = [], orbit } = props.current
      const hasPulse = pulses.some((q) => now - q.at < 20000)
      const hasLive = pins.some((q) => q.live)
      if (!reduced) {
        try {
          m.setPaintProperty('zone-glow', 'fill-opacity', 0.12 + 0.16 * (0.5 + 0.5 * Math.sin(now / 420)))
        } catch { /* not ready */ }
        if (orbit) {
          orbitBearing.current = (orbitBearing.current + 0.05) % 360
          m.setBearing(orbitBearing.current)
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

  useEffect(() => {
    const m = map.current
    if (!m || !ready.current) return
    for (const [k, v] of Object.entries(basePaint(!!p.dark))) {
      try { m.setPaintProperty('base', k, v) } catch { /* style not ready */ }
    }
  }, [p.dark])

  useEffect(() => {
    const m = map.current
    if (!m || !ready.current) return
    m.setTerrain(p.terrain === false ? null : { source: 'dem', exaggeration: 1.6 })
  }, [p.terrain])

  useEffect(() => {
    const m = map.current
    if (!m || !p.flyTo) return
    m.flyTo({ center: [p.flyTo.lon, p.flyTo.lat], zoom: p.flyTo.zoom ?? 11, pitch: 62, bearing: -25,
              duration: prefersReducedMotion() ? 0 : 1800, essential: true })
  }, [p.flyTo])

  useEffect(() => {
    const m = map.current
    if (!m || !p.orbit) return
    m.jumpTo({ center: [p.orbit.lon, p.orbit.lat], zoom: p.orbit.zoom ?? 11.8, pitch: 64, bearing: orbitBearing.current })
  }, [p.orbit?.lat, p.orbit?.lon])  // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={host} className="map-host" />
}

export const rgb = hexToRgb
