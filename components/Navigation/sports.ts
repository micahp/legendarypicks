import { useEffect, useState } from 'react'

export type NavigationSurface = 'props' | 'leagues' | 'predict'

export type Competition = {
  league: string
  sport: string
}

export type SportGroup = {
  key: string
  sport: string
  label: string
  competitions: Competition[]
}

const SPORT_ORDER = ['football', 'soccer', 'tennis', 'basketball', 'baseball', 'hockey', 'mma', 'esports']
const ROLLUP_HUB_SPORTS = new Set(['soccer', 'tennis', 'esports'])
const SPORT_LABELS: Record<string, string> = {
  football: 'Football',
  soccer: 'Soccer',
  tennis: 'Tennis',
  basketball: 'Basketball',
  baseball: 'Baseball',
  hockey: 'Hockey',
  mma: 'MMA',
  esports: 'Esports',
}

export const LEAGUE_LABELS: Record<string, string> = {
  mlb: 'MLB',
  nba: 'NBA',
  nhl: 'NHL',
  nfl: 'NFL',
  ncaaf: 'NCAAF',
  mls: 'MLS',
  lcup: 'Leagues Cup',
  wc: 'World Cup',
  atp: 'ATP',
  wta: 'WTA',
  ufc: 'UFC',
  tennis: 'Tennis',
  soccer: 'Soccer',
  esports: 'Esports',
}

export function leagueNavigationLabel(league: string): string {
  return LEAGUE_LABELS[league] || league.toUpperCase()
}

function sportRank(sport: string): number {
  const rank = SPORT_ORDER.indexOf(sport)
  return rank === -1 ? SPORT_ORDER.length : rank
}

function competitionSort(a: Competition, b: Competition): number {
  const footballOrder = ['nfl', 'ncaaf']
  const soccerOrder = ['mls', 'lcup']
  const tennisOrder = ['atp', 'wta']
  const order = a.sport === 'football'
    ? footballOrder
    : a.sport === 'soccer'
      ? soccerOrder
      : a.sport === 'tennis'
        ? tennisOrder
        : []
  const aRank = order.indexOf(a.league)
  const bRank = order.indexOf(b.league)
  return (aRank === -1 ? order.length : aRank) - (bRank === -1 ? order.length : bRank)
    || leagueNavigationLabel(a.league).localeCompare(leagueNavigationLabel(b.league))
}

export function groupSportNavigation(
  rows: Competition[],
  surface: NavigationSurface,
): SportGroup[] {
  const bySport = new Map<string, Competition[]>()
  for (const row of rows) {
    if (!row || !row.league || !row.sport) continue
    const competition = {
      league: String(row.league).toLowerCase(),
      sport: String(row.sport).toLowerCase(),
    }
    const current = bySport.get(competition.sport) || []
    if (!current.some(item => item.league === competition.league)) current.push(competition)
    bySport.set(competition.sport, current)
  }

  const groups: SportGroup[] = []
  for (const [sport, unsorted] of Array.from(bySport.entries())) {
    const competitions = surface === 'leagues' && ROLLUP_HUB_SPORTS.has(sport)
      ? [{ league: sport, sport }]
      : [...unsorted].sort(competitionSort)
    // NFL and NCAAF deliberately remain direct top-level choices on the props
    // product. The league directory still groups both under Football.
    if ((surface === 'props' || surface === 'predict') && sport === 'football') {
      for (const competition of competitions) {
        groups.push({
          key: `${sport}:${competition.league}`,
          sport,
          label: leagueNavigationLabel(competition.league),
          competitions: [competition],
        })
      }
      continue
    }

    const label = surface === 'leagues' || ROLLUP_HUB_SPORTS.has(sport) || competitions.length > 1
      ? SPORT_LABELS[sport] || sport.replace(/\b\w/g, letter => letter.toUpperCase())
      : leagueNavigationLabel(competitions[0].league)
    groups.push({ key: sport, sport, label, competitions })
  }

  return groups.sort((a, b) => {
    const sportDifference = sportRank(a.sport) - sportRank(b.sport)
    if (sportDifference) return sportDifference
    if (a.sport === 'football' && (surface === 'props' || surface === 'predict')) {
      const order = ['nfl', 'ncaaf']
      return order.indexOf(a.competitions[0].league) - order.indexOf(b.competitions[0].league)
    }
    return a.label.localeCompare(b.label)
  })
}

export function useSportNavigation(surface: NavigationSurface) {
  const [rows, setRows] = useState<Competition[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    let live = true
    fetch('/api/navigation/sports')
      .then(response => {
        if (!response.ok) throw new Error(String(response.status))
        return response.json()
      })
      .then(payload => {
        if (!live) return
        setRows(Array.isArray(payload?.[surface]) ? payload[surface] : [])
        setLoading(false)
      })
      .catch(() => {
        if (!live) return
        setRows([])
        setError(true)
        setLoading(false)
      })
    return () => { live = false }
  }, [surface])

  return { groups: groupSportNavigation(rows, surface), loading, error }
}
