import { useCallback, useEffect, useRef, useState } from 'react'
import type { UfcOptimizerFighter } from './ufcOptimizer'

export interface UfcSlateFight {
  key: string
  startTime: string | null
  fighters: [UfcOptimizerFighter, UfcOptimizerFighter]
}

export function formatLocalFightTime(startTime: string | null | undefined): string {
  if (!startTime) return 'Time unavailable'
  const date = new Date(startTime)
  if (Number.isNaN(date.getTime())) return 'Time unavailable'
  // Match the shared Scores/GameCard convention: browser-local time, with no
  // hardcoded publisher timezone suffix.
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

function timeRank(startTime: string | null): number {
  if (!startTime) return Number.MAX_SAFE_INTEGER
  const timestamp = new Date(startTime).getTime()
  return Number.isNaN(timestamp) ? Number.MAX_SAFE_INTEGER : timestamp
}

export function buildUfcSlateFights(fighters: UfcOptimizerFighter[]): UfcSlateFight[] {
  const groups = new Map<string, UfcOptimizerFighter[]>()
  fighters.forEach(fighter => {
    groups.set(fighter.gameInfo, [...(groups.get(fighter.gameInfo) || []), fighter])
  })
  return Array.from(groups.entries())
    .filter((entry): entry is [string, [UfcOptimizerFighter, UfcOptimizerFighter]] => entry[1].length === 2)
    .map(([key, pair], sourceOrder) => ({
      key,
      fighters: pair,
      startTime: pair[0].startTime || pair[1].startTime || null,
      sourceOrder,
    }))
    .sort((left, right) => timeRank(left.startTime) - timeRank(right.startTime) || left.sourceOrder - right.sourceOrder)
    .map(({ sourceOrder: _sourceOrder, ...fight }) => fight)
}

function lastName(name: string): string {
  return name.trim().split(/\s+/).slice(-1)[0] || name
}

function ordinal(value: number): string {
  const mod100 = value % 100
  if (mod100 >= 11 && mod100 <= 13) return `${value}th`
  if (value % 10 === 1) return `${value}st`
  if (value % 10 === 2) return `${value}nd`
  if (value % 10 === 3) return `${value}rd`
  return `${value}th`
}

function dateLabel(isoDate: string | null): string {
  if (!isoDate) return 'Current slate'
  const [year, month, day] = isoDate.split('-').map(Number)
  if (!year || !month || !day) return isoDate
  return `${new Intl.DateTimeFormat('en-US', { month: 'long', timeZone: 'UTC' }).format(new Date(Date.UTC(year, month - 1, day)))} ${ordinal(day)}`
}

export type UfcPoolSort = 'game_time' | 'salary' | 'projection' | 'value'

export default function UfcSlateRail({
  fighters,
  slateDate,
  selectedFight,
  sort,
  onSelectFight,
  onSort,
  onChangeSlate,
}: {
  fighters: UfcOptimizerFighter[]
  slateDate: string | null
  selectedFight: string | null
  sort: UfcPoolSort
  onSelectFight: (fightKey: string | null) => void
  onSort: (sort: UfcPoolSort) => void
  onChangeSlate: () => void
}) {
  const fights = buildUfcSlateFights(fighters)
  const railRef = useRef<HTMLDivElement>(null)
  const [canGoBack, setCanGoBack] = useState(false)
  const [canGoForward, setCanGoForward] = useState(true)

  const measureRail = useCallback(() => {
    const rail = railRef.current
    if (!rail) return
    setCanGoBack(rail.scrollLeft > 1)
    setCanGoForward(rail.scrollLeft + rail.clientWidth < rail.scrollWidth - 1)
  }, [])

  useEffect(() => {
    const frame = requestAnimationFrame(measureRail)
    window.addEventListener('resize', measureRail)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', measureRail)
    }
  }, [fighters, measureRail])

  const moveRail = (direction: -1 | 1) => {
    const rail = railRef.current
    if (!rail) return
    rail.scrollBy({ left: direction * Math.max(rail.clientWidth * 0.8, 300), behavior: 'smooth' })
  }

  return (
    <section className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900" aria-label="UFC slate fights">
      <div className="flex flex-col gap-3 border-b border-zinc-800 px-4 py-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-sm font-semibold text-zinc-200">{dateLabel(slateDate)}</span>
          <span className="text-xs tabular-nums text-zinc-500">{fights.length} fights</span>
          <button type="button" onClick={onChangeSlate} className="text-xs font-semibold text-emerald-400 hover:text-emerald-300">
            Change Slate
          </button>
          {selectedFight && (
            <button type="button" onClick={() => onSelectFight(null)} className="text-xs text-zinc-500 hover:text-zinc-300">
              Clear fight filter ×
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-2">
            <span className="text-xs text-zinc-500">Sort by</span>
            <select
              aria-label="Sort fighter pool"
              value={sort}
              onChange={event => onSort(event.target.value as UfcPoolSort)}
              className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-xs text-zinc-300 outline-none focus:border-emerald-500"
            >
              <option value="game_time">Game Time</option>
              <option value="salary">Salary</option>
              <option value="projection">Projection</option>
              <option value="value">Value</option>
            </select>
          </label>
        </div>
      </div>
      <div className="relative">
        <div
          ref={railRef}
          onScroll={measureRail}
          className="flex overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          data-slate-fight-rail
        >
          {fights.map(fight => {
            const selected = selectedFight === fight.key
            return (
              <button
                key={fight.key}
                type="button"
                aria-pressed={selected}
                aria-label={`Filter ${fight.fighters[0].name} versus ${fight.fighters[1].name}`}
                onClick={() => onSelectFight(selected ? null : fight.key)}
                className={`min-w-[150px] border-r border-zinc-800 px-4 py-3 text-left transition-colors last:border-r-0 ${
                  selected ? 'bg-emerald-500/10' : 'hover:bg-zinc-800/50'
                }`}
              >
                <span className="block text-[10px] font-medium tabular-nums text-zinc-600">{formatLocalFightTime(fight.startTime)}</span>
                <span className={`mt-1.5 block text-xs font-semibold ${selected ? 'text-emerald-300' : 'text-zinc-300'}`}>
                  {lastName(fight.fighters[0].name)}
                </span>
                <span className="mt-0.5 block text-xs text-zinc-500">{lastName(fight.fighters[1].name)}</span>
              </button>
            )
          })}
        </div>
        <div className="pointer-events-none absolute inset-0 hidden items-center justify-between sm:flex" aria-label="Fight rail navigation">
          <button
            type="button"
            aria-label="Previous fights"
            disabled={!canGoBack}
            onClick={() => moveRail(-1)}
            className="pointer-events-auto ml-2 flex h-9 w-9 items-center justify-center rounded-full border border-zinc-700 bg-zinc-950/95 text-zinc-300 shadow-lg shadow-black/50 backdrop-blur hover:border-zinc-500 hover:bg-zinc-900 hover:text-white disabled:pointer-events-none disabled:opacity-0"
          >
            <span aria-hidden="true">←</span>
          </button>
          <button
            type="button"
            aria-label="Next fights"
            disabled={!canGoForward}
            onClick={() => moveRail(1)}
            className="pointer-events-auto mr-2 flex h-9 w-9 items-center justify-center rounded-full border border-zinc-700 bg-zinc-950/95 text-zinc-300 shadow-lg shadow-black/50 backdrop-blur hover:border-zinc-500 hover:bg-zinc-900 hover:text-white disabled:pointer-events-none disabled:opacity-0"
          >
            <span aria-hidden="true">→</span>
          </button>
        </div>
      </div>
    </section>
  )
}
