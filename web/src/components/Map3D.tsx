/**
 * 3D terrain map for the control room and the replay page.
 *
 * MapLibre GL JS on OpenFreeMap vector tiles (free, no key): the `dark` style
 * in dark mode, `positron` in light mode, both re-tuned here — English labels
 * only, POIs / minor roads / buildings hidden until zoom 13, land, water and
 * roads recoloured to the product palette. AWS Terrain Tiles (terrarium DEM)
 * give gentle relief (1.2x) with a soft hillshade; sky and fog fade the
 * horizon. Everything outside the monitored zones is dimmed.
 *
 * Our own layers are spliced in under the basemap labels: severity-coloured
 * zones (soft glow on HIGH, pulsing on CRITICAL, name labels from zoom 9),
 * clustered citizen reports, diamond sensors, orange blocked roads with a
 * marker at the break, cut-off villages, and a rain radar: a smooth
 * precipitation surface built from the hourly per-zone rain (Gaussian kernel,
 * ~8 km) as GeoJSON isobands so it drapes on the terrain, with
 * "NN mm / 24 h" chips at zone centres from zoom 10. Rain is blue → violet →
 * magenta only; risk is green → yellow → orange → red only.
 *
 * Only ever imported from the control room and the replay page, so the
 * citizen bundle never pays for it. The 2D fallback is components/MapView.tsx.
 */
import { useEffect, useRef } from 'react'
import maplibregl, { type LngLatBoundsLike, type Map as MLMap } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { MapboxOverlay } from '@deck.gl/mapbox'
import { ScatterplotLayer } from '@deck.gl/layers'
import { prefersReducedMotion } from '../hooks'
import { SEVERITY_FILL, asSeverity } from './Severity'

/** One zone's rain: this hour (drives the radar) and the 24 h total (the chip). */
export interface RainPoint { lat: number; lon: number; mm: number; mm24?: number }
export interface Pin { lon: number; lat: number; live?: boolean; failed?: boolean; anomalous?: boolean; label?: string; source?: string }
export interface Pulse { lon: number; lat: number; at: number; big?: boolean; color?: [number, number, number] }
export interface ReportPoint { id: number; lat: number; lon: number; label?: string }
export interface View { lon: number; lat: number; zoom?: number }
export interface Layers3D { zones: boolean; reports: boolean; sensors: boolean; rain: boolean; roads: boolean }

interface Props {
  zones?: any
  roads?: any
  villages?: any
  reports?: ReportPoint[]
  rain?: RainPoint[]
  /** Replay: mm of rain this hour → light falling particles over the event area. */
  rainParticles?: number
  pins?: Pin[]
  pulses?: Pulse[]
  layers?: Partial<Layers3D>
  selectedZoneId?: number | null
  onSelectZone?: (id: number) => void
  flyTo?: { lat: number; lon: number; zoom?: number } | null
  /** Replay: centre on a point; `orbitActive` turns the slow rotation on. */
  orbit?: { lat: number; lon: number; zoom?: number } | null
  orbitActive?: boolean
  dark?: boolean
  terrain?: boolean
  basemap?: 'map' | 'satellite'
  center?: [number, number]
  zoom?: number
  /** Turn slowly after 30 s without input; any touch stops it. */
  idleRotate?: boolean
  /** Fly over these points once (bump `id` to start) so their tiles are cached. */
  tour?: { id: number; stops: View[]; onDone?: () => void } | null
  /** Bump to return to the default view (fit to the monitored zones). */
  resetSignal?: number
}

const STYLE_URL = { dark: 'https://tiles.openfreemap.org/styles/dark', light: 'https://tiles.openfreemap.org/styles/positron' }
const GLYPHS = 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf'
const FONT = ['Noto Sans Regular']
const DEM_TILES = ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png']
const SAT_TILES = ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}']
const OSM_TILES = ['https://tile.openstreetmap.org/{z}/{x}/{y}.png']
const TERRAIN_ATTRIB = 'Terrain: <a href="https://registry.opendata.aws/terrain-tiles/">AWS Terrain Tiles</a> (Mapzen)'
const SAT_ATTRIB = 'Imagery © Esri, Maxar, Earthstar Geographics'
const OSM_ATTRIB = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
const EXAGGERATION = 1.2
const IDLE_MS = 30000
// North-East India: users cannot pan off into Tibet or the Bay of Bengal.
const MAX_BOUNDS: LngLatBoundsLike = [[85.5, 20.5], [98.8, 30.2]]
const DEFAULT_BOUNDS: LngLatBoundsLike = [[87.9, 22.5], [96.2, 28.6]]
const EMPTY = { type: 'FeatureCollection', features: [] as any[] }
const SEV = ['match', ['get', 'severity']]
const ENGLISH = ['coalesce', ['get', 'name:en'], ['get', 'name_en'], ['get', 'name']]
const HIDE = /poi|airport|place_other|place_suburb|label_other|highway-name-path|highway-name-minor|highway_name_other|road_oneway|building|shield_us|us-interstate|aeroway|pier/
const MINOR = /minor|path|service|track|pedestrian|_link|railway|rail_/

/** Weather-radar ramp: 0 mm clear → 2 light blue → 10 blue → 30 violet → 60+ magenta.
 *  Blue/violet family only, so it can never be confused with risk colours. */
export const RAIN_RAMP: Array<[number, [number, number, number]]> = [
  [0, [125, 211, 252]], [2, [125, 211, 252]], [10, [59, 130, 246]], [30, [139, 92, 246]], [60, [236, 72, 153]],
]
export function rainColor(mm: number): [number, number, number, number] {
  const r = RAIN_RAMP
  let i = 0
  while (i < r.length - 2 && mm > r[i + 1][0]) i++
  const [a, ca] = r[i], [b, cb] = r[i + 1]
  const k = Math.max(0, Math.min(1, (mm - a) / (b - a)))
  const alpha = Math.round(255 * Math.max(0, Math.min(1, mm / 2)))     // fades in over the first 2 mm
  return [Math.round(ca[0] + (cb[0] - ca[0]) * k), Math.round(ca[1] + (cb[1] - ca[1]) * k), Math.round(ca[2] + (cb[2] - ca[2]) * k), alpha]
}
const SIGMA_KM = 8
const LEVELS = [1, 2, 4, 7, 10, 18, 30, 45, 60]

