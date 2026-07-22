import type { NflSeasonContext } from './types'

interface Props {
  data: NflSeasonContext | null
  loading: boolean
  error: string | null
}

export default function NflCampHero({ data, loading, error }: Props) {
  if (loading) {
    return (
      <div className="animate-pulse space-y-3 rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <div className="h-5 w-36 rounded bg-zinc-800" />
        <div className="h-4 w-64 rounded bg-zinc-800" />
        <div className="h-10 w-full rounded bg-zinc-800" />
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <p className="text-sm text-zinc-500">
          {error || 'Season context unavailable.'}
        </p>
      </div>
    )
  }

  const nextEvent = data.next_event

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5 sm:p-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-widest text-emerald-400">
              {data.phase_label}
            </span>
            <span className="text-xs text-zinc-600">
              {data.current_season} season
            </span>
          </div>
          {nextEvent && (
            <p className="text-sm text-zinc-300 mt-2">
              <span className="font-semibold text-white">{nextEvent.label}</span>
              <span className="text-zinc-500">
                {' '}· {formatCountdown(nextEvent.days_until)}
              </span>
            </p>
          )}
        </div>
        {nextEvent && (
          <div className="flex items-center gap-1.5 text-xs text-zinc-500 shrink-0">
            <span>{formatDate(nextEvent.date)}</span>
          </div>
        )}
      </div>
    </div>
  )
}

function formatDate(iso: string): string {
  const date = new Date(`${iso}T12:00:00`)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  })
}

function formatCountdown(days: number): string {
  if (days === 0) return 'Today'
  if (days === 1) return 'Tomorrow'
  return `${days} days away`
}
