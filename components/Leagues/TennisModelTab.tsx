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
  lockedAt?: string | null
  preview?: boolean
  status: 'scheduled' | 'live' | 'final' | 'unknown'
  home: string
  away: string
  projection: ModelProjection | null
  odds?: {
    matchWinner: { home: number | null; away: number | null }
    totalGames: { line: number; over: number | null; under: number | null } | null
    capturedAt: string | null
  } | null
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

function localDateKey(value: string | null) {
  if (!value) return ''
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return ''
  return `${parsed.getFullYear()}-${String(parsed.getMonth() + 1).padStart(2, '0')}-${String(parsed.getDate()).padStart(2, '0')}`
}

function todayKey() {
  return localDateKey(new Date().toISOString())
}

function number(value: number | null, digits = 1) {
  return value == null || !Number.isFinite(value) ? 'n/a' : value.toFixed(digits)
}

function impliedProbability(price: number | null | undefined) {
  if (price == null) return null
  return price < 0 ? -price / (-price + 100) : 100 / (price + 100)
}

function fairPrice(probability: number) {
  const clamped = Math.min(Math.max(probability, 0.001), 0.999)
  const price = clamped >= 0.5
    ? -Math.round((100 * clamped) / (1 - clamped))
    : Math.round((100 * (1 - clamped)) / clamped)
  return price > 0 ? `+${price}` : `${price}`
}

function MatchCard({ match }: { match: ModelMatch }) {
  const projection = match.projection
  const result = match.result
  const status = match.status === 'final' ? 'Final' : match.status === 'live' ? 'In progress' : null
  const price = (value: number | null | undefined) => (value == null ? 'n/a' : value > 0 ? `+${value}` : `${value}`)

  // Edge compares the model's pick probability with the Vegas no-vig probability for the same side.
  const winnerPrices = match.odds?.matchWinner ?? null
  const pickSide = projection?.projectedWinner && projection.probability != null
    ? (projection.projectedWinner === match.home ? 'home' : 'away')
    : null
  const pickPrice = pickSide && winnerPrices ? winnerPrices[pickSide] : null
  const otherPrice = pickSide && winnerPrices ? winnerPrices[pickSide === 'home' ? 'away' : 'home'] : null
  const pickImplied = impliedProbability(pickPrice)
  const otherImplied = impliedProbability(otherPrice)
  const winnerEdge = projection?.probability != null && pickImplied != null && otherImplied != null
    ? (projection.probability - pickImplied / (pickImplied + otherImplied)) * 100
    : null
  const winnerEdgeLabel = winnerEdge == null ? 'n/a' : `${winnerEdge >= 0 ? '+' : ''}${winnerEdge.toFixed(1)} pts`

  // Edge on the total is the model's projected games minus the Bovada line, in games.
  const totalLine = match.odds?.totalGames ?? null
  const totalEdge = totalLine && projection?.totalGames != null ? projection.totalGames - totalLine.line : null
  const totalEdgeLabel = totalEdge == null ? 'n/a' : `${Math.abs(totalEdge).toFixed(1)} games ${totalEdge >= 0 ? 'over' : 'under'}`

  return (
    <article className="space-y-3 py-4">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div>
          <h3 className="font-semibold text-zinc-100">{match.away} at {match.home}</h3>
          <p className="text-xs text-zinc-500">{[match.tour.toUpperCase(), match.event, match.round].filter(Boolean).join(' · ')}</p>
        </div>
        <p className="text-sm tabular-nums text-zinc-400">
          {status ?? (match.startTime ? new Date(match.startTime).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }) : 'Start time unknown')}
          {match.status === 'scheduled' && <span className="ml-2 text-xs text-zinc-500">{match.lockedAt ? 'Locked' : 'Preview'}</span>}
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
            <p className="text-zinc-200">{projection.projectedWinner ?? 'n/a'}{projection.probability == null ? '' : ` · ${Math.round(projection.probability * 100)}%`}</p>
            {match.grades?.winner && <p className={match.grades.winner === 'correct' ? 'text-emerald-400' : 'text-rose-400'}>Pick {match.grades.winner}</p>}
            <p className="text-xs tabular-nums text-zinc-500">Vegas line {price(pickPrice)}</p>
            <p className="text-xs tabular-nums text-zinc-500">Model line {projection.probability == null ? 'n/a' : fairPrice(projection.probability)}</p>
            <p className="text-xs tabular-nums text-zinc-500">Edge {winnerEdgeLabel}</p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Aces</p>
            <p className="text-zinc-200">{match.home} {number(projection.homeAces)} · {match.away} {number(projection.awayAces)}</p>
            {match.grades && (match.grades.homeAcesError != null || match.grades.awayAcesError != null) && (
              <p className="text-xs text-zinc-500">Absolute error {number(match.grades.homeAcesError)} / {number(match.grades.awayAcesError)}</p>
            )}
            <p className="text-xs text-zinc-500">Vegas line n/a</p>
            <p className="text-xs tabular-nums text-zinc-500">Model line {number(projection.homeAces)} / {number(projection.awayAces)}</p>
            <p className="text-xs text-zinc-500">Edge n/a</p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Total games</p>
            <p className="text-zinc-200">{number(projection.totalGames)}{projection.totalGamesInterval ? ` · ${number(projection.totalGamesInterval[0], 0)}–${number(projection.totalGamesInterval[1], 0)}` : ''}</p>
            {projection.totalGamesLabel && <p className="text-xs text-amber-400">{projection.totalGamesLabel}</p>}
            {match.grades?.totalGamesError != null && <p className="text-xs text-zinc-500">Absolute error {number(match.grades.totalGamesError)} games</p>}
            <p className="text-xs tabular-nums text-zinc-500">Vegas line {totalLine ? `${totalLine.line} · over ${price(totalLine.over)} / under ${price(totalLine.under)}` : 'n/a'}</p>
            <p className="text-xs tabular-nums text-zinc-500">Model line {projection.totalGames == null ? 'n/a' : number(projection.totalGames)}</p>
            <p className="text-xs tabular-nums text-zinc-500">Edge {totalEdgeLabel}</p>
          </div>
        </div>
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