/** The rain field as isoband polygons: a Gaussian-kernel mean of the zone
 *  values on a 2 km grid, then marching squares at each level, painted in
 *  ascending order (higher bands cover lower ones). Fill layers drape on the
 *  terrain; image/canvas sources do not. */
function buildRadar(pts: RainPoint[], box: [number, number, number, number]): any {
  const [west, south, east, north] = box
  const midLat = (south + north) / 2
  const kx = 111.32 * Math.cos(midLat * Math.PI / 180), ky = 110.57
  // ~2 km cells for one event, coarser over the whole North-East (keeps it ~150 cells wide).
  const CELL_KM = Math.max(2, ((east - west) * kx) / 150)
  const dLon = CELL_KM / kx, dLat = CELL_KM / ky
  const nx = Math.ceil((east - west) / dLon) + 1, ny = Math.ceil((north - south) / dLat) + 1
  const sw = new Float32Array(nx * ny), swv = new Float32Array(nx * ny)
  const reach = Math.ceil((3 * SIGMA_KM) / CELL_KM), s2 = 2 * SIGMA_KM * SIGMA_KM
  let minI = nx, maxI = -1, minJ = ny, maxJ = -1
  for (const q of pts) {
    const ci = Math.round((q.lon - west) / dLon), cj = Math.round((q.lat - south) / dLat)
    for (let j = Math.max(0, cj - reach); j <= Math.min(ny - 1, cj + reach); j++) {
      const dy = (south + j * dLat - q.lat) * ky
      for (let i = Math.max(0, ci - reach); i <= Math.min(nx - 1, ci + reach); i++) {
        const dx = (west + i * dLon - q.lon) * kx
        const d2 = dx * dx + dy * dy
        if (d2 > 9 * SIGMA_KM * SIGMA_KM) continue
        const w = Math.exp(-d2 / s2)
        const k = j * nx + i
        sw[k] += w; swv[k] += w * q.mm
        if (i < minI) minI = i; if (i > maxI) maxI = i; if (j < minJ) minJ = j; if (j > maxJ) maxJ = j
      }
    }
  }
  const val = (i: number, j: number) => { const k = j * nx + i; return sw[k] < 0.3 ? 0 : (swv[k] / sw[k]) * Math.min(1, (sw[k] - 0.3) / 0.5) }
  const features: any[] = []
  for (let li = 0; li < LEVELS.length; li++) {
    const level = LEVELS[li], next = LEVELS[li + 1] ?? Infinity
    const [r, g, b, a] = rainColor(level)
    const c = `rgba(${r},${g},${b},${(a / 255).toFixed(2)})`
    for (let j = minJ; j < maxJ; j++) {
      for (let i = minI; i < maxI; i++) {
        // Corners counter-clockwise from the south-west; walk the square and
        // keep corners above the level plus the interpolated edge crossings.
        const v = [val(i, j), val(i + 1, j), val(i + 1, j + 1), val(i, j + 1)]
        if (v[0] < level && v[1] < level && v[2] < level && v[3] < level) continue
        // Fully inside the next band up: that band paints it, so bands don't stack.
        if (v[0] >= next && v[1] >= next && v[2] >= next && v[3] >= next) continue
        const px = [west + i * dLon, west + (i + 1) * dLon, west + (i + 1) * dLon, west + i * dLon]
        const py = [south + j * dLat, south + j * dLat, south + (j + 1) * dLat, south + (j + 1) * dLat]
        const ring: number[][] = []
        for (let k = 0; k < 4; k++) {
          const n = (k + 1) % 4
          if (v[k] >= level) ring.push([px[k], py[k]])
          if ((v[k] >= level) !== (v[n] >= level)) {
            const t = (level - v[k]) / (v[n] - v[k])
            ring.push([px[k] + (px[n] - px[k]) * t, py[k] + (py[n] - py[k]) * t])
          }
        }
        if (ring.length < 3) continue
        ring.push(ring[0])
        features.push({ type: 'Feature', properties: { c, level }, geometry: { type: 'Polygon', coordinates: [ring] } })
      }
    }
  }
  return { type: 'FeatureCollection', features }
}

const styleCache = new Map<string, Promise<any>>()
function fetchStyle(url: string): Promise<any> {
  if (!styleCache.has(url)) {
    styleCache.set(url, fetch(url).then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.json() })
      .catch((e) => { styleCache.delete(url); throw e }))
  }
  return styleCache.get(url)!
}

/** Venue Wi-Fi fallback: raster OSM, dimmed; our layers still draw. */
function fallbackStyle(dark: boolean): any {
  return {
    version: 8, glyphs: GLYPHS,
    sources: { osm: { type: 'raster', tiles: OSM_TILES, tileSize: 256, attribution: OSM_ATTRIB, maxzoom: 19 } },
    layers: [{ id: 'osm', type: 'raster', source: 'osm', paint: dark
      ? { 'raster-saturation': -0.9, 'raster-brightness-max': 0.35, 'raster-brightness-min': 0.03 }
      : { 'raster-saturation': -0.5, 'raster-brightness-max': 0.95 } }],
  }
}

