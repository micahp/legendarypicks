import { useEffect, useRef } from 'react'
import GameCard from '../Scores/GameCard'
import type { Game, NflWeekEntry } from '../../services/sports'

interface NflScheduleTabProps {
  selectedKey: string
  weekEntry: NflWeekEntry | null
  phaseLabel: string
  phases: { season_type: number; label: string }[]
  weeksInPhase: NflWeekEntry[]
  prevWeekKey: string | null
  nextWeekKey: string | null
  dateGroups: [string, Game[]][]
  games: Game[]
  gamesLoading: boolean
  gamesError: string | null
  catalogLoading: boolean
  catalogError: string | null
  onSelectWeek: (key: string) => void
}

export default function NflScheduleTab({
  selectedKey,
  weekEntry,
  phaseLabel,
  phases,
  weeksInPhase,
  prevWeekKey,
  nextWeekKey,
  dateGroups,
  games,
  gamesLoading,
  gamesError,
  catalogLoading,
  catalogError,
  onSelectWeek,
}: NflScheduleTabProps) {
  const weekStripRef = useRef<HTMLDivElement>(null)
  const phaseStripRef = useRef<HTMLDivElement>(null)

  // Scroll selected week pill into view
  useEffect(() => {
    const strip = weekStripRef.current
    if (!strip) return
    const pill = strip.querySelector(`[data-week-key="${selectedKey}"]`) as HTMLElement | null
    if (pill) pill.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'auto' })
  }, [selectedKey])

  // Scroll selected phase pill into view
  useEffect(() => {
    const strip = phaseStripRef.current
    if (!strip || !weekEntry) return
    const pill = strip.querySelector(`[data-season-type="${weekEntry.season_type}"]`) as HTMLElement | null
    if (pill) pill.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'auto' })
  }, [weekEntry?.season_type])

  if (catalogError) {
    return (
      <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 text-red-400 text-sm">
        {catalogError}
      </div>
    )
  }

  if (catalogLoading) {
    return (
      <div className="space-y-3 animate-pulse">
        <div className="h-8 bg-zinc-800 rounded w-64" />
        <div className="h-6 bg-zinc-800 rounded w-48" />
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-24 bg-zinc-800 rounded-xl" />
        ))}
      </div>
    )
  }

  const selectedPhaseType = weekEntry?.season_type

  return (
    <div className="space-y-4">
      {/* ── Phase selector ── */}
      <div
        ref={phaseStripRef}
        className="flex gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {phases.map(p => (
          <button
            key={p.season_type}
            type="button"
            data-season-type={p.season_type}
            onClick={() => {
              const first = weeksInPhase.find(w => w.season_type === p.season_type)
              if (first) onSelectWeek(first.key)
            }}
            className={`px-3 py-1.5 text-xs font-semibold rounded-md whitespace-nowrap transition-colors ${
              p.season_type === selectedPhaseType
                ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                : 'bg-zinc-800 text-zinc-400 hover:text-zinc-200 border border-zinc-700'
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* ── Week selector + prev/next ── */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => prevWeekKey && onSelectWeek(prevWeekKey)}
          disabled={!prevWeekKey}
          aria-label="Previous week"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-lg leading-none text-zinc-300 hover:bg-zinc-800 active:scale-95 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          ‹
        </button>

        <div
          ref={weekStripRef}
          className="flex gap-1 overflow-x-auto flex-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {weeksInPhase
            .filter(w => w.season_type === selectedPhaseType)
            .map(w => (
              <button
                key={w.key}
                type="button"
                data-week-key={w.key}
                onClick={() => onSelectWeek(w.key)}
                className={`px-2.5 py-1.5 text-xs font-medium rounded-md whitespace-nowrap transition-colors ${
                  w.key === selectedKey
                    ? 'bg-zinc-700 text-white'
                    : 'bg-zinc-800/50 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800'
                }`}
              >
                {w.alternate_label || w.label}
              </button>
            ))}
        </div>

        <button
          type="button"
          onClick={() => nextWeekKey && onSelectWeek(nextWeekKey)}
          disabled={!nextWeekKey}
          aria-label="Next week"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-lg leading-none text-zinc-300 hover:bg-zinc-800 active:scale-95 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          ›
        </button>
      </div>

      {/* ── Week info ── */}
      {weekEntry && (
        <div className="text-center space-y-1">
          <div className="text-xs font-medium text-zinc-500">{phaseLabel}</div>
          <div className="text-lg font-bold text-zinc-100">{weekEntry.label}</div>
          {weekEntry.detail && (
            <div className="text-sm text-zinc-400">{weekEntry.detail}</div>
          )}
        </div>
      )}

      {/* ── Games ── */}
      {gamesError && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 text-red-400 text-sm">
          {gamesError}
        </div>
      )}

      {gamesLoading ? (
        <div className="space-y-3 animate-pulse">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-24 bg-zinc-800 rounded-xl" />
          ))}
        </div>
      ) : gamesError ? null : games.length === 0 ? (
        <div className="text-center py-12 text-zinc-500 text-sm">
          No games scheduled for {weekEntry?.label}.
        </div>
      ) : (
        <div className="space-y-6">
          {dateGroups.map(([date, dayGames]) => (
            <section key={date} className="space-y-3">
              <h2 className="text-sm font-semibold tracking-wide text-zinc-400">
                {new Date(date + 'T12:00:00').toLocaleDateString(undefined, {
                  weekday: 'short',
                  month: 'short',
                  day: 'numeric',
                })}
              </h2>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {dayGames.map(game => (
                  <GameCard key={game.gameId} {...game} showScheduledTime />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
