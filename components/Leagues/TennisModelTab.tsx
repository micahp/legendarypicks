import { useEffect, useState } from 'react'

type Tour = 'all' | 'atp' | 'wta'

interface ModelProjection {
  probability: number | null
  projectedWinner: string | null
  homeAces: number | null
  awayAces: number | null
  totalGames: number | null
  totalGamesInterval: [number, number] | null
  totalGamesLabel?: string | null
  unavailableReason?: string | null
  modelVersion?: string
}

interface ModelResult {
  winner: string | null
  homeAces: number | null
  awayAces: number | null
  totalGames: number | null
  sets: { home: number[]; away: number[] } | null
}

interface ModelMatch {
  gameId: string
  tour: 'atp' | 'wta'
  event: string | null
  round: string | null
  startTime: string | null
  status: 'scheduled' | 'live' | 'final' | 'unknown'
  home: string
  away: string
  projection: ModelProjection | null
  result: ModelResult | null
  grades: {
    winner: 'correct' | 'incorrect' | null
    homeAcesError: number | null
    awayAcesError: number | null
    totalGamesError: number | null
  } | null
}

interface Payload {
  available: boolean
  reason?: string | null
  source?: string
  matches: ModelMatch[]
}

function dateLabel(date: string) {
  const parsed = new Date(`${date}T12:00:00`)
  return parsed.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })
}

function shiftDate(value: string, offset: number) {
  const date = new Date(`${value}T12:00:00`)
  date.setDate(date.getDate() + offset)
  return date.toLocaleDateString('en-CA')
}

function number(value: number | null, digits = 1) {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits)
}

function MatchCard({ match }: { match: ModelMatch }) {
  const projection = match.projection
  const result = match.result
  const status = match.status === 'final' ? 'Final' : match.status === 'live' ? 'In progress' : null

  return (
    <article className="space-y-3 py-4">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div>
          <h3 className="font-semibold text-zinc-100">{match.away} at {match.home}</h3>
          <p className="text-xs text-zinc-500">{[match.tour.toUpperCase(), match.event, match.round].filter(Boolean).join(' · ')}</p>
        </div>
        <p className="text-sm tabular-nums text-zinc-400">
          {status ?? (match.startTime ? new Date(match.startTime).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }) : 'Start time unknown')}
        </p>
      </header>

      {!projection ? (
        <p className="text-sm text-amber-400">No projection is available for this match.</p>
      ) : (
        <div className="space-y-2">
        {projection.unavailableReason && <p className="text-xs text-amber-400">{projection.unavailableReason}</p>}
        <div className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Match winner</p>
            <p className="text-zinc-200">{projection.projectedWinner ?? '—'}{projection.probability == null ? '' : ` · ${Math.round(projection.probability * 100)}%`}</p>
            {match.grades?.winner && <p className={match.grades.winner === 'correct' ? 'text-emerald-400' : 'text-rose-400'}>Pick {match.grades.winner}</p>}
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Aces</p>
            <p className="text-zinc-200">{match.home} {number(projection.homeAces)} · {match.away} {number(projection.awayAces)}</p>
            {match.grades && (match.grades.homeAcesError != null || match.grades.awayAcesError != null) && (
              <p className="text-xs text-zinc-500">Absolute error {number(match.grades.homeAcesError)} / {number(match.grades.awayAcesError)}</p>
            )}
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Total games</p>
            <p className="text-zinc-200">{number(projection.totalGames)}{projection.totalGamesInterval ? ` · ${number(projection.totalGamesInterval[0], 0)}–${number(projection.totalGamesInterval[1], 0)}` : ''}</p>
            {projection.totalGamesLabel && <p className="text-xs text-amber-400">{projection.totalGamesLabel}</p>}
            {match.grades?.totalGamesError != null && <p className="text-xs text-zinc-500">Absolute error {number(match.grades.totalGamesError)} games</p>}
          </div>
        </div>
        <p className="text-[11px] text-zinc-600">Walk-forward research projections · {projection.modelVersion ?? 'development model'}</p>
        </div>
      )}

      {result && <div className="space-y-2 border-t border-zinc-800 pt-3">
        <p className="text-xs text-zinc-400">
          Final: {result.winner ?? 'winner unavailable'} · {number(result.totalGames, 0)} games
        </p>
        {result.sets && result.sets.home.length > 0 && (
          <table className="text-xs tabular-nums text-zinc-400">
            <thead><tr><th className="pr-5 text-left font-semibold uppercase tracking-wide text-zinc-500">Set</th>
              {result.sets.home.map((_, index) => <th key={index} className="px-2 pb-1 text-center font-medium text-zinc-500">{index + 1}</th>)}
            </tr></thead>
            <tbody>
              <tr><th className="pr-5 text-left font-medium">{match.home}</th>
                {result.sets.home.map((games, index) => <td key={index} className="px-2 py-0.5 text-center text-zinc-200">{games}</td>)}
              </tr>
              <tr><th className="pr-5 text-left font-medium">{match.away}</th>
                {result.sets.away.map((games, index) => <td key={index} className="px-2 py-0.5 text-center text-zinc-200">{games}</td>)}
              </tr>
            </tbody>
          </table>
        )}
        <p className="text-xs text-zinc-500">
          Match aces and other player stats are not present in the current score feed.
        </p>
      </div>}
    </article>
  )
}

