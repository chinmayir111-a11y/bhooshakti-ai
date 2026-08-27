/** Live channel. Single socket, auto-reconnecting, shared by every screen. */
import { useEffect, useRef, useState } from 'react'

export const WS_URL: string =
  (import.meta.env.VITE_WS_URL as string) || 'ws://localhost:8000/ws/live'

export interface LiveMessage { event: string; payload: any; ts?: string }
type Handler = (m: LiveMessage) => void

class LiveChannel {
  private socket: WebSocket | null = null
  private handlers = new Set<Handler>()
  private retry = 0
  private timer: number | null = null
  private keepAlive: number | null = null
  connected = false

  subscribe(fn: Handler): () => void {
    this.handlers.add(fn)
    this.open()
    return () => {
      this.handlers.delete(fn)
      if (this.handlers.size === 0) this.close()
    }
  }

  private open() {
    if (this.socket && (this.socket.readyState === WebSocket.OPEN ||
                        this.socket.readyState === WebSocket.CONNECTING)) return
    try { this.socket = new WebSocket(WS_URL) } catch { this.scheduleRetry(); return }

    this.socket.onopen = () => {
      this.connected = true
      this.retry = 0
      this.emit({ event: 'ws.open', payload: {} })
      // Some proxies drop idle sockets; a periodic ping keeps the path warm.
      this.keepAlive = window.setInterval(() => {
        if (this.socket?.readyState === WebSocket.OPEN) this.socket.send('ping')
      }, 25000)
    }
    this.socket.onmessage = (ev) => {
      try { this.emit(JSON.parse(ev.data) as LiveMessage) } catch { /* ignore junk frames */ }
    }
    this.socket.onclose = () => {
      this.connected = false
      this.clearKeepAlive()
      this.emit({ event: 'ws.close', payload: {} })
      if (this.handlers.size > 0) this.scheduleRetry()
    }
    this.socket.onerror = () => { try { this.socket?.close() } catch { /* ignore */ } }
  }

  private scheduleRetry() {
    if (this.timer) return
    const delay = Math.min(1000 * 2 ** this.retry++, 15000)
    this.timer = window.setTimeout(() => { this.timer = null; this.open() }, delay)
  }

  private clearKeepAlive() {
    if (this.keepAlive) { clearInterval(this.keepAlive); this.keepAlive = null }
  }

  private close() {
    this.clearKeepAlive()
    if (this.timer) { clearTimeout(this.timer); this.timer = null }
    try { this.socket?.close() } catch { /* ignore */ }
    this.socket = null
    this.connected = false
  }

  private emit(m: LiveMessage) { this.handlers.forEach((h) => { try { h(m) } catch { /* one bad handler must not stop the rest */ } }) }
}

export const live = new LiveChannel()

/** Subscribe to the live channel for the lifetime of a component. */
export function useLive(onMessage: (m: LiveMessage) => void) {
  const ref = useRef(onMessage)
  ref.current = onMessage
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    return live.subscribe((m) => {
      if (m.event === 'ws.open') setConnected(true)
      else if (m.event === 'ws.close') setConnected(false)
      ref.current(m)
    })
  }, [])

  return connected
}
