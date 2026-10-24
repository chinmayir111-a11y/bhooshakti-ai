/**
 * Pictograms for people who cannot read. Inline SVG, drawn for this project
 * (no icon fonts, no copyrighted sets), bold strokes that survive a cheap
 * 360 px screen. Each takes `size` and inherits colour from `currentColor`
 * unless it paints its own.
 */
import type { SVGProps } from 'react'

type P = SVGProps<SVGSVGElement> & { size?: number }

function Svg({ size = 64, children, ...rest }: P) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" stroke="currentColor"
         strokeWidth={3.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...rest}>
      {children}
    </svg>
  )
}

/** A hillside letting go: slope line, falling boulders, debris fan. */
export function PictoLandslide(p: P) {
  return (
    <Svg {...p}>
      <path d="M4 52L26 14l8 10" />
      <path d="M34 24c6 4 10 12 12 20" strokeDasharray="4 5" />
      <circle cx="30" cy="34" r="4" fill="currentColor" stroke="none" />
      <circle cx="40" cy="42" r="3" fill="currentColor" stroke="none" />
      <circle cx="22" cy="44" r="2.5" fill="currentColor" stroke="none" />
      <path d="M8 56h50M14 52h40M20 48h30" />
      <path d="M50 20c4-3 8-3 10 0" />
    </Svg>
  )
}

/** Road with a debris heap across it and a barrier. */
export function PictoRoadBlocked(p: P) {
  return (
    <Svg {...p}>
      <path d="M10 58L24 8M54 58L40 8" />
      <path d="M32 50v-6M32 36v-6M32 22v-6" strokeDasharray="1 6" />
      <path d="M18 42h28" />
      <circle cx="24" cy="36" r="4" fill="currentColor" stroke="none" />
      <circle cx="33" cy="32" r="5" fill="currentColor" stroke="none" />
      <circle cx="41" cy="37" r="3.5" fill="currentColor" stroke="none" />
      <path d="M12 16h40M14 10l4 6M26 10l4 6M38 10l4 6" />
    </Svg>
  )
}

/** Ground with a widening crack, a house on the edge. */
export function PictoCrack(p: P) {
  return (
    <Svg {...p}>
      <path d="M4 44h56" />
      <path d="M26 44l4 6-3 6 5 4" />
      <path d="M26 44l-3-8 5-6-4-8 3-6" />
      <path d="M38 44v-14h12v14" />
      <path d="M36 30l8-8 8 8" />
    </Svg>
  )
}

/** Trees and a pole leaning downhill — the classic creep sign. */
export function PictoTiltedTrees(p: P) {
  return (
    <Svg {...p}>
      <path d="M4 54L60 40" />
      <path d="M16 50l6-22" />
      <path d="M22 28l-8 4 4-10 6-2-1-8 6 6 5-4-2 9 6 3-9 4z" fill="currentColor" stroke="none" opacity=".9" />
      <path d="M40 46l5-30" />
      <path d="M42 18h8M44 22h8" />
      <path d="M36 20a6 6 0 0 1 10-4" strokeDasharray="2 4" />
    </Svg>
  )
}

/** Stream turning brown: wavy water with sediment dots. */
export function PictoMuddyWater(p: P) {
  return (
    <Svg {...p}>
      <path d="M6 30c6-6 12 6 18 0s12 6 18 0 12 6 16 0" />
      <path d="M6 42c6-6 12 6 18 0s12 6 18 0 12 6 16 0" />
      <path d="M6 54c6-6 12 6 18 0s12 6 18 0 12 6 16 0" />
      <circle cx="18" cy="36" r="1.8" fill="currentColor" stroke="none" />
      <circle cx="30" cy="48" r="1.8" fill="currentColor" stroke="none" />
      <circle cx="44" cy="36" r="1.8" fill="currentColor" stroke="none" />
      <circle cx="52" cy="48" r="1.8" fill="currentColor" stroke="none" />
      <path d="M14 18l8-8M22 18l8-8M30 18l8-8" opacity=".6" />
    </Svg>
  )
}

/** Person moving away from a slope, arrow uphill-sideways. */
export function PictoEvacuate(p: P) {
  return (
    <Svg {...p}>
      <path d="M4 56L30 20" />
      <circle cx="42" cy="18" r="5" />
      <path d="M42 24v14l-8 14M42 38l8 14M34 30l8-4 10 4" />
      <path d="M8 18h18M20 12l6 6-6 6" />
    </Svg>
  )
}

/** Camera, for the "take a photo" step. */
export function PictoCamera(p: P) {
  return (
    <Svg {...p}>
      <rect x="6" y="18" width="52" height="34" rx="6" />
      <path d="M22 18l4-7h12l4 7" />
      <circle cx="32" cy="35" r="9" />
      <circle cx="48" cy="26" r="1.5" fill="currentColor" stroke="none" />
    </Svg>
  )
}

export function PictoMic(p: P) {
  return (
    <Svg {...p}>
      <rect x="24" y="8" width="16" height="30" rx="8" />
      <path d="M14 30a18 18 0 0 0 36 0M32 48v8M22 56h20" />
    </Svg>
  )
}

export function PictoPhone(p: P) {
  return (
    <Svg {...p}>
      <path d="M18 8h10l5 12-7 5a28 28 0 0 0 13 13l5-7 12 5v10a6 6 0 0 1-6 6C27 52 12 37 12 14a6 6 0 0 1 6-6z" />
    </Svg>
  )
}

export function PictoSpeaker(p: P) {
  return (
    <Svg {...p}>
      <path d="M10 24h10l12-10v36L20 40H10z" fill="currentColor" stroke="none" />
      <path d="M40 24a10 10 0 0 1 0 16M46 17a19 19 0 0 1 0 30" />
    </Svg>
  )
}

export function PictoPin(p: P) {
  return (
    <Svg {...p}>
      <path d="M32 58S12 38 12 24a20 20 0 0 1 40 0c0 14-20 34-20 34z" />
      <circle cx="32" cy="24" r="7" />
    </Svg>
  )
}

export function PictoShield(p: P) {
  return (
    <Svg {...p}>
      <path d="M32 6l22 8v16c0 14-10 24-22 28C20 54 10 44 10 30V14z" />
      <path d="M22 32l7 7 13-14" />
    </Svg>
  )
}

/** Soft rolling hills for the citizen header. Paints its own colours. */
export function HillsHeader({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 400 120" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#0F766E" /><stop offset="1" stopColor="#14B8A6" />
        </linearGradient>
      </defs>
      <rect width="400" height="120" fill="url(#sky)" />
      <path d="M0 95C60 60 110 55 170 80s120 30 230-25V120H0z" fill="#0D9488" opacity=".75" />
      <path d="M0 110C70 85 130 70 200 92s130 20 200-15V120H0z" fill="#115E59" />
      <path d="M0 120C80 100 150 96 230 108s110 6 170-10V120z" fill="#B45309" opacity=".85" />
    </svg>
  )
}

export const ISSUE_PICTOS = {
  landslide: PictoLandslide,
  road_blockage: PictoRoadBlocked,
  crack: PictoCrack,
  tilted_trees: PictoTiltedTrees,
  muddy_water: PictoMuddyWater,
  evacuate: PictoEvacuate,
} as const
