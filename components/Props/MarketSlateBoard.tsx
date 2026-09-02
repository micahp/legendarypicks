import { useEffect, useMemo, useRef, useState } from 'react'
import FightForm from './FightForm'
import PropChart, { PropHistory } from './PropChart'

interface BoardProp {
  id: number
  market: string
  line: number
  side: string
  source: string
  offer_kind?: 'sportsbook_odds' | 'pickem_threshold'
  source_label?: string
  captured_at: string
  odds: number | null
  player_id: number
  player_name: string
  player_team: string
  league: string
  game_home: string | null
  game_away: string | null
  game_date: string
}

interface BoardRow {
  key: string
  playerId: number
  player: string
  team: string
  league: string
  market: string
  rawMarket: string
  line: number
  source: string
  offerKind: 'sportsbook_odds' | 'pickem_threshold'
  sourceLabel: string
  home: string
  away: string
  date: string
  over?: BoardProp
  under?: BoardProp
}

interface HistoryState {
  loading: boolean
  data: PropHistory | null
}

interface MarketOption {
  market: string
  count: number
}

interface SlateMarketSummary {
  markets?: MarketOption[]
}

interface SourceStatus {
  status: string
  message?: string
}

type SortKey = 'hit-rate' | 'edge' | 'line'
type SortDirection = 'asc' | 'desc'


const MARKET_LABELS: Record<string, string> = {
  strikeouts: 'Strikeouts',
  goals: 'Goalscorer',
  shots_on_target: 'Shots on target',
  total_bases: 'Total bases',
  hits_allowed: 'Hits allowed',
  earned_runs: 'Earned runs',
  passing_yards: 'Passing yards',
  rushing_yards: 'Rushing yards',
  receiving_yards: 'Receiving yards',
  win_by_ko: 'Win by KO',
  win_by_submission: 'Win by submission',
  win_by_decision: 'Win by decision',
}

function baseMarket(market: string): string {
  return (market || '').split('___')[0].trim().toLowerCase()
}