/** English labels, fewer labels, product colours. Mutates a copy of the base style. */
function tune(base: any, dark: boolean): any {
  const layers = (base.layers ?? []).map((l: any) => {
    const L = { ...l, layout: { ...(l.layout ?? {}) }, paint: { ...(l.paint ?? {}) } }
    const id: string = L.id
    if (HIDE.test(id)) L.layout.visibility = 'none'
    if (MINOR.test(id) || /village/.test(id)) L.minzoom = Math.max(L.minzoom ?? 0, 13)
    if (L.type === 'symbol' && L.layout['text-field'] !== undefined) {
      L.layout['text-field'] = ENGLISH
      L.paint['text-color'] = dark ? '#B9C6C0' : '#3E4C59'
      L.paint['text-halo-color'] = dark ? '#0F1A17' : '#F4F1EA'
      L.paint['text-halo-width'] = 1.2
    }
    if (dark) {
      if (L.type === 'background') L.paint['background-color'] = '#0F1A17'
      else if (L.type === 'fill' && /water/.test(id)) L.paint['fill-color'] = '#1E3A4A'
      else if (L.type === 'line' && /waterway/.test(id)) L.paint['line-color'] = '#1E3A4A'
      else if (L.type === 'fill') { L.paint['fill-color'] = '#13201C'; L.paint['fill-opacity'] = 0.6 }
      else if (L.type === 'line' && /boundary/.test(id)) { L.paint['line-color'] = 'rgba(232,239,234,.35)'; delete L.paint['line-dasharray'] }
      else if (L.type === 'line' && /casing/.test(id)) L.paint['line-color'] = '#0B1411'
      else if (L.type === 'line') L.paint['line-color'] = '#3A4842'
    } else if (L.type === 'line' && /boundary/.test(id)) L.paint['line-color'] = 'rgba(62,76,89,.45)'
    return L
  })
  return { ...base, layers, glyphs: base.glyphs ?? GLYPHS }
}

function sky(dark: boolean): any {
  return dark
    ? { 'sky-color': '#0E1512', 'horizon-color': '#1F2A24', 'fog-color': '#0F1A17', 'sky-horizon-blend': 0.6, 'horizon-fog-blend': 0.7, 'fog-ground-blend': 0.3, 'atmosphere-blend': 0.4 }
    : { 'sky-color': '#BFD3DE', 'horizon-color': '#EDEBE4', 'fog-color': '#F4F1EA', 'sky-horizon-blend': 0.55, 'horizon-fog-blend': 0.75, 'fog-ground-blend': 0.3, 'atmosphere-blend': 0.6 }
}

function ourSources(): Record<string, any> {
  return {
    rain: { type: 'geojson', data: EMPTY },
    'rain-chips': { type: 'geojson', data: EMPTY },
    sat: { type: 'raster', tiles: SAT_TILES, tileSize: 256, attribution: SAT_ATTRIB, maxzoom: 18 },
    dem: { type: 'raster-dem', tiles: DEM_TILES, tileSize: 256, encoding: 'terrarium', maxzoom: 15, attribution: TERRAIN_ATTRIB },
    'dem-hs': { type: 'raster-dem', tiles: DEM_TILES, tileSize: 256, encoding: 'terrarium', maxzoom: 15 },
    dim: { type: 'geojson', data: EMPTY },
    zones: { type: 'geojson', data: EMPTY, promoteId: 'id' },
    'zone-labels': { type: 'geojson', data: EMPTY },
    roads: { type: 'geojson', data: EMPTY },
    'road-blocks': { type: 'geojson', data: EMPTY },
    villages: { type: 'geojson', data: EMPTY },
    sensors: { type: 'geojson', data: EMPTY },
    reports: { type: 'geojson', data: EMPTY, cluster: true, clusterRadius: 40, clusterMaxZoom: 13 },
  }
}

