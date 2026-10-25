/**
 * The 2D / low-data map: Leaflet + OpenStreetMap raster tiles. No WebGL, no
 * token, a fraction of the download of the 3D view — the fallback for slow
 * networks and low-end phones. Same props as Map3D where they overlap.
 */
import { useEffect, useRef } from 'react'
import type { VolunteerPoint } from './Map3D'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { SEVERITY_FILL, asSeverity } from './Severity'
import type { Severity } from '../api/client'

const INK = '#2F6B3A'

export interface Layers {
  risk: boolean; roads: boolean; villages: boolean
  sensors: boolean; historical: boolean; volunteers?: boolean
}

interface Props {
  zones: any
  infrastructure: any
  sensors: any
  historical: any
  layers: Layers
  selectedZoneId: number | null
  onSelectZone: (id: number) => void
  /** zone_id -> mm for the current rain frame */
  rain?: Record<string, number> | null
  /** fresh citizen reports to pulse */
  pulses?: Array<{ lat: number; lon: number; at: number }>
  /** Gaon Prahari volunteers with their last gauge reading */
  volunteers?: VolunteerPoint[]
}

function createBaseLayer(): L.TileLayer {
  return L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18, attribution: '© OpenStreetMap contributors',
  })
}

const NER_CENTER: L.LatLngExpression = [26.2, 91.8]