export default function TennisModelTab({ tour }: {
  tour: Tour
}) {
  const [view, setView] = useState<'projections' | 'record'>('projections')
  const [recordDate, setRecordDate] = useState(todayKey())
  const date = view === 'projections' ? todayKey() : recordDate
  const [payload, setPayload] = useState<Payload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    const utcOffsetMinutes = new Date().getTimezoneOffset()
    fetch(`/api/tennis/model?date=${encodeURIComponent(date)}&tour=${tour}&utc_offset_minutes=${utcOffsetMinutes}`, { cache: 'no-store' })
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
      <section className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1 rounded-lg bg-zinc-900 p-1">
          {(['projections', 'record'] as const).map(item => (
            <button key={item} type="button" onClick={() => setView(item)} aria-pressed={view === item}
              className={`rounded-md px-3 py-2 text-sm capitalize ${view === item ? 'bg-zinc-700 text-white' : 'text-zinc-400 hover:text-white'}`}>
              {item}
            </button>
          ))}
        </div>
        {view === 'record' ? <div className="flex items-center gap-3">
          <button type="button" aria-label="Previous day" onClick={() => setRecordDate(shiftDate(recordDate, -1))}
            className="flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-xl text-zinc-300 hover:bg-zinc-800">‹</button>
          <h2 className="min-w-[13rem] text-center text-sm font-semibold text-zinc-200" aria-live="polite">{dateLabel(recordDate)}</h2>
          <button type="button" aria-label="Next day" disabled={recordDate >= todayKey()} onClick={() => setRecordDate(shiftDate(recordDate, 1))}
            className="flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-xl text-zinc-300 hover:bg-zinc-800 disabled:opacity-40">›</button>
        </div> : <h2 className="text-sm font-semibold text-zinc-200">Today’s projections · {dateLabel(date)}</h2>}
      </section>

      {error ? <p role="alert" className="rounded-xl bg-zinc-900 px-4 py-3 text-sm text-red-400">{error}</p> : null}
      {loading && !payload ? <div className="h-36 animate-pulse rounded-2xl bg-zinc-800" /> : null}
      {!loading && payload && !payload.available ? <p className="rounded-xl bg-zinc-900 px-4 py-3 text-sm text-zinc-400">{payload.reason ?? 'No tennis model projections are available for this slate yet.'}</p> : null}
      {payload?.available && payload.reason && <p className="rounded-xl bg-zinc-900 px-4 py-3 text-sm text-zinc-400">{payload.reason}</p>}
      {payload?.available && payload.matches.length === 0 ? <p className="text-sm text-zinc-400">No matches for this tour and date.</p> : null}

      {payload?.available && payload.matches.length > 0 && (() => {
        const matches = payload.matches.filter(match => localDateKey(match.startTime) === date)
        const visible = view === 'projections'
          ? matches.filter(match => match.status === 'scheduled' && match.startTime && Date.parse(match.startTime) > Date.now())
          : matches.filter(match => match.status === 'final')
        return visible.length ? (
        <section className="divide-y divide-zinc-800 rounded-2xl bg-zinc-900 px-4">
          {visible.map(match => <MatchCard key={`${match.tour}-${match.gameId}`} match={match} />)}
        </section>
        ) : <p className="text-sm text-zinc-400">{view === 'projections' ? 'No upcoming matches today.' : 'No completed matches for this day.'}</p>
      })()}
    </div>
  )
}
