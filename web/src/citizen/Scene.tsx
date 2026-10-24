/**
 * The citizen header: an Eastern-Himalaya scene that changes with the risk
 * where the person is. Four ridge lines fade into the distance and drift a
 * little for depth, fog slides across the valleys, fine slanted rain falls
 * when the zone had rain in the last hour, and in a storm the sky darkens and
 * lightning flickers. Inline SVG + CSS only; every motion stops under
 * prefers-reduced-motion. The risk is one big word with a pulsing dot.
 */
import { useMemo, type ReactNode } from 'react'
import type { SceneState } from './rain'

export const SCENE: Record<SceneState, { sky: string; ridges: [string, string, string, string]; dot: string; flash: boolean }> = {
  unknown: { sky: '#6F8C8A', ridges: ['#55776E', '#3B5C50', '#27443A', '#0F1A17'], dot: '#AEBDB6', flash: false },
  safe:    { sky: '#8FB3B0', ridges: ['#5E8478', '#3F6656', '#284A3C', '#0F1A17'], dot: '#4ADE80', flash: false },
  watch:   { sky: '#5E6E73', ridges: ['#4D5F5A', '#36493F', '#22352C', '#0F1A17'], dot: '#FACC15', flash: false },
  danger:  { sky: '#2B3236', ridges: ['#353F3D', '#26302C', '#1A2420', '#0F1A17'], dot: '#F87171', flash: true },
}

export default function Scene({ state, raining, compact = false, top, big }: {
  state: SceneState; raining: boolean; compact?: boolean; top: ReactNode; big?: ReactNode
}) {
  const s = SCENE[state]
  // Fixed pseudo-random streaks so they don't jump between renders.
  const streaks = useMemo(() => Array.from({ length: 46 }, (_, i) => ({
    left: `${(i * 37) % 112 - 6}%`, dur: `${(0.5 + ((i * 29) % 35) / 100).toFixed(2)}s`, delay: `-${((i * 53) % 100) / 100}s`,
  })), [])
  return (
    <div className={`scene${compact ? ' compact' : ''}`} style={{ background: s.sky }}>
      {/* One 300-unit ridge period, tiled five times with mirrored copies so
          the seams join, and sliced from the bottom: on a phone you see one
          period, on a desktop the range keeps its shape instead of stretching. */}
      <svg viewBox="0 0 1500 250" preserveAspectRatio="xMidYMax slice" aria-hidden="true">
        <defs>
          <path id="r1" d="M-20 150 L20 118 L48 132 L92 92 L128 120 L160 100 L200 128 L236 96 L272 118 L320 104 V250 H-20Z" />
          <path id="r2" d="M-20 176 L30 150 L70 166 L110 140 L150 162 L196 136 L240 160 L280 146 L320 158 V250 H-20Z" />
          <path id="r3" d="M-20 206 L40 182 L90 198 L140 178 L190 200 L240 184 L320 200 V250 H-20Z" />
          <path id="r4" d="M-20 236 Q60 214 150 228 T320 222 V250 H-20Z" />
        </defs>
        {/* Each ridge line is one layer (so its drift moves every tile together). */}
        {(['r1', 'r2', 'r3', 'r4'] as const).map((id, li) => (
          <g key={id} className={li === 0 ? 'p1' : li === 1 ? 'p2' : undefined} fill={s.ridges[li]} style={{ transition: 'fill 1.2s' }}>
            {[0, 1, 2, 3, 4].map((k) => (
              <use key={k} href={`#${id}`} transform={k % 2 ? `translate(${300 * (k + 1)} 0) scale(-1 1)` : `translate(${300 * k} 0)`} />
            ))}
          </g>
        ))}
      </svg>
      <div className="fog" style={{ top: '48%', animationDuration: '38s' }} />
      <div className="fog" style={{ top: '64%', animationDuration: '52s', animationDirection: 'reverse', opacity: .8 }} />
      <div className="fog" style={{ top: '79%', animationDuration: '44s' }} />
      <div className={`rain${raining ? ' on' : ''}`} aria-hidden="true">
        {streaks.map((d, i) => <i key={i} style={{ left: d.left, animationDuration: d.dur, animationDelay: d.delay }} />)}
      </div>
      <div className={`flash${s.flash ? ' on' : ''}`} aria-hidden="true" />
      <div className="scene-top">{top}</div>
      {big && <div className="scene-big">{big}</div>}
    </div>
  )
}

/** The pulsing dot beside the risk word. */
export function Dot({ state }: { state: SceneState }) {
  const c = SCENE[state].dot
  return <span className="dot" style={{ background: c, ['--g' as any]: c }} aria-hidden="true" />
}
