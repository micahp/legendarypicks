import { useState, useEffect } from 'react'

interface Leader {
  player_id: number; name: string; team: string; market: string
  line: number; actual: number; cashed: string; margin: number
}

function marketLabel(market: string) {
  return market.replace(/_/g, ' ')
}

// Fixed anchor: the line always sits at 55% of the track, same constant across every
// gauge, so a reader learns the visual once. Fill is actual/line scaled against that
// anchor — a result exactly on the line lands the fill exactly on the tick.
const LINE_ANCHOR = 55

export default function WhatDecidedIt({ league, gameId }: { league: string; gameId: string }) {
  const [leaders, setLeaders] = useState<Leader[]>([])
  const [settledLines, setSettledLines] = useState(0)

  useEffect(() => {
    let alive = true
    setLeaders([])
    setSettledLines(0)
    fetch(`/api/game/${league}/${gameId}/props`)
      .then(r => r.json())
      .then(d => {
        if (!alive) return
        setLeaders(d.leaders || [])
        setSettledLines(d.settled_lines || 0)
      })
      .catch(() => {})
    return () => { alive = false }
  }, [league, gameId])

  if (!leaders.length) return null

  return (
    <section className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-bold text-zinc-400 uppercase tracking-wider">What decided it</h2>
        <span className="font-mono text-[11px] tabular-nums text-zinc-500">
          {leaders.length} of {settledLines} settled {settledLines === 1 ? 'line' : 'lines'}
        </span>
      </div>
      <div className="grid gap-px bg-zinc-800 border border-zinc-800 rounded-lg overflow-hidden sm:grid-cols-3">
        {leaders.map((l) => {
          const line = Number(l.line) || 1
          const actual = Number(l.actual) || 0
          const short = actual < line
          const rawPct = (actual / line) * LINE_ANCHOR
          const pct = Math.min(100, rawPct)
          const overflow = rawPct > 100
          const diff = actual - line
          const diffLabel = `${diff > 0 ? '+' : ''}${diff.toFixed(1)} vs the line`
          return (
            <div key={`${l.player_id}-${l.market}-${l.line}`} className="bg-zinc-900 p-4 flex flex-col gap-3">
              <div className="text-[11px] uppercase tracking-wider text-zinc-500 font-bold">
                {marketLabel(l.market)}
              </div>
              <div className="flex items-baseline gap-2 min-w-0">
                <a href={`/player/${l.player_id}`} className="text-base font-semibold hover:text-emerald-400 truncate">
                  {l.name}
                </a>
                <span className="text-xs text-zinc-500 shrink-0">{l.team}</span>
              </div>
              <div className="flex flex-col gap-2 pt-2">
                <div className="relative h-8 bg-zinc-800 rounded ring-1 ring-zinc-700/50">
                  <div
                    className={`absolute inset-y-0 left-0 rounded-l ${short ? 'bg-red-500' : 'bg-emerald-500'}`}
                    style={{ width: `${pct}%` }}
                  />
                  <div className="absolute -top-1 -bottom-1 w-0.5 bg-white" style={{ left: `${LINE_ANCHOR}%` }} />
                  {overflow && (
                    <span className="absolute right-1 top-1/2 -translate-y-1/2 text-[11px] text-zinc-900">▶</span>
                  )}
                  <span
                    className="absolute -top-4 text-[10px] text-zinc-500 font-mono whitespace-nowrap"
                    style={{ left: `${LINE_ANCHOR}%`, transform: 'translateX(-50%)' }}
                  >
                    line {l.line}
                  </span>
                </div>
                <div className="flex items-baseline justify-between text-xs text-zinc-500">
                  <div><span className="text-lg font-bold text-white font-mono">{l.actual}</span> recorded</div>
                  <div className={`text-[11px] uppercase tracking-wider font-bold ${short ? 'text-red-400' : 'text-emerald-400'}`}>
                    {diffLabel}
                  </div>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
