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

  const dateParts = nextEvent ? formatDateParts(nextEvent.date) : null

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5 sm:p-6">
      <div className="flex justify-between gap-4">
        <div className="min-w-0 flex flex-col justify-between">
          {nextEvent && <p className="text-lg font-bold text-white">{nextEvent.label}</p>}
          {nextEvent && (
            <p className="text-xs text-zinc-500">{formatCountdown(nextEvent.days_until)}</p>
          )}
        </div>
        {dateParts && (
          <div className="text-right leading-none shrink-0 flex flex-col justify-between items-end">
            <div className="text-xs font-semibold uppercase tracking-widest text-zinc-500">
              {dateParts.month}
            </div>
            <div className="text-4xl font-black text-white mt-1">{dateParts.day}</div>
          </div>
        )}
      </div>
    </div>
  )
}

function formatDateParts(iso: string): { month: string; day: string } {
  const date = new Date(`${iso}T12:00:00`)
  if (Number.isNaN(date.getTime())) return { month: '', day: iso }
  return {
    month: date.toLocaleDateString(undefined, { month: 'short' }),
    day: date.toLocaleDateString(undefined, { day: 'numeric' }),
  }
}

function formatCountdown(days: number): string {
  if (days === 0) return 'Today'
  if (days === 1) return 'Tomorrow'
  return `In ${days} days`
}
