/** Same palette as the dashboard: one navy accent, severity as a tint ramp. */
export const C = {
  navy: '#1F3864',
  navyInk: '#16294A',
  panel: '#EDF1F6',
  panelDeep: '#E2E9F1',
  line: '#D6DFEA',
  lineStrong: '#C2CFDE',
  text: '#22303F',
  muted: '#5C7EA4',
  faint: '#8A9EB5',
  white: '#FFFFFF',
}

export const SEVERITY_BG: Record<string, string> = {
  LOW: '#D6DFEA', MODERATE: '#A8BCD1', HIGH: '#5C7EA4', CRITICAL: '#1F3864',
}
export const SEVERITY_FG: Record<string, string> = {
  LOW: '#1F3864', MODERATE: '#1F3864', HIGH: '#FFFFFF', CRITICAL: '#FFFFFF',
}