function ourLayers(satellite: boolean, dark: boolean): any[] {
  const hover = ['boolean', ['feature-state', 'hover'], false]
  const sel = ['boolean', ['get', 'selected'], false]
  return [
    { id: 'sat', type: 'raster', source: 'sat', layout: { visibility: satellite ? 'visible' : 'none' },
      paint: dark ? { 'raster-saturation': -0.25, 'raster-brightness-max': 0.7 } : { 'raster-saturation': 0.05 } },
    // From zoom 7 only: at the regional view it reads as noise, not depth.
    { id: 'hillshade', type: 'hillshade', source: 'dem-hs', minzoom: 7,
      paint: { 'hillshade-exaggeration': satellite ? 0.12 : 0.25, 'hillshade-shadow-color': '#0A1210',
               'hillshade-highlight-color': dark ? '#243029' : '#FFFFFF', 'hillshade-accent-color': dark ? '#0A1210' : '#6A7A6E' } },
    { id: 'dim', type: 'fill', source: 'dim', paint: { 'fill-color': dark ? '#0F1A17' : '#F4F1EA', 'fill-opacity': 0.55 } },
    { id: 'rain-radar', type: 'fill', source: 'rain', paint: { 'fill-color': ['get', 'c'], 'fill-antialias': false,
               // Light rain stays a faint wash; heavy cores read at full strength.
               'fill-opacity': ['interpolate', ['linear'], ['get', 'level'], 1, 0.28, 10, 0.5, 30, 0.6] } },
    // Knocks the radar out inside zones so red over blue never turns pink
    // (pink is the 60+ mm rain colour); the chip still gives that zone's rain.
    { id: 'zone-knockout', type: 'fill', source: 'zones', paint: { 'fill-color': dark ? '#0F1A17' : '#F4F1EA', 'fill-opacity': 0.8, 'fill-antialias': false } },
    { id: 'zone-fill', type: 'fill', source: 'zones',
      paint: { 'fill-color': ['to-color', ['get', 'color']],
               'fill-opacity': ['+', [...SEV, 'LOW', 0.10, 'MODERATE', 0.25, 'HIGH', 0.40, 'CRITICAL', 0.55, 0.1], ['case', hover, 0.15, 0]] } },
    { id: 'zone-glow-high', type: 'line', source: 'zones', filter: ['==', ['get', 'severity'], 'HIGH'],
      paint: { 'line-color': ['to-color', ['get', 'color']], 'line-width': 12, 'line-blur': 8, 'line-opacity': 0.45 } },
    { id: 'zone-glow-critical', type: 'line', source: 'zones', filter: ['==', ['get', 'severity'], 'CRITICAL'],
      paint: { 'line-color': ['to-color', ['get', 'color']], 'line-width': 16, 'line-blur': 10, 'line-opacity': 0.5 } },
    { id: 'zone-line', type: 'line', source: 'zones',
      paint: { 'line-color': ['case', sel, dark ? '#FFFFFF' : '#1F2A33', ['to-color', ['get', 'color']]],
               'line-width': ['case', sel, 3, 1.5], 'line-opacity': ['case', sel, 1, hover, 1, 0.85] } },
    { id: 'roads', type: 'line', source: 'roads',
      paint: { 'line-color': ['match', ['get', 'status'], 'BLOCKED', '#FB923C', 'RESTRICTED', '#E3B23C', dark ? '#6B7A74' : '#8A9790'],
               'line-width': ['match', ['get', 'status'], 'BLOCKED', 4, ['case', ['==', ['get', 'criticality'], 'lifeline'], 2.4, 1.6]],
               'line-opacity': 0.95 } },
    { id: 'road-blocks', type: 'symbol', source: 'road-blocks', minzoom: 8, layout: { 'icon-image': 'blocked', 'icon-size': 1, 'icon-allow-overlap': true } },
    { id: 'villages', type: 'symbol', source: 'villages', minzoom: 8.5,
      layout: { 'icon-image': ['case', ['boolean', ['get', 'is_cut_off'], false], 'house-cut', 'house'], 'icon-size': 1, 'icon-allow-overlap': true } },
    { id: 'sensors', type: 'symbol', source: 'sensors', minzoom: 7.5,
      layout: { 'icon-image': ['case', ['boolean', ['get', 'anomalous'], false], 'sensor-anomaly', ['boolean', ['get', 'live'], false], 'sensor-live', 'sensor-sim'],
                'icon-size': 1, 'icon-allow-overlap': true } },
    { id: 'reports-clusters', type: 'circle', source: 'reports', filter: ['has', 'point_count'],
      paint: { 'circle-color': '#DC2626', 'circle-radius': ['step', ['get', 'point_count'], 13, 5, 16, 10, 20], 'circle-stroke-color': '#FFFFFF', 'circle-stroke-width': 2 } },
    { id: 'reports-count', type: 'symbol', source: 'reports', filter: ['has', 'point_count'],
      layout: { 'text-field': ['get', 'point_count_abbreviated'], 'text-font': FONT, 'text-size': 12, 'text-allow-overlap': true }, paint: { 'text-color': '#FFFFFF' } },
    { id: 'reports', type: 'circle', source: 'reports', filter: ['!', ['has', 'point_count']],
      paint: { 'circle-color': '#DC2626', 'circle-radius': 6, 'circle-stroke-color': '#FFFFFF', 'circle-stroke-width': 2 } },
    { id: 'zone-labels', type: 'symbol', source: 'zone-labels', minzoom: 9,
      layout: { 'text-field': ['get', 'name'], 'text-font': FONT, 'text-size': 12.5, 'text-anchor': 'center', 'text-allow-overlap': false },
      paint: { 'text-color': '#FFFFFF', 'text-halo-color': '#0F1A17', 'text-halo-width': 1.5 } },
  ]
}

/** Base style with our sources, our layers under its labels, and sky. */
// Above every base layer: with terrain, base lines after the first symbol
// layer would otherwise draw across the chips.
const RAIN_CHIPS = { id: 'rain-chips', type: 'symbol', source: 'rain-chips', minzoom: 10,
  layout: { 'icon-image': ['get', 'chip'], 'icon-text-fit': 'both', 'icon-text-fit-padding': [1, 4, 1, 2], 'icon-allow-overlap': true,
            'text-field': ['get', 'label'], 'text-font': FONT, 'text-size': 11.5, 'text-anchor': 'center', 'text-allow-overlap': true, 'text-ignore-placement': true },
  paint: { 'text-color': '#FFFFFF', 'text-halo-color': 'rgba(15,26,23,.55)', 'text-halo-width': 0.8 } }

function compose(base: any, satellite: boolean, dark: boolean): any {
  const layers: any[] = base.layers ?? []
  let cut = layers.findIndex((l) => l.type === 'symbol')
  if (cut < 0) cut = layers.length
  return { ...base, sources: { ...base.sources, ...ourSources() }, layers: [...layers.slice(0, cut), ...ourLayers(satellite, dark), ...layers.slice(cut), RAIN_CHIPS], sky: sky(dark) }
}

