import { useEffect, useState } from 'react'
import { SportsService } from '../../../services/sports'
import type { KnockoutRound, StandingGroup, TeamStats } from '../types'

export function useStandingsData(
  league: string,
  isWorldCup: boolean,
  isUFC: boolean,
) {
  const [teams, setTeams] = useState<TeamStats[]>([])
  const [groups, setGroups] = useState<StandingGroup[]>([])
  const [knockout, setKnockout] = useState<KnockoutRound[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!league || isUFC) return
    let ignore = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        if (isWorldCup) {
          const knockoutResponse = await fetch('/api/wc/knockout')
          const knockoutData = await knockoutResponse.json()
          const rounds = Array.isArray(knockoutData)
            ? knockoutData
            : (knockoutData?.rounds ?? [])
          if (!ignore) {
            const hasMatches = Array.isArray(rounds)
              && rounds.length > 0
              && rounds.some((round: any) => round.matches?.length > 0)
            if (hasMatches) {
              setKnockout(rounds)
            } else {
              const standingsResponse = await fetch('/api/wc/standings')
              const standings = await standingsResponse.json()
              if (!ignore) setGroups(Array.isArray(standings) ? standings : [])
            }
          }
        } else {
          const strength = await SportsService.getStrength(league)
          if (!ignore) setTeams(Array.isArray(strength) ? strength : [])
        }
      } catch {
        if (!ignore) setError('Unable to load standings.')
      } finally {
        if (!ignore) setLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [league, isWorldCup, isUFC])

  return { teams, groups, knockout, loading, error }
}
