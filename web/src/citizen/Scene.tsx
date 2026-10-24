/**
 * The citizen hero: an Eastern-Himalaya scene that changes with the risk
 * where the person is. Four ridge lines fade into the distance and drift a
 * little for depth, fog slides across the valleys, fine slanted rain falls
 * when the zone had rain in the last hour, and in a storm the sky darkens and
 * lightning flickers. Inline SVG + CSS only; every motion stops under
 * prefers-reduced-motion.
 *
 * The ridges are one wide drawing (1600 x 400 units) sliced from the bottom
 * centre, so a phone sees the middle of the range and a wide monitor sees
 * more of it — never stretched, never repeated.
 */
import { useMemo, type ReactNode } from 'react'
import type { SceneState } from './rain'

export const SCENE: Record<SceneState, { sky: string; ridges: [string, string, string, string]; dot: string; flash: boolean }> = {
  unknown: { sky: '#6F8C8A', ridges: ['#55776E', '#3B5C50', '#27443A', '#0F1A17'], dot: '#AEBDB6', flash: false },
  safe:    { sky: '#8FB3B0', ridges: ['#5E8478', '#3F6656', '#284A3C', '#0F1A17'], dot: '#4ADE80', flash: false },
  watch:   { sky: '#5E6E73', ridges: ['#4D5F5A', '#36493F', '#22352C', '#0F1A17'], dot: '#FACC15', flash: false },
  danger:  { sky: '#2B3236', ridges: ['#353F3D', '#26302C', '#1A2420', '#0F1A17'], dot: '#F87171', flash: true },
}

const W = 1600, H = 400

/** A jagged ridge across the full width: `n` peaks around `base`, up to `amp`
 *  high, with a deterministic wobble so it looks hand-placed, not periodic. */
function ridge(base: number, amp: number, n: number, seed: number): string {
  const pts: string[] = [`M0 ${base}`]
  const step = W / n
  for (let i = 0; i < n; i++) {
    const w1 = Math.sin(seed * 7.3 + i * 2.1), w2 = Math.cos(seed * 3.1 + i * 1.7)
    const px = Math.round(i * step + step * (0.42 + 0.16 * w1))        // peak
    const py = Math.round(base - amp * (0.55 + 0.45 * Math.abs(w2)))
    const vx = Math.round((i + 1) * step)                               // valley
    const vy = Math.round(base - amp * 0.18 * (1 + w1))
    pts.push(`L${px} ${py}`, `L${vx} ${i === n - 1 ? base : vy}`)
  }
  pts.push(`V${H} H0Z`)
  return pts.join(' ')
}

const PATHS = [
  ridge(235, 95, 13, 1),   // far range, tallest
  ridge(285, 60, 10, 2),
  ridge(330, 36, 8, 3),
  `M0 378 Q${W * 0.25} 352 ${W * 0.5} 370 T${W} 362 V${H} H0Z`,   // foreground bank
]

export default function Scene({ state, raining, compact = false, children }: {
  state: SceneState; raining: boolean; compact?: boolean; children: ReactNode
}) {
  const s = SCENE[state]
  // Fixed pseudo-random streaks so they don't jump between renders.
  const streaks = useMemo(() => Array.from({ length: 70 }, (_, i) => ({
    left: `${(i * 37) % 112 - 6}%`, dur: `${(0.55 + ((i * 29) % 35) / 100).toFixed(2)}s`, delay: `-${((i * 53) % 100) / 100}s`,
  })), [])
  return (
    <div className={`scene${compact ? ' compact' : ''}`} style={{ background: s.sky }}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMax slice" aria-hidden="true">
        {PATHS.map((d, i) => (
          <g key={i} className={i === 0 ? 'p1' : i === 1 ? 'p2' : undefined}>
            <path className="ridge" fill={s.ridges[i]} d={d} />
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
      <div className="scene-inner">{children}</div>
    </div>
  )
}

/** The pulsing dot beside the risk word. */
export function Dot({ state }: { state: SceneState }) {
  const c = SCENE[state].dot
  return <span className="dot" style={{ background: c, ['--g' as any]: c }} aria-hidden="true" />
}
