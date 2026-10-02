import { useEffect, useState } from 'react'
import type { LeagueReadiness, LeagueReadinessPayload } from '../../../lib/leagueReadiness'

export function useLeagueReadiness(league: string, enabled = true) {
  const [readiness, setReadiness] = useState<LeagueReadiness | null>(null)

  useEffect(() => {
    if (!enabled || !league) {
      setReadiness(null)
      return
    }
    let ignore = false
    const load = async () => {
      try {
        const response = await fetch('/api/readiness/leagues', { cache: 'no-store' })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const payload: LeagueReadinessPayload = await response.json()
        if (payload?.contract !== 'league-readiness-v3' || !Array.isArray(payload.leagues)) {
          throw new Error('Incompatible readiness response')
        }
        if (!ignore) {
          setReadiness(payload.leagues.find(row => row.league === league) ?? null)
        }
      } catch {
        if (!ignore) setReadiness(null)
      }
    }
    void load()
    return () => { ignore = true }
  }, [enabled, league])

  return readiness
}
