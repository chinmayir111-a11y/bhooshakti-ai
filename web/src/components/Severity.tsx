/**
 * Severity, three ways at once: colour, shape and icon.
 *
 *   LOW       green  circle   ✓
 *   MODERATE  yellow triangle !
 *   HIGH      orange diamond  ⚠
 *   CRITICAL  red    octagon  ✕  (pulses)
 *
 * A colour-blind operator reads the shape; someone who cannot read gets the
 * icon; everyone else gets all three. Never render severity as colour alone.
 */
import type { Severity } from '../api/client'

export const SEVERITY_FILL: Record<Severity, string> = {
  LOW: '#22C55E', MODERATE: '#FACC15', HIGH: '#F97316', CRITICAL: '#DC2626',
}
export const SEVERITY_INK: Record<Severity, string> = {
  LOW: '#15803D', MODERATE: '#854D0E', HIGH: '#C2410C', CRITICAL: '#B91C1C',
}
export const SEVERITY_FG: Record<Severity, string> = {
  LOW: '#052E16', MODERATE: '#422006', HIGH: '#431407', CRITICAL: '#FFFFFF',
}
export const SEVERITY_ORDER: Severity[] = ['CRITICAL', 'HIGH', 'MODERATE', 'LOW']
export const SEVERITY_RANK: Record<Severity, number> = { LOW: 0, MODERATE: 1, HIGH: 2, CRITICAL: 3 }

export function asSeverity(v: unknown): Severity {
  return (typeof v === 'string' && v in SEVERITY_FILL ? v : 'LOW') as Severity
}

/** Shape + icon glyph, scalable. `fill` defaults to the severity colour. */
export function SeverityShape({ value, size = 16, fill, stroke, title }: {
  value: Severity; size?: number; fill?: string; stroke?: string; title?: string
}) {
  const f = fill ?? SEVERITY_FILL[value]
  const g = SEVERITY_FG[value]
  const s = stroke ?? 'rgba(0,0,0,.18)'
  const common = { fill: f, stroke: s, strokeWidth: 1 }
  const glyph = { stroke: g, strokeWidth: 2.2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, fill: 'none' }
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden={!title} role={title ? 'img' : undefined}>
      {title && <title>{title}</title>}
      {value === 'LOW' && <>
        <circle cx="12" cy="12" r="10.5" {...common} />
        <path d="M7.5 12.5l3 3 6-7" {...glyph} />
      </>}
      {value === 'MODERATE' && <>
        <path d="M12 2.5L22.5 21H1.5z" {...common} />
        <path d="M12 9v5.5" {...glyph} /><circle cx="12" cy="17.6" r="1.2" fill={g} />
      </>}
      {value === 'HIGH' && <>
        <path d="M12 1.5L22.5 12 12 22.5 1.5 12z" {...common} />
        <path d="M12 7.5v5.5" {...glyph} /><circle cx="12" cy="16.3" r="1.2" fill={g} />
      </>}
      {value === 'CRITICAL' && <>
        <path d="M7.8 1.5h8.4l6.3 6.3v8.4l-6.3 6.3H7.8l-6.3-6.3V7.8z" {...common} />
        <path d="M8.5 8.5l7 7M15.5 8.5l-7 7" {...glyph} />
      </>}
    </svg>
  )
}

/** Compact chip: shape + word. Use everywhere a severity label appears. */
export function SeverityChip({ value, size = 14, label }: { value: Severity | string; size?: number; label?: string }) {
  const sev = asSeverity(value)
  return (
    <span className={`sevmark ${sev}`} style={{ color: `var(--sev-${sev.toLowerCase()}-ink, ${SEVERITY_INK[sev]})`, fontSize: Math.max(10.5, size - 3) }}>
      <SeverityShape value={sev} size={size} />
      {label ?? sev}
    </span>
  )
}

/** What the API tiers are called on screen. API values never change. */
export const TIER_LABEL: Record<string, string> = { ADVISORY: 'Be alert (unconfirmed)', WARNING: 'Danger (confirmed)' }
export const TIER_SHORT: Record<string, string> = { ADVISORY: 'Be alert', WARNING: 'Danger' }
const STATUS_LABEL: Record<string, string> = { RESOLVED: 'resolved', CANCELLED: 'cancelled', EXPIRED: 'expired', SUPERSEDED: 'superseded' }

/** ADVISORY (machine, unconfirmed) vs WARNING (human-confirmed / model CRITICAL). */
export function TierChip({ tier, status }: { tier?: string; status?: string }) {
  const tr = tier === 'ADVISORY' ? 'ADVISORY' : 'WARNING'
  const closed = status && status !== 'ACTIVE'
  return (
    <span className={`tier tier-${tr}${closed ? ' closed' : ''}`}
          title={tr === 'ADVISORY' ? 'Issued by the system from unverified evidence (API tier ADVISORY)' : 'Confirmed by an officer, or model CRITICAL (API tier WARNING)'}>
      {TIER_LABEL[tr]}{closed ? ` · ${STATUS_LABEL[status!] ?? status!.toLowerCase()}` : ''}
    </span>
  )
}