/** Marker images drawn on a canvas: no sprite sheet to host, re-added after every style swap. */
function makeIcon(size: number, draw: (c: CanvasRenderingContext2D, s: number) => void): ImageData {
  const c = document.createElement('canvas'); c.width = c.height = size
  const ctx = c.getContext('2d')!
  draw(ctx, size)
  return ctx.getImageData(0, 0, size, size)
}
function addIcons(m: MLMap) {
  const diamond = (fill: string, stroke: string, glow?: string) => makeIcon(28, (c, s) => {
    const h = s / 2
    if (glow) { c.shadowColor = glow; c.shadowBlur = 8 }
    c.beginPath(); c.moveTo(h, 6); c.lineTo(s - 6, h); c.lineTo(h, s - 6); c.lineTo(6, h); c.closePath()
    c.fillStyle = fill; c.fill(); c.shadowBlur = 0; c.lineWidth = 1.5; c.strokeStyle = stroke; c.stroke()
  })
  const icons: Record<string, ImageData> = {
    'sensor-sim': diamond('#8A9C94', '#0F1A17'),
    'sensor-live': diamond('#7FD1AE', '#0F1A17', 'rgba(127,209,174,.9)'),
    'sensor-anomaly': makeIcon(28, (c, s) => {
      const h = s / 2
      c.beginPath(); c.arc(h, h, 11, 0, Math.PI * 2); c.lineWidth = 2.5; c.strokeStyle = '#F87171'; c.stroke()
      c.beginPath(); c.moveTo(h, 7); c.lineTo(s - 7, h); c.lineTo(h, s - 7); c.lineTo(7, h); c.closePath()
      c.fillStyle = '#F87171'; c.fill(); c.lineWidth = 1.5; c.strokeStyle = '#0F1A17'; c.stroke()
    }),
    blocked: makeIcon(26, (c, s) => {
      const h = s / 2
      c.beginPath(); c.arc(h, h, 10, 0, Math.PI * 2); c.fillStyle = '#FB923C'; c.fill(); c.lineWidth = 2; c.strokeStyle = '#FFFFFF'; c.stroke()
      c.fillStyle = '#FFFFFF'; c.fillRect(h - 6, h - 1.5, 12, 3)
    }),
    house: makeIcon(22, (c, s) => house(c, s, '#FFFFFF', '#0F1A17')),
    'house-cut': makeIcon(26, (c, s) => {
      house(c, s - 4, '#FFFFFF', '#0F1A17')
      c.beginPath(); c.arc(s - 6, 6, 5, 0, Math.PI * 2); c.fillStyle = '#FB923C'; c.fill(); c.lineWidth = 1.5; c.strokeStyle = '#FFFFFF'; c.stroke()
    }),
  }
  function house(c: CanvasRenderingContext2D, s: number, fill: string, stroke: string) {
    const x = 3, w = s - 6, y = s * 0.42, hgt = s - y - 3
    c.beginPath(); c.moveTo(x, y); c.lineTo(x + w / 2, 3); c.lineTo(x + w, y); c.lineTo(x + w, y + hgt); c.lineTo(x, y + hgt); c.closePath()
    c.fillStyle = fill; c.fill(); c.lineWidth = 1.5; c.strokeStyle = stroke; c.stroke()
  }
  for (const [name, img] of Object.entries(icons)) if (!m.hasImage(name)) m.addImage(name, img, { pixelRatio: 1 })
  // Rain chips: a stretchable rounded pill with a raindrop in its fixed left part.
  const chip = (fill: string) => {
    const cv = document.createElement('canvas'); cv.width = 64; cv.height = 28
    const c = cv.getContext('2d')!
    c.beginPath(); c.roundRect(0.5, 0.5, 63, 27, 13.5); c.fillStyle = fill; c.fill()
    c.lineWidth = 1; c.strokeStyle = 'rgba(15,26,23,.6)'; c.stroke()
    c.beginPath(); c.moveTo(14, 6); c.bezierCurveTo(14, 6, 7.5, 14, 7.5, 17.5); c.arc(14, 17.5, 6.5, Math.PI, 0, true); c.closePath()
    c.fillStyle = '#FFFFFF'; c.fill()
    return c.getImageData(0, 0, 64, 28)
  }
  const chips: Record<string, string> = { 'chip-0': '#3A4842', 'chip-1': '#5BAEE0', 'chip-2': '#3B82F6', 'chip-3': '#8B5CF6', 'chip-4': '#EC4899' }
  for (const [name, fill] of Object.entries(chips)) if (!m.hasImage(name)) m.addImage(name, chip(fill), { pixelRatio: 1, stretchX: [[30, 50]], content: [26, 5, 56, 23] })
}
function chipFor(mm24: number): string { return mm24 < 1 ? 'chip-0' : mm24 < 10 ? 'chip-1' : mm24 < 30 ? 'chip-2' : mm24 < 60 ? 'chip-3' : 'chip-4' }

