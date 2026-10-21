import { useState, useMemo, useEffect } from 'react'
import { trackPropChartOpened } from '../../lib/analytics'
import WithoutControl, { TeammateOut, WithoutSample } from './WithoutControl'

// ── types ────────────────────────────────────────────────
export interface GameLog {
  date: string
  value: number | null
  opponent: string
  home: boolean | null
  hit: boolean | null
  status?: 'played' | 'dnp' | 'missing'
  appearance_status?: 'played' | 'dnp' | 'unknown'
  season?: number | null
  game_type?: string | null
}

export interface PropHistory {
  player_id: number
  player: string
  team: string
  league: string
  market: string
  line: number
  side: 'over' | 'under'
  projection: number | null
  hit_rate: { l5: number | null; l10: number | null; l20: number | null; season: number | null }
  // How many games are actually behind each window. A window's NAME is not
  // its size: `games[:20]` on a player with three matches is three matches,
  // and L5/L10/L20 then all print the same number, which reads as a
  // twenty-game record. Optional so an older payload still renders.
  hit_rate_n?: { l5: number; l10: number; l20: number; season: number }
  season?: number
  games: GameLog[]
  // Present only on a response filtered by teammate availability (?without=).
  n_games?: number
  n_excluded_unknown?: number
  n_excluded_not_teammate?: number
}

type Window = 'l5' | 'l10' | 'l20' | 'season'
type Venue = 'all' | 'home' | 'away'

const WINDOWS: { key: Window; label: string }[] = [
  { key: 'l5', label: 'L5' },
  { key: 'l10', label: 'L10' },
  { key: 'l20', label: 'L20' },
  { key: 'season', label: 'S' },
]

export function nbaSeasonStartYear(date: string): number | null {
  const match = /^(\d{4})-(\d{2})/.exec(date || '')
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  return Number.isFinite(year) && Number.isFinite(month)
    ? (month >= 7 ? year : year - 1)
    : null
}

// ── helpers ───────────────────────────────────────────────
// M/D, the form the reference uses under each bar. Noon-anchored so a UTC date
// string does not roll backwards in a negative offset.
function shortDate(iso: string): string {
  const d = new Date(iso + 'T12:00:00')
  return Number.isNaN(d.getTime()) ? iso : `${d.getMonth() + 1}/${d.getDate()}`
}

function chartOpponent(opponent: string, league: string): string {
  if (league !== 'ufc') return opponent
  const parts = opponent.trim().split(/\s+/).filter(Boolean)
  if (parts.length < 2) return opponent
  const suffix = parts[parts.length - 1]
  if (/^(Jr\.?|Sr\.?|II|III|IV)$/i.test(suffix) && parts.length > 2) {
    return `${parts[parts.length - 2]} ${suffix}`
  }
  return suffix
}

// ── component ─────────────────────────────────────────────
// The chart reads the shared URL's ?without=<player id> and writes it back, so a filtered view can be sent
// to someone; it is applied only when that id is one of this player's teammates who missed games.
function readWithoutParam(): number | null {
  try {
    const raw = new URLSearchParams(window.location.search).get('without')
    const id = raw === null ? NaN : Number(raw)
    return Number.isInteger(id) ? id : null
  } catch { return null }
}

function writeWithoutParam(id: number | null) {
  try {
    const url = new URL(window.location.href)
    if (id === null) url.searchParams.delete('without')
    else url.searchParams.set('without', String(id))
    window.history.replaceState(window.history.state, '', url.toString())
  } catch { /* a view without history support just does not carry the filter */ }
}

