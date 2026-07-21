import type { NflMilestone, NflSeasonContext } from './types'

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
  const upcoming = data.milestones.filter(m => m.status !== 'past')
  const past = data.milestones.filter(m => m.status === 'past')

  return (
    <section className="space-y-4">
      {/* Hero card */}
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

      {/* Milestone timeline */}
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-zinc-500 mb-4">
          Season Timeline
        </h3>
        <div className="space-y-0">
          {data.milestones.map((milestone, index) => (
            <TimelineRow
              key={milestone.id}
              milestone={milestone}
              isLast={index === data.milestones.length - 1}
            />
          ))}
        </div>
      </div>

      {/* Experience gates — only show blocked ones */}
      {data.experiences.opportunity_movers.status === 'blocked' && (
        <div className="rounded-lg border border-amber-500/10 bg-amber-500/5 px-4 py-3">
          <p className="text-xs text-amber-400/70">
            Opportunity Movers are unavailable until roster data is refreshed.
          </p>
        </div>
      )}
      {data.experiences.camp_battles.status === 'blocked' && (
        <div className="rounded-lg border border-amber-500/10 bg-amber-500/5 px-4 py-3">
          <p className="text-xs text-amber-400/70">
            Camp Battles require a verified depth-chart feed.
          </p>
        </div>
      )}
    </section>
  )
}

function TimelineRow({
  milestone,
  isLast,
}: {
  milestone: NflMilestone
  isLast: boolean
}) {
  const isPast = milestone.status === 'past'
  const isToday = milestone.status === 'today'

  return (
    <div className="flex gap-3">
      {/* line + dot */}
      <div className="flex flex-col items-center">
        <div
          className={`mt-1.5 h-2.5 w-2.5 rounded-full shrink-0 ${
            isToday
              ? 'bg-emerald-400 ring-2 ring-emerald-400/30'
              : isPast
                ? 'bg-zinc-600'
                : 'border-2 border-zinc-700 bg-transparent'
          }`}
        />
        {!isLast && <div className="w-px flex-1 bg-zinc-800 my-1" />}
      </div>
      {/* content */}
      <div className={`pb-4 ${isLast ? '' : ''}`}>
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span
            className={`text-sm font-medium ${
              isPast ? 'text-zinc-500' : isToday ? 'text-white' : 'text-zinc-300'
            }`}
          >
            {milestone.label}
          </span>
          <span className="text-xs text-zinc-600">
            {formatDate(milestone.date)}
          </span>
        </div>
        {milestone.days_until != null && milestone.days_until > 0 && (
          <p className="text-xs text-zinc-600 mt-0.5">
            {milestone.days_until} day{milestone.days_until === 1 ? '' : 's'} away
          </p>
        )}
        {isToday && (
          <p className="text-xs text-emerald-400 mt-0.5 font-medium">Today</p>
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
