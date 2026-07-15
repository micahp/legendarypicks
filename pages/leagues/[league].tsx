import { useState, useEffect, useRef } from 'react'
import Head from 'next/head'
import Link from 'next/link'
import { useRouter } from 'next/router'
import { SportsService, Game } from '../../services/sports'
import GameCard from '../../components/Scores/GameCard'

// ── Types ───────────────────────────────────────────────────
interface TeamStats {
  abbrev: string; name: string
  wins: number; losses: number; win_pct: number
  differential: number; streak: string; last10: string
  games_played: number
}

interface StandingRow {
  rank: number; abbrev: string; name: string
  played: number; wins: number; draws: number; losses: number
  gf: number; ga: number; gd: number; points: number
}
interface StandingGroup { group: string; rows: StandingRow[] }

interface Leader {
  player_id: number; name: string; team: string; games: number
  [stat: string]: number | string | null
}

type MetricFormat = 'integer' | 'decimal_1' | 'decimal_3' | 'percent_1' | 'time'
interface StatMetric { key: string; label: string; format: MetricFormat }
interface StatCategory { key: string; label: string; stats: StatMetric[] }
interface ChangeComparison {
  recent_label: string
  baseline_label: string
  recent_games: number
  min_baseline_games: number
  status: 'display_only'
  eligible_leaders: number
  qualified_leaders: number
}
interface StatChange {
  player_id: number
  name: string
  team: string
  metric: StatMetric
  recent_value: number | string | null
  baseline_value: number | string | null
  delta: number
  direction: 'rising' | 'falling' | 'flat'
  recent_games: number
  baseline_games: number
}

interface LeadersData {
  league: string; season: number | string | null
  stat: string | null; stat_type: string | null
  category: string | null
  categories: StatCategory[]
  columns: StatMetric[]
  leaders: Leader[]
  change_metric: StatMetric | null
  comparison: ChangeComparison | null
  changes: StatChange[]
}

interface TeamColumn { key: string; label: string; format: string }
interface TeamStatCategory { key: string; label: string; columns: TeamColumn[] }
interface TeamAggregate {
  team: string
  games: number; wins: number; losses: number
  [key: string]: number | string
}
interface TeamAggregateCoverage {
  status: 'measured' | 'incomplete' | 'unavailable'
  scope: 'captured_completed_games'
  team_count: number; expected_teams: number
  games: number; paired_games: number; invalid_games: number
  first_game_date: string | null; last_game_date: string | null
  external_schedule_reconciled: boolean
}
interface TeamAggregatesData {
  league: string; season: number | null
  supported: boolean; reason: string | null
  coverage: TeamAggregateCoverage
  categories: TeamStatCategory[]
  columns: TeamColumn[]
  teams: TeamAggregate[]
}

// UFC types
interface UFCRanked { rank: number; fighter: string; champion?: boolean }
interface UFCDivision { division: string; champion: string; ranked: UFCRanked[] }
interface UFCRankings {
  pound_for_pound: { men: UFCRanked[]; women: UFCRanked[] }
  divisions: UFCDivision[]
}

// WC knockout types
interface KnockoutTeam { abbrev: string; name: string }
interface KnockoutMatch {
  home: KnockoutTeam; away: KnockoutTeam
  homeScore: number | null; awayScore: number | null
  winner: string | null; status: string; state: string
}
interface KnockoutRound { round: string; matches: KnockoutMatch[] }

type SubView = 'players' | 'teams'

const LEAGUE_NAMES: Record<string, string> = {
  mlb: 'MLB', nba: 'NBA', nhl: 'NHL', nfl: 'NFL', wc: 'World Cup', ufc: 'UFC',
}

const LEAGUE_EMOJIS: Record<string, string> = {
  mlb: '⚾', nba: '🏀', nhl: '🏒', nfl: '🏈', wc: '⚽', ufc: '🥊',
}

const LEAGUE_SWITCHER = ['mlb', 'nba', 'nhl', 'nfl', 'wc', 'ufc'] as const

// Weight class → lbs for UFC division cards
const WEIGHT_CLASS_LBS: Record<string, number> = {
  Flyweight: 125, Bantamweight: 135, Featherweight: 145,
  Lightweight: 155, Welterweight: 170, Middleweight: 185,
  'Light Heavyweight': 205, Heavyweight: 265,
  "Women's Strawweight": 115, "Women's Flyweight": 125, "Women's Bantamweight": 135,
}

function formatMetric(metric: StatMetric, value: number | string | null | undefined): string {
  if (value == null) return '—'
  if (metric.format === 'time') return String(value)
  const numeric = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(numeric)) return '—'
  if (metric.format === 'integer') return numeric.toFixed(0)
  if (metric.format === 'decimal_3') return numeric.toFixed(3)
  if (metric.format === 'percent_1') return `${numeric.toFixed(1)}%`
  return numeric.toFixed(1)
}

// Team-aggregate columns use a coarser format vocabulary (number/decimal/percent)
// than player StatMetrics, and percent values arrive as 0–1 ratios.
function formatTeamMetric(col: TeamColumn, value: number | string | null | undefined): string {
  if (value == null) return '—'
  const numeric = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(numeric)) return '—'
  if (col.format === 'percent') return `${(numeric * 100).toFixed(1)}%`
  if (col.format === 'decimal') return numeric.toFixed(1)
  return Number.isInteger(numeric) ? numeric.toFixed(0) : numeric.toFixed(1)
}

function formatSignedMetric(metric: StatMetric, value: number): string {
  const formatted = formatMetric(metric, value)
  return value > 0 ? `+${formatted}` : formatted
}

function directionDisplay(direction: StatChange['direction']) {
  if (direction === 'rising') return { glyph: '↑', label: 'Rising', className: 'text-emerald-400' }
  if (direction === 'falling') return { glyph: '↓', label: 'Falling', className: 'text-amber-400' }
  return { glyph: '→', label: 'Flat', className: 'text-zinc-400' }
}

type HubTab = 'standings' | 'stats' | 'schedule' | 'rankings'

const TAB_LABELS: Record<HubTab, string> = {
  standings: 'Standings',
  stats: 'Stats',
  schedule: 'Schedule',
  rankings: 'Rankings',
}

const DATE_PARAM = /^\d{4}-\d{2}-\d{2}$/

