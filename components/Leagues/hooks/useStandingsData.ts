import { useEffect, useState } from 'react'
import { SportsService } from '../../../services/sports'
import type { KnockoutRound, StandingGroup, StandingsSeason, TeamStats } from '../types'

const NO_SEASON: StandingsSeason = {
  season: null, seasonLabel: null, phase: null, inProgress: null, asOf: null,
}

/**
 * Standings arrive in two shapes, and the difference is whether the endpoint
 * knows which season it is serving.
 *
 *   bare  `[{group, rows}]`                    — NCAAF, World Cup: no season stated
 *   named `{season, phase, in_progress, groups}` — MLS since 2026-08-17
 *
 * Read the named shape when it is offered and fall back to the bare one, so a
 * league adopting the season envelope needs no change here. A bare response
 * yields NO_SEASON, which the table renders as "season not stated" — never as a
 * guess, and never as silence.
 */
function readStandings(payload: any): { groups: StandingGroup[]; season: StandingsSeason } {
  if (payload && !Array.isArray(payload) && Array.isArray(payload.groups)) {
    return {
      groups: payload.groups as StandingGroup[],
      season: {
        season: payload.season ?? null,
        seasonLabel: payload.season_label ?? null,
        phase: payload.phase ?? null,
        inProgress: payload.in_progress ?? null,
        asOf: payload.as_of ?? null,
      },
    }
  }
  const grouped = Array.isArray(payload)
    && payload.length > 0
    && typeof (payload[0] as any)?.group === 'string'
    && Array.isArray((payload[0] as any)?.rows)
  return { groups: grouped ? (payload as StandingGroup[]) : [], season: NO_SEASON }
}

// Leagues whose standings are conference-grouped ({group, rows}[]). The
// backend serves that shape once their standings route lands; until then the
// same endpoint returns flat W-L rows and we fall back to the team table.
const GROUPED_LEAGUES = ['mls', 'ncaaf']

export function useStandingsData(
  league: string,
  isWorldCup: boolean,
  isUFC: boolean,
) {
  const [teams, setTeams] = useState<TeamStats[]>([])
  const [groups, setGroups] = useState<StandingGroup[]>([])
  const [knockout, setKnockout] = useState<KnockoutRound[]>([])
  const [season, setSeason] = useState<StandingsSeason>(NO_SEASON)
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
            const read = readStandings(standings)
            if (read.groups.length > 0) {
              setGroups(read.groups)
              setSeason(read.season)
              setTeams([])
            } else {
              setTeams(Array.isArray(standings) ? (standings as TeamStats[]) : [])
              setGroups([])
              setSeason(NO_SEASON)
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
          setSeason(NO_SEASON)
        }
      } finally {
        if (!ignore) setLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [league, isWorldCup, isUFC])

  return { teams, groups, knockout, season, loading, error }
}
