import { useState } from 'react'

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

  // Slice games for the selected window
  const maxGames = win === 'l5' ? 5 : win === 'l10' ? 10 : win === 'l20' ? 20 : data.games.length
  const games = data.games.slice(0, maxGames).reverse() // oldest→newest for left→right
  const hitRate = data.hit_rate[win]

  if (!games.length) {
    return (
      <div className="text-center py-4 text-zinc-500 text-xs">No game history yet.</div>
    )
  }

  // Chart dimensions
  const maxVal = Math.max(data.line, ...games.map(g => g.value))
  const minVal = Math.min(0, ...games.map(g => g.value))
  const range = maxVal - minVal || 1
  const barW = 28
  const gap = 6
  const chartW = games.length * (barW + gap) - gap
  const chartH = 72
  const padTop = 16
  const padBottom = 8
  const svgH = chartH + padTop + padBottom + 22

  // Scale: map value → y position (higher value = higher on chart)
  const y = (v: number) => padTop + chartH * (1 - (v - minVal) / range)
  const lineY = y(data.line)

  // Determine if a bar is a "hit" — respects side inversion
  const isHit = (v: number) => data.side === 'over' ? v >= data.line : v <= data.line

  return (
    <div className="space-y-2">
      {/* Header row: player + market + line + hit-rate + projection */}
      <div className="flex items-center gap-3 text-sm flex-wrap">
        <span className="font-semibold text-zinc-200">{data.player}</span>
        <span className="text-zinc-500 text-xs">{data.team}</span>
        <span className="text-zinc-400 capitalize">{data.market.replace(/_/g, ' ')}</span>
        <span className="font-bold tabular-nums text-zinc-200">Line {data.line}</span>
        {data.projection !== null && (
          <span className="text-xs text-zinc-500 tabular-nums">Proj {data.projection.toFixed(1)}</span>
        )}
        <span className="text-xs tabular-nums">
          <span className={hitRate >= 0.5 ? 'text-emerald-400' : 'text-red-400'}>
            {Math.round(hitRate * 100)}%
          </span>
          <span className="text-zinc-600"> ({win === 'season' ? 'season' : win.toUpperCase()})</span>
        </span>
      </div>

      {/* Window toggle */}
      <div className="flex gap-1.5">
        {WINDOWS.map(w => (
          <button key={w.key} onClick={() => setWin(w.key)}
            className={`px-2.5 py-0.5 rounded text-[11px] font-medium transition-colors ${
              win === w.key ? 'bg-zinc-700 text-zinc-200' : 'text-zinc-500 hover:text-zinc-300'
            }`}
          >
            {w.label}
          </button>
        ))}
      </div>

      {/* Bar chart */}
      <div className="overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" style={{ maxWidth: '100%' }}>
        <svg width={chartW} height={svgH} className="block" style={{ minWidth: chartW }}>
          {/* Horizontal line at the prop line */}
          <line x1={0} y1={lineY} x2={chartW} y2={lineY}
            stroke="#71717a" strokeWidth={1} strokeDasharray="4,3" />

          {/* Line label */}
          <text x={chartW + 2} y={lineY + 4} className="text-[9px] fill-zinc-500" textAnchor="start">
            {data.line}
          </text>

          {/* Bars */}
          {games.map((g, i) => {
            const x = i * (barW + gap)
            const barH = Math.max(2, chartH * (g.value - minVal) / range)
            const barY = padTop + chartH - barH
            const hit = isHit(g.value)
            const color = hit ? '#34d399' : '#71717a'
            const alpha = hit ? '0.9' : '0.5'

            return (
              <g key={i}>
                {/* Bar */}
                <rect x={x} y={barY} width={barW} height={barH} rx={3}
                  fill={color} opacity={alpha} />
                {/* Value under bar */}
                <text x={x + barW / 2} y={svgH - 4} className="text-[9px] fill-zinc-500" textAnchor="middle">
                  {g.value}
                </text>
                {/* Date/opponent on last bar */}
                {i === games.length - 1 && (
                  <text x={x + barW / 2} y={svgH - 4} className="text-[9px] fill-zinc-500" textAnchor="middle"
                    dy={-svgH + padTop + chartH + 18}>
                    {gameLabel(g, i, games.length)}
                  </text>
                )}
              </g>
            )
          })}
        </svg>
      </div>

      {/* Opponent labels row */}
      <div className="flex gap-[6px] text-[10px] text-zinc-600" style={{ paddingLeft: 0 }}>
        {games.map((g, i) => (
          <div key={i} className="text-center overflow-hidden" style={{ width: barW, flexShrink: 0 }}>
            <span title={`${g.home ? 'vs' : '@'} ${g.opponent} · ${g.date}`}>
              {g.opponent.length > 5 ? g.opponent.slice(0, 5) : g.opponent}
            </span>
            <span className="text-zinc-700 ml-0.5">{g.home ? '' : '↑'}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
