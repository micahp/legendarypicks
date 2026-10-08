import { useEffect, useState } from 'react'

/**
 * Live MLB/NBA cards whose radio is a blackout loop right now, from
 * GET /api/radio/blackouts (backend/radio_blackout_check.py samples each stream
 * every 5 minutes). One request shared by every card on the page, refreshed
 * every 2 minutes. A stale or failed check returns no games, so no label.
 */
type Blackouts = Record<string, boolean>

let cache: { at: number; games: Blackouts } | null = null
let inflight: Promise<Blackouts> | null = null
const listeners = new Set<(g: Blackouts) => void>()
const REFRESH_MS = 2 * 60 * 1000

function load(): Promise<Blackouts> {
  if (cache && Date.now() - cache.at < REFRESH_MS) return Promise.resolve(cache.games)
  if (inflight) return inflight
  if (typeof fetch !== 'function') return Promise.resolve({})
  inflight = fetch('/api/radio/blackouts')
    .then((r) => (r.ok ? r.json() : { games: {} }))
    .catch(() => ({ games: {} }))
    .then((d) => {
      const games: Blackouts = {}
      for (const [id, g] of Object.entries(d.games || {})) games[id] = !!(g as { blackout?: boolean }).blackout
      cache = { at: Date.now(), games }
      inflight = null
      listeners.forEach((fn) => fn(games))
      return games
    })
  return inflight
}

export function useRadioBlackout(gameId: string | undefined, enabled: boolean): boolean {
  const [games, setGames] = useState<Blackouts>(cache?.games ?? {})
  useEffect(() => {
    if (!enabled) return
    listeners.add(setGames)
    load().then(setGames)
    const t = setInterval(() => load(), REFRESH_MS)
    return () => {
      listeners.delete(setGames)
      clearInterval(t)
    }
  }, [enabled])
  return !!(gameId && games[gameId])
}
