import { useState, useMemo, useEffect } from 'react'
import { trackPropChartOpened } from '../../lib/analytics'

// ── types ────────────────────────────────────────────────
export interface GameLog {
  date: string
  value: number
  opponent: string
  home: boolean | null
  hit: boolean
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
  hit_rate: { l5: number; l10: number; l20: number; season: number }
  // How many games are actually behind each window. A window's NAME is not
  // its size: `games[:20]` on a player with three matches is three matches,
  // and L5/L10/L20 then all print the same number, which reads as a
  // twenty-game record. Optional so an older payload still renders.
  hit_rate_n?: { l5: number; l10: number; l20: number; season: number }
  games: GameLog[]
}

type Window = 'l5' | 'l10' | 'l20' | 'season'
type Venue = 'all' | 'home' | 'away'

const WINDOWS: { key: Window; label: string }[] = [
  { key: 'l5', label: 'L5' },
  { key: 'l10', label: 'L10' },
  { key: 'l20', label: 'L20' },
  { key: 'season', label: 'S' },
]

// ── helpers ───────────────────────────────────────────────
// M/D, the form the reference uses under each bar. Noon-anchored so a UTC date
// string does not roll backwards in a negative offset.
function shortDate(iso: string): string {
  const d = new Date(iso + 'T12:00:00')
  return Number.isNaN(d.getTime()) ? iso : `${d.getMonth() + 1}/${d.getDate()}`
}

// ── component ─────────────────────────────────────────────
export default function PropChart({ data, window: initialWindow = 'l10' }: { data: PropHistory; window?: Window }) {
  const [win, setWin] = useState<Window>(initialWindow)
  const [venue, setVenue] = useState<Venue>('all')
  const [vsOpp, setVsOpp] = useState(false)

  // A caller can swap `data` to a different player/market/side without remounting
  // this component (e.g. clicking between prop buttons on the same card). Reset
  // filters whenever the underlying series identity changes so a filter chosen for
  // the last chart doesn't silently blank out the new one.
  const seriesKey = `${data.player_id}:${data.market}:${data.side}:${data.line}`
  useEffect(() => {
    setWin(initialWindow)
    setVenue('all')
    setVsOpp(false)
  }, [seriesKey, initialWindow])

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
    if (venue === 'home') filtered = filtered.filter(g => g.home === true)
    else if (venue === 'away') filtered = filtered.filter(g => g.home === false)
    if (vsOpp && opponents.length > 0) {
      const target = opponents[0]
      filtered = filtered.filter(g => g.opponent === target)
    }
    const maxGames = win === 'l5' ? 5 : win === 'l10' ? 10 : win === 'l20' ? 20 : filtered.length
    return filtered.slice(0, maxGames).reverse()
  }, [data.games, win, venue, vsOpp, opponents])

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
    if (displayGames.length < required) return null
    const hits = displayGames.filter(g => g.hit).length
    return hits / displayGames.length
  }, [displayGames, win])

  // "2.8 avg last 5" in the reference: the mean of what is actually drawn, so
  // it moves with the window and the venue filters rather than describing a
  // different set of games than the bars above it.
  const average = useMemo(() => {
    if (!displayGames.length) return null
    return displayGames.reduce((sum, g) => sum + g.value, 0) / displayGames.length
  }, [displayGames])

  const isDefaultFilters = win === initialWindow && venue === 'all' && !vsOpp
  const resetFilters = () => { setWin(initialWindow); setVenue('all'); setVsOpp(false) }

  const hasGames = displayGames.length > 0
  const maxVal = hasGames ? Math.max(data.line, ...displayGames.map(g => g.value)) : data.line
  const minVal = hasGames ? Math.min(0, ...displayGames.map(g => g.value)) : 0
  const range = maxVal - minVal || 1
  // Wide enough for an away abbreviation (`@BOS`) at the label size below the
  // bar. It was 28, which clipped four characters.
  const barW = 34
  const gap = 6
  const chartW = hasGames ? displayGames.length * (barW + gap) - gap : 0
  const chartH = 72
  const padTop = 16

  const y = (v: number) => padTop + chartH * (1 - (v - minVal) / range)
  const lineY = y(data.line)
  const isHit = (v: number) => data.side === 'over' ? v >= data.line : v <= data.line

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3 text-sm flex-wrap">
        <span className="font-semibold text-zinc-200">{data.player}</span>
        <span className="text-zinc-500 text-xs">{data.team}</span>
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
                  const barH = Math.max(3, chartH * (g.value - minVal) / range)
                  const barY = padTop + chartH - barH
                  const hit = isHit(g.value)
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
                    <div className="text-[11px] font-semibold text-zinc-200 tabular-nums">{g.value}</div>
                    {/* No slice and no truncate. `@BOS` is four characters and
                        was being clipped by a 28px column, which reads as a data
                        problem rather than a layout one. The column is sized to
                        hold a real abbreviation instead. */}
                    <div className="whitespace-nowrap text-[10px] text-zinc-400"
                         title={`${g.home === false ? '@ ' : ''}${g.opponent} · ${g.date}`}>
                      {g.home === false ? '@' : ''}{g.opponent || '—'}
                    </div>
                    <div className="text-[10px] text-zinc-500 tabular-nums">{shortDate(g.date)}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {average !== null && (
            <p className="text-center text-[11px] text-zinc-400">
              <span className="font-semibold text-zinc-200 tabular-nums">{average.toFixed(1)}</span>
              {' '}avg last {displayGames.length}
            </p>
          )}
        </>
      )}
    </div>
  )
}