function marketLabel(market: string): string {
  return MARKET_LABELS[market] || market.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function formatOdds(odds: number | null | undefined): string {
  if (odds === null || odds === undefined) return '—'
  return odds > 0 ? `+${odds}` : String(odds)
}

function formatValue(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function matchup(row: BoardRow): string {
  if (!row.home && !row.away) return row.league.toUpperCase()
  const game = row.home && row.away ? `${row.away} @ ${row.home}` : row.home || row.away
  if (!row.team) return game
  const team = row.team.toLowerCase()
  if (row.home.toLowerCase() === team) return `${row.team} vs ${row.away}`
  if (row.away.toLowerCase() === team) return `${row.team} @ ${row.home}`
  return `${row.team} · ${game}`
}

function groupProps(props: BoardProp[]): BoardRow[] {
  const grouped = new Map<string, BoardRow>()

  for (const prop of props) {
    const market = baseMarket(prop.market)
    const home = prop.game_home || ''
    const away = prop.game_away || ''
    const key = [prop.player_id, market, prop.line, prop.source, prop.game_date, home, away].join('|')
    let row = grouped.get(key)
    if (!row) {
      row = {
        key,
        playerId: prop.player_id,
        player: prop.player_name,
        team: prop.player_team || '',
        league: prop.league,
        market,
        rawMarket: prop.market,
        line: prop.line,
        source: prop.source,
        offerKind: prop.offer_kind || 'sportsbook_odds',
        sourceLabel: prop.source_label || prop.source,
        home,
        away,
        date: prop.game_date,
      }
      grouped.set(key, row)
    }

    const side = prop.side.toLowerCase()
    if (side === 'under' || side === 'no') {
      if (!row.under) row.under = prop
    } else if (!row.over) {
      row.over = prop
      row.rawMarket = prop.market
    }
  }

  return Array.from(grouped.values())
}

function RateChip({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100)
  const tone = pct >= 60
    ? 'border-emerald-800/70 bg-emerald-950/40 text-emerald-300'
    : pct < 40
      ? 'border-red-900/60 bg-red-950/30 text-red-300'
      : 'border-zinc-700 bg-zinc-800/70 text-zinc-300'
  return (
    <span className={`rounded-md border px-2 py-1 text-[11px] tabular-nums ${tone}`}>
      <span className="text-zinc-500">{label}</span> {pct}%
    </span>
  )
}

function LoadingEvidence() {
  return (
    <div className="flex flex-wrap gap-1.5 animate-pulse" aria-label="Loading model evidence">
      {[0, 1, 2, 3].map(i => <span key={i} className="h-7 w-16 rounded-md bg-zinc-800" />)}
    </div>
  )
}

function EmptyBoard({ date, sourceStatus }: { date: string; sourceStatus: SourceStatus | null }) {
  const unavailable = sourceStatus && sourceStatus.status !== 'PUBLISHED'
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 px-5 py-16 text-center">
      <p className="text-sm font-medium text-zinc-300">{unavailable ? 'MLS prop source unavailable for this slate.' : 'No prop markets for this slate.'}</p>
      <p className="mt-1 text-xs text-zinc-500">{unavailable ? sourceStatus.message : `Try another league or move off ${date}.`}</p>
    </div>
  )
}

export default function MarketSlateBoard({ league, date }: { league: string; date: string }) {
  const [props, setProps] = useState<BoardProp[]>([])
  const [marketOptions, setMarketOptions] = useState<MarketOption[]>([])
  const [loadedMarket, setLoadedMarket] = useState('')
  const [selectedMarket, setSelectedMarket] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('hit-rate')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sourceStatus, setSourceStatus] = useState<SourceStatus | null>(null)
  const [historyByRow, setHistoryByRow] = useState<Record<string, HistoryState>>({})
  const historyRequest = useRef(0)

  useEffect(() => {
    const controller = new AbortController()
    const summaryParams = new URLSearchParams({ date, summary: '1' })
    if (league !== 'All') summaryParams.set('league', league)

    setLoading(true)
    setError(null)
    setSourceStatus(null)
    setProps([])
    setMarketOptions([])
    setLoadedMarket('')

    const loadMarketSummary = async () => {
      const statusRequest = league === 'mls'
        ? fetch('/api/props/source-status?league=mls', { signal: controller.signal })
        : null
      const response = await fetch(`/api/props/slate?${summaryParams}`, { signal: controller.signal })
      if (!response.ok) throw new Error(`Market summary request failed (${response.status})`)
      const games = await response.json()
      if (!Array.isArray(games)) throw new Error('Market summary response was not a list')
      if (statusRequest) {
        const statusResponse = await statusRequest
        if (statusResponse.ok) {
          const status = await statusResponse.json()
          if (status && typeof status.status === 'string') setSourceStatus(status)
        }
      }

      // New summaries carry counts only; one selected market is fetched below.
      // During a managed backend rollout, fall back to the old list contract so
      // an already-running worker can keep painting the board until it reloads.
      const hasMarketSummary = games.length === 0
        || games.every((game: SlateMarketSummary) => Array.isArray(game.markets))
      if (hasMarketSummary) {
        const counts = new Map<string, number>()
        for (const game of games as SlateMarketSummary[]) {
          for (const item of game.markets || []) {
            counts.set(item.market, (counts.get(item.market) || 0) + item.count)
          }
        }
        setMarketOptions(Array.from(counts, ([market, count]) => ({ market, count })))
        if (!counts.size) setLoading(false)
        return
      }

      const fallbackParams = new URLSearchParams({ date, limit: '500' })
      if (league !== 'All') fallbackParams.set('league', league)
      const fallbackResponse = await fetch(`/api/props?${fallbackParams}`, { signal: controller.signal })
      if (!fallbackResponse.ok) throw new Error(`Props request failed (${fallbackResponse.status})`)
      const fallbackProps = await fallbackResponse.json()
      if (!Array.isArray(fallbackProps)) throw new Error('Props response was not a list')
      const counts = new Map<string, number>()
      for (const row of groupProps(fallbackProps)) {
        counts.set(row.market, (counts.get(row.market) || 0) + 1)
      }
      setProps(fallbackProps)
      setMarketOptions(Array.from(counts, ([market, count]) => ({ market, count })))
      setLoadedMarket('*')
      setLoading(false)
    }

    void loadMarketSummary().catch(err => {
      if (err.name === 'AbortError') return
      setProps([])
      setMarketOptions([])
      setError('The prop board could not be loaded. Try again in a moment.')
      setLoading(false)
    })

    return () => controller.abort()
  }, [date, league])

  const allRows = useMemo(() => groupProps(props), [props])
  const markets = useMemo(
    () => [...marketOptions].sort((a, b) =>
      b.count - a.count || marketLabel(a.market).localeCompare(marketLabel(b.market))),
    [marketOptions],
  )

  const activeMarket = markets.some(item => item.market === selectedMarket)
    ? selectedMarket
    : markets[0]?.market || ''

  useEffect(() => {
    if (activeMarket !== selectedMarket) setSelectedMarket(activeMarket)
  }, [activeMarket, selectedMarket])

  useEffect(() => {
    if (!activeMarket || loadedMarket === '*' || loadedMarket === activeMarket) return
    const controller = new AbortController()
    const params = new URLSearchParams({ date, limit: '500', market: activeMarket })
    if (league !== 'All') params.set('league', league)

    setLoading(true)
    setError(null)
    fetch(`/api/props?${params}`, { signal: controller.signal })
      .then(response => {
        if (!response.ok) throw new Error(`Props request failed (${response.status})`)
        return response.json()
      })
      .then(data => {
        if (!Array.isArray(data)) throw new Error('Props response was not a list')
        setProps(data)
        setLoadedMarket(activeMarket)
        setLoading(false)
      })
      .catch(err => {
        if (err.name === 'AbortError') return
        setProps([])
        setError('The prop board could not be loaded. Try again in a moment.')
        setLoading(false)
      })

    return () => controller.abort()
  }, [activeMarket, date, league, loadedMarket])

  const marketRows = useMemo(
    () => allRows.filter(row => row.market === activeMarket),
    [activeMarket, allRows],
  )

  useEffect(() => {
    const requestId = ++historyRequest.current
    const controller = new AbortController()
    const initial: Record<string, HistoryState> = {}
    for (const row of marketRows) {
      initial[row.key] = { loading: row.league !== 'ufc', data: null }
    }
    setHistoryByRow(initial)

    for (const row of marketRows) {
      // Method-of-victory props are categorical. FightForm lazily loads the
      // fighter's ESPN form only when its disclosure is opened.
      if (row.league === 'ufc') continue
      const chartProp = row.over || row.under
      if (!chartProp) continue
      const params = new URLSearchParams({
        player_id: String(row.playerId),
        market: row.rawMarket,
        line: String(row.line),
        side: row.over ? 'over' : 'under',
        league: row.league,
      })
      fetch(`/api/props/history?${params}`, { signal: controller.signal })
        .then(response => {
          if (!response.ok) throw new Error(`History request failed (${response.status})`)
          return response.json()
        })
        .then(data => {
          if (historyRequest.current !== requestId) return
          const history = !data.error && Array.isArray(data.games) && data.games.length
            ? data as PropHistory
            : null
          setHistoryByRow(current => ({ ...current, [row.key]: { loading: false, data: history } }))
        })
        .catch(err => {
          if (err.name === 'AbortError' || historyRequest.current !== requestId) return
          setHistoryByRow(current => ({ ...current, [row.key]: { loading: false, data: null } }))
        })
    }

    return () => controller.abort()
  }, [marketRows])

  const sortedRows = useMemo(() => {
    const valueFor = (row: BoardRow): number | null => {
      const history = historyByRow[row.key]?.data
      if (sortKey === 'line') return row.line
      if (!history) return null
      if (sortKey === 'hit-rate') return history.hit_rate.l10
      return history.projection === null ? null : Math.abs(history.projection - row.line)
    }
    // Hit rate over ten games takes eleven distinct values, so ties are the common
    // case, not the edge case: a real slate put six rows on 40% at once. Falling
    // through to the player's name turned the research board into an alphabetical
    // list — the reader sees an order and reads meaning into it, and there is none.
    // So every tie breaks on another number, in a stated order, and the row key is
    // only ever a determinism guard so React keys stay stable across renders.
    const tiebreakers: ((row: BoardRow) => number)[] = [
      row => {
        const h = historyByRow[row.key]?.data
        return h?.projection == null ? -Infinity : Math.abs(h.projection - row.line)
      },
      row => historyByRow[row.key]?.data?.hit_rate.season ?? -Infinity,
      row => historyByRow[row.key]?.data?.games.length ?? -Infinity,
      row => row.line,
    ]
    return [...marketRows].sort((a, b) => {
      const av = valueFor(a)
      const bv = valueFor(b)
      if (av === null && bv !== null) return 1
      if (av !== null && bv === null) return -1
      if (av !== null && bv !== null && av !== bv) {
        return sortDirection === 'desc' ? bv - av : av - bv
      }
      // Ties always resolve most-evidence-first, whichever way the primary points.
      for (const key of tiebreakers) {
        const d = key(b) - key(a)
        if (d) return d
      }
      return a.key.localeCompare(b.key)
    })
  }, [historyByRow, marketRows, sortDirection, sortKey])

  const chooseSort = (next: SortKey) => {
    if (next === sortKey) setSortDirection(direction => direction === 'desc' ? 'asc' : 'desc')
    else {
      setSortKey(next)
      setSortDirection('desc')
    }
  }

  if (loading) {
    return (
      <div className="space-y-3 animate-pulse" aria-label="Loading prop board">
        <div className="h-10 rounded-xl bg-zinc-800" />
        {[0, 1, 2].map(i => <div key={i} className="h-52 rounded-xl bg-zinc-900" />)}
      </div>
    )
  }

  if (error) {
    return <div className="rounded-xl border border-red-900/60 bg-red-950/30 px-4 py-4 text-sm text-red-200">{error}</div>
  }

  if (!markets.length) return <EmptyBoard date={date} sourceStatus={sourceStatus} />

  return (
    <section className="min-w-0 space-y-4" aria-label="Market-first prop board">
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-3 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-zinc-200">Choose a market</h2>
            <p className="text-xs text-zinc-500">Every available player line across this slate</p>
          </div>
          <span className="shrink-0 text-xs text-zinc-500 tabular-nums">{marketRows.length} lines</span>
        </div>
        <div className="flex max-w-full gap-2 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {markets.map(item => (
            <button
              key={item.market}
              type="button"
              onClick={() => setSelectedMarket(item.market)}
              aria-pressed={activeMarket === item.market}
              className={`shrink-0 rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${
                activeMarket === item.market
                  ? 'border-emerald-500/60 bg-emerald-950/70 text-emerald-300'
                  : 'border-zinc-800 bg-zinc-950 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200'
              }`}
            >
              {marketLabel(item.market)} <span className="ml-1 text-[10px] tabular-nums opacity-60">{item.count}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-zinc-500">Sort the research board</p>
        <div className="flex flex-wrap gap-1.5" aria-label="Sort prop board">
          {([
            ['hit-rate', 'Hit rate'],
            ['edge', 'Edge'],
            ['line', 'Line'],
          ] as [SortKey, string][]).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => chooseSort(key)}
              aria-pressed={sortKey === key}
              className={`rounded-md px-2.5 py-1.5 text-xs transition-colors ${
                sortKey === key ? 'bg-zinc-700 text-zinc-100' : 'bg-zinc-900 text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {label}{sortKey === key ? (sortDirection === 'desc' ? ' ↓' : ' ↑') : ''}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-3">
        {sortedRows.map(row => {
          const historyState = historyByRow[row.key]
          const history = historyState?.data
          const isUfc = row.league === 'ufc'
          const projection = history?.projection ?? null
          const edge = projection === null ? null : projection - row.line
          return (
            <article key={row.key} data-market-row className="min-w-0 overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900">
              <div className="grid min-w-0 gap-4 p-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-start">
                <div className="min-w-0">
                  <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
                    <h3 className="truncate font-semibold text-zinc-100">{row.player}</h3>
                    <span className="text-xs font-medium text-zinc-500">{row.team}</span>
                  </div>
                  <p className="mt-0.5 truncate text-xs text-zinc-500">{matchup(row)}</p>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <span className="text-2xl font-bold text-white tabular-nums">{formatValue(row.line)}</span>
                    {row.offerKind === 'pickem_threshold' ? <>
                      <span className="rounded-md border border-emerald-900/60 bg-emerald-950/40 px-2 py-1 text-xs text-emerald-300">
                        More
                      </span>
                      <span className="rounded-md border border-zinc-700 bg-zinc-800/70 px-2 py-1 text-xs text-zinc-300">
                        Less
                      </span>
                      <span className="text-[10px] tracking-wide text-zinc-600">{row.sourceLabel}</span>
                    </> : <>
                      <span className="rounded-md border border-emerald-900/60 bg-emerald-950/40 px-2 py-1 text-xs text-emerald-300 tabular-nums">
                        O <strong>{formatOdds(row.over?.odds)}</strong>
                      </span>
                      <span className="rounded-md border border-zinc-700 bg-zinc-800/70 px-2 py-1 text-xs text-zinc-300 tabular-nums">
                        U <strong>{formatOdds(row.under?.odds)}</strong>
                      </span>
                      <span className="text-[10px] uppercase tracking-wide text-zinc-600">{row.sourceLabel}</span>
                    </>}
                  </div>
                </div>

                <div className="min-w-0 md:text-right">
                  {isUfc ? (
                    <p className="text-xs text-zinc-600">Method-of-victory market</p>
                  ) : historyState?.loading ? <LoadingEvidence /> : history ? (
                    <div className="space-y-2">
                      <div className="flex flex-wrap gap-1.5 md:justify-end">
                        <RateChip label="L5" value={history.hit_rate.l5} />
                        <RateChip label="L10" value={history.hit_rate.l10} />
                        <RateChip label="L20" value={history.hit_rate.l20} />
                      </div>
                      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs md:justify-end">
                        <span className="text-zinc-500">Projection <strong className="text-zinc-200 tabular-nums">{projection === null ? '—' : formatValue(projection)}</strong></span>
                        <span className="text-zinc-500">Edge <strong className={`${edge !== null && Math.abs(edge) > 0 ? 'text-emerald-300' : 'text-zinc-300'} tabular-nums`}>
                          {edge === null ? '—' : edge === 0 ? 'Even' : `${edge > 0 ? 'O' : 'U'} +${Math.abs(edge).toFixed(1)}`}
                        </strong></span>
                      </div>
                    </div>
                  ) : (
                    <p className="text-xs text-zinc-600">Model evidence unavailable</p>
                  )}
                </div>
              </div>

              {isUfc ? (
                <div data-market-chart className="min-w-0 overflow-hidden border-t border-zinc-800 bg-zinc-950/40">
                  <FightForm playerId={row.playerId} fighter={row.player} />
                </div>
              ) : history?.games.length ? (
                <div data-market-chart className="min-w-0 overflow-hidden border-t border-zinc-800 bg-zinc-950/40 p-3 sm:p-4">
                  <PropChart data={history} />
                </div>
              ) : historyState?.loading ? (
                <div data-market-chart className="min-w-0 overflow-hidden border-t border-zinc-800 bg-zinc-950/40 p-3 sm:p-4">
                  <div className="h-32 animate-pulse rounded-lg bg-zinc-800/60" />
                </div>
              ) : (
                <div data-history-empty className="border-t border-zinc-800 bg-zinc-950/40 px-4 py-3 text-xs text-zinc-600">
                  No history yet.
                </div>
              )}
            </article>
          )
        })}
      </div>
    </section>
  )
}
