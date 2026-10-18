import { useEffect, useState } from 'react'

type Tour = 'all' | 'atp' | 'wta'
type WinnerModel = 'page' | 'elo_informed_v2'

interface ModelProjection {
  probability: number | null
  projectedWinner: string | null
  homeAces: number | null
  awayAces: number | null
  homeDoubleFaults: number | null
  awayDoubleFaults: number | null
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
  acesSourceUrl?: string | null
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
  frozenOdds?: {
    matchWinner: { home: number | null; away: number | null }
    totalGames: { line: number; over: number | null; under: number | null } | null
    capturedAt: string | null
  } | null
  preview?: boolean
  lockStatus?: 'locked' | 'preview' | 'not_due' | 'missed' | 'unknown'
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
    winnerBrier?: number | null
    homeAcesError: number | null
    awayAcesError: number | null
    totalGamesError: number | null
  } | null
}

interface Payload {
  available: boolean
  reason?: string | null
  winnerModel?: WinnerModel
  winnerModelReason?: string | null
  accuracy?: { winnerBrier: number | null; brierN: number }
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

function MatchCard({ match, showActuals }: { match: ModelMatch; showActuals: boolean }) {
  const projection = match.projection
  const result = match.result
  const status = match.status === 'final' ? 'Final' : match.status === 'live' ? 'In progress' : null
  const price = (value: number | null | undefined) => (value == null ? 'n/a' : value > 0 ? `+${value}` : `${value}`)
  const quote = match.lockedAt ? match.frozenOdds ?? null : match.odds ?? null
  const quoteLabel = match.lockedAt ? 'Frozen line' : 'Current line'

  // Edge compares the model's pick probability with the Vegas no-vig probability for the same side.
  const winnerPrices = quote?.matchWinner ?? null
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
  const totalLine = quote?.totalGames ?? null
  const totalEdge = totalLine && projection?.totalGames != null ? projection.totalGames - totalLine.line : null
  const totalSide = totalEdge == null ? null : totalEdge >= 0 ? 'over' : 'under'
  const totalEdgeLabel = totalEdge == null ? 'n/a' : `${Math.abs(totalEdge).toFixed(1)} games on ${totalSide}`

  return (
    <article className="space-y-3 py-4">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div>
          <h3 className="font-semibold text-zinc-100">{match.away} at {match.home}</h3>
          <p className="text-xs text-zinc-500">{[match.tour.toUpperCase(), match.event, match.round].filter(Boolean).join(' · ')}</p>
        </div>
        <p className="text-sm tabular-nums text-zinc-400">
          {status ?? (match.startTime ? new Date(match.startTime).toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : 'Start time unknown')}
          {match.lockStatus === 'missed' && <span className="ml-2 text-xs font-medium text-amber-400">Missed lock window</span>}
          {match.status === 'scheduled' && match.lockedAt && <span className="ml-2 text-xs text-zinc-500">Locked</span>}
          {match.status === 'scheduled' && match.preview && <span className="ml-2 text-xs text-amber-400">Preview · not locked</span>}
        </p>
      </header>

      {projection?.unavailableReason && <p className="text-xs text-amber-400">{projection.unavailableReason}</p>}
      <div className="grid grid-cols-1 gap-x-6 gap-y-4 text-sm sm:grid-cols-2 xl:grid-cols-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Match winner</p>
          {projection ? <>
            <p className="text-zinc-200">{projection.projectedWinner ?? 'n/a'}{projection.probability == null ? '' : ` · ${Math.round(projection.probability * 100)}%`}</p>
            {match.grades?.winner && <p className={match.grades.winner === 'correct' ? 'text-emerald-400' : 'text-rose-400'}>
              <span aria-hidden="true">{match.grades.winner === 'correct' ? '✓' : '×'}</span> Pick {match.grades.winner}
            </p>}
            <div className="mt-1">
              <p className="text-xs tabular-nums text-zinc-500">{quoteLabel} · Bovada <b className="font-normal text-white">{price(pickPrice)}</b></p>
              <p className="text-xs tabular-nums text-zinc-500">Model line <b className="font-normal text-white">{projection.probability == null ? 'n/a' : fairPrice(projection.probability)}</b></p>
              <p className="text-xs tabular-nums text-zinc-500">Edge <b className="font-normal text-white">{winnerEdgeLabel}</b></p>
              {quote?.capturedAt && <p className="text-xs text-zinc-500">Bovada captured {quote.capturedAt}</p>}
              {match.lockedAt && !match.frozenOdds && <p className="text-xs text-amber-400">No frozen sportsbook line was recorded for this forecast.</p>}
            </div>
          </> : <p className="text-amber-400">No projection is available.</p>}
        </div>
        {result && <div>
          {result.sets && result.sets.home.length > 0 && (
            <table className="mt-1 text-xs tabular-nums text-zinc-400">
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
        </div>}
        <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Aces</p>
            {projection && <>
            <p className="text-zinc-200">{match.home} {number(projection.homeAces)}</p>
            <p className="text-zinc-200">{match.away} {number(projection.awayAces)}</p>
            </>}
            {showActuals && <>
              <p className="mt-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">Actual</p>
              {result?.homeAces != null && result.awayAces != null ? <>
                <p className="text-zinc-200">{match.home} {result.homeAces}</p>
                <p className="text-zinc-200">{match.away} {result.awayAces}</p>
              </> : <p className="text-zinc-200">n/a</p>}
            </>}
            {projection && <>
              <div className="mt-1">
                <p className="text-xs tabular-nums text-zinc-500">{quoteLabel} · Bovada <b className="font-normal text-white">n/a</b></p>
                <p className="text-xs tabular-nums text-zinc-500">Model line <b className="font-normal text-white">{number(projection.homeAces)} / {number(projection.awayAces)}</b></p>
                <p className="text-xs text-zinc-500">Edge <b className="font-normal text-white">n/a</b></p>
              </div>
              <div className="mt-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Double faults</p>
                <p className="text-zinc-200">{match.home} {number(projection.homeDoubleFaults)}</p>
                <p className="text-zinc-200">{match.away} {number(projection.awayDoubleFaults)}</p>
              </div>
            </>}
        </div>
        <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Total games</p>
            {projection && <>
            <p className="text-zinc-200">{number(projection.totalGames)}{projection.totalGamesInterval ? ` · ${number(projection.totalGamesInterval[0], 0)}–${number(projection.totalGamesInterval[1], 0)}` : ''}</p>
            {projection.totalGamesLabel && <p className="text-xs text-amber-400">{projection.totalGamesLabel}</p>}
            {match.grades?.totalGamesError != null && <p className="text-xs text-zinc-500">Absolute error {number(match.grades.totalGamesError)} games</p>}
            </>}
            {showActuals && <>
              <p className="mt-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">Actual</p>
              <p className="text-zinc-200">{result ? `${number(result.totalGames, 0)} games` : 'n/a'}</p>
            </>}
            {projection && <>
              <div className="mt-1">
                <p className="text-xs tabular-nums text-zinc-500">{quoteLabel} · total games <b className="font-normal text-white">{totalLine ? `${totalLine.line} · over ${price(totalLine.over)} / under ${price(totalLine.under)}` : 'n/a'}</b></p>
                <p className="text-xs tabular-nums text-zinc-500">Model line <b className="font-normal text-white">{projection.totalGames == null ? 'n/a' : totalSide && totalLine ? `${totalSide === 'over' ? 'Over' : 'Under'} ${totalLine.line} · ${number(projection.totalGames)} games` : `${number(projection.totalGames)} games`}</b></p>
                <p className="text-xs tabular-nums text-zinc-500">Edge <b className="font-normal text-white">{totalEdgeLabel}</b></p>
              </div>
            </>}
        </div>
      </div>
    </article>
  )
}

function ModelAccuracy({ accuracy, winnerModel }: {
  accuracy?: Payload['accuracy']
  winnerModel: WinnerModel
}) {
  const brier = accuracy?.winnerBrier ?? null
  return (
    <div role="tooltip" className="absolute right-0 top-full z-50 mt-2 w-[min(92vw,360px)] rounded-xl border border-zinc-700 bg-zinc-900 p-4 shadow-2xl">
      <h3 className="text-sm font-semibold text-zinc-100">Winner model accuracy</h3>
      <p className="mt-1 text-xs text-zinc-400">{winnerModel === 'page' ? 'Global + surface Elo blend' : 'Elo-informed simulator V2'} · settled locked forecasts in the available archive.</p>
      <dl className="mt-3 grid grid-cols-2 gap-3 text-sm tabular-nums">
        <div><dt className="text-xs text-zinc-500">Winner Brier ↓</dt><dd className="mt-0.5 text-zinc-100">{brier == null ? '—' : brier.toFixed(4)}</dd></div>
        <div><dt className="text-xs text-zinc-500">Brier n</dt><dd className="mt-0.5 text-zinc-100">{accuracy?.brierN ?? 0}</dd></div>
      </dl>
      <p className="mt-3 text-xs text-zinc-500">Lower is better; 0.2500 is a constant 50% forecast. Other markets are not included.</p>
    </div>
  )
}

export default function TennisModelTab({ tour }: {
  tour: Tour
}) {
  const [view, setView] = useState<'projections' | 'record'>('projections')
  const [winnerModel, setWinnerModel] = useState<WinnerModel>('page')
  const [recordDate, setRecordDate] = useState(todayKey())
  const date = view === 'projections' ? todayKey() : recordDate
  const [payload, setPayload] = useState<Payload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [accuracyOpen, setAccuracyOpen] = useState(false)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    const utcOffsetMinutes = new Date().getTimezoneOffset()
    const dates = view === 'projections'
      ? [date, shiftDate(date, 1), shiftDate(date, 2)]
      : [date]
    Promise.all(dates.map(async modelDate => {
      const response = await fetch(`/api/tennis/model?date=${encodeURIComponent(modelDate)}&tour=${tour}&utc_offset_minutes=${utcOffsetMinutes}&winner_model=${winnerModel}`, { cache: 'no-store' })
      if (!response.ok) throw new Error(`Tennis model data did not load (HTTP ${response.status}).`)
      return response.json() as Promise<Payload>
    }))
      .then(payloads => {
        if (!active) return
        const matches = payloads.flatMap(data => data.matches)
        const uniqueMatches = Array.from(new Map(matches.map(match => [`${match.tour}-${match.gameId}`, match])).values())
        const available = payloads.some(data => data.available)
        const hasWinnerProjections = uniqueMatches.some(match => match.projection?.projectedWinner != null)
        setPayload({
          available,
          reason: available ? null : payloads.find(data => data.reason)?.reason ?? null,
          winnerModel,
          winnerModelReason: hasWinnerProjections ? null : payloads.find(data => data.winnerModelReason)?.winnerModelReason ?? null,
          accuracy: payloads.find(data => data.accuracy)?.accuracy,
          source: payloads.find(data => data.source)?.source,
          matches: uniqueMatches,
        })
      })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : 'Tennis model data did not load.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [date, tour, view, winnerModel])

  return (
    <div className="space-y-5">
      <section className="flex flex-wrap items-center justify-between gap-3">
        <nav className="flex gap-1 rounded-full bg-zinc-900 p-1" aria-label="Tennis model views">
          {([['projections', 'Projections'], ['record', 'Record']] as const).map(([key, label]) => (
            <button key={key} type="button" onClick={() => setView(key)} aria-current={view === key ? 'page' : undefined} className={`rounded-full px-3 py-1.5 text-sm ${view === key ? 'bg-zinc-100 text-zinc-900' : 'text-zinc-400 hover:text-zinc-100'}`}>{label}</button>
          ))}
        </nav>
        <label className="flex items-center gap-2 text-sm text-zinc-400">
          <span>Match winner model</span>
          <select value={winnerModel} onChange={event => setWinnerModel(event.target.value as WinnerModel)}
            className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100">
            <option value="page">Global + surface Elo blend</option>
            <option value="elo_informed_v2">Elo-informed simulator V2</option>
          </select>
        </label>
        <div className="relative">
          <button type="button" aria-label="Model accuracy" aria-expanded={accuracyOpen}
            onClick={() => setAccuracyOpen(open => !open)}
            className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs font-medium text-zinc-200 hover:bg-zinc-800">
            Model accuracy
          </button>
          {accuracyOpen && <ModelAccuracy accuracy={payload?.accuracy} winnerModel={winnerModel} />}
        </div>
        {view === 'record' ? <div className="flex items-center gap-3">
          <button type="button" aria-label="Previous day" onClick={() => setRecordDate(shiftDate(recordDate, -1))}
            className="flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-xl text-zinc-300 hover:bg-zinc-800">‹</button>
          <h2 className="min-w-[13rem] text-center text-sm font-semibold text-zinc-200" aria-live="polite">{dateLabel(recordDate)}</h2>
          <button type="button" aria-label="Next day" disabled={recordDate >= todayKey()} onClick={() => setRecordDate(shiftDate(recordDate, 1))}
            className="flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-xl text-zinc-300 hover:bg-zinc-800 disabled:opacity-40">›</button>
        </div> : null}
      </section>

      {error ? <p role="alert" className="rounded-xl bg-zinc-900 px-4 py-3 text-sm text-red-400">{error}</p> : null}
      {loading && !payload ? <div className="h-36 animate-pulse rounded-2xl bg-zinc-800" /> : null}
      {!loading && payload && !payload.available ? <p className="rounded-xl bg-zinc-900 px-4 py-3 text-sm text-zinc-400">{payload.reason ?? 'No tennis model projections are available for this slate yet.'}</p> : null}
      {payload?.available && payload.reason && <p className="rounded-xl bg-zinc-900 px-4 py-3 text-sm text-zinc-400">{payload.reason}</p>}
      {payload?.available && payload.matches.length === 0 ? <p className="text-sm text-zinc-400">{view === 'projections' ? 'No ungraded projections are available.' : 'No matches for this tour and date.'}</p> : null}

      {payload?.available && payload.matches.length > 0 && (() => {
        const matches = view === 'projections'
          ? payload.matches
          : payload.matches.filter(match => localDateKey(match.startTime) === date)
        const visible = view === 'projections'
          ? matches.filter(match => match.lockStatus === 'missed' || (match.projection != null && match.grades?.winner == null))
          : matches.filter(match => match.status === 'final' &&
            (winnerModel === 'page' || match.projection?.projectedWinner != null || match.lockStatus === 'missed'))
        return visible.length ? (
          <section className="divide-y divide-zinc-800 rounded-2xl bg-zinc-900 px-4">
            {visible.map(match => <MatchCard key={`${match.tour}-${match.gameId}`} match={match} showActuals={view === 'record'} />)}
          </section>
        ) : <p className="text-sm text-zinc-400">{winnerModel === 'elo_informed_v2'
          ? (payload.winnerModelReason ?? (view === 'projections' ? 'No ungraded V2 projections are available.' : 'No completed matches with a V2 forecast are available for this day.'))
          : (view === 'projections' ? 'No ungraded projections are available.' : 'No completed matches for this day.')}</p>
      })()}
    </div>
  )
}