export default function TennisModelTab({ date, setDate, tour }: {
  date: string
  setDate: (date: string) => void
  tour: Tour
}) {
  const [payload, setPayload] = useState<Payload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    fetch(`/api/tennis/model?date=${encodeURIComponent(date)}&tour=${tour}`, { cache: 'no-store' })
      .then(async response => {
        if (!response.ok) throw new Error(`Tennis model data did not load (HTTP ${response.status}).`)
        return response.json() as Promise<Payload>
      })
      .then(data => { if (active) setPayload(data) })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : 'Tennis model data did not load.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [date, tour])

  return (
    <div className="space-y-5">
      <section className="flex items-center justify-center gap-3">
        <button type="button" aria-label="Previous day" onClick={() => setDate(shiftDate(date, -1))}
          className="flex h-10 w-10 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-xl text-zinc-300 hover:bg-zinc-800">‹</button>
        <h2 className="min-w-[15rem] text-center text-sm font-semibold text-zinc-200" aria-live="polite">{dateLabel(date)}</h2>
        <button type="button" aria-label="Next day" onClick={() => setDate(shiftDate(date, 1))}
          className="flex h-10 w-10 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-xl text-zinc-300 hover:bg-zinc-800">›</button>
      </section>

      <p className="max-w-prose text-sm text-zinc-400">
        Free walk-forward projections use 2020 onward match history dated before the selected day and resolve player history through the tennis spine. Winner probabilities blend global and surface Elo; ace means use the per-match baseline; total games use the point simulator where the event surface is mapped. Final score data includes set scores but no ace statistics, so ace grades are unavailable.
      </p>

      {error ? <p role="alert" className="rounded-xl bg-zinc-900 px-4 py-3 text-sm text-red-400">{error}</p> : null}
      {loading && !payload ? <div className="h-36 animate-pulse rounded-2xl bg-zinc-800" /> : null}
      {!loading && payload && !payload.available ? <p className="rounded-xl bg-zinc-900 px-4 py-3 text-sm text-zinc-400">{payload.reason ?? 'No tennis model projections are available for this slate yet.'}</p> : null}
      {payload?.available && payload.reason && <p className="rounded-xl bg-zinc-900 px-4 py-3 text-sm text-zinc-400">{payload.reason}</p>}
      {payload?.available && payload.matches.length === 0 ? <p className="text-sm text-zinc-400">No matches for this tour and date.</p> : null}

      {payload?.available && payload.matches.length > 0 && (
        <section className="divide-y divide-zinc-800 rounded-2xl bg-zinc-900 px-4">
          {payload.matches.map(match => <MatchCard key={`${match.tour}-${match.gameId}`} match={match} />)}
        </section>
      )}
    </div>
  )
}
