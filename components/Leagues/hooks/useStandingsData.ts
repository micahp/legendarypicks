import { useEffect, useState } from 'react'
import type { KnockoutRound, StandingGroup, TeamStats } from '../types'

// Leagues whose standings are conference-grouped ({group, rows}[]).
const GROUPED_LEAGUES = ['mls', 'ncaaf']

/**
 * MLS returns `{season, available_seasons, groups}`; NCAAF and the World Cup
 * return a bare `[{group, rows}]`. Read both out of either shape — a league
 * that sends no season list simply gets no season picker.
 */
function readStandings(payload: any): {
  groups: StandingGroup[]
  season: number | null
  availableSeasons: number[]
} {
  if (payload && !Array.isArray(payload) && Array.isArray(payload.groups)) {
    return {
      groups: payload.groups as StandingGroup[],
      season: typeof payload.season === 'number' ? payload.season : null,
      availableSeasons: Array.isArray(payload.available_seasons)
        ? (payload.available_seasons as number[])
        : [],
    }
  }
  const grouped = Array.isArray(payload)
    && payload.length > 0
    && typeof (payload[0] as any)?.group === 'string'
    && Array.isArray((payload[0] as any)?.rows)
  return {
    groups: grouped ? (payload as StandingGroup[]) : [],
    season: null,
    availableSeasons: [],
  }
}

export function useStandingsData(
  league: string,
  isWorldCup: boolean,
  isUFC: boolean,
) {
  const [teams, setTeams] = useState<TeamStats[]>([])
  const [groups, setGroups] = useState<StandingGroup[]>([])
  const [knockout, setKnockout] = useState<KnockoutRound[]>([])
  const [season, setSeason] = useState<number | null>(null)
  const [availableSeasons, setAvailableSeasons] = useState<number[]>([])
  // null = "whatever the publisher calls current". Set only by the picker, so
  // the default view never pins a year that will go stale next season.
  const [requestedSeason, setRequestedSeason] = useState<number | null>(null)
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
          const query = requestedSeason != null ? `?season=${requestedSeason}` : ''
          const standingsResponse = await fetch(`/api/${league}/standings${query}`)
          // A 503 here is the endpoint refusing to serve a stale season rather
          // than a transport failure, and it carries a reason worth showing.
          if (!standingsResponse.ok) {
            const body = await standingsResponse.json().catch(() => null)
            throw new Error(body?.detail || 'Standings are unavailable.')
          }
          const standings = await standingsResponse.json()
          if (!ignore) {
            const parsed = readStandings(standings)
            if (parsed.groups.length > 0) {
              setGroups(parsed.groups)
              setSeason(parsed.season)
              setAvailableSeasons(parsed.availableSeasons)
              setTeams([])
            } else {
              setTeams(Array.isArray(standings) ? (standings as TeamStats[]) : [])
              setGroups([])
            }
          }
        } else {
          // NFL / NBA / MLB / NHL — a flat W-L table that now arrives inside an
          // envelope naming its season, so the year can be shown and switched
          // the same way MLS does it. /strength stays the bare row list.
          const query = requestedSeason != null ? `?season=${requestedSeason}` : ''
          const standingsResponse = await fetch(`/api/${league}/standings${query}`)
          if (!standingsResponse.ok) {
            const body = await standingsResponse.json().catch(() => null)
            throw new Error(body?.detail || 'Standings are unavailable.')
          }
          const standings = await standingsResponse.json()
          if (!ignore) {
            const rows = Array.isArray(standings) ? standings : standings?.teams
            setTeams(Array.isArray(rows) ? (rows as TeamStats[]) : [])
            setSeason(typeof standings?.season === 'number' ? standings.season : null)
            setAvailableSeasons(
              Array.isArray(standings?.available_seasons) ? standings.available_seasons : [],
            )
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
  }, [league, isWorldCup, isUFC, requestedSeason])

  // Switching leagues must drop a year picked for the previous one.
  useEffect(() => { setRequestedSeason(null) }, [league])

  return {
    teams, groups, knockout, loading, error,
    season, availableSeasons,
    selectSeason: (next: number) => setRequestedSeason(next),
  }
}
