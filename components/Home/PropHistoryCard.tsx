import React from 'react'
import type { FeaturedProp } from './types'
import { asOfText, gameDate, marketLabel, pct, unitWord } from './format'
import { cardBase, QuietCard, SourceLine } from './CardShell'

const W = 360
const X0 = 32
const X1 = 356
const BASE = 166
const TOP_H = 145
const STEPS = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000]

function chart(prop: FeaturedProp) {
  const games = prop.games
  const max = Math.max(prop.line, ...games.map((g) => g.value), 1)
  const step = STEPS.find((s) => s >= max / 3.5) ?? STEPS[STEPS.length - 1]
  const k = TOP_H / max
  const ticks: number[] = []
  for (let v = 0; v <= max; v += step) ticks.push(v)
  const slot = (X1 - X0) / 20
  const barW = slot * 0.72
  const start = X1 - slot * games.length
  return { k, ticks, slot, barW, start }
}

export default function PropHistoryCard({ prop }: { prop: FeaturedProp | null | undefined }) {
  if (!prop) return <QuietCard label="Example prop history" kind="absent" />
  const { k, ticks, slot, barW, start } = chart(prop)
  const m = prop.matchup
  const subtitle = [m ? `${m.away} at ${m.home}` : null, marketLabel(prop.market), `over ${prop.line}`]
    .filter(Boolean)
    .join(', ')
  const boxes: [string, 'l5' | 'l10' | 'l20' | 'season'][] = [
    ['Last 5', 'l5'],
    ['Last 10', 'l10'],
    ['Last 20', 'l20'],
    ['History', 'season'],
  ]
  const unit = unitWord(prop.market)
  const first = prop.games[0]
  const last = prop.games[prop.games.length - 1]
  const lineY = BASE - prop.line * k
  return (
    <div className={cardBase} aria-label="Example prop history">
      <div className="mb-3 flex flex-col gap-0.5 text-sm">
        <b className="text-base">{prop.player}</b>
        <span className="text-xs text-zinc-400">{subtitle}</span>
      </div>
      <div className="mb-3 grid grid-cols-2 gap-2 tabular-nums min-[521px]:grid-cols-4">
        {boxes.map(([label, key]) => {
          const n = prop.hit_rate_n[key]
          return (
            <span key={key} className="flex min-w-0 flex-col gap-px rounded-lg border border-zinc-800 px-2 py-1.5">
              <i className="text-[10px] uppercase not-italic tracking-[.05em] text-zinc-500">{label}</i>
              {n > 0 ? (
                <b className="text-xl leading-[1.1]">{pct(prop.hit_rate[key])}</b>
              ) : (
                <b className="text-xl leading-[1.1] text-amber-400">n/a</b>
              )}
              <small className="text-[11px] text-zinc-400">
                {n} {n === 1 ? 'game' : 'games'}
              </small>
            </span>
          )
        })}
      </div>
      <svg
        viewBox={`0 0 ${W} 190`}
        role="img"
        aria-label={`${marketLabel(prop.market)} game by game over the last ${prop.games.length} games against the line of ${prop.line}`}
        className="block h-auto w-full"
      >
        {ticks.map((v) => (
          <g key={v}>
            <line x1={X0} x2={X1} y1={BASE - v * k} y2={BASE - v * k} className="stroke-zinc-800" />
            <text x={27} y={BASE - v * k + 4} fontSize={12} textAnchor="end" className="fill-zinc-500">
              {v}
            </text>
          </g>
        ))}
        {prop.games.map((g, i) => {
          const h = g.value * k
          return (
            <rect
              key={`${g.date}-${i}`}
              x={start + i * slot + (slot - barW) / 2}
              y={BASE - h}
              width={barW}
              height={h}
              rx={2}
              className={g.hit ? 'fill-emerald-500' : 'fill-[#e0867a]'}
              data-hit={g.hit ? '1' : '0'}
            >
              <title>{`${g.date} vs ${g.opponent}: ${g.value} ${unit}`}</title>
            </rect>
          )
        })}
        <line x1={X0} x2={X1} y1={lineY} y2={lineY} strokeWidth={1.6} strokeDasharray="5 4" className="stroke-amber-400" />
        {first && (
          <text x={X0} y={184} fontSize={12} className="fill-zinc-500">
            {gameDate(first.date)}
          </text>
        )}
        {last && (
          <text x={X1} y={184} fontSize={12} textAnchor="end" className="fill-zinc-500">
            {gameDate(last.date)}
          </text>
        )}
      </svg>
      <p className="mt-1 text-[11px] text-zinc-500">Each bar is one game.</p>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-400">
        <span><s className="mr-1.5 inline-block h-2.5 w-2.5 rounded-sm bg-emerald-500 align-[-1px] no-underline" />Cleared the line</span>
        <span><s className="mr-1.5 inline-block h-2.5 w-2.5 rounded-sm bg-[#e0867a] align-[-1px] no-underline" />Missed it</span>
        <span><s className="mr-1.5 inline-block w-3.5 border-t-2 border-dashed border-amber-400 align-[3px] no-underline" />Line {prop.line}</span>
      </div>
      <div className="mt-2">
        <SourceLine>
          Line from the prop board {asOfText(prop.source.as_of)}. History from the player&apos;s game logs.
        </SourceLine>
      </div>
    </div>
  )
}
