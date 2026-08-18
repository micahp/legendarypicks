import { useEffect, useState } from 'react'
import { SportsService } from '../../../services/sports'
import type { KnockoutRound, StandingGroup, TeamStats } from '../types'

// Leagues whose standings are conference-grouped ({group, rows}[]).
const GROUPED_LEAGUES = ['mls', 'ncaaf']

/**
 * MLS returns `{season, groups}`; NCAAF and the World Cup return a bare
 * `[{group, rows}]`. Read the groups out of either.
 */
function readGroups(payload: any): StandingGroup[] {
  if (payload && !Array.isArray(payload) && Array.isArray(payload.groups)) {
    return payload.groups as StandingGroup[]
  }
  const grouped = Array.isArray(payload)
    && payload.length > 0
    && typeof (payload[0] as any)?.group === 'string'
    && Array.isArray((payload[0] as any)?.rows)
  return grouped ? (payload as StandingGroup[]) : []
}

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
        } else if (GROUPED_LEAGUES.includes(league)) {
          // MLS / NCAAF — conference-grouped standings, in either the bare or
          // the season-named shape (see readStandings). A flat W-L body still
          // falls back to the team table.
          const standingsResponse = await fetch(`/api/${league}/standings`)
          // A 503 here is the endpoint refusing to serve a stale season rather
          // than a transport failure, and it carries a reason worth showing.
          if (!standingsResponse.ok) {
            const body = await standingsResponse.json().catch(() => null)
            throw new Error(body?.detail || 'Standings are unavailable.')
          }
          const standings = await standingsResponse.json()
          if (!ignore) {
            const parsed = readGroups(standings)
            if (parsed.length > 0) {
              setGroups(parsed)
              setTeams([])
            } else {
              setTeams(Array.isArray(standings) ? (standings as TeamStats[]) : [])
              setGroups([])
            }
          }
        } else {
          const strength = await SportsService.getStrength(league)
          if (!ignore) {
            setTeams(Array.isArray(strength) ? strength : [])
            setGroups([])
          }
        }
      } catch (err) {
        if (!ignore) {
          setError(err instanceof Error && err.message ? err.message : 'Unable to load standings.')
          setGroups([])
        }
      } finally {
        if (!ignore) setLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [league, isWorldCup, isUFC])

  return { teams, groups, knockout, loading, error }
}
