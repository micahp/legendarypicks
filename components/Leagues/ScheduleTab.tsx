import type { Game } from '../../services/sports'
import GameCard from '../Scores/GameCard'

interface ScheduleTabProps {
  scheduleDate: string
  formattedDate: string
  isToday: boolean
  isUFC: boolean
  leagueName: string
  games: Game[]
  groups: Record<string, Game[]>
  loading: boolean
  error: string | null
  explanation: string | null
  prevDate: string | null
  nextDate: string | null
  navLoading: boolean
  onGoPrev: () => void
  onGoNext: () => void
  onSelectDate: (date: string) => void
  today: () => string
}

export default function ScheduleTab({
  scheduleDate,
  formattedDate,
  isToday,
  isUFC,
  leagueName,
  games,
  groups,
  loading,
  error,
  explanation,
  prevDate,
  nextDate,
  navLoading,
  onGoPrev,
  onGoNext,
  onSelectDate,
  today,
}: ScheduleTabProps) {
  return (
    <>
      <div className="space-y-1.5 text-center">
        <div className="flex items-center justify-center gap-2 sm:gap-3">
          <button
            type="button"
            onClick={onGoPrev}
            disabled={!prevDate || navLoading}
            aria-label="Previous game date"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-xl leading-none text-zinc-300 hover:bg-zinc-800 active:scale-95 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            ‹
          </button>
          <div className="min-w-[9rem] text-center sm:min-w-[10.5rem]" aria-live="polite">
            <div className="text-sm font-bold text-zinc-200">{formattedDate}</div>
            {!isToday && (
              <button
                type="button"
                onClick={() => onSelectDate(today())}
                className="mt-1 text-xs font-medium text-emerald-400 hover:text-emerald-300"
              >
                Jump to today
              </button>
            )}
          </div>
          <button
            type="button"
            onClick={onGoNext}
            disabled={!nextDate || navLoading}
            aria-label="Next game date"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-xl leading-none text-zinc-300 hover:bg-zinc-800 active:scale-95 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            ›
          </button>
          <label className="relative flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200 focus-within:border-emerald-500 focus-within:ring-1 focus-within:ring-emerald-500">
            <span className="sr-only">Choose date</span>
            <svg viewBox="0 0 20 20" aria-hidden="true" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.5">
              <rect x="3" y="4.5" width="14" height="12.5" rx="2" />
              <path d="M6.5 2.5v4M13.5 2.5v4M3 8h14" />
            </svg>
            <input
              type="date"
              aria-label="Choose schedule date"
              value={scheduleDate}
              onChange={event => onSelectDate(event.target.value)}
              className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
            />
          </label>
        </div>
      </div>

      {explanation && (
        <p className="text-center text-xs text-zinc-500 -mt-1">
          {explanation}
        </p>
      )}

      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 text-red-400 text-sm">
          {error}
        </div>
      )}

      {navLoading && (
        <div className="flex justify-center py-4">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-zinc-600 border-t-emerald-400" />
        </div>
      )}

      {loading ? (
        <div className="space-y-3 animate-pulse">
          {[...Array(4)].map((_, index) => (
            <div key={index} className="h-24 bg-zinc-800 rounded-xl" />
          ))}
        </div>
      ) : error ? null : games.length === 0 ? (
        <div className="text-center py-12 text-zinc-500 text-sm">
          No {leagueName} games scheduled for {formattedDate}.
        </div>
      ) : (
        <div className="space-y-6">
          {Object.entries(groups).map(([subtitle, groupedGames]) => (
            <section key={subtitle || 'schedule'} className="space-y-3">
              {subtitle && (
                <h2 className="text-sm font-semibold tracking-wide text-zinc-400">
                  {subtitle}
                </h2>
              )}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {groupedGames.map(game => (
                  <GameCard key={game.gameId} {...game} showScheduledTime={isUFC} />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </>
  )
}