function localToday(): string {
  return new Date().toLocaleDateString('en-CA')
}

function validScheduleDate(value: unknown): value is string {
  if (typeof value !== 'string' || !DATE_PARAM.test(value)) return false
  const parsed = new Date(`${value}T12:00:00`)
  return !Number.isNaN(parsed.getTime()) && parsed.toLocaleDateString('en-CA') === value
}

function formatScheduleDate(date: string): string {
  return new Date(`${date}T12:00:00`).toLocaleDateString(undefined, {
    weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
  })
}

export default function LeagueHubPage() {
  const router = useRouter()
  const { league } = router.query
  const lg = (typeof league === 'string' ? league : '').toLowerCase()

  const leagueName = LEAGUE_NAMES[lg] || lg.toUpperCase()
  const leagueEmoji = LEAGUE_EMOJIS[lg] || ''

  // Determine valid tabs for this league
  const isWC = lg === 'wc'
  const isUFC = lg === 'ufc'
  const supportsTeamStats = lg === 'mlb' || lg === 'nba' || lg === 'nhl' || lg === 'nfl'

  // WC: Standings (bracket during knockouts / group tables) + Schedule. No player stats.
  // UFC: Rankings (default) + Schedule — NO Stats or Standings (loader skips both, so
  //       an empty Stats tab would render). Rankings must be first so it is the default.
  let validTabs: HubTab[]
  if (isUFC) {
    validTabs = ['rankings', 'schedule']
  } else {
    validTabs = ['standings', 'stats', 'schedule']
    if (isWC) validTabs.splice(validTabs.indexOf('stats'), 1)
  }

  const [activeTab, setActiveTab] = useState<HubTab>('standings')
  const [scheduleDate, setScheduleDate] = useState<string>(() => localToday())

  // The query string is the shareable source of truth. Canonicalize invalid
  // tabs (notably stats/standings on UFC) and ensure Schedule always has a day.
  useEffect(() => {
    if (!router.isReady || !lg) return
    const queryTab = typeof router.query.tab === 'string' ? router.query.tab : ''
    const nextTab = validTabs.includes(queryTab as HubTab)
      ? queryTab as HubTab
      : validTabs[0]
    const nextDate = validScheduleDate(router.query.date) ? router.query.date : localToday()
    setActiveTab(nextTab)
    setScheduleDate(nextDate)

    const tabNeedsUpdate = router.query.tab !== nextTab
    const dateNeedsUpdate = nextTab === 'schedule' && router.query.date !== nextDate
    if (tabNeedsUpdate || dateNeedsUpdate) {
      const query: Record<string, string | string[] | undefined> = {
        ...router.query, league: router.query.league || lg, tab: nextTab,
      }
      if (nextTab === 'schedule') query.date = nextDate
      void router.replace({ pathname: router.pathname, query }, undefined, { shallow: true })
    }
  }, [router.isReady, router.query.tab, router.query.date, lg])

  const updateRoute = (tab: HubTab, date = scheduleDate) => {
    const query: Record<string, string | string[] | undefined> = {
      ...router.query, league: router.query.league || lg, tab,
    }
    if (tab === 'schedule') query.date = date
    void router.replace({ pathname: router.pathname, query }, undefined, { shallow: true })
  }

  const selectTab = (tab: HubTab) => {
    setActiveTab(tab)
    updateRoute(tab)
  }

  const selectScheduleDate = (date: string) => {
    if (!validScheduleDate(date)) return
    setScheduleDate(date)
    updateRoute('schedule', date)
  }

  const shiftScheduleDay = (delta: number) => {
    const date = new Date(`${scheduleDate}T12:00:00`)
    date.setDate(date.getDate() + delta)
    selectScheduleDate(date.toLocaleDateString('en-CA'))
  }

  // ── Standings state ─────────────────────────────────────
  const [teams, setTeams] = useState<TeamStats[]>([])
  const [groups, setGroups] = useState<StandingGroup[]>([])
  const [knockout, setKnockout] = useState<KnockoutRound[]>([])
  const [standingsLoading, setStandingsLoading] = useState(false)
  const [standingsError, setStandingsError] = useState<string | null>(null)

  // ── Stats (leaders) state ────────────────────────────────
  const [subView, setSubView] = useState<SubView>('players')
  const [leadersData, setLeadersData] = useState<LeadersData | null>(null)
  const [playerLoading, setPlayerLoading] = useState(false)
  const [playerError, setPlayerError] = useState<string | null>(null)
  const [playerFilterError, setPlayerFilterError] = useState(false)
  const [mlbType, setMlbType] = useState<'batting' | 'pitching'>('batting')
  const [teamAggregates, setTeamAggregates] = useState<TeamAggregatesData | null>(null)
  const [teamStatsLoading, setTeamStatsLoading] = useState(false)
  const [teamStatsError, setTeamStatsError] = useState<string | null>(null)
  const [teamCategory, setTeamCategory] = useState<string | null>(null)
  // Read current sub-view inside the capability fetch without making it a dep
  // (adding subView as a dep re-fired the fetch on every Players/Teams click,
  // nulling teamAggregates and flickering the toggle).
  const subViewRef = useRef<SubView>('players')
  // Always-fresh view of router.query for async callbacks. Spreading the closure's
  // router.query after an await can write back a stale `tab` and clobber a tab the
  // user just changed (e.g. clicking Stats reverted to standings/schedule).
  const queryRef = useRef(router.query)
  // Signature the leaders effect just wrote into the URL as canonical defaults.
  // The write re-fires the effect (category/stat are deps); skip that echo so we
  // don't re-fetch identical data and flash loading→results twice.
  const canonicalRef = useRef<string | null>(null)

  // ── Schedule state ──────────────────────────────────────
  const [games, setGames] = useState<Game[]>([])
  const [scheduleLoading, setScheduleLoading] = useState(false)
  const [scheduleError, setScheduleError] = useState<string | null>(null)

  // ── UFC rankings state ──────────────────────────────────
  const [ufcRankings, setUfcRankings] = useState<UFCRankings | null>(null)
  const [ufcLoading, setUfcLoading] = useState(false)
  const [ufcError, setUfcError] = useState<string | null>(null)

  // Stats view/type are URL-owned and canonical only while the Stats tab is active.
  useEffect(() => {
    if (!router.isReady || !lg || router.query.tab !== 'stats') return
    const nextView: SubView = supportsTeamStats && router.query.view === 'teams' ? 'teams' : 'players'
    const nextType: 'batting' | 'pitching' = router.query.type === 'pitching' ? 'pitching' : 'batting'
    setSubView(nextView)
    if (lg === 'mlb' && nextView === 'players') setMlbType(nextType)

    const query: Record<string, string | string[] | undefined> = { ...router.query }
    let needsUpdate = false
    if (router.query.view !== nextView) {
      query.view = nextView
      needsUpdate = true
    }
    if (lg === 'mlb' && nextView === 'players') {
      if (router.query.type !== nextType) {
        query.type = nextType
        needsUpdate = true
      }
    } else if (router.query.type !== undefined) {
      delete query.type
      needsUpdate = true
    }
    if (nextView === 'teams') {
      for (const key of ['category', 'stat']) {
        if (query[key] !== undefined) {
          delete query[key]
          needsUpdate = true
        }
      }
    }
    if (needsUpdate) {
      void router.replace({ pathname: router.pathname, query }, undefined, { shallow: true })
    }
  }, [router.isReady, router.query.tab, router.query.view, router.query.type, router.query.category, router.query.stat, lg, supportsTeamStats])

  useEffect(() => {
    setLeadersData(null)
    setPlayerError(null)
    setPlayerFilterError(false)
  }, [lg, mlbType])

  useEffect(() => {
    setTeamAggregates(null)
    setTeamStatsError(null)
  }, [lg])

  const replaceStatsQuery = (
    updates: Record<string, string>,
    remove: string[] = [],
  ) => {
    const query: Record<string, string | string[] | undefined> = {
      ...router.query,
      league: router.query.league || lg,
      tab: 'stats',
      ...updates,
    }
    for (const key of remove) delete query[key]
    if (lg !== 'mlb') delete query.type
    void router.replace({ pathname: router.pathname, query }, undefined, { shallow: true })
  }

  const selectSubView = (view: SubView) => {
    setSubView(view)
    if (view === 'teams') {
      replaceStatsQuery({ view }, ['type', 'category', 'stat'])
    } else {
      replaceStatsQuery(
        lg === 'mlb' ? { view, type: mlbType } : { view },
        ['category', 'stat'],
      )
    }
  }

  const selectMlbType = (type: 'batting' | 'pitching') => {
    setLeadersData(null)
    replaceStatsQuery({ view: 'players', type }, ['category', 'stat'])
  }

  const selectStatCategory = (category: string) => {
    replaceStatsQuery({ view: 'players', category }, ['stat'])
  }

  const selectSortMetric = (stat: string) => {
    if (!leadersData?.category) return
    replaceStatsQuery({ view: 'players', category: leadersData.category, stat })
  }

  const resetStatsFilters = () => {
    setPlayerError(null)
    setPlayerFilterError(false)
    const updates: Record<string, string> = { view: 'players' }
    if (lg === 'mlb') {
      updates.type = router.query.type === 'pitching' ? 'pitching' : 'batting'
      setMlbType(updates.type as 'batting' | 'pitching')
    }
    replaceStatsQuery(updates, ['category', 'stat'])
  }

  // ── Load standings ──────────────────────────────────────
  useEffect(() => {
    if (!lg) return
    if (isUFC) return // UFC uses rankings tab, not standings
    let ignore = false
    const load = async () => {
      setStandingsLoading(true); setStandingsError(null)
      try {
        if (isWC) {
          // Try the canonical knockout bracket first; fall back to group standings
          // when knockouts haven't begun (endpoint returns {rounds:[]}).
          const kres = await fetch('/api/wc/knockout')
          const kdata = await kres.json()
          const krounds = Array.isArray(kdata) ? kdata : (kdata?.rounds ?? [])
          if (!ignore) {
            if (Array.isArray(krounds) && krounds.length > 0 && krounds.some((r: any) => r.matches?.length > 0)) {
              setKnockout(krounds)
            } else {
              // Fall back to group standings
              const gres = await fetch('/api/wc/standings')
              const gdata = await gres.json()
              if (!ignore) setGroups(Array.isArray(gdata) ? gdata : [])
            }
          }
        } else {
          const data = await SportsService.getStrength(lg)
          if (!ignore) setTeams(Array.isArray(data) ? data : [])
        }
      } catch {
        if (!ignore) setStandingsError('Unable to load standings.')
      } finally {
        if (!ignore) setStandingsLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [lg, isWC, isUFC])

  // ── Load players ─────────────────────────────────────────
  useEffect(() => {
    if (!router.isReady || !lg || activeTab !== 'stats' || subView !== 'players') return
    if (isWC || isUFC) return
    if (lg === 'mlb' && router.query.type !== mlbType) return
    // Skip the re-fire caused by our own canonical-default URL write (data already loaded).
    const reqCat = typeof router.query.category === 'string' ? router.query.category : ''
    const reqStat = typeof router.query.stat === 'string' ? router.query.stat : ''
    const sig = `${lg}|${mlbType}|${reqCat}|${reqStat}`
    if (canonicalRef.current === sig) { canonicalRef.current = null; return }
    let ignore = false
    const load = async () => {
      setPlayerLoading(true); setPlayerError(null); setPlayerFilterError(false)
      try {
        const params = new URLSearchParams({ limit: '25' })
        if (lg === 'mlb') params.set('type', mlbType)
        const requestedCategory = typeof router.query.category === 'string' ? router.query.category : null
        const requestedStat = typeof router.query.stat === 'string' ? router.query.stat : null
        if (requestedCategory) params.set('category', requestedCategory)
        if (requestedStat) params.set('stat', requestedStat)
        const res = await fetch(`/api/${lg}/leaders?${params.toString()}`)
        if (!res.ok) {
          let detail = `HTTP ${res.status}`
          try {
            const payload = await res.json()
            if (typeof payload?.detail === 'string') detail = payload.detail
            else if (payload?.detail != null) detail = JSON.stringify(payload.detail)
          } catch { /* retain the HTTP detail */ }
          const error: any = new Error(detail)
          error.status = res.status
          throw error
        }
        const payload: any = await res.json()
        if (!Array.isArray(payload?.categories) || !Array.isArray(payload?.columns)) {
          const error: any = new Error('Incompatible stats response.')
          if (requestedCategory || requestedStat) error.status = 400
          throw error
        }
        const data: LeadersData = {
          ...payload,
          change_metric: payload.change_metric ?? null,
          comparison: payload.comparison ?? null,
          changes: Array.isArray(payload.changes) ? payload.changes : [],
        }
        if (!ignore) {
          setLeadersData(data)
          if (
            queryRef.current.tab === 'stats' &&
            ((!requestedCategory && data.category) || (!requestedStat && data.stat))
          ) {
            const query: Record<string, string | string[] | undefined> = { ...queryRef.current }
            if (!requestedCategory && data.category) query.category = data.category
            if (!requestedStat && data.stat) query.stat = data.stat
            // Remember what we're writing so the resulting effect re-fire is skipped.
            canonicalRef.current = `${lg}|${mlbType}|${(query.category as string) || ''}|${(query.stat as string) || ''}`
            void router.replace({ pathname: router.pathname, query }, undefined, { shallow: true })
          }
        }
      } catch (e: any) {
        if (!ignore) {
          setLeadersData(null)
          setPlayerFilterError(e?.status === 400)
          setPlayerError(`Unable to load player stats: ${e?.message || 'Unknown error'}`)
        }
      } finally {
        if (!ignore) setPlayerLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [router.isReady, router.query.category, router.query.stat, router.query.type, lg, mlbType, isWC, isUFC, activeTab, subView])

  useEffect(() => { subViewRef.current = subView }, [subView])
  useEffect(() => { queryRef.current = router.query }, [router.query])

  // ── Load team aggregates/capability ─────────────────────
  // Capability probe: runs once per league/tab, NOT per sub-view toggle. Keeps
  // any existing data visible during a refetch so the Players/Teams toggle does
  // not flicker, and only steers out of the Teams view if the fetch actually fails.
  useEffect(() => {
    if (!router.isReady || !supportsTeamStats || activeTab !== 'stats') return
    let ignore = false
    const load = async () => {
      setTeamStatsLoading(true)
      setTeamStatsError(null)
      try {
        const res = await fetch(`/api/${lg}/team-aggregates`)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const payload: TeamAggregatesData = await res.json()
        if (!payload.supported || !Array.isArray(payload.teams)) {
          throw new Error('Measured team coverage is incomplete.')
        }
        if (!ignore) setTeamAggregates(payload)
      } catch (error: any) {
        if (!ignore) {
          setTeamAggregates(null)
          setTeamStatsError(error?.message || 'Unable to load team stats.')
          if (subViewRef.current === 'teams') {
            setSubView('players')
            const query: Record<string, string | string[] | undefined> = {
              ...queryRef.current, view: 'players',
            }
            if (lg === 'mlb') query.type = mlbType
            delete query.category
            delete query.stat
            void router.replace({ pathname: router.pathname, query }, undefined, { shallow: true })
          }
        }
      } finally {
        if (!ignore) setTeamStatsLoading(false)
      }
    }
    load()
    return () => { ignore = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router.isReady, lg, supportsTeamStats, activeTab])

  // ── Load schedule ───────────────────────────────────────
  useEffect(() => {
    if (!lg || activeTab !== 'schedule') return
    let ignore = false
    const load = async () => {
      setGames([])
      setScheduleLoading(true); setScheduleError(null)
      try {
        const data = await SportsService.getGamesByDate(lg, scheduleDate)
        if (!ignore) setGames(Array.isArray(data) ? data : [])
      } catch {
        if (!ignore) setScheduleError('Unable to load schedule.')
      } finally {
        if (!ignore) setScheduleLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [lg, scheduleDate, activeTab])

  // ── Load UFC rankings ───────────────────────────────────
  useEffect(() => {
    if (!isUFC || !lg) return
    let ignore = false
    const load = async () => {
      setUfcLoading(true); setUfcError(null)
      try {
        const res = await fetch('/api/ufc/rankings')
        if (!res.ok) throw new Error(`${res.status}`)
        const data: UFCRankings = await res.json()
        if (!ignore) setUfcRankings(data)
      } catch (e: any) {
        if (!ignore) setUfcError(e.message || 'Unable to load UFC rankings.')
      } finally {
        if (!ignore) setUfcLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [isUFC, lg])

  // ── Derived schedule data ───────────────────────────────
  const formattedScheduleDate = formatScheduleDate(scheduleDate)
  const isScheduleToday = scheduleDate === localToday()
  const sortedScheduleGames = [...games].sort(
    (a, b) => new Date(a.startTime).getTime() - new Date(b.startTime).getTime()
  )
  const scheduleGroups = sortedScheduleGames.reduce((groups, game) => {
    const subtitle = game.subtitle || ''
    if (!groups[subtitle]) groups[subtitle] = []
    groups[subtitle].push(game)
    return groups
  }, {} as Record<string, Game[]>)

  // ── Loading (no league yet) ─────────────────────────────
  if (!lg) {
    return (
      <div className="space-y-3 animate-pulse">
        <div className="h-8 bg-zinc-800 rounded w-48" />
        <div className="h-10 bg-zinc-800 rounded" />
      </div>
    )
  }

  return (
    <>
      <Head>
        <title>{leagueName} — Legendary Picks</title>
      </Head>

      <div className="space-y-4">
        {/* League switcher */}
        <nav
          aria-label="Leagues"
          className="-mx-4 flex items-center gap-3 overflow-x-auto px-4 text-sm sm:gap-4 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {LEAGUE_SWITCHER.map(leagueKey => (
            <Link
              key={leagueKey}
              href={`/leagues/${leagueKey}`}
              aria-current={lg === leagueKey ? 'page' : undefined}
              className="whitespace-nowrap text-zinc-500 transition-colors hover:text-emerald-400"
            >
              {LEAGUE_NAMES[leagueKey]}
            </Link>
          ))}
        </nav>

        {/* League header */}
        <div className="flex items-center gap-3">
          <span className="text-2xl">{leagueEmoji}</span>
          <h1 className="text-3xl font-extrabold tracking-tight">{leagueName}</h1>
        </div>

        {/* Tab bar */}
        <div className="flex gap-0 overflow-x-auto border-b border-zinc-800 -mx-4 px-4 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {validTabs.map(t => (
            <button
              key={t}
              onClick={() => selectTab(t)}
              className={`px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px ${
                activeTab === t
                  ? 'border-emerald-500 text-white'
                  : 'border-transparent text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {TAB_LABELS[t]}
            </button>
          ))}
        </div>

        {/* ── Standings tab ──────────────────────────────── */}
        {activeTab === 'standings' && (
          <>
            {standingsError && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 text-red-400 text-sm">
                {standingsError}
              </div>
            )}

            {standingsLoading ? (
              <div className="text-zinc-500 text-sm py-8 text-center">Loading standings...</div>
            ) : isWC ? (
              // ── WC: knockout bracket or group tables ──
              knockout.length > 0 ? (
                <div className="space-y-8">
                  {knockout.map(round => (
                    <div key={round.round}>
                      <div className="flex items-center gap-3 mb-3">
                        <span className="text-[10px] text-emerald-500/60 bg-emerald-500/10 px-2 py-0.5 rounded font-bold uppercase tracking-widest">
                          {round.round}
                        </span>
                      </div>
                      <div className="space-y-2">
                        {round.matches.map((m, i) => {
                          const isFinal = m.state === 'post'
                          const homeWon = isFinal && m.winner === m.home.abbrev
                          const awayWon = isFinal && m.winner === m.away.abbrev
                          return (
                            <div key={i} className="bg-zinc-900 border border-zinc-800 rounded-lg px-4 py-3 flex items-center justify-between gap-3">
                              <div className="flex-1 min-w-0">
                                <span className={`font-semibold text-sm ${isFinal ? (homeWon ? 'text-white' : 'text-zinc-500') : 'text-zinc-200'}`}>
                                  {m.home.name || m.home.abbrev}
                                </span>
                              </div>
                              <div className="flex items-center gap-2 shrink-0">
                                {isFinal ? (
                                  <span className="font-mono tabular-nums text-lg font-bold text-zinc-100">
                                    {m.homeScore ?? '—'} – {m.awayScore ?? '—'}
                                  </span>
                                ) : (
                                  <span className="text-xs text-zinc-500">{m.status || 'Upcoming'}</span>
                                )}
                              </div>
                              <div className="flex-1 min-w-0 text-right">
                                <span className={`font-semibold text-sm ${isFinal ? (awayWon ? 'text-white' : 'text-zinc-500') : 'text-zinc-200'}`}>
                                  {m.away.name || m.away.abbrev}
                                </span>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              ) : groups.length === 0 ? (
                <div className="text-zinc-500 text-sm">No standings available.</div>
              ) : (
                // ── WC group tables ──
                <div className="space-y-8">
                  {groups.map(g => (
                    <div key={g.group}>
                      <h2 className="text-lg font-bold text-white mb-3">{g.group}</h2>
                      <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-900 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="border-b border-zinc-800 text-zinc-400 text-xs uppercase tracking-wider">
                              <th className="text-left py-3 px-3">#</th>
                              <th className="text-left py-3 px-3">Team</th>
                              <th className="text-center py-3 px-2">P</th><th className="text-center py-3 px-2">W</th>
                              <th className="text-center py-3 px-2">D</th><th className="text-center py-3 px-2">L</th>
                              <th className="text-center py-3 px-2">GF</th><th className="text-center py-3 px-2">GA</th>
                              <th className="text-center py-3 px-2">GD</th><th className="text-center py-3 px-2 font-bold">Pts</th>
                            </tr>
                          </thead>
                          <tbody>
                            {g.rows.map(r => (
                              <tr key={r.abbrev} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                                <td className="py-3 px-3 text-zinc-500">{r.rank}</td>
                                <td className="py-3 px-3">
                                  <span className="font-semibold text-zinc-200">{r.abbrev}</span>
                                  <span className="text-zinc-500 ml-2">{r.name}</span>
                                </td>
                                <td className="py-3 px-2 text-center text-zinc-300">{r.played}</td>
                                <td className="py-3 px-2 text-center text-zinc-300">{r.wins}</td>
                                <td className="py-3 px-2 text-center text-zinc-300">{r.draws}</td>
                                <td className="py-3 px-2 text-center text-zinc-300">{r.losses}</td>
                                <td className="py-3 px-2 text-center text-zinc-300">{r.gf}</td>
                                <td className="py-3 px-2 text-center text-zinc-300">{r.ga}</td>
                                <td className="py-3 px-2 text-center">
                                  <span className={r.gd > 0 ? 'text-emerald-400' : r.gd < 0 ? 'text-red-400' : 'text-zinc-400'}>
                                    {r.gd > 0 ? '+' : ''}{r.gd}
                                  </span>
                                </td>
                                <td className="py-3 px-2 text-center font-bold text-white">{r.points}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ))}
                </div>
              )
            ) : teams.length === 0 ? (
              <div className="text-zinc-500 text-sm">No data available for {leagueName}.</div>
            ) : (
              // ── US team sports standings ──
              <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-900 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-zinc-800 text-zinc-400 text-xs uppercase tracking-wider">
                      <th className="text-left py-3 pr-4 pl-4">#</th>
                      <th className="text-left py-3 pr-4">Team</th>
                      <th className="text-right py-3 px-3">W</th>
                      <th className="text-right py-3 px-3">L</th>
                      <th className="text-right py-3 px-3">Win%</th>
                      <th className="text-right py-3 px-3">Diff</th>
                      <th className="text-right py-3 px-3">Streak</th>
                      <th className="text-right py-3 pl-3 pr-4">L10</th>
                    </tr>
                  </thead>
                  <tbody>
                    {teams.map((t, i) => (
                      <tr key={t.abbrev} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                        <td className="py-3 pr-4 pl-4 text-zinc-500">{i + 1}</td>
                        <td className="py-3 pr-4">
                          <span className="font-semibold text-zinc-200">{t.abbrev}</span>
                          <span className="text-zinc-500 ml-2">{t.name}</span>
                        </td>
                        <td className="py-3 px-3 text-right text-zinc-200">{t.wins}</td>
                        <td className="py-3 px-3 text-right text-zinc-200">{t.losses}</td>
                        <td className="py-3 px-3 text-right text-zinc-200 font-mono tabular-nums">
                          {(t.win_pct * 100).toFixed(1)}%
                        </td>
                        <td className="py-3 px-3 text-right">
                          <span className={t.differential > 0 ? 'text-emerald-400' : t.differential < 0 ? 'text-red-400' : 'text-zinc-400'}>
                            {t.differential > 0 ? '+' : ''}{t.differential}
                          </span>
                        </td>
                        <td className="py-3 px-3 text-right">
                          <span className={t.streak?.startsWith('W') ? 'text-emerald-400' : 'text-red-400'}>
                            {t.streak}
                          </span>
                        </td>
                        <td className="py-3 pl-3 pr-4 text-right text-zinc-400 font-mono tabular-nums">{t.last10}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        {/* ── Stats tab ──────────────────────────────────── */}
        {activeTab === 'stats' && (
          <>
            {/* MLB has measured player and team data; other leagues expose players only. */}
            {supportsTeamStats && teamAggregates?.supported && (
              <div className="flex gap-0 border-b border-zinc-800 -mx-4 px-4">
                {(['players', 'teams'] as SubView[]).map(v => (
                <button key={v} onClick={() => selectSubView(v)}
                  className={`px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px capitalize ${
                    subView === v ? 'border-emerald-500 text-white' : 'border-transparent text-zinc-500 hover:text-zinc-300'
                  }`}
                >
                  {v}
                </button>
                ))}
              </div>
            )}

            {/* MLB batting/pitching toggle (Players sub-view only) */}
            {lg === 'mlb' && subView === 'players' && (
              <div className="flex items-center gap-2">
                {(['batting', 'pitching'] as const).map(t => (
                  <button key={t} onClick={() => selectMlbType(t)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors capitalize ${
                      mlbType === t
                        ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                        : 'bg-zinc-900 text-zinc-500 border border-zinc-800 hover:text-zinc-300'
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            )}

            {subView === 'players' && leadersData?.categories?.length ? (
              <div className="flex flex-wrap items-center gap-2" aria-label="Player stat categories">
                {leadersData.categories.map(category => (
                  <button
                    key={category.key}
                    type="button"
                    onClick={() => selectStatCategory(category.key)}
                    className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                      leadersData.category === category.key
                        ? 'border-emerald-500/30 bg-emerald-500/20 text-emerald-400'
                        : 'border-zinc-800 bg-zinc-900 text-zinc-500 hover:text-zinc-300'
                    }`}
                  >
                    {category.label}
                  </button>
                ))}
              </div>
            ) : null}

            {subView === 'players' && !playerLoading && !playerError
              && leadersData?.change_metric && leadersData.comparison ? (
              <section
                aria-labelledby="what-changed-heading"
                className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900"
              >
                <div className="flex flex-wrap items-start justify-between gap-3 border-b border-zinc-800 px-4 py-3">
                  <div>
                    <h2 id="what-changed-heading" className="text-sm font-semibold text-zinc-100">What changed</h2>
                    <p className="mt-0.5 text-xs text-zinc-500">
                      {leadersData.comparison.recent_label} vs {leadersData.comparison.baseline_label}
                    </p>
                  </div>
                  {leadersData.comparison.status === 'display_only' && (
                    <span className="rounded-full border border-zinc-700 px-2.5 py-1 text-[11px] font-medium text-zinc-400">
                      Display-only trend
                    </span>
                  )}
                </div>

                {leadersData.changes.length === 0 || leadersData.comparison.qualified_leaders === 0 ? (
                  <p className="px-4 py-4 text-sm text-zinc-400">
                    Not enough valid game history for a Last 5 comparison.
                  </p>
                ) : (
                  <div className="divide-y divide-zinc-800">
                    {leadersData.changes.map(change => {
                      const direction = directionDisplay(change.direction)
                      return (
                        <div key={`${change.player_id}-${change.metric.key}`} className="px-4 py-3">
                          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                            <div className="min-w-0">
                              <a
                                href={`/player/${change.player_id}`}
                                className="font-medium text-zinc-200 transition-colors hover:text-emerald-400"
                              >
                                {change.name}
                              </a>
                              {change.team && <span className="ml-1.5 text-xs text-zinc-500">{change.team}</span>}
                            </div>
                            <div className="flex items-center gap-2 font-mono text-sm tabular-nums text-zinc-300">
                              <span role="img" aria-label={direction.label} className={direction.className}>
                                {direction.glyph}
                              </span>
                              <span>{formatSignedMetric(change.metric, change.delta)} {change.metric.label}</span>
                            </div>
                          </div>
                          <p className="mt-1 text-xs text-zinc-500">
                            Recent {formatMetric(change.metric, change.recent_value)} · Earlier {formatMetric(change.metric, change.baseline_value)} · {change.recent_games} recent / {change.baseline_games} earlier
                          </p>
                        </div>
                      )
                    })}
                  </div>
                )}
              </section>
            ) : null}

            {/* Players sub-view */}
            {subView === 'players' && (
              <>
                {playerError && (
                  <div className="space-y-2 rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-400">
                    <div>{playerError}</div>
                    {playerFilterError && (
                      <button
                        type="button"
                        onClick={resetStatsFilters}
                        className="rounded-lg border border-red-400/30 px-2.5 py-1 text-xs font-semibold text-red-300 hover:bg-red-500/10"
                      >
                        Reset stats filters
                      </button>
                    )}
                  </div>
                )}

                {playerLoading ? (
                  <div className="text-zinc-500 text-sm py-8 text-center">Loading players...</div>
                ) : playerError ? null : !leadersData?.leaders?.length ? (
                  <div className="text-center py-12 text-zinc-500 text-sm">
                    Player statistics are not available for {leagueName} yet.
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="flex items-center gap-3 text-xs text-zinc-500">
                      <span>Season {leadersData.season}</span>
                      <span>·</span>
                      <span>
                        Sorted by {leadersData.columns.find(metric => metric.key === leadersData.stat)?.label || leadersData.stat}
                      </span>
                    </div>

                    <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-900 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-zinc-800 text-zinc-500 text-[11px] uppercase tracking-wider">
                            <th className="text-left px-4 py-3 font-medium w-10">#</th>
                            <th className="text-left px-3 py-3 font-medium">Player</th>
                            <th className="text-right px-3 py-3 font-medium">GP</th>
                            {leadersData.columns.map(metric => (
                              <th
                                key={metric.key}
                                aria-sort={metric.key === leadersData.stat ? 'descending' : 'none'}
                                className="px-3 py-3 text-right font-medium"
                              >
                                <button
                                  type="button"
                                  onClick={() => selectSortMetric(metric.key)}
                                  className={`inline-flex items-center gap-1 whitespace-nowrap hover:text-zinc-200 ${
                                    metric.key === leadersData.stat ? 'text-emerald-400' : 'text-zinc-500'
                                  }`}
                                >
                                  {metric.label}
                                  {metric.key === leadersData.stat && <span aria-hidden="true">↓</span>}
                                </button>
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {leadersData.leaders.map((l, i) => (
                            <tr key={`${l.player_id}-${l.team}-${i}`} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                              <td className="px-4 py-2.5 text-zinc-500 text-xs">{i + 1}</td>
                              <td className="px-3 py-2.5">
                                <a href={`/player/${l.player_id}`} className="font-medium text-zinc-200 hover:text-emerald-400 transition-colors">
                                  {l.name}
                                </a>
                                {l.team && <span className="text-zinc-500 ml-1.5 text-xs">{l.team}</span>}
                              </td>
                              <td className="px-3 py-2.5 text-right font-mono tabular-nums text-zinc-400">{l.games}</td>
                              {leadersData.columns.map(metric => (
                                <td key={metric.key} className={`px-3 py-2.5 text-right font-mono tabular-nums ${
                                  metric.key === leadersData.stat ? 'text-emerald-300 font-bold' : 'text-zinc-300'
                                }`}>
                                  {formatMetric(metric, l[metric.key])}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </>
            )}

            {/* MLB team aggregates from captured completed games. */}
            {supportsTeamStats && subView === 'teams' && (
              <>
                {teamStatsLoading ? (
                  <div className="text-zinc-500 text-sm py-8 text-center">Loading team stats...</div>
                ) : teamStatsError ? (
                  <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
                    Team statistics are hidden because complete measured coverage is not available.
                  </div>
                ) : !teamAggregates?.teams.length ? (
                  <div className="text-zinc-500 text-sm">No measured team data available for {leagueName}.</div>
                ) : (() => {
                  const cats = teamAggregates.categories ?? []
                  const activeCat = cats.find(c => c.key === teamCategory) ?? cats[0]
                  const cols = activeCat?.columns ?? teamAggregates.columns ?? []
                  return (
                  <div className="space-y-3">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500">
                      <span>Season {teamAggregates.season}</span>
                      <span>·</span>
                      <span>{teamAggregates.coverage.games} captured completed games</span>
                      <span>·</span>
                      <span>Through {teamAggregates.coverage.last_game_date}</span>
                    </div>
                    {cats.length > 1 && (
                      <div className="flex flex-wrap items-center gap-2" aria-label="Team stat categories">
                        {cats.map(c => (
                          <button key={c.key} type="button" onClick={() => setTeamCategory(c.key)}
                            className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                              activeCat?.key === c.key
                                ? 'border-emerald-500/30 bg-emerald-500/20 text-emerald-400'
                                : 'border-zinc-800 bg-zinc-900 text-zinc-500 hover:text-zinc-300'
                            }`}
                          >
                            {c.label}
                          </button>
                        ))}
                      </div>
                    )}
                    <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-900 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                      <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-zinc-800 text-zinc-400 text-xs uppercase tracking-wider">
                          <th className="text-left py-3 pr-4 pl-4">#</th>
                          <th className="text-left py-3 pr-4">Team</th>
                          {cols.map(col => (
                            <th key={col.key} className="text-right py-3 px-3 whitespace-nowrap">{col.label}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {teamAggregates.teams.map((team, i) => (
                          <tr key={team.team} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                            <td className="py-3 pr-4 pl-4 text-zinc-500">{i + 1}</td>
                            <td className="py-3 pr-4 font-semibold text-zinc-200">{team.team}</td>
                            {cols.map(col => (
                              <td key={col.key} className="py-3 px-3 text-right text-zinc-200 font-mono tabular-nums">
                                {formatTeamMetric(col, team[col.key])}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                      </table>
                    </div>
                    {!teamAggregates.coverage.external_schedule_reconciled && (
                      <p className="text-xs text-zinc-600">
                        Covers captured completed games; not independently reconciled against the official schedule.
                      </p>
                    )}
                  </div>
                  )
                })()}
              </>
            )}
          </>
        )}

        {/* ── Schedule tab ────────────────────────────────── */}
        {activeTab === 'schedule' && (
          <>
            <div className="space-y-1.5 text-center">
              <div className="flex items-center justify-center gap-2 sm:gap-3">
                <button
                  type="button"
                  onClick={() => shiftScheduleDay(-1)}
                  aria-label="Previous day"
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-xl leading-none text-zinc-300 hover:bg-zinc-800 active:scale-95"
                >
                  ‹
                </button>
                <div className="min-w-[9rem] text-center sm:min-w-[10.5rem]" aria-live="polite">
                  <div className="text-sm font-bold text-zinc-200">{formattedScheduleDate}</div>
                  {!isScheduleToday && (
                    <button
                      type="button"
                      onClick={() => selectScheduleDate(localToday())}
                      className="mt-1 text-xs font-medium text-emerald-400 hover:text-emerald-300"
                    >
                      Jump to today
                    </button>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => shiftScheduleDay(1)}
                  aria-label="Next day"
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-xl leading-none text-zinc-300 hover:bg-zinc-800 active:scale-95"
                >
                  ›
                </button>
                <label className="relative flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200 focus-within:border-emerald-500 focus-within:ring-1 focus-within:ring-emerald-500">
                  <span className="sr-only">Choose date</span>
                  <svg viewBox="0 0 20 20" aria-hidden="true" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <rect x="3" y="4.5" width="14" height="12.5" rx="2" />
                    <path d="M6.5 2.5v4M13.5 2.5v4M3 8h14" />
                  </svg>
                  <input
                    type="date"
                    aria-label="Choose schedule date"
                    value={scheduleDate}
                    onChange={(event) => selectScheduleDate(event.target.value)}
                    className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                  />
                </label>
              </div>
            </div>

            {scheduleError && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 text-red-400 text-sm">
                {scheduleError}
              </div>
            )}

            {scheduleLoading ? (
              <div className="space-y-3 animate-pulse">
                {[...Array(4)].map((_, i) => (
                  <div key={i} className="h-24 bg-zinc-800 rounded-xl" />
                ))}
              </div>
            ) : scheduleError ? null : games.length === 0 ? (
              <div className="text-center py-12 text-zinc-500 text-sm">
                No {leagueName} games scheduled for {formattedScheduleDate}.
              </div>
            ) : (
              <div className="space-y-6">
                {Object.entries(scheduleGroups).map(([subtitle, groupedGames]) => (
                  <section key={subtitle || 'schedule'} className="space-y-3">
                    {subtitle && (
                      <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">
                        {subtitle}
                      </h2>
                    )}
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                      {groupedGames.map(game => (
                        <GameCard
                          key={game.gameId}
                          {...game}
                          showScheduledTime={isUFC}
                        />
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            )}
          </>
        )}

        {/* ── Rankings tab (UFC only) ──────────────────────── */}
        {activeTab === 'rankings' && (
          <>
            {ufcError && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 text-red-400 text-sm">
                {ufcError}
              </div>
            )}

            {ufcLoading ? (
              <div className="space-y-4 animate-pulse">
                <div className="h-6 bg-zinc-800 rounded w-48" />
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {[...Array(4)].map((_, i) => (
                    <div key={i} className="h-48 bg-zinc-800 rounded-xl" />
                  ))}
                </div>
              </div>
            ) : !ufcRankings ? (
              <div className="text-center py-12 text-zinc-500 text-sm">
                No UFC rankings available.
              </div>
            ) : (
              <div className="space-y-8">
                {/* Pound-for-Pound */}
                <section>
                  <div className="flex items-center gap-3 mb-4">
                    <span className="text-[10px] text-emerald-500/60 bg-emerald-500/10 px-2 py-0.5 rounded font-bold uppercase tracking-widest">
                      Pound-for-Pound
                    </span>
                    <span className="text-[10px] text-zinc-600 uppercase tracking-wider">
                      The best across all weight classes
                    </span>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {/* Men's P4P */}
                    <div className="bg-zinc-900/80 border border-zinc-800/80 rounded-xl overflow-hidden">
                      <div className="px-4 py-2.5 border-b border-zinc-800/60 flex items-center gap-2">
                        <span className="text-[11px] font-semibold text-zinc-300 uppercase tracking-wider">Men's</span>
                      </div>
                      <ol className="divide-y divide-zinc-800/40">
                        {ufcRankings.pound_for_pound.men.map(f => (
                          <li key={f.rank}
                            className={`flex items-center gap-3 px-4 py-2 text-sm ${
                              f.champion ? 'bg-emerald-500/5' : ''
                            }`}
                          >
                            <span className={`w-5 text-right text-xs tabular-nums font-medium ${
                              f.champion ? 'text-emerald-400' : 'text-zinc-600'
                            }`}>
                              {f.champion ? '♛' : f.rank}
                            </span>
                            <span className={f.champion ? 'text-emerald-300 font-semibold' : 'text-zinc-300'}>
                              {f.fighter}
                            </span>
                          </li>
                        ))}
                      </ol>
                    </div>
                    {/* Women's P4P */}
                    <div className="bg-zinc-900/80 border border-zinc-800/80 rounded-xl overflow-hidden">
                      <div className="px-4 py-2.5 border-b border-zinc-800/60 flex items-center gap-2">
                        <span className="text-[11px] font-semibold text-zinc-300 uppercase tracking-wider">Women's</span>
                      </div>
                      <ol className="divide-y divide-zinc-800/40">
                        {ufcRankings.pound_for_pound.women.map(f => (
                          <li key={f.rank}
                            className={`flex items-center gap-3 px-4 py-2 text-sm ${
                              f.champion ? 'bg-emerald-500/5' : ''
                            }`}
                          >
                            <span className={`w-5 text-right text-xs tabular-nums font-medium ${
                              f.champion ? 'text-emerald-400' : 'text-zinc-600'
                            }`}>
                              {f.champion ? '♛' : f.rank}
                            </span>
                            <span className={f.champion ? 'text-emerald-300 font-semibold' : 'text-zinc-300'}>
                              {f.fighter}
                            </span>
                          </li>
                        ))}
                      </ol>
                    </div>
                  </div>
                </section>

                {/* Weight Divisions */}
                <section>
                  <div className="flex items-center gap-3 mb-4">
                    <span className="text-[10px] text-zinc-500 bg-zinc-900 px-2 py-0.5 rounded font-bold uppercase tracking-widest border border-zinc-800">
                      Divisions
                    </span>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    {ufcRankings.divisions.map(div => {
                      const lbs = WEIGHT_CLASS_LBS[div.division]
                      return (
                      <div key={div.division}
                        className="bg-zinc-900/80 border border-zinc-800/80 rounded-xl overflow-hidden group"
                      >
                        <div className="px-4 pt-4 pb-1">
                          <div className="flex items-baseline gap-2">
                            <span className="text-3xl font-black text-zinc-200 tabular-nums tracking-tight">
                              {lbs}
                            </span>
                            <span className="text-xs text-zinc-600 font-medium uppercase tracking-widest">LBS</span>
                          </div>
                          <h3 className="text-[11px] font-semibold text-zinc-500 uppercase tracking-wider mt-0.5">
                            {div.division}
                          </h3>
                        </div>
                        {div.champion && (
                          <div className="mx-4 mt-2 mb-1 flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-500/5 border border-emerald-500/10">
                            <span className="text-emerald-400 text-xs">◆</span>
                            <span className="text-sm text-emerald-300 font-semibold">
                              {div.champion}
                            </span>
                          </div>
                        )}
                        <ol className="px-4 pb-3 pt-1 space-y-0.5">
                          {div.ranked.map(f => (
                            <li key={f.rank}
                              className="flex items-center gap-3 text-sm group-hover:text-zinc-300 transition-colors"
                            >
                              <span className="w-5 text-right text-[11px] tabular-nums text-zinc-600 font-medium">
                                {f.rank}
                              </span>
                              <span className="text-zinc-400">{f.fighter}</span>
                            </li>
                          ))}
                        </ol>
                      </div>
                    )})}
                  </div>
                </section>
              </div>
            )}
          </>
        )}
      </div>
    </>
  )
}
