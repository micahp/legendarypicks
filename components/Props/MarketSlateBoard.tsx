import { useEffect, useMemo, useRef, useState } from 'react'
import FightForm from './FightForm'
import MatchForm from './MatchForm'
import PropChart, { PropHistory } from './PropChart'

interface BoardProp {
  id: number
  market: string
  line: number
  side: string
  source: string
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

interface BoardLine {
  offerKey: string
  rawMarket: string
  line: number
  source: string
  over?: BoardProp
  under?: BoardProp
}

interface BoardRow {
  key: string
  playerId: number
  player: string
  team: string
  league: string
  market: string
  home: string
  away: string
  date: string
  lines: BoardLine[]
}

type ActiveBoardRow = BoardRow & BoardLine

function historyKey(row: ActiveBoardRow): string {
  return `${row.key}::${row.offerKey}`
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

type SortKey = 'hit-rate' | 'confidence' | 'odds' | 'edge' | 'line'
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

// Books that quote no per-leg price. PrizePicks, Underdog, Sleeper and Pick6 are
// pick'em products: you choose over or under and the payout comes from the
// ENTRY's multiplier (2-pick, 3-pick, flex), not from a price on the leg.
//
// RotoWire populates the field anyway with a constant. Verified in its raw
// payload 2026-08-26: across every archived prop, `prizepicks` and `underdog`
// each carry exactly ONE (over, under) pair -- (-137, -137) -- while sleeper has
// 231 distinct pairs, draftkings-sb 351 and fanduel-sb 88. In our own table the
// same shows as 2,688 prizepicks rows and 1,870 underdog rows with a single
// distinct odds value.
//
// -137 is roughly 57.8% implied, about what a pick'em leg needs to break even at
// standard multipliers. It is a sensible convention and it is not a price: it
// never varies, and it is identical on both sides, which no real book does. Shown
// as a number it invites a comparison that cannot mean anything -- so it is not
// shown. A blank is honest; a placeholder rendered as a measurement is not.
const PICKEM_SOURCES = /^(rotowire:)?(prizepicks|underdog|sleeper|pick6)(-demon|-goblin)?$/

function isPickem(source: string | undefined): boolean {
  return PICKEM_SOURCES.test((source || '').trim().toLowerCase())
}

function sourceLabel(source: string): string {
  // Keep the full value (for example `rotowire:underdog`) in the data model:
  // it records how the offer reached us. The reader only needs the app where
  // the offer can be played, so the relay prefix does not belong on the card.
  return source.replace(/^rotowire:/i, '')
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
    // One card is one player's market in one game. Provider+line belongs one
    // level below as a selectable offer; putting it in this key produced up to
    // 26 duplicate cards for one player/market/game.
    const identity = prop.player_id ?? `name:${prop.player_name}:${prop.player_team || ''}`
    const key = [identity, market, prop.game_date, home, away].join('|')
    let row = grouped.get(key)
    if (!row) {
      row = {
        key,
        playerId: prop.player_id,
        player: prop.player_name,
        team: prop.player_team || '',
        league: prop.league,
        market,
        home,
        away,
        date: prop.game_date,
        lines: [],
      }
      grouped.set(key, row)
    }

    // Equal numbers at two providers are still two offers. Over and under at
    // one provider+line are the two sides of one offer, not two dropdown items.
    const offerKey = `${String(prop.line)}|${prop.source}`
    let offer = row.lines.find(item => item.offerKey === offerKey)
    if (!offer) {
      offer = {
        offerKey,
        rawMarket: prop.market,
        line: prop.line,
        source: prop.source,
      }
      row.lines.push(offer)
    }

    const side = prop.side.toLowerCase()
    if (side === 'under' || side === 'no') {
      if (!offer.under) offer.under = prop
    } else if (!offer.over) {
      offer.over = prop
      offer.rawMarket = prop.market
    }
  }

  return Array.from(grouped.values()).map(row => ({
    ...row,
    lines: row.lines.sort((a, b) =>
      a.line - b.line
      || sourceLabel(a.source).localeCompare(sourceLabel(b.source))
      || a.source.localeCompare(b.source)),
  }))
}

const PROP_PAGE_SIZE = 500
const MAX_PROP_PAGES = 20

async function fetchAllProps(params: URLSearchParams, signal: AbortSignal): Promise<BoardProp[]> {
  const rows: BoardProp[] = []
  for (let page = 0; page < MAX_PROP_PAGES; page += 1) {
    const pageParams = new URLSearchParams(params)
    pageParams.set('limit', String(PROP_PAGE_SIZE))
    pageParams.set('offset', String(page * PROP_PAGE_SIZE))
    const response = await fetch(`/api/props?${pageParams}`, { signal })
    if (!response.ok) throw new Error(`Props request failed (${response.status})`)
    const data = await response.json()
    if (!Array.isArray(data)) throw new Error('Props response was not a list')
    rows.push(...data)
    if (data.length < PROP_PAGE_SIZE) return rows
  }
  throw new Error(`Props response exceeded ${MAX_PROP_PAGES * PROP_PAGE_SIZE} rows`)
}

// A window's NAME is a claim about its SAMPLE. The API computes L20 as
// games[:20], which on a player with three matches is three matches, so L5,
// L10 and L20 all print the same figure and a 3-for-3 player reads as a
// perfect twenty-game record. Reported from the board 2026-08-26 on Liga MX,
// whose players have ~8 appearances where an MLS player has 40.
//
// `sample` is hit_rate_n from the API: the games actually behind this window.
// Short of the window's own count there is no L10 to report, so the chip shows
// a dash. Undefined (an older payload) keeps the previous behaviour rather
// than blanking every chip.

// The lower edge of the range of true hit rates a record is consistent with
// (Wilson score interval, 95%). Ranking on it answers "how likely is this to
// hit again", where the raw rate answers "what fraction hit so far" -- and
// those differ most exactly where this board lives.
//
// A Liga MX player has ~8 appearances because the Apertura is five matchdays
// old; an MLS player has 40. Sorting their raw rates against each other puts a
// 3-for-3 above a 28-for-48, because the percentage discards the sample size,
// which is most of the information. 3/3 is consistent with a true rate
// anywhere in 43.8%..100%; 28/48 with 44.3%..71.2%. The bottom of the range is
// the pessimistic read, and it can only be high when a record is BOTH good and
// well evidenced.
//
// As n grows every correction term vanishes and this converges on the raw
// rate, so a 40-game player is ranked on his actual number. It needs no
// minimum-games threshold, which is the thing a "hide rows under 10 games"
// rule cannot avoid -- and such a rule would bury all but three Liga MX
// players for a reason that is about the calendar, not the player.
function confidenceFloor(hits: number, games: number): number {
  if (games <= 0) return 0
  const z = 1.96
  const p = hits / games
  const denom = 1 + (z * z) / games
  const centre = p + (z * z) / (2 * games)
  const margin = z * Math.sqrt((p * (1 - p)) / games + (z * z) / (4 * games * games))
  return Math.max(0, (centre - margin) / denom)
}

function RateChip({ label, value, sample, required }: {
  label: string; value: number; sample?: number; required: number
}) {
  const short = sample !== undefined && sample < required
  const pct = Math.round(value * 100)
  const tone = short
    ? 'border-zinc-800 bg-zinc-900/60 text-zinc-600'
    : pct >= 60
      ? 'border-emerald-800/70 bg-emerald-950/40 text-emerald-300'
      : pct < 40
        ? 'border-red-900/60 bg-red-950/30 text-red-300'
        : 'border-zinc-700 bg-zinc-800/70 text-zinc-300'
  return (
    <span data-rate-chip={label}
          className={`rounded-md border px-2 py-1 text-[11px] tabular-nums ${tone}`}>
      <span className="text-zinc-500">{label}</span> {short ? '—' : `${pct}%`}
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

function EmptyBoard({ date }: { date: string }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 px-5 py-16 text-center">
      <p className="text-sm font-medium text-zinc-300">No prop markets for this slate.</p>
      <p className="mt-1 text-xs text-zinc-500">Try another league or move off {date}.</p>
    </div>
  )
}

export default function MarketSlateBoard({ league, date }: { league: string; date: string }) {
  const [props, setProps] = useState<BoardProp[]>([])
  const [marketOptions, setMarketOptions] = useState<MarketOption[]>([])
  const [loadedMarket, setLoadedMarket] = useState('')
  const [selectedMarket, setSelectedMarket] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('hit-rate')
  const [helpOpen, setHelpOpen] = useState(false)
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [historyByRow, setHistoryByRow] = useState<Record<string, HistoryState>>({})
  const [selectedLineByRow, setSelectedLineByRow] = useState<Record<string, string>>({})
  const historyRequest = useRef(0)
  const requestedHistory = useRef(new Set<string>())
  const historyControllers = useRef(new Map<string, AbortController>())

  useEffect(() => {
    const controller = new AbortController()
    const summaryParams = new URLSearchParams({ date, summary: '1' })
    if (league !== 'All') summaryParams.set('league', league)

    setLoading(true)
    setError(null)
    setProps([])
    setMarketOptions([])
    setLoadedMarket('')
    setSelectedLineByRow({})

    const loadMarketSummary = async () => {
      const response = await fetch(`/api/props/slate?${summaryParams}`, { signal: controller.signal })
      if (!response.ok) throw new Error(`Market summary request failed (${response.status})`)
      const games = await response.json()
      if (!Array.isArray(games)) throw new Error('Market summary response was not a list')

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

      const fallbackParams = new URLSearchParams({ date })
      if (league !== 'All') fallbackParams.set('league', league)
      const fallbackProps = await fetchAllProps(fallbackParams, controller.signal)
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
  const activeRows = useMemo<ActiveBoardRow[]>(() => allRows.map(row => {
    const selected = row.lines.find(line => line.offerKey === selectedLineByRow[row.key])
      || row.lines[0]
    return { ...row, ...selected }
  }), [allRows, selectedLineByRow])
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
    const params = new URLSearchParams({ date, market: activeMarket })
    if (league !== 'All') params.set('league', league)

    setLoading(true)
    setError(null)
    fetchAllProps(params, controller.signal)
      .then(data => {
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
    () => activeRows.filter(row => row.market === activeMarket),
    [activeMarket, activeRows],
  )

  const marketLineCount = useMemo(
    () => marketRows.reduce((count, row) => count + row.lines.length, 0),
    [marketRows],
  )

  // A new slate or market invalidates the history population. Selecting one
  // alternate does not: histories for already-viewed offers stay cached.
  useEffect(() => {
    const requestId = ++historyRequest.current
    for (const controller of historyControllers.current.values()) controller.abort()
    historyControllers.current.clear()
    requestedHistory.current.clear()
    setHistoryByRow({})
    return () => {
      if (historyRequest.current !== requestId) return
      for (const controller of historyControllers.current.values()) controller.abort()
      historyControllers.current.clear()
    }
  }, [activeMarket, date, league])

  useEffect(() => {
    const requestId = historyRequest.current
    for (const row of marketRows) {
      const key = historyKey(row)
      if (requestedHistory.current.has(key)) continue
      requestedHistory.current.add(key)
      setHistoryByRow(current => ({
        ...current,
        [key]: { loading: row.league !== 'ufc', data: null },
      }))

      // Method-of-victory props are categorical. FightForm lazily loads the
      // fighter's ESPN form only when its disclosure is opened.
      if (row.league === 'ufc') continue
      const chartProp = row.over || row.under
      if (!chartProp) continue
      const controller = new AbortController()
      historyControllers.current.set(key, controller)
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
          setHistoryByRow(current => ({ ...current, [key]: { loading: false, data: history } }))
        })
        .catch(err => {
          if (err.name === 'AbortError' || historyRequest.current !== requestId) return
          setHistoryByRow(current => ({ ...current, [key]: { loading: false, data: null } }))
        })
        .finally(() => {
          if (historyControllers.current.get(key) === controller) {
            historyControllers.current.delete(key)
          }
        })
    }
  }, [marketRows])

  const sortedRows = useMemo(() => {
    const valueFor = (row: ActiveBoardRow): number | null => {
      const history = historyByRow[historyKey(row)]?.data
      if (sortKey === 'line') return row.line
      // American odds are MONOTONIC as raw integers: -400, -160, +120, +900 is
      // 80%, 61.5%, 45.5%, 10% -- strictly decreasing probability across the
      // negative/positive boundary. So a plain numeric sort is already
      // shortest-price-to-longest, and needs no conversion.
      //
      // A pick'em row returns null and therefore sorts LAST in either direction
      // (see the comparator). Its stored -137 is the relay's constant for books
      // that quote no per-leg price, so ranking it against a real -160 would be
      // ranking a placeholder against a measurement.
      if (sortKey === 'odds') {
        if (isPickem(row.source)) return null
        const price = row.over?.odds ?? row.under?.odds
        return price === null || price === undefined ? null : price
      }
      if (!history) return null
      if (sortKey === 'hit-rate') return history.hit_rate.l10
      // Over EVERY game held, not a window: the point of this sort is to use
      // all the evidence rather than to truncate it.
      if (sortKey === 'confidence') {
        return confidenceFloor(history.games.filter(g => g.hit).length, history.games.length)
      }
      return history.projection === null ? null : Math.abs(history.projection - row.line)
    }
    // Hit rate over ten games takes eleven distinct values, so ties are the common
    // case, not the edge case: a real slate put six rows on 40% at once. Falling
    // through to the player's name turned the research board into an alphabetical
    // list — the reader sees an order and reads meaning into it, and there is none.
    // So every tie breaks on another number, in a stated order, and the row key is
    // only ever a determinism guard so React keys stay stable across renders.
    const tiebreakers: ((row: ActiveBoardRow) => number)[] = [
      row => {
        const h = historyByRow[historyKey(row)]?.data
        return h?.projection == null ? -Infinity : Math.abs(h.projection - row.line)
      },
      row => historyByRow[historyKey(row)]?.data?.hit_rate.season ?? -Infinity,
      row => historyByRow[historyKey(row)]?.data?.games.length ?? -Infinity,
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

  // Descending is the right default for every key where BIGGER IS BETTER -- hit
  // rate, confidence, edge. Odds is the exception: ascending is shortest price
  // first, which is the favourite. Sorting it descending opens on +10000
  // longshots, which is the least useful end of the board.
  const DEFAULT_DIRECTION: Record<SortKey, 'asc' | 'desc'> = {
    'hit-rate': 'desc', confidence: 'desc', edge: 'desc', line: 'desc',
    odds: 'asc',
  }

  const chooseSort = (next: SortKey) => {
    if (next === sortKey) setSortDirection(direction => direction === 'desc' ? 'asc' : 'desc')
    else {
      setSortKey(next)
      setSortDirection(DEFAULT_DIRECTION[next])
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

  if (!markets.length) return <EmptyBoard date={date} />

  return (
    <section className="min-w-0 space-y-4" aria-label="Market-first prop board">
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-3 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-zinc-200">Choose a market</h2>
            <p className="text-xs text-zinc-500">Every available player line across this slate</p>
          </div>
          <span className="shrink-0 text-xs text-zinc-500 tabular-nums">
            {marketRows.length} props{marketLineCount !== marketRows.length ? ` · ${marketLineCount} lines` : ''}
          </span>
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

      {/* "Sort by" sits next to the controls it labels. It used to read "Sort
          the research board" and was pushed to the far side of a
          justify-between row, so the label and the buttons it described were at
          opposite ends of the screen. */}
      <div className="flex flex-wrap items-center gap-2">
        <p className="shrink-0 text-xs text-zinc-500">Sort by</p>
        <div className="flex flex-wrap items-center gap-1.5" aria-label="Sort prop board">
          {([
            ['hit-rate', 'Hit rate'],
            ['confidence', 'Confidence'],
            ['odds', 'Odds'],
            ['edge', 'Edge'],
            ['line', 'Line'],
          ] as [SortKey, string][]).map(([key, label]) => (
            <span key={key} className="inline-flex items-center">
              <button
                type="button"
                onClick={() => chooseSort(key)}
                aria-pressed={sortKey === key}
                className={`rounded-md px-2.5 py-1.5 text-xs transition-colors ${
                  sortKey === key ? 'bg-zinc-700 text-zinc-100' : 'bg-zinc-900 text-zinc-500 hover:text-zinc-300'
                }`}
              >
                {label}{sortKey === key ? (sortDirection === 'desc' ? ' ↓' : ' ↑') : ''}
              </button>
            </span>
          ))}
          {/* Immediately after the last sort button. `ml-auto` used to push it to
              the far edge of the row, which separated it from the controls it
              explains once the row stopped being justify-between. Still a tap
              target, not a hover tooltip: hover does not exist on touch and this
              board is read on phones. The panel opens right-aligned so it cannot
              push the layout sideways on a narrow screen. */}
          <span className="relative inline-flex items-center">
            <button
              type="button"
              aria-label="What Confidence means"
              aria-expanded={helpOpen}
              onClick={() => setHelpOpen(open => !open)}
              className="grid h-5 w-5 place-items-center rounded-full border border-zinc-700 text-[10px] leading-none text-zinc-500 transition-colors hover:border-zinc-500 hover:text-zinc-300"
            >
              i
            </button>
            {helpOpen && (
              <div
                role="dialog"
                aria-label="About Confidence"
                className="absolute right-0 top-full z-20 mt-1.5 w-72 rounded-lg border border-zinc-700 bg-zinc-900 p-3 text-xs leading-relaxed text-zinc-400 shadow-xl"
              >
                <p>
                  <span className="text-zinc-200">Confidence</span> ranks by the hit
                  rate a record can actually support, not the rate it happens to
                  show. A player who is 3-for-3 has too few games to prove much, so
                  he sits below someone at 58% over 48 games. The more games behind
                  a rate, the closer this gets to the rate itself.
                </p>
                <button
                  type="button"
                  onClick={() => setHelpOpen(false)}
                  className="mt-2 text-[11px] text-zinc-500 hover:text-zinc-300"
                >
                  Got it
                </button>
              </div>
            )}
          </span>
        </div>
      </div>

      <div className="space-y-3">
        {sortedRows.map(row => {
          const historyState = historyByRow[historyKey(row)]
          const history = historyState?.data
          const isUfc = row.league === 'ufc'
          const hasAlternates = row.lines.length > 1
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
                    {hasAlternates ? (
                      <span className="relative inline-flex max-w-full items-center gap-1 text-2xl font-bold text-white tabular-nums">
                        <span data-selected-line>{formatValue(row.line)}</span>
                        <span aria-hidden="true">▾</span>
                        <select
                          aria-label={`Line and provider for ${row.player} ${marketLabel(row.market)}`}
                          data-line-selector
                          value={row.offerKey}
                          onChange={event => setSelectedLineByRow(current => ({
                            ...current,
                            [row.key]: event.target.value,
                          }))}
                          className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                        >
                          {row.lines.map(line => (
                            <option key={line.offerKey} value={line.offerKey}>
                              {formatValue(line.line)} · {sourceLabel(line.source)}
                            </option>
                          ))}
                        </select>
                      </span>
                    ) : (
                      <span className="text-2xl font-bold text-white tabular-nums">{formatValue(row.line)}</span>
                    )}
                    {isPickem(row.source) ? (
                      /* No price to show. The book has none, so the row says so
                         rather than printing the relay's constant. */
                      <span className="rounded-md border border-zinc-800 bg-zinc-900/60 px-2 py-1 text-[11px] text-zinc-500">
                        pick&rsquo;em &middot; no line price
                      </span>
                    ) : (
                      <>
                        <span className="rounded-md border border-emerald-900/60 bg-emerald-950/40 px-2 py-1 text-xs text-emerald-300 tabular-nums">
                          O <strong>{formatOdds(row.over?.odds)}</strong>
                        </span>
                        <span className="rounded-md border border-zinc-700 bg-zinc-800/70 px-2 py-1 text-xs text-zinc-300 tabular-nums">
                          U <strong>{formatOdds(row.under?.odds)}</strong>
                        </span>
                      </>
                    )}
                  </div>
                </div>

                <div className="min-w-0 md:text-right">
                  {isUfc ? (
                    <p className="text-xs text-zinc-600">Method-of-victory market</p>
                  ) : historyState?.loading ? <LoadingEvidence /> : history ? (
                    <div className="space-y-2">
                      <div className="flex flex-wrap gap-1.5 md:justify-end">
                        <RateChip label="L5" value={history.hit_rate.l5} sample={history.hit_rate_n?.l5} required={5} />
                        <RateChip label="L10" value={history.hit_rate.l10} sample={history.hit_rate_n?.l10} required={10} />
                        <RateChip label="L20" value={history.hit_rate.l20} sample={history.hit_rate_n?.l20} required={20} />
                      </div>
                      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs md:justify-end">
                        {/* Every other sort key is a number the reader can see on the
                            row -- hit rate in the chips, edge and line here. Sorting by
                            a value that is nowhere on screen asks someone to trust an
                            order they cannot check. */}
                        <span className="text-zinc-500">Confidence <strong className="text-zinc-200 tabular-nums">
                          {history.games.length
                            ? `${Math.round(confidenceFloor(history.games.filter(g => g.hit).length, history.games.length) * 100)}%`
                            : '—'}
                        </strong></span>
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
              ) : (row.league === 'lcup' || row.league === 'ligamx') ? (
                // No chart because we hold no logs for this player: Liga MX has
                // no season ingest, so its athletes had three tournament games
                // against an MLS player's forty-two. The click reads five
                // matches from ESPN and STORES them, so the chart fills in from
                // ordinary use rather than waiting for a backfill window.
                //
                // Matches BOTH labels. /api/props returns the PLAYER's league,
                // so a Leagues Cup prop on a Liga MX athlete arrives as
                // `ligamx` and one on an MLS athlete as `mls`. Checking only
                // 'lcup' matched neither, and every Liga MX row fell through to
                // "No history" with nothing to click.
                <div data-market-chart className="min-w-0 overflow-hidden border-t border-zinc-800 bg-zinc-950/40">
                  <MatchForm playerId={row.playerId} player={row.player} />
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
