/** Control-room-wide switches: dark mode, "show data sources", sound. */
import { createContext, useContext } from 'react'

export interface ControlState {
  dark: boolean; setDark: (v: boolean) => void
  sources: boolean; setSources: (v: boolean) => void
  sound: boolean; setSound: (v: boolean) => void
}

export const ControlCtx = createContext<ControlState>({
  dark: false, setDark: () => {}, sources: false, setSources: () => {}, sound: false, setSound: () => {},
})

export const useControl = () => useContext(ControlCtx)
