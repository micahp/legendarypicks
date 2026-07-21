import { useState, useMemo, useEffect } from 'react'

// ── types ────────────────────────────────────────────────
export interface GameLog {
  date: string
  value: number
  opponent: string
  home: boolean
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
function gameLabel(g: GameLog, i: number, total: number): string {
  const isLast = i === total - 1
  const loc = g.home ? 'vs' : '@'
  return isLast ? `${new Date(g.date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} · ${loc} ${g.opponent}` : ''
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

  const opponents = useMemo(() => {
    const seen = new Set<string>()
    return data.games.filter(g => { if (seen.has(g.opponent)) return false; seen.add(g.opponent); return !!g.opponent }).map(g => g.opponent)
  }, [data.games])

  const displayGames = useMemo(() => {
    let filtered = data.games
    if (venue === 'home') filtered = filtered.filter(g => g.home)
    else if (venue === 'away') filtered = filtered.filter(g => !g.home)
    if (vsOpp && opponents.length > 0) {
      const target = opponents[0]
      filtered = filtered.filter(g => g.opponent === target)
    }
    const maxGames = win === 'l5' ? 5 : win === 'l10' ? 10 : win === 'l20' ? 20 : filtered.length
    return filtered.slice(0, maxGames).reverse()
  }, [data.games, win, venue, vsOpp, opponents])

  const hitRate = useMemo(() => {
    if (!displayGames.length) return null
    const hits = displayGames.filter(g => g.hit).length
    return hits / displayGames.length
  }, [displayGames])

  const isDefaultFilters = win === initialWindow && venue === 'all' && !vsOpp
  const resetFilters = () => { setWin(initialWindow); setVenue('all'); setVsOpp(false) }

  const hasGames = displayGames.length > 0
  const maxVal = hasGames ? Math.max(data.line, ...displayGames.map(g => g.value)) : data.line
  const minVal = hasGames ? Math.min(0, ...displayGames.map(g => g.value)) : 0
  const range = maxVal - minVal || 1
  const barW = 28
  const gap = 6
  const chartW = hasGames ? displayGames.length * (barW + gap) - gap : 0
  const chartH = 72
  const padTop = 16
  const padBottom = 8
  const svgH = chartH + padTop + padBottom + 22

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
          <div className="overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" style={{ maxWidth: '100%' }}>
            <svg width={chartW} height={svgH} className="block" style={{ minWidth: chartW }}>
              <line x1={0} y1={lineY} x2={chartW} y2={lineY} stroke="#71717a" strokeWidth={1} strokeDasharray="4,3" />
              <text x={chartW + 2} y={lineY + 4} className="text-[9px] fill-zinc-500" textAnchor="start">{data.line}</text>

              {displayGames.map((g, i) => {
                const x = i * (barW + gap)
                const barH = Math.max(2, chartH * (g.value - minVal) / range)
                const barY = padTop + chartH - barH
                const hit = isHit(g.value)
                const color = hit ? '#34d399' : '#71717a'
                const alpha = hit ? '0.9' : '0.5'
                return (
                  <g key={i}>
                    <rect x={x} y={barY} width={barW} height={barH} rx={3} fill={color} opacity={alpha} />
                    <text x={x + barW / 2} y={svgH - 4} className="text-[9px] fill-zinc-500" textAnchor="middle">{g.value}</text>
                    {i === displayGames.length - 1 && (
                      <text x={x + barW / 2} y={svgH - 4} className="text-[9px] fill-zinc-500" textAnchor="middle" dy={-svgH + padTop + chartH + 18}>
                        {gameLabel(g, i, displayGames.length)}
                      </text>
                    )}
                  </g>
                )
              })}
            </svg>
          </div>

          <div className="flex gap-[6px] text-[10px] text-zinc-600" style={{ paddingLeft: 0 }}>
            {displayGames.map((g, i) => (
              <div key={i} className="text-center overflow-hidden" style={{ width: barW, flexShrink: 0 }}>
                <span title={`${g.home ? 'vs' : '@'} ${g.opponent} · ${g.date}`}>
                  {g.opponent.length > 5 ? g.opponent.slice(0, 5) : g.opponent || '—'}
                </span>
                <span className="text-zinc-700 ml-0.5">{g.home ? '' : '↑'}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
