import { useEffect, useState } from 'react'
import { normalizeGame, type Game } from '../../../services/sports'

export type NflScoreboardState = {
  games: Game[]
  source: string | null
  age: number | null
  loading: boolean
  unavailable: boolean
}

function todayLocal() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

export function useNflScoreboard(enabled = true): NflScoreboardState {
  const [scores, setScores] = useState<NflScoreboardState>(
    { games: [], source: null, age: null, loading: true, unavailable: false },
  )

  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    let refreshing = false
    const load = async () => {
      if (refreshing || controller.signal.aborted) return
      refreshing = true
      try {
        const response = await fetch(`/api/nfl/games?date=${todayLocal()}`, { cache: 'no-store', signal: controller.signal })
        if (!response.ok) throw new Error(String(response.status))
        const payload = await response.json()
        const games = Array.isArray(payload) ? payload.map((game: unknown) => normalizeGame(game, 'nfl')) : []
        const source = response.headers.get('x-lp-data-source')
        const age = Number(response.headers.get('x-lp-data-age'))
        setScores({ games, source, age: Number.isFinite(age) && age > 0 ? age : null, loading: false, unavailable: source === 'unavailable' })
      } catch {
        if (!controller.signal.aborted) setScores({ games: [], source: null, age: null, loading: false, unavailable: true })
      } finally {
        refreshing = false
      }
    }
    const refreshWhenVisible = () => {
      if (document.visibilityState === 'visible') void load()
    }
    void load()
    const interval = window.setInterval(refreshWhenVisible, 60_000)
    document.addEventListener('visibilitychange', refreshWhenVisible)
    return () => {
      controller.abort()
      window.clearInterval(interval)
      document.removeEventListener('visibilitychange', refreshWhenVisible)
    }
  }, [enabled])

  return scores
}