function bbox(fc: any): [number, number, number, number] | null {
  let minX = 180, minY = 90, maxX = -180, maxY = -90, any = false
  const walk = (c: any) => {
    if (typeof c[0] === 'number') { any = true; minX = Math.min(minX, c[0]); maxX = Math.max(maxX, c[0]); minY = Math.min(minY, c[1]); maxY = Math.max(maxY, c[1]) }
    else for (const x of c) walk(x)
  }
  for (const f of fc?.features ?? []) if (f.geometry?.coordinates) walk(f.geometry.coordinates)
  return any ? [minX, minY, maxX, maxY] : null
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
  const fitted = useRef(false)
  const pendingFly = useRef<Props['flyTo']>(null)
  const hovered = useRef<number | null>(null)
  const radarPrev = useRef<Map<string, number>>(new Map())
  const radarAnim = useRef(0)
  const particles = useRef<Array<{ dx: number; dy: number; ph: number }>>([])

  async function loadStyle() {
    const m = map.current
    if (!m) return
    const seq = ++styleSeq.current
    const { dark, basemap } = props.current
    let style: any
    try { style = compose(tune(await fetchStyle(dark ? STYLE_URL.dark : STYLE_URL.light), !!dark), basemap === 'satellite', !!dark) }
    catch { style = compose(fallbackStyle(!!dark), basemap === 'satellite', !!dark) }
    if (seq !== styleSeq.current || !map.current) return
    ready.current = false
    m.setStyle(style, { diff: false })
  }

  function defaultView(animate: boolean) {
    const m = map.current
    if (!m) return
    const b = bbox(props.current.zones) ?? (DEFAULT_BOUNDS as any)
    const bounds: LngLatBoundsLike = Array.isArray(b) && typeof b[0] === 'number' ? [[b[0], b[1]], [b[2], b[3]]] : b
    // Fit flat first (pitch makes fitBounds back off too far), then tilt.
    const cam = m.cameraForBounds(bounds, { padding: { top: 40, bottom: 110, left: 40, right: 40 } })
    if (!cam) return
    const opts = { center: cam.center, zoom: (cam.zoom ?? 6) + 0.35, pitch: 50, bearing: -15 }
    if (animate && !prefersReducedMotion()) m.easeTo({ ...opts, duration: 1600 }); else m.jumpTo(opts)
  }

  // ----------------------------------------------------------------- init
  useEffect(() => {
    if (!host.current || map.current) return
    const m = new maplibregl.Map({
      container: host.current,
      center: p.center ?? [91.5, 25.8], zoom: p.zoom ?? 6, pitch: p.orbit ? 62 : 50, bearing: -15,
      maxPitch: 75, maxBounds: p.orbit ? undefined : MAX_BOUNDS, attributionControl: false,
      style: { version: 8, sources: {}, layers: [{ id: 'bg', type: 'background', paint: { 'background-color': p.dark ? '#0F1A17' : '#EAE6DD' } }] },
    })
    const attrib = new maplibregl.AttributionControl({ compact: true })
    m.addControl(attrib, 'bottom-right')
    // Compact attribution opens expanded; start it folded to the (i) button.
    m.once('load', () => { try { (attrib as any)._container?.classList.remove('maplibregl-compact-show') } catch { /* fine */ } })
    m.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right')
    const ov = new MapboxOverlay({ interleaved: false, layers: [], getTooltip: ({ object }: any) => object?.label ? { text: object.label } : null })
    m.addControl(ov as any)
    overlay.current = ov
    map.current = m

    m.on('style.load', () => {
      if (!m.getSource('zones')) return          // the placeholder style
      ready.current = true
      addIcons(m)
      if (props.current.terrain !== false) m.setTerrain({ source: 'dem', exaggeration: EXAGGERATION })
      prevColors.current = {}
      syncAll()
      if (pendingFly.current) { flyNow(pendingFly.current); pendingFly.current = null }
      else if (!fitted.current && !props.current.orbit && !props.current.center) { defaultView(false); fitted.current = true }
    })
    m.on('click', 'zone-fill', (e) => {
      const f = e.features?.[0]
      if (f && select.current) select.current(Number(f.properties?.id))
    })
    m.on('click', 'reports-clusters', (e) => {
      const f = e.features?.[0]
      if (!f) return
      const src = m.getSource('reports') as any
      src.getClusterExpansionZoom(f.properties!.cluster_id).then((z: number) => m.easeTo({ center: (f.geometry as any).coordinates, zoom: z }))
    })
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, className: 'zone-tip' })
    const setHover = (id: number | null) => {
      if (hovered.current != null) m.setFeatureState({ source: 'zones', id: hovered.current }, { hover: false })
      hovered.current = id
      if (id != null) m.setFeatureState({ source: 'zones', id }, { hover: true })
    }
    m.on('mousemove', 'zone-fill', (e) => {
      const q = e.features?.[0]?.properties
      if (!q) return
      m.getCanvas().style.cursor = 'pointer'
      setHover(Number(q.id))
      const rain = q.rain24 != null ? `${Number(q.rain24).toFixed(0)} mm rain · 24 h` : ''
      popup.setLngLat(e.lngLat).setHTML(
        `<strong>${q.name}</strong><div class="tip-row"><span class="tip-sev ${q.severity}">${q.severity}</span>${q.risk_score != null ? ` risk ${Number(q.risk_score).toFixed(0)}/100` : ''}${q.confidence != null ? ` · ${Math.round(Number(q.confidence) * 100)}% sure` : ''}</div>${rain ? `<div class="tip-row muted">${rain}</div>` : ''}`
      ).addTo(m)
    })
    m.on('mouseleave', 'zone-fill', () => { m.getCanvas().style.cursor = ''; setHover(null); popup.remove() })
    for (const id of ['reports', 'reports-clusters']) {
      m.on('mouseenter', id, () => { m.getCanvas().style.cursor = 'pointer' })
      m.on('mouseleave', id, () => { m.getCanvas().style.cursor = '' })
    }

    const touched = () => { lastInput.current = performance.now() }
    const el = host.current
    for (const ev of ['pointerdown', 'wheel', 'keydown', 'touchstart'] as const) el.addEventListener(ev, touched, { passive: true })

    loadStyle()
    startLoop()
    const ro = new ResizeObserver(() => m.resize())
    ro.observe(el)
    return () => {
      cancelAnimationFrame(raf.current)
      cancelAnimationFrame(radarAnim.current)
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
        return { ...f, id: f.properties.id, properties: { ...f.properties, severity: sev, color, prevColor: prevColors.current[f.properties.id] ?? color, selected: f.properties.id === props.current.selectedZoneId } }
      }),
    }
  }

  function animateZoneColours(fc: any) {
    const m = map.current
    if (!m || prefersReducedMotion()) return
    if (!fc.features.some((f: any) => f.properties.prevColor !== f.properties.color)) return
    const t0 = performance.now(), ms = 900
    const step = () => {
      const k = Math.min(1, (performance.now() - t0) / ms), e = 1 - Math.pow(1 - k, 3)
      try { m.setPaintProperty('zone-fill', 'fill-color', ['interpolate', ['linear'], e, 0, ['to-color', ['get', 'prevColor']], 1, ['to-color', ['get', 'color']]] as any) } catch { /* not ready */ }
      if (k < 1) requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  }

  function syncZones() {
    const m = map.current
    if (!m || !ready.current) return
    const fc = zonesWithColor()
    ;(m.getSource('zones') as any)?.setData(fc)
    ;(m.getSource('zone-labels') as any)?.setData({ type: 'FeatureCollection', features: fc.features.filter((f: any) => f.properties.centroid)
      .map((f: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [f.properties.centroid[1], f.properties.centroid[0]] }, properties: { name: f.properties.name } })) })
    const b = bbox(fc)
    ;(m.getSource('dim') as any)?.setData(b ? { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [
      [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]],
      [[b[0] - 0.45, b[1] - 0.35], [b[0] - 0.45, b[3] + 0.35], [b[2] + 0.45, b[3] + 0.35], [b[2] + 0.45, b[1] - 0.35], [b[0] - 0.45, b[1] - 0.35]],
    ] } } : EMPTY)
    animateZoneColours(fc)
    for (const f of fc.features) prevColors.current[f.properties.id] = f.properties.color
  }

  function syncRoads() {
    const m = map.current
    if (!m || !ready.current) return
    const roads = props.current.roads ?? EMPTY
    ;(m.getSource('roads') as any)?.setData(roads)
    // One marker at the middle of every blocked road.
    const blocks = (roads.features ?? []).filter((f: any) => f.properties?.status === 'BLOCKED').map((f: any) => {
      const c = f.geometry.type === 'MultiLineString' ? f.geometry.coordinates.flat() : f.geometry.coordinates
      return { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: c[Math.floor(c.length / 2)] } }
    })
    ;(m.getSource('road-blocks') as any)?.setData({ type: 'FeatureCollection', features: blocks })
  }

  function syncPoints() {
    const m = map.current
    if (!m || !ready.current) return
    ;(m.getSource('villages') as any)?.setData(props.current.villages ?? EMPTY)
    ;(m.getSource('sensors') as any)?.setData({ type: 'FeatureCollection', features: (props.current.pins ?? []).map((s) => ({
      type: 'Feature', properties: { live: !!s.live, anomalous: !!s.anomalous, label: s.label }, geometry: { type: 'Point', coordinates: [s.lon, s.lat] } })) })
    ;(m.getSource('reports') as any)?.setData({ type: 'FeatureCollection', features: (props.current.reports ?? []).map((r) => ({
      type: 'Feature', properties: { id: r.id, label: r.label }, geometry: { type: 'Point', coordinates: [r.lon, r.lat] } })) })
  }

  // Rain radar: isobands over a box around the points, tweened from the
  // previous hour's values; chips at the points with the 24 h total.
  function syncRain(animate = true) {
    const m = map.current
    if (!m || !ready.current) return
    const pts = props.current.rain ?? []
    const src = m.getSource('rain') as any
    const chipsSrc = m.getSource('rain-chips') as any
    if (!src) return
    cancelAnimationFrame(radarAnim.current)
    if (!pts.length) { src.setData(EMPTY); chipsSrc?.setData(EMPTY); return }
    const lons = pts.map((q) => q.lon), lats = pts.map((q) => q.lat)
    const pad = 0.3
    const box: [number, number, number, number] = [Math.min(...lons) - pad, Math.min(...lats) - pad, Math.max(...lons) + pad, Math.max(...lats) + pad]
    chipsSrc?.setData({ type: 'FeatureCollection', features: pts.filter((q) => (q.mm24 ?? 0) >= 1).map((q) => ({
      type: 'Feature', properties: { label: `${(q.mm24 ?? 0).toFixed(0)} mm / 24 h`, chip: chipFor(q.mm24 ?? 0) }, geometry: { type: 'Point', coordinates: [q.lon, q.lat] } })) })
    const key = (q: RainPoint) => `${q.lat.toFixed(4)},${q.lon.toFixed(4)}`
    const from = pts.map((q) => radarPrev.current.get(key(q)) ?? 0)
    radarPrev.current = new Map(pts.map((q) => [key(q), q.mm]))
    const draw = (k: number) => src.setData(buildRadar(pts.map((q, i) => ({ ...q, mm: from[i] + (q.mm - from[i]) * k })), box))
    if (!animate || prefersReducedMotion() || from.every((f, i) => Math.abs(f - pts[i].mm) < 0.05)) { draw(1); return }
    const t0 = performance.now(), ms = 520
    let last = 0
    const step = () => {
      const now = performance.now(), k = Math.min(1, (now - t0) / ms)
      if (now - last > 130 || k >= 1) { last = now; draw(1 - Math.pow(1 - k, 2)) }
      if (k < 1) radarAnim.current = requestAnimationFrame(step)
    }
    radarAnim.current = requestAnimationFrame(step)
  }

  function syncVisibility() {
    const m = map.current
    if (!m || !ready.current) return
    const L = { zones: true, reports: true, sensors: true, rain: true, roads: true, ...(props.current.layers ?? {}) }
    const vis = (ids: string[], on: boolean) => ids.forEach((id) => { try { m.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none') } catch { /* missing */ } })
    vis(['zone-fill', 'zone-glow-high', 'zone-glow-critical', 'zone-line', 'zone-labels'], L.zones)
    vis(['reports', 'reports-clusters', 'reports-count'], L.reports)
    vis(['sensors'], L.sensors)
    vis(['rain-radar', 'rain-chips'], L.rain)
    vis(['zone-knockout'], L.rain && L.zones)
    vis(['roads', 'road-blocks', 'villages'], L.roads)
  }

  function deckLayers(now: number) {
    const { pulses = [], rainParticles = 0, orbit } = props.current
    const L = { reports: true, ...(props.current.layers ?? {}) }
    const m = map.current
    const elev = (lon: number, lat: number) => { try { return (m?.queryTerrainElevation([lon, lat]) ?? 0) || 0 } catch { return 0 } }
    const layers: any[] = []
    // Replay: light rain over the event area, density from this hour's rain.
    const want = orbit && rainParticles > 0.2 ? Math.min(220, Math.round(rainParticles * 14) + 10) : 0
    if (particles.current.length !== want) {
      particles.current = Array.from({ length: want }, (_, i) => ({ dx: (Math.sin(i * 12.9898) * 43758.5453 % 1) * 0.06 - 0.03, dy: (Math.cos(i * 78.233) * 12345.678 % 1) * 0.06 - 0.03, ph: (i * 0.37) % 1 }))
    }
    if (want && orbit) {
      const fall = 0.025
      layers.push(new ScatterplotLayer({
        id: 'rain-particles', data: particles.current, radiusUnits: 'pixels', getRadius: 1.4, stroked: false,
        getPosition: (q: { dx: number; dy: number; ph: number }) => {
          const t = ((now / 1400) + q.ph) % 1
          return [orbit.lon + q.dx - t * 0.004, orbit.lat + q.dy + (0.5 - t) * fall, elev(orbit.lon + q.dx, orbit.lat + q.dy) + 1200 - t * 1400]
        },
        getFillColor: [191, 219, 254, 170], updateTriggers: { getPosition: now },
      }))
    }
    // A new report ripples out once; the replay's landslide moment keeps pulsing.
    const life = (q: Pulse) => (q.big ? 20000 : 2400)
    const live = L.reports ? pulses.filter((q) => now - q.at < life(q)) : []
    if (live.length) {
      const ring = (q: Pulse) => { const period = q.big ? 2600 : 2400; const k = ((now - q.at) % period) / period; return { r: k * (q.big ? 9000 : 3200), a: 1 - k } }
      layers.push(new ScatterplotLayer({
        id: 'pulses', data: live, radiusUnits: 'meters', stroked: true, filled: true,
        getPosition: (q: Pulse) => [q.lon, q.lat, elev(q.lon, q.lat) + 20],
        getRadius: (q: Pulse) => ring(q).r,
        getFillColor: (q: Pulse) => [...(q.color ?? [220, 38, 38]), Math.round(40 * ring(q).a)] as any,
        getLineColor: (q: Pulse) => [...(q.color ?? [220, 38, 38]), Math.round(230 * ring(q).a)] as any,
        lineWidthMinPixels: 2, updateTriggers: { getRadius: now, getFillColor: now, getLineColor: now },
      }))
    }
    const bigDots = pulses.filter((q) => q.big && now - q.at < 20000)
    if (bigDots.length) {
      layers.push(new ScatterplotLayer({
        id: 'pulse-dots', data: bigDots, radiusUnits: 'pixels', getRadius: 9,
        getPosition: (q: Pulse) => [q.lon, q.lat, elev(q.lon, q.lat) + 20],
        getFillColor: (q: Pulse) => [...(q.color ?? [220, 38, 38]), 255] as any, stroked: true, getLineColor: [255, 255, 255, 255], lineWidthMinPixels: 2,
      }))
    }
    return layers
  }

  function syncDeck(now = performance.now()) { overlay.current?.setProps({ layers: deckLayers(now) }) }

  function syncAll() {
    if (!map.current || !ready.current) return
    syncZones(); syncRoads(); syncPoints(); syncRain(false); syncVisibility(); syncDeck()
  }

  // Animation loop: CRITICAL glow pulse, ripples, orbit, idle rotation.
  function startLoop() {
    cancelAnimationFrame(raf.current)
    const reduced = prefersReducedMotion()
    const tick = () => {
      const m = map.current
      if (!m) return
      const now = performance.now()
      const { pulses = [], orbit, orbitActive, idleRotate, rainParticles = 0 } = props.current
      const hasPulse = pulses.some((q) => now - q.at < 20000) || (!!orbit && rainParticles > 0.2)
      if (!reduced && ready.current) {
        try { m.setPaintProperty('zone-glow-critical', 'line-opacity', 0.3 + 0.35 * (0.5 + 0.5 * Math.sin(now / 600))) } catch { /* not ready */ }
        if (orbit && orbitActive) { orbitBearing.current = (orbitBearing.current + 0.05) % 360; m.setBearing(orbitBearing.current) }
        else if (!orbit && idleRotate && !touring.current && now - lastInput.current > IDLE_MS && !m.isMoving()) m.setBearing((m.getBearing() + 0.03) % 360)
      }
      if (hasPulse && now - lastPulseRender.current > 40) { lastPulseRender.current = now; syncDeck(now) }
      raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
  }

  useEffect(() => { syncZones() }, [p.zones, p.selectedZoneId])          // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { syncRoads() }, [p.roads])                             // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { syncPoints() }, [p.villages, p.pins, p.reports])      // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { syncVisibility(); syncDeck() }, [p.layers?.zones, p.layers?.reports, p.layers?.sensors, p.layers?.rain, p.layers?.roads])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (ready.current) syncDeck() }, [p.pulses, p.rainParticles])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { syncRain() }, [p.rain])                                         // eslint-disable-line react-hooks/exhaustive-deps

  const firstDark = useRef(true)
  useEffect(() => { if (firstDark.current) { firstDark.current = false; return } loadStyle() }, [p.dark])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const m = map.current
    if (!m || !ready.current) return
    const sat = p.basemap === 'satellite'
    try { m.setLayoutProperty('sat', 'visibility', sat ? 'visible' : 'none'); m.setPaintProperty('hillshade', 'hillshade-exaggeration', sat ? 0.12 : 0.25) } catch { /* not ready */ }
  }, [p.basemap])

  useEffect(() => {
    const m = map.current
    if (!m || !ready.current) return
    m.setTerrain(p.terrain === false ? null : { source: 'dem', exaggeration: EXAGGERATION })
  }, [p.terrain])

  useEffect(() => {
    const m = map.current
    if (!m || !p.flyTo) return
    fitted.current = true                       // a deep link beats the default fit
    // Before the style has loaded a flight gets cut short; run it on load.
    if (!ready.current) { pendingFly.current = p.flyTo; return }
    flyNow(p.flyTo)
  }, [p.flyTo])

  function flyNow(f: NonNullable<Props['flyTo']>) {
    lastInput.current = performance.now()
    map.current?.flyTo({ center: [f.lon, f.lat], zoom: f.zoom ?? 11, pitch: 58, bearing: -20, duration: prefersReducedMotion() ? 0 : 1800, essential: true })
  }

  const firstReset = useRef(true)
  useEffect(() => { if (firstReset.current) { firstReset.current = false; return } lastInput.current = performance.now(); defaultView(true) }, [p.resetSignal])  // eslint-disable-line react-hooks/exhaustive-deps

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
    const settle = () => new Promise<void>((res) => { const t = window.setTimeout(res, 9000); m.once('idle', () => { window.clearTimeout(t); res() }) })
    ;(async () => {
      for (const s of tour.stops) {
        if (cancelled) return
        m.flyTo({ center: [s.lon, s.lat], zoom: s.zoom ?? 11, pitch: 55, bearing: -15, duration: 2200, essential: true })
        await new Promise((r) => window.setTimeout(r, 2300))
        await settle()
      }
      if (cancelled) return
      defaultView(true)
      touring.current = false
      lastInput.current = performance.now()
      tour.onDone?.()
    })()
    return () => { cancelled = true; touring.current = false }
  }, [p.tour?.id])  // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={host} className="map-host" />
}

export const rgb = hexToRgb
