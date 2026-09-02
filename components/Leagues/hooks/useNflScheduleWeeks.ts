import { useEffect, useMemo, useState } from 'react'
import {
  SportsService,
  normalizeGame,
  type Game,
  type NflScheduleWeeksResponse,
  type NflWeekEntry,
} from '../../../services/sports'
import { localToday } from '../presentation'

interface NflScheduleState {
  catalog: NflScheduleWeeksResponse | null
  catalogError: string | null
  catalogLoading: boolean
  games: Game[]
  gamesError: string | null
  gamesLoading: boolean
  selectedKey: string
  weekEntry: NflWeekEntry | null
  phaseLabel: string
  prevWeekKey: string | null
  nextWeekKey: string | null
  dateGroups: [string, Game[]][]
}

export function useFootballScheduleWeeks(
  league: 'nfl' | 'ncaaf',
  enabled: boolean,
  explicitWeek: string | null,
): NflScheduleState {
  const [catalog, setCatalog] = useState<NflScheduleWeeksResponse | null>(null)
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [catalogLoading, setCatalogLoading] = useState(true)
  const [games, setGames] = useState<Game[]>([])
  const [gamesError, setGamesError] = useState<string | null>(null)
  const [gamesLoading, setGamesLoading] = useState(false)

  // Resolve target week: explicit > catalog default
  const selectedKey = useMemo(() => {
    if (!catalog) return ''
    if (explicitWeek && catalog.weeks.some(w => w.key === explicitWeek)) {
      return explicitWeek
    }
    return catalog.default_week_key
  }, [catalog, explicitWeek])

  const weekEntry = useMemo(() => {
    if (!catalog) return null
    return catalog.weeks.find(w => w.key === selectedKey) || null
  }, [catalog, selectedKey])

  // Phase for the selected week
  const phaseLabel = useMemo(() => {
    if (!catalog || !weekEntry) return ''
    const phase = catalog.phases.find(p => p.season_type === weekEntry.season_type)
    return phase?.label || ''
  }, [catalog, weekEntry])

  // Flat week index for prev/next
  const weekIndex = useMemo(() => {
    if (!catalog) return -1
    return catalog.weeks.findIndex(w => w.key === selectedKey)
  }, [catalog, selectedKey])

  const prevWeekKey = weekIndex > 0 ? catalog?.weeks[weekIndex - 1]?.key || null : null
  const nextWeekKey = weekIndex >= 0 && catalog && weekIndex < catalog.weeks.length - 1
    ? catalog.weeks[weekIndex + 1]?.key || null
    : null

  // Fetch catalog — only when enabled
  useEffect(() => {
    if (!enabled) {
      setCatalog(null)
      setCatalogError(null)
      setGames([])
      setGamesError(null)
      setCatalogLoading(true) // ready for re-entry, no flash
      return
    }
    let ignore = false
    setCatalogLoading(true)
    setCatalogError(null)
    SportsService.getFootballScheduleWeeks(league, localToday()).then(data => {
      if (ignore) return
      if (data) {
        setCatalog(data)
      } else {
        setCatalogError(`Unable to load ${league.toUpperCase()} schedule.`)
      }
      setCatalogLoading(false)
    }).catch(() => {
      if (!ignore) {
        setCatalogError(`Unable to load ${league.toUpperCase()} schedule.`)
        setCatalogLoading(false)
      }
    })
    return () => { ignore = true }
  }, [enabled, league])

  // Fetch games for selected week
  useEffect(() => {
    if (!enabled || !weekEntry || !catalog) {
      setGamesLoading(false)
      return
    }
    let ignore = false
    setGames([])
    setGamesLoading(true)
    setGamesError(null)
    SportsService.getFootballScheduleWeek(league, catalog.season, weekEntry.season_type, weekEntry.week).then(data => {
      if (ignore) return
      if (data && Array.isArray(data.games)) {
        setGames(data.games.map((g: any) => ({
          ...normalizeGame(g, league),
          league: league.toUpperCase(),
        })))
      } else {
        setGamesError('Unable to load games.')
      }
      setGamesLoading(false)
    }).catch(() => {
      if (!ignore) {
        setGamesError('Unable to load games.')
        setGamesLoading(false)
      }
    })
    return () => { ignore = true }
  }, [enabled, league, catalog?.season, weekEntry?.season_type, weekEntry?.week])

  // Group games by local date
  const dateGroups = useMemo(() => {
    const groups: Record<string, Game[]> = {}
    for (const g of games) {
      const d = new Date(g.startTime).toLocaleDateString('en-CA')
      if (!groups[d]) groups[d] = []
      groups[d].push(g)
    }
    // Sort groups by date
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b))
  }, [games])

  return {
    catalog,
    catalogError,
    catalogLoading,
    games,
    gamesError,
    gamesLoading,
    selectedKey,
    weekEntry,
    phaseLabel,
    prevWeekKey,
    nextWeekKey,
    dateGroups,
  }
}

export function useNflScheduleWeeks(enabled: boolean, explicitWeek: string | null): NflScheduleState {
  return useFootballScheduleWeeks('nfl', enabled, explicitWeek)
}
