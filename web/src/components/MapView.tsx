/**
 * The map layer.
 *
 * Leaflet + OpenStreetMap by default — no token, works offline-ish, and is
 * what the demo runs on. The tile layer is isolated behind `createBaseLayer`
 * so Mapbox GL JS can be swapped in when VITE_MAPBOX_TOKEN is present without
 * touching any of the overlay logic below.
 */
import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { SEVERITY_FILL } from './common'
import type { Severity } from '../api/client'

const MAPBOX_TOKEN = (import.meta.env.VITE_MAPBOX_TOKEN as string) || ''

export interface Layers {
  risk: boolean; roads: boolean; villages: boolean
  sensors: boolean; historical: boolean
}

interface Props {
  zones: any
  infrastructure: any
  sensors: any
  historical: any
  layers: Layers
  selectedZoneId: number | null
  onSelectZone: (id: number) => void
}

function createBaseLayer(): L.TileLayer {
  if (MAPBOX_TOKEN) {
    // Mapbox raster tiles keep the same L.TileLayer contract, so the overlay
    // code is identical. Swapping to Mapbox GL JS vector tiles would replace
    // only this function and the map constructor.
    return L.tileLayer(
      `https://api.mapbox.com/styles/v1/mapbox/light-v11/tiles/{z}/{x}/{y}?access_token=${MAPBOX_TOKEN}`,
      { tileSize: 512, zoomOffset: -1, maxZoom: 18, attribution: '© Mapbox © OpenStreetMap' },
    )
  }
  return L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18, attribution: '© OpenStreetMap contributors',
  })
}

const NER_CENTER: L.LatLngExpression = [26.2, 91.8]

export default function MapView({
  zones, infrastructure, sensors, historical, layers, selectedZoneId, onSelectZone,
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
      roads: L.layerGroup().addTo(map),
      villages: L.layerGroup().addTo(map),
      sensors: L.layerGroup().addTo(map),
      historical: L.layerGroup().addTo(map),
    }
    return () => { map.remove(); mapRef.current = null }
  }, [])

  // --- zone choropleth ---------------------------------------------------
  useEffect(() => {
    const g = groups.current.risk
    if (!g || !zones?.features) return
    g.clearLayers()

    L.geoJSON(zones, {
      style: (feature: any) => {
        const p = feature.properties
        const sev = (p.severity || 'LOW') as Severity
        const selected = p.id === selectedZoneId
        return {
          color: selected ? '#1F3864' : 'rgba(31,56,100,.45)',
          weight: selected ? 2.5 : 1,
          fillColor: SEVERITY_FILL[sev] ?? SEVERITY_FILL.LOW,
          fillOpacity: sev === 'LOW' ? 0.5 : 0.72,
        }
      },
      onEachFeature: (feature: any, layer) => {
        const p = feature.properties
        layer.bindTooltip(
          `<strong>${p.code} — ${p.name}</strong><br>${p.district}, ${p.state}` +
          `<br>${p.severity}${p.risk_score != null ? ` · ${p.risk_score.toFixed(0)}/100` : ''}` +
          (p.confidence != null ? ` · confidence ${(p.confidence * 100).toFixed(0)}%` : ''),
          { sticky: true },
        )
        layer.on('click', () => selectRef.current(p.id))
      },
    }).addTo(g)
  }, [zones, selectedZoneId])

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
          color: blocked ? '#1F3864' : restricted ? '#5C7EA4' : '#5C7EA4',
          weight: blocked ? 5 : feature.properties.criticality === 'lifeline' ? 3 : 2,
          opacity: blocked ? 1 : 0.62,
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
          radius: cut ? 7 : 4,
          color: '#1F3864',
          weight: cut ? 2.5 : 1,
          fillColor: cut ? '#1F3864' : '#FFFFFF',
          fillOpacity: 1,
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
        const failed = feature.properties.status === 'FAILED'
        return L.marker(latlng, {
          icon: L.divIcon({
            className: '',
            iconSize: [11, 11],
            iconAnchor: [5.5, 5.5],
            html: `<div style="width:11px;height:11px;border:1.5px solid #1F3864;background:${
              failed ? 'transparent' : '#1F3864'
            };transform:rotate(45deg);${failed ? 'opacity:.55' : ''}"></div>`,
          }),
        })
      },
      onEachFeature: (feature: any, layer) => {
        const p = feature.properties
        const latest = p.latest
        layer.bindTooltip(
          `<strong>${p.node_id}</strong> — ${p.status}<br>${p.zone_name}` +
          (latest ? `<br>rain ${latest.rainfall_mm ?? '—'} mm · soil ${latest.soil_moisture_pct ?? '—'}%` +
                    `<br>tilt ${latest.tilt_deg ?? '—'}°` : '<br>no telemetry') +
          (p.note ? `<br><em>${p.note}</em>` : ''),
          { sticky: true },
        )
      },
    }).addTo(g)
  }, [sensors])

  // --- historical events -------------------------------------------------
  useEffect(() => {
    const g = groups.current.historical
    if (!g || !historical?.features) return
    g.clearLayers()

    L.geoJSON(historical, {
      pointToLayer: (_f: any, latlng) => L.circleMarker(latlng, {
        radius: 3, color: '#1F3864', weight: 1, opacity: .55,
        fillColor: '#1F3864', fillOpacity: .28,
      }),
      onEachFeature: (feature: any, layer) => {
        const p = feature.properties
        const when = p.occurred_at ? new Date(p.occurred_at).toLocaleDateString(undefined, { month: 'short', year: 'numeric' }) : ''
        layer.bindTooltip(
          `<strong>Recorded event — ${when}</strong><br>${p.zone_name}` +
          `<br>72h rainfall ${p.rainfall_72h} mm · soil ${p.soil_moisture_pct}%` +
          `<br>trigger: ${p.trigger}${p.fatalities ? ` · ${p.fatalities} fatalities` : ''}` +
          `<br><em>simulated record</em>`,
          { sticky: true },
        )
      },
    }).addTo(g)
  }, [historical])

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

  return <div ref={hostRef} style={{ height: '100%', width: '100%' }} />
}