export default function MapView({
  zones, infrastructure, sensors, historical, layers, selectedZoneId, onSelectZone, rain, pulses, volunteers,
}: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<L.Map | null>(null)
  const groups = useRef<Record<string, L.LayerGroup>>({})
  const selectRef = useRef(onSelectZone)
  selectRef.current = onSelectZone

  // --- init once ---------------------------------------------------------
  useEffect(() => {
    if (!hostRef.current || mapRef.current) return
    const map = L.map(hostRef.current, {
      center: NER_CENTER, zoom: 7, zoomControl: true, attributionControl: true,
    })
    createBaseLayer().addTo(map)
    mapRef.current = map
    groups.current = {
      risk: L.layerGroup().addTo(map),
      rain: L.layerGroup().addTo(map),
      roads: L.layerGroup().addTo(map),
      villages: L.layerGroup().addTo(map),
      sensors: L.layerGroup().addTo(map),
      historical: L.layerGroup().addTo(map),
      pulses: L.layerGroup().addTo(map),
      volunteers: L.layerGroup().addTo(map),
    }
    // The host is a flex cell on desktop but a fixed-height block on a phone.
    // Both change size without a window resize, which Leaflet does not notice
    // on its own — an uninvalidated map renders as grey tiles. pan:false keeps
    // the opening view from drifting on the observer's first callback.
    const ro = new ResizeObserver(() => map.invalidateSize({ pan: false }))
    ro.observe(hostRef.current)
    return () => { ro.disconnect(); map.remove(); mapRef.current = null }
  }, [])

  // --- zone choropleth ---------------------------------------------------
  useEffect(() => {
    const g = groups.current.risk
    if (!g || !zones?.features) return
    g.clearLayers()
    L.geoJSON(zones, {
      style: (feature: any) => {
        const p = feature.properties
        const sev = asSeverity(p.severity) as Severity
        const selected = p.id === selectedZoneId
        return {
          color: selected ? INK : 'rgba(20,40,36,.75)',
          weight: selected ? 3 : 1.5,
          fillColor: SEVERITY_FILL[sev] ?? SEVERITY_FILL.LOW,
          fillOpacity: sev === 'LOW' ? 0.55 : 0.72,
        }
      },
      onEachFeature: (feature: any, layer) => {
        const p = feature.properties
        layer.bindTooltip(
          `<strong>${p.code} — ${p.name}</strong><br>${p.district}, ${p.state}` +
          `<br>${p.severity}${p.risk_score != null ? ` · ${p.risk_score.toFixed(0)}/100` : ''}` +
          (p.confidence != null ? ` · ${(p.confidence * 100).toFixed(0)}% sure` : ''),
          { sticky: true },
        )
        layer.on('click', () => selectRef.current(p.id))
      },
    }).addTo(g)
  }, [zones, selectedZoneId])

  // --- rain overlay (one circle per zone, sized by the frame's mm) --------
  useEffect(() => {
    const g = groups.current.rain
    if (!g) return
    g.clearLayers()
    if (!rain || !zones?.features) return
    for (const f of zones.features) {
      const mm = rain[String(f.properties.id)] ?? 0
      if (mm <= 0.05) continue
      const [lat, lon] = f.properties.centroid
      L.circleMarker([lat, lon], {
        radius: Math.min(34, 4 + Math.sqrt(mm) * 7), color: '#0369A1', weight: 1,
        fillColor: '#0EA5E9', fillOpacity: 0.45, interactive: false,
      }).addTo(g)
    }
  }, [rain, zones])

  // --- roads -------------------------------------------------------------
  useEffect(() => {
    const g = groups.current.roads
    if (!g || !infrastructure?.roads) return
    g.clearLayers()
    L.geoJSON(infrastructure.roads, {
      style: (feature: any) => {
        const blocked = feature.properties.status === 'BLOCKED'
        const restricted = feature.properties.status === 'RESTRICTED'
        return {
          color: blocked ? '#DC2626' : restricted ? '#F97316' : '#5B6B66',
          weight: blocked ? 5 : feature.properties.criticality === 'lifeline' ? 3 : 2,
          opacity: blocked ? 1 : 0.7,
          dashArray: blocked ? '9 5' : undefined,
        }
      },
      onEachFeature: (feature: any, layer) => {
        const p = feature.properties
        layer.bindTooltip(
          `<strong>${p.name}</strong><br>${p.road_class} · ${p.length_km} km · ${p.criticality}` +
          `<br>Status: <strong>${p.status}</strong>${p.status_note ? `<br>${p.status_note}` : ''}`,
          { sticky: true },
        )
      },
    }).addTo(g)
  }, [infrastructure])

  // --- villages ----------------------------------------------------------
  useEffect(() => {
    const g = groups.current.villages
    if (!g || !infrastructure?.villages) return
    g.clearLayers()
    L.geoJSON(infrastructure.villages, {
      pointToLayer: (feature: any, latlng) => {
        const cut = feature.properties.is_cut_off
        return L.circleMarker(latlng, {
          radius: cut ? 7 : 4, color: '#1C2B27', weight: cut ? 2.5 : 1,
          fillColor: cut ? '#DC2626' : '#FFFFFF', fillOpacity: 1,
        })
      },
      onEachFeature: (feature: any, layer) => {
        const p = feature.properties
        layer.bindTooltip(
          `<strong>${p.name}</strong><br>${p.district} · pop ${p.population.toLocaleString()}` +
          (p.is_cut_off ? `<br><strong>CUT OFF</strong> — ${p.cut_off_reason}` : ''),
          { sticky: true },
        )
      },
    }).addTo(g)
  }, [infrastructure])

  // --- sensors -----------------------------------------------------------
  useEffect(() => {
    const g = groups.current.sensors
    if (!g || !sensors?.features) return
    g.clearLayers()
    L.geoJSON(sensors, {
      pointToLayer: (feature: any, latlng) => {
        const q = feature.properties
        const failed = q.status === 'FAILED'
        const live = !!q.live
        const colour = failed ? '#7A8580' : live ? '#22C55E' : q.source === 'hardware' ? '#FACC15' : INK
        const style = live
          ? `width:13px;height:13px;border-radius:50%;border:2px solid #fff;background:${colour};animation:live 1.6s ease-out infinite`
          : `width:12px;height:12px;border:2px solid #fff;box-shadow:0 0 0 1.5px ${colour};background:${failed ? 'transparent' : colour};transform:rotate(45deg);${failed ? 'opacity:.6' : ''}`
        return L.marker(latlng, {
          icon: L.divIcon({ className: '', iconSize: [13, 13], iconAnchor: [6.5, 6.5], html: `<div style="${style}"></div>` }),
        })
      },
      onEachFeature: (feature: any, layer) => {
        const p = feature.properties
        const latest = p.latest
        const kind = p.source === 'hardware' ? (p.live ? 'LIVE hardware' : 'hardware, not reporting') : 'simulated'
        layer.bindTooltip(
          `<strong>${p.node_id}</strong> — ${p.status} · ${kind}<br>${p.zone_name}` +
          (latest ? `<br>rain ${latest.rainfall_mm ?? '—'} mm · soil ${latest.soil_moisture_pct ?? '—'}%` +
                    `<br>tilt ${latest.tilt_deg ?? '—'}°` : '<br>no telemetry') +
          (p.note ? `<br><em>${p.note}</em>` : ''),
          { sticky: true },
        )
      },
    }).addTo(g)
  }, [sensors])

  // --- historical events (REAL, from NASA GLC / curated) ------------------
  useEffect(() => {
    const g = groups.current.historical
    if (!g || !historical?.features) return
    g.clearLayers()
    L.geoJSON(historical, {
      pointToLayer: (f: any, latlng) => L.circleMarker(latlng, {
        radius: f.properties.real ? 4 : 3, color: f.properties.real ? '#B45309' : '#7A8580', weight: 1, opacity: .8,
        fillColor: f.properties.real ? '#B45309' : '#7A8580', fillOpacity: .35,
      }),
      onEachFeature: (feature: any, layer) => {
        const p = feature.properties
        const when = p.occurred_at ? new Date(p.occurred_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : ''
        layer.bindTooltip(
          `<strong>${p.real ? 'REAL recorded landslide' : 'Simulated event'} — ${when}</strong>` +
          `<br>${p.title || ''}${p.state ? ` · ${p.state}` : ''}` +
          `<br>trigger: ${p.trigger || '—'}${p.fatalities ? ` · ${p.fatalities} fatalities` : ''}` +
          `<br><em>${p.real ? `source: ${p.source}` : 'synthetic development record'}</em>`,
          { sticky: true },
        )
      },
    }).addTo(g)
  }, [historical])

  // --- pulsing report markers --------------------------------------------
  useEffect(() => {
    const g = groups.current.pulses
    if (!g) return
    g.clearLayers()
    for (const q of pulses ?? []) {
      L.marker([q.lat, q.lon], {
        icon: L.divIcon({ className: '', iconSize: [14, 14], iconAnchor: [7, 7], html: '<div class="pulse-marker"></div>' }),
        interactive: false,
      }).addTo(g)
    }
  }, [pulses])

  // --- village volunteers: a person; grey when quiet in the rain, red at ALERT
  useEffect(() => {
    const g = groups.current.volunteers
    if (!g) return
    g.clearLayers()
    const esc = (v: unknown) => String(v ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]!))
    for (const v of volunteers ?? []) {
      const fill = v.stale ? '#7A8580' : v.level === 'alert' ? '#FFFFFF' : '#7FD1AE'
      const ring = v.level === 'alert' && !v.stale ? '#F87171' : fill
      const html = `<svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10.5" fill="#0F1A17" stroke="${ring}" stroke-width="2"/>`
        + `<circle cx="12" cy="8.5" r="3.2" fill="${fill}"/><path d="M6.5 18.5Q12 9.5 17.5 18.5Z" fill="${fill}"/></svg>`
      const last = v.last_mm == null ? 'no reading yet' : `last ${v.last_mm.toFixed(0)} mm · ${v.ago}`
      L.marker([v.lat, v.lon], { icon: L.divIcon({ className: '', iconSize: [24, 24], iconAnchor: [12, 12], html }), keyboard: false })
        .bindTooltip(`<strong>${esc(v.name)}</strong>${v.simulated ? ' · SIMULATED' : ''}<br>Village gauge at ${esc(v.place)}<br>`
          + `${v.total_24h.toFixed(0)} mm in 24 h · ${last}${v.stale ? '<br>No reading for 12 h while it is raining' : ''}`)
        .addTo(g)
    }
  }, [volunteers])

  // --- layer visibility --------------------------------------------------
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    ;(Object.keys(layers) as Array<keyof Layers>).forEach((key) => {
      const g = groups.current[key]
      if (!g) return
      if (layers[key]) { if (!map.hasLayer(g)) g.addTo(map) }
      else if (map.hasLayer(g)) map.removeLayer(g)
    })
  }, [layers])

  // --- pan to the selected zone -----------------------------------------
  useEffect(() => {
    const map = mapRef.current
    if (!map || selectedZoneId == null || !zones?.features) return
    const f = zones.features.find((x: any) => x.properties.id === selectedZoneId)
    if (!f) return
    const [lat, lon] = f.properties.centroid
    map.flyTo([lat, lon], Math.max(map.getZoom(), 10), { duration: 0.6 })
  }, [selectedZoneId, zones])

  return <div ref={hostRef} className="map-host" />
}
