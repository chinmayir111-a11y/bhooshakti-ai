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

/**
 * Citizen header: layered hills, terraced fields and a hamlet on the ridge,
 * drawn for this project in a loose hand-inked style (slightly wobbly lines,
 * flat fills from the palette). Sliced, not stretched, so houses keep their
 * shape on any width; the text sits over the plain sky on the left.
 */
export function HillsHeader({ className }: { className?: string }) {
  const ink = { fill: 'none', stroke: '#1E3A25', strokeWidth: 1.3, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
  return (
    <svg className={className} viewBox="0 0 400 140" preserveAspectRatio="xMidYMax slice" aria-hidden="true">
      <rect width="400" height="140" fill="#2F5A3A" />
      {/* far range, misty */}
      <path d="M0 78C30 66 52 60 78 66s44 4 70-10 52-16 80-4 40 14 66 6 54-22 106-12V140H0z" fill="#4C7556" />
      <path d="M0 78C30 66 52 60 78 66s44 4 70-10 52-16 80-4 40 14 66 6 54-22 106-12" {...ink} opacity=".35" />
      {/* middle hill with terraces */}
      <path d="M-4 104C40 86 78 74 120 80c30 4 48 16 80 16s56-22 96-26 76 10 108 22V140H-4z" fill="#3B7A45" />
      <path d="M-4 104C40 86 78 74 120 80c30 4 48 16 80 16s56-22 96-26 76 10 108 22" {...ink} opacity=".55" />
      <path d="M232 92c22-8 42-13 64-14M226 100c26-9 50-14 76-14 22 0 44 5 62 11M224 108c30-8 58-12 86-11 26 1 48 6 70 13M228 116c32-6 62-8 92-6 22 2 44 6 62 11" {...ink} opacity=".45" />
      <path d="M40 104c18-6 36-10 54-11M30 112c24-7 48-10 72-10 14 0 28 2 40 5" {...ink} opacity=".4" />
      {/* hamlet on the ridge */}
      <g transform="translate(228 88)">
        <path d="M0 14V7l6-6 6 6v7z" fill="#F4F1EA" />
        <path d="M-1.5 7.5L6 0l7.5 7.5" fill="none" stroke="#B4532A" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
        <rect x="4.6" y="9" width="2.8" height="5" fill="#3E4C59" />
        <path d="M17 15V9.5l5-4.5 5 4.5V15z" fill="#F4F1EA" />
        <path d="M15.6 10l6.4-5.8 6.4 5.8" fill="none" stroke="#B4532A" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M31 16v-4l4-3.6 4 3.6v4z" fill="#E3B23C" />
        <path d="M29.8 12.6l5.2-4.6 5.2 4.6" fill="none" stroke="#8C3F1F" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M-6 15c12 1 30 1 50-1" {...ink} />
      </g>
      {/* a few trees */}
      <g fill="#24532D">
        <path d="M206 98c-3-5 0-12 3-14 3 2 6 9 3 14z" /><path d="M216 100c-2-4 0-9 2-11 2 2 5 7 2 11z" />
        <path d="M290 98c-3-5 0-12 3-14 3 2 6 9 3 14z" /><path d="M110 84c-2-4 0-9 2-11 2 2 5 7 2 11z" />
      </g>
      {/* front slope: terraced tea rows over red soil */}
      <path d="M-4 126c50-10 104-16 160-14 60 2 110 12 168 8 30-2 56-6 80-10V140H-4z" fill="#24532D" />
      <path d="M-4 134c56-8 120-11 180-9 62 2 118 9 228 1V140H-4z" fill="#B4532A" />
      <path d="M-4 126c50-10 104-16 160-14 60 2 110 12 168 8 30-2 56-6 80-10" {...ink} opacity=".7" />
      <path d="M20 128c18-3 36-5 52-5M96 123c20-2 40-2 58-1M190 121c24 1 46 3 70 4M300 122c20-1 40-3 60-6" fill="none" stroke="#3B7A45" strokeWidth="2" strokeLinecap="round" />
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

/* Small UI icons (24 px grid) — used instead of emoji or symbol glyphs, which
   render differently on every phone. */
type I = SVGProps<SVGSVGElement> & { size?: number }
function Icon({ size = 18, children, ...rest }: I) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ verticalAlign: '-0.2em', flex: '0 0 auto' }} {...rest}>
      {children}
    </svg>
  )
}
export const IconCheck = (p: I) => <Icon {...p}><path d="M5 12.5l4.5 4.5L19 7.5" /></Icon>
export const IconArrow = (p: I) => <Icon {...p}><path d="M5 12h14M13 6l6 6-6 6" /></Icon>
export const IconBack = (p: I) => <Icon {...p}><path d="M15 5l-7 7 7 7" /></Icon>
export const IconRefresh = (p: I) => <Icon {...p}><path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" /></Icon>
export const IconMail = (p: I) => <Icon {...p}><rect x="3" y="5.5" width="18" height="13" rx="2" /><path d="M3.5 7l8.5 6 8.5-6" /></Icon>
export const IconAlert = (p: I) => <Icon {...p}><path d="M12 3.5L22 20H2z" /><path d="M12 10v4.5M12 17.3v.2" /></Icon>
export const IconBell = (p: I) => <Icon {...p}><path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z" /><path d="M10 20.5a2 2 0 0 0 4 0" /></Icon>
export const IconBellOff = (p: I) => <Icon {...p}><path d="M6 16V11a6 6 0 0 1 9.5-4.9M18 11v5l1.5 2h-15" /><path d="M10 20.5a2 2 0 0 0 4 0M4 4l16 16" /></Icon>
export const IconSun = (p: I) => <Icon {...p}><circle cx="12" cy="12" r="4" /><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4" /></Icon>
export const IconMoon = (p: I) => <Icon {...p}><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" /></Icon>
export const IconPlay = (p: I) => <Icon {...p}><path d="M7 4.5v15l12-7.5z" fill="currentColor" /></Icon>
export const IconPause = (p: I) => <Icon {...p}><path d="M8 5v14M16 5v14" /></Icon>
export const IconExternal = (p: I) => <Icon {...p}><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></Icon>
export const IconChevron = (p: I) => <Icon {...p}><path d="M6 9l6 6 6-6" /></Icon>
export const IconGear = (p: I) => <Icon {...p}><circle cx="12" cy="12" r="3.2" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></Icon>
export const IconLayers = (p: I) => <Icon {...p}><path d="M12 3l9 5-9 5-9-5z" /><path d="M3 13l9 5 9-5M3 17l9 5 9-5" /></Icon>
export const IconPin = (p: I) => <Icon {...p}><path d="M12 21s-6.5-6.2-6.5-11a6.5 6.5 0 0 1 13 0c0 4.8-6.5 11-6.5 11z" /><circle cx="12" cy="10" r="2.4" /></Icon>
export const IconCompass = (p: I) => <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="M15.5 8.5l-2 5-5 2 2-5z" fill="currentColor" /></Icon>
export const IconPlus = (p: I) => <Icon {...p}><path d="M12 5v14M5 12h14" /></Icon>
export const IconMinus = (p: I) => <Icon {...p}><path d="M5 12h14" /></Icon>