export default function PropChart({ data: base, window: initialWindow = 'l10' }: { data: PropHistory; window?: Window }) {
  const [win, setWin] = useState<Window>(initialWindow)
  const [without, setWithout] = useState<number | null>(null)
  const [teammates, setTeammates] = useState<TeammateOut[]>([])
  const [filtered, setFiltered] = useState<PropHistory | null>(null)
  const [filterLoading, setFilterLoading] = useState(false)
  const [filterFailed, setFilterFailed] = useState(false)
  // Everything below reads `data`: the unfiltered history, or the one for the selected teammate once it lands.
  const data = without !== null && filtered && !filterLoading ? filtered : base
  const [venue, setVenue] = useState<Venue>('all')
  const [vsOpp, setVsOpp] = useState(false)

  // A caller can swap `data` to a different player/market/side without remounting
  // this component (e.g. clicking between prop buttons on the same card). Reset
  // filters whenever the underlying series identity changes so a filter chosen for
  // the last chart doesn't silently blank out the new one.
  const seriesKey = `${base.player_id}:${base.market}:${base.side}:${base.line}`
  useEffect(() => {
    setWin(initialWindow)
    setVenue('all')
    setVsOpp(false)
    setWithout(null)
    setFiltered(null)
    setFilterFailed(false)
  }, [seriesKey, initialWindow])

  // Teammates who missed games, NFL only (availability exists for no other league).
  const playerId = base.player_id
  const isNfl = base.league === 'nfl'
  useEffect(() => {
    setTeammates([])
    if (!isNfl || !playerId) return
    let live = true
    fetch(`/api/props/player/${playerId}/teammates-out`)
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => {
        if (!live) return
        const list: TeammateOut[] = Array.isArray(d?.teammates) ? d.teammates : []
        setTeammates(list)
        const fromUrl = readWithoutParam()
        if (fromUrl !== null && list.some(t => t.player_id === fromUrl)) setWithout(fromUrl)
      })
      .catch(() => { if (live) setTeammates([]) })
    return () => { live = false }
  }, [playerId, isNfl, seriesKey])

  // The history for the selected teammate, from the same route the unfiltered chart uses.
  useEffect(() => {
    if (without === null) { setFiltered(null); setFilterFailed(false); return }
    let live = true
    setFilterLoading(true); setFilterFailed(false)
    const params = new URLSearchParams({
      player_id: String(base.player_id), market: base.market, line: String(base.line),
      side: base.side, league: base.league, without: String(without),
    })
    if (base.season !== undefined) params.set('season', String(base.season))
    fetch(`/api/props/history?${params}`)
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => {
        if (!live) return
        if (!Array.isArray(d?.games)) throw new Error('no games')
        setFiltered(d)
      })
      .catch(() => { if (live) { setFiltered(null); setFilterFailed(true) } })
      .finally(() => { if (live) setFilterLoading(false) })
    return () => { live = false }
  }, [without, seriesKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const selectWithout = (id: number | null) => { setWithout(id); writeWithoutParam(id) }

  // Keyed on seriesKey rather than mount: callers swap `data` between prop buttons
  // without remounting, and each of those is a chart opened.
  useEffect(() => {
    trackPropChartOpened({
      player_id: data.player_id,
      league: data.league,
      market: data.market,
    })
  }, [seriesKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const opponents = useMemo(() => {
    const seen = new Set<string>()
    return data.games.filter(g => { if (seen.has(g.opponent)) return false; seen.add(g.opponent); return !!g.opponent }).map(g => g.opponent)
  }, [data.games])

  const displayGames = useMemo(() => {
    let filtered = data.games
    if (data.league === 'nba' && win === 'season' && data.season !== undefined) {
      filtered = filtered.filter(g => g.season === data.season)
    }
    if (venue === 'home') filtered = filtered.filter(g => g.home === true)
    else if (venue === 'away') filtered = filtered.filter(g => g.home === false)
    if (vsOpp && opponents.length > 0) {
      const target = opponents[0]
      filtered = filtered.filter(g => g.opponent === target)
    }
    const maxGames = win === 'l5' ? 5 : win === 'l10' ? 10 : win === 'l20' ? 20 : filtered.length
    if (data.league === 'nba' && win !== 'season') {
      const selected: GameLog[] = []
      let played = 0
      for (const game of filtered) {
        selected.push(game)
        if (game.status === 'played' || (!game.status && game.value !== null)) played += 1
        if (played >= maxGames) break
      }
      return selected.reverse()
    }
    return filtered.slice(0, maxGames).reverse()
  }, [data.games, data.league, data.season, win, venue, vsOpp, opponents])

  // A window's NAME is a claim about its SAMPLE. `games.slice(0, 20)` on a
  // player with three matches is three matches, so L5, L10 and L20 all
  // reported the same figure and a 3-for-3 player read as a perfect
  // twenty-game record. Liga MX surfaced it -- those players have ~8
  // appearances where an MLS player has 40 -- but the arithmetic was always
  // this. Below the window's own count there is no L10 to report, so it
  // renders as a dash rather than as a number that overstates what it saw.
  //
  // Season is exempt: it claims whatever exists, so it is never short.
  const hitRate = useMemo(() => {
    if (!displayGames.length) return null
    const required = win === 'l5' ? 5 : win === 'l10' ? 10 : win === 'l20' ? 20 : 0
    const windowGames = data.league === 'nba'
      ? displayGames.filter(g => g.status === 'played' || (!g.status && g.value !== null)).length
      : displayGames.length
    const measured = displayGames.filter(g => g.value !== null && g.hit !== null
      && (data.league !== 'nba' || g.status === 'played' || !g.status))
    if (windowGames < required || !measured.length) return null
    const hits = measured.filter(g => g.hit === true).length
    return hits / measured.length
  }, [displayGames, win, data.league])

  // "2.8 avg last 5" in the reference: the mean of what is actually drawn, so
  // it moves with the window and the venue filters rather than describing a
  // different set of games than the bars above it.
  const average = useMemo(() => {
    const measured = displayGames.filter(g => g.value !== null
      && (data.league !== 'nba' || g.status === 'played' || !g.status))
    if (!measured.length) return null
    return measured.reduce((sum, g) => sum + (g.value as number), 0) / measured.length
  }, [displayGames, data.league])

  const isDefaultFilters = win === initialWindow && venue === 'all' && !vsOpp && without === null
  const resetFilters = () => { setWin(initialWindow); setVenue('all'); setVsOpp(false); selectWithout(null) }
  const selectedName = teammates.find(t => t.player_id === without)?.name ?? `player ${without}`
  const sample: WithoutSample | null = without !== null && filtered && !filterLoading
    ? { n_games: filtered.n_games ?? filtered.games.length,
        n_excluded_unknown: filtered.n_excluded_unknown ?? 0,
        n_excluded_not_teammate: filtered.n_excluded_not_teammate ?? 0 }
    : null

  const hasGames = displayGames.length > 0
  const measuredValues = displayGames.filter(g => g.value !== null
    && (data.league !== 'nba' || g.status === 'played' || !g.status))
    .map(g => g.value as number)
  const maxVal = measuredValues.length ? Math.max(data.line, ...measuredValues) : data.line
  const minVal = measuredValues.length ? Math.min(0, ...measuredValues) : 0
  const range = maxVal - minVal || 1
  // Wide enough for an away abbreviation (`@BOS`) at the label size below the
  // bar. It was 28, which clipped four characters.
  const barW = data.league === 'ufc' ? 72 : 34
  const gap = data.league === 'ufc' ? 8 : 6
  const chartW = hasGames ? displayGames.length * (barW + gap) - gap : 0
  const chartH = 72
  const padTop = 16

  const y = (v: number) => padTop + chartH * (1 - (v - minVal) / range)
  const lineY = y(data.line)
  const isHit = (v: number) => data.side === 'over' ? v >= data.line : v <= data.line

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3 text-sm flex-wrap">
        {/* Player and team are already on the card directly above this chart;
            repeating them here spent the widest row on information the reader
            just read. */}
        <span className="text-zinc-400 capitalize">{data.market.replace(/_/g, ' ')}</span>
        <span className="font-bold tabular-nums text-zinc-200">Line {data.line}</span>
        {data.projection !== null && (
          <span className="text-xs text-zinc-500 tabular-nums">Proj {data.projection.toFixed(1)}</span>
        )}
        <span className="text-xs tabular-nums">
          {hitRate === null ? (
            <span className="text-zinc-600">—</span>
          ) : (
            <span className={hitRate >= 0.5 ? 'text-emerald-400' : 'text-red-400'}>
              {Math.round(hitRate * 100)}%
            </span>
          )}
          <span className="text-zinc-600"> ({win === 'season' ? 'season' : win.toUpperCase()})</span>
        </span>
      </div>

      {data.league === 'nba' && (
        <div className="flex flex-wrap gap-3 text-[10px] text-zinc-500" aria-label="Game status legend">
          <span><span className="mr-1 text-zinc-500">●</span>DNP</span>
          <span><span className="mr-1 text-amber-500">●</span>Stat data missing</span>
        </div>
      )}

      <div className="flex gap-1.5 flex-wrap items-center">
        {WINDOWS.map(w => (
          <button key={w.key} onClick={() => setWin(w.key)}
            className={`px-2.5 py-0.5 rounded text-[11px] font-medium transition-colors ${win === w.key ? 'bg-zinc-700 text-zinc-200' : 'text-zinc-500 hover:text-zinc-300'}`}>
            {w.label}
          </button>
        ))}
        <span className="text-zinc-700 mx-1">·</span>
        {(['all', 'home', 'away'] as Venue[]).map(v => (
          <button key={v} onClick={() => setVenue(v)}
            className={`px-2.5 py-0.5 rounded text-[11px] font-medium transition-colors ${venue === v ? 'bg-zinc-700 text-zinc-200' : 'text-zinc-500 hover:text-zinc-300'}`}>
            {v === 'all' ? 'All' : v === 'home' ? 'Home' : 'Away'}
          </button>
        ))}
        {opponents.length > 0 && (
          <button onClick={() => setVsOpp(!vsOpp)}
            className={`px-2.5 py-0.5 rounded text-[11px] font-medium transition-colors ${vsOpp ? 'bg-zinc-700 text-zinc-200' : 'text-zinc-500 hover:text-zinc-300'}`}>
            vs {opponents[0]}
          </button>
        )}
        {!isDefaultFilters && (
          <button onClick={resetFilters}
            className="ml-auto px-2.5 py-0.5 rounded text-[11px] font-medium text-emerald-400/80 hover:text-emerald-300">
            Reset filters
          </button>
        )}
      </div>

      <WithoutControl teammates={teammates} selected={without} selectedName={selectedName}
        sample={sample} loading={filterLoading} failed={filterFailed} onSelect={selectWithout} />

      {!hasGames ? (
        <div className="flex flex-col items-center gap-2 py-6 text-center">
          <p className="text-zinc-500 text-xs">No games match these filters.</p>
          <button onClick={resetFilters}
            className="px-2.5 py-1 rounded text-[11px] font-medium bg-zinc-800 text-zinc-300 hover:bg-zinc-700">
            Reset filters
          </button>
        </div>
      ) : (
        <>
          {/* Bars only. A miss is RED, not a dimmed green: at a glance the
              question is hit-or-miss, and two shades of one hue answer it more
              slowly than two hues. The dashed rule is the line itself, labelled
              at the right where it ends.
              #34d399 / #f87171 are OUR emerald-400 and red-400 -- the same pair
              the hit-rate headline above already uses. The reference's neon
              green is not copied: matching a competitor's layout is not a
              reason to adopt their palette. */}
          <div className="overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" style={{ maxWidth: '100%' }}>
            <div style={{ minWidth: chartW + 26 }}>
              <svg width={chartW + 26} height={chartH + padTop + 6} className="block">
                <line x1={0} y1={lineY} x2={chartW} y2={lineY}
                      stroke="#d4d4d8" strokeWidth={1} strokeDasharray="5,4" />
                <text x={chartW + 4} y={lineY + 4} className="text-[10px] font-semibold fill-zinc-300"
                      textAnchor="start">{data.line}</text>
                {displayGames.map((g, i) => {
                  const x = i * (barW + gap)
                  const isDnp = g.status === 'dnp'
                  const hasValue = g.value !== null && !isDnp
                  if (!hasValue) {
                    const markerY = padTop + chartH
                    return (
                      <g key={i}>
                        <circle cx={x + barW / 2} cy={markerY - 2} r={4}
                          fill={isDnp ? '#71717a' : '#f59e0b'} />
                        <title>{isDnp ? 'DNP' : 'Stat data missing'} · {g.date}</title>
                      </g>
                    )
                  }
                  const barH = Math.max(3, chartH * ((g.value as number) - minVal) / range)
                  const barY = padTop + chartH - barH
                  const hit = isHit(g.value as number)
                  return (
                    <rect key={i} x={x} y={barY} width={barW} height={barH}
                          rx={6} ry={6} fill={hit ? '#34d399' : '#f87171'} />
                  )
                })}
                {/* Baseline the bars stand on. */}
                <line x1={0} y1={padTop + chartH} x2={chartW} y2={padTop + chartH}
                      stroke="#3f3f46" strokeWidth={1.5} />
              </svg>

              {/* Value, opponent and date stacked under each bar, aligned to the
                  same column width. Away games carry the @ the reference uses. */}
              <div data-game-labels className="flex" style={{ gap }}>
                {displayGames.map((g, i) => (
                  <div key={i} className="text-center" style={{ width: barW, flexShrink: 0 }}>
                    {/* One colour for all three lines. A three-tone ramp implied
                        a hierarchy between value, opponent and date that nobody
                        reading a game log wants. */}
                    <div className="text-[11px] font-semibold text-zinc-400 tabular-nums"
                         title={g.status === 'dnp' ? 'Did not play' : g.status === 'missing'
                           ? (g.appearance_status === 'played' ? 'Played; stat data missing' : 'Stat data missing')
                           : 'Played'}>
                      {g.status === 'dnp' ? 'DNP' : g.value === null ? '—' : g.value}
                    </div>
                    {/* Team sports publish compact abbreviations. UFC publishes
                        full names, which collided across five 34px columns on
                        desktop; show a wider surname label while retaining the
                        complete opponent and date in the tooltip. */}
                    <div
                         data-ufc-opponent-label={data.league === 'ufc' ? 'true' : undefined}
                         className={`whitespace-nowrap text-[10px] text-zinc-400 ${data.league === 'ufc' ? 'overflow-hidden text-ellipsis' : ''}`}
                         title={`${g.home === false ? '@ ' : ''}${g.opponent} · ${g.date}`}>
                      {g.home === false ? '@' : ''}{chartOpponent(g.opponent || '—', data.league)}
                    </div>
                    <div className="text-[10px] text-zinc-400 tabular-nums">{shortDate(g.date)}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {average !== null && (
            <p className="text-center text-[11px] text-zinc-400">
              <span className="font-semibold text-zinc-200 tabular-nums">{average.toFixed(1)}</span>
              {' '}avg last {displayGames.filter(g => g.value !== null
                && (data.league !== 'nba' || g.status === 'played' || !g.status)).length} played
            </p>
          )}
        </>
      )}
    </div>
  )
}
