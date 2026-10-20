import { useEffect, useMemo, useState } from 'react'
import ModelSelect from './ModelSelect'

interface Line {
  spread: number | null
  total: number | null
  home_moneyline: number | null
  away_moneyline: number | null
  captured_at: string | null
  source: 'snapshot' | 'lock row'
}

interface LeanMarket {
  side: 'home' | 'away' | 'over' | 'under' | 'none'
  reason?: string
  edge_pts?: number | null
  edge_pp?: number | null
}

interface WagerMarket {
  status: string
  reason?: string
}

interface Wager {
  policy: string
  status: string
  reason: string | null
  policy_note?: string
  markets?: Record<string, WagerMarket>
}

interface Lock {
  proj_home: number | null
  proj_away: number | null
  margin: number
  total: number | null
  p_home_win: number
  locked_at: string | null
  preview: boolean
  previewed_at: string | null
  line: Line
  grade: { brier: number | null; margin_err: number; total_err: number; ats: string; su: string | null } | null
  prediction?: { proj_home: number | null; proj_away: number | null; margin: number; total: number | null; p_home_win: number }
  lean?: { ml: LeanMarket; spread: LeanMarket; total: LeanMarket }
  wager?: Wager
}

interface ModelInfo {
  version: string
  family: 'v1' | 'v2' | 'v1+elo'
  label: string
  adopted: boolean
  locks: number
}

interface ModelGame {
  game_id: string
  week: number
  home_record: string | null
  away_record: string | null
  home: string
  away: string
  neutral: boolean
  kickoff_utc: string | null
  final: { home: number; away: number } | null
  locks: Record<string, Lock>
}

interface Tally {
  win: number
  loss: number
  tie?: number
  push?: number
  no_pick: number
  no_line?: number
}

interface RecordRow extends ModelInfo {
  locked: number
  graded: number
  awaiting: number
  su: Tally | null
  ats: Tally | null
  total_lean?: Tally | null
  wager?: { policy: string; issued: number; priced: number; status: string; reason?: string; policy_note?: string } | null
  mean_brier?: number | null
  brier_n?: number
}

interface Payload {
  season: number
  week: number | null
  weeks: number[]
  models: ModelInfo[]
  games: ModelGame[]
  record: RecordRow[]
}

interface RatingTeam {
  team: string
  team_name: string
  conference: string
  division: string
  off: number | null
  def: number | null
  overall: number | null
  games: number
}

interface RatingsPayload {
  season: number
  week: number | null
  model_version: string
  as_of: string | null
  teams: RatingTeam[]
}

type ModelView = 'projections' | 'record' | 'ratings'
type EdgeFilter = 'all' | '3' | '6'

const one = (value: number) => value.toFixed(1)
const signed = (value: number) => `${value > 0 ? '+' : ''}${one(value)}`

function dayLabel(iso: string | null) {
  if (!iso) return 'Date unknown'
  return new Date(iso).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })
}

function timeLabel(iso: string | null) {
  if (!iso) return 'Kickoff unknown'
  return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

// nflverse spread_line is the market's expected home margin: positive means home favored.
function lineSide(home: string, away: string, homeMargin: number | null) {
  if (homeMargin == null) return 'No line'
  if (homeMargin === 0) return 'Pick'
  return homeMargin > 0 ? `${home} -${one(homeMargin)}` : `${away} -${one(Math.abs(homeMargin))}`
}

function modelSide(home: string, away: string, homeMargin: number) {
  if (homeMargin === 0) return 'Pick'
  return homeMargin > 0 ? `${home} -${one(homeMargin)}` : `${away} -${one(Math.abs(homeMargin))}`
}

function pickSide(game: ModelGame, lock: Lock) {
  const marketMargin = lock.line.spread
  if (marketMargin == null) return null
  const spread = Math.abs(marketMargin)
  if (lock.margin === marketMargin) return 'No lean' // model agrees with the line exactly: no side
  const homePick = lock.margin > marketMargin
  if (marketMargin === 0) return `${homePick ? game.home : game.away} Pick`
  if (homePick) return `${game.home} ${marketMargin > 0 ? `-${one(spread)}` : `+${one(spread)}`}`
  return `${game.away} ${marketMargin < 0 ? `-${one(spread)}` : `+${one(spread)}`}`
}

function mlLean(game: ModelGame, lock: Lock) {
  const side = lock.lean?.ml?.side
  if (!side || side === 'none') return 'No lean'
  return side === 'home' ? `${game.home} ML` : `${game.away} ML`
}

function totalLean(lock: Lock) {
  const side = lock.lean?.total?.side
  if (!side || side === 'none') return 'No lean'
  const line = lock.line.total
  return side === 'over' ? `Over${line == null ? '' : ` ${one(line)}`}` : `Under${line == null ? '' : ` ${one(line)}`}`
}

function wagerLabel(lock: Lock) {
  const status = lock.wager?.status
  if (status === 'qualifying_wager') return 'Qualifying wager'
  if (status === 'insufficient_price_data') return 'No price data'
  return 'No qualifying wager'
}

function edge(lock: Lock) {
  return lock.line.spread == null ? null : Math.abs(lock.margin - lock.line.spread)
}

function totalEdge(lock: Lock) {
  return lock.line.total == null || lock.total == null ? null : lock.total - lock.line.total
}

function statusLabel(lock: Lock) {
  if (!lock.grade) return 'AWAITING'
  return { win: 'WIN', loss: 'LOSS', push: 'PUSH', no_pick: 'NO PICK', no_line: 'NO LINE' }[lock.grade.ats] || lock.grade.ats.toUpperCase()
}

function statusClass(lock: Lock) {
  if (!lock.grade) return 'text-zinc-500'
  if (lock.grade.ats === 'win') return 'text-emerald-400'
  if (lock.grade.ats === 'loss') return 'text-rose-400'
  return 'text-zinc-300'
}

function lineCaptureLabel(lock: Lock) {
  const time = lock.line.captured_at
    ? `${lock.line.source === 'snapshot' ? 'captured' : 'captured'} ${lock.line.captured_at}`
    : 'capture time unavailable'
  return `Line · ${lock.line.source} · ${time}`
}

function isMissedLock(game: ModelGame, version: string, now = Date.now()) {
  const lock = game.locks[version]
  if ((lock && !lock.preview) || !game.kickoff_utc) return false
  const kickoff = Date.parse(game.kickoff_utc)
  return Number.isFinite(kickoff) && kickoff <= now
}

function MissedLockList({ games, version }: { games: ModelGame[]; version: string }) {
  const missed = games.filter(game => isMissedLock(game, version))
  if (!missed.length) return null
  return (
    <section aria-label="Missed lock window" className="space-y-2">
      <h3 className="text-sm font-medium text-zinc-400">Missed lock window</h3>
      <div className="divide-y divide-zinc-800 rounded-2xl bg-zinc-900 px-4">
        {missed.map(game => <article key={game.game_id} className="flex flex-wrap justify-between gap-2 py-3 text-sm">
          <span className="font-medium text-zinc-200">{game.away} {game.neutral ? 'vs' : '@'} {game.home}</span>
          <span className="text-zinc-500">No forecast locked before kickoff · {game.kickoff_utc}</span>
        </article>)}
      </div>
    </section>
  )
}

function ModelAccuracy({ models, records }: { models: ModelInfo[]; records: RecordRow[] }) {
  const byVersion = new Map(records.map(record => [record.version, record]))
  const score = (value: number | null | undefined) => value == null ? '—' : value.toFixed(4)
  return (
    <div role="tooltip" className="absolute right-0 top-full z-50 mt-2 w-[min(92vw,420px)] rounded-xl border border-zinc-700 bg-zinc-900 p-4 shadow-2xl">
      <h3 className="text-sm font-semibold text-zinc-100">Season winner accuracy</h3>
      <p className="mt-1 text-xs text-zinc-400">Brier score on settled forecasts · lower is better · 0.2500 is a constant 50% forecast.</p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[300px] text-sm tabular-nums">
          <thead className="border-b border-zinc-700 text-xs text-zinc-500"><tr>
            <th className="py-2 text-left font-medium">Model</th><th className="py-2 text-right font-medium">Brier ↓</th><th className="py-2 text-right font-medium">Brier n</th>
          </tr></thead>
          <tbody className="divide-y divide-zinc-800">{models.map(model => {
            const record = byVersion.get(model.version)
            return <tr key={model.version}>
              <th scope="row" className="py-2 text-left font-medium text-zinc-200">{model.label}</th>
              <td className="py-2 text-right text-zinc-100">{score(record?.mean_brier)}</td>
              <td className="py-2 text-right text-zinc-300">{record?.brier_n ?? 0}</td>
            </tr>
          })}</tbody>
        </table>
      </div>
    </div>
  )
}

// One game as a card, the same panel design as the homepage's NFL example. The projection and the record use this
// card; the record adds the final score and the pick's result.
export function GameCard({ game, lock, mode }: { game: ModelGame; lock: Lock; mode: 'projection' | 'record' }) {
  const record = mode === 'record'
  const status = record ? statusLabel(lock) : null
  const tone = record ? statusClass(lock) : 'text-emerald-400'
  const projected = (value: number | null) => (value == null ? '—' : one(value))
  return (
    <article className="space-y-2 rounded-2xl border border-zinc-800 bg-zinc-900 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="font-semibold text-zinc-100">{game.away} {game.neutral ? 'vs' : '@'} {game.home}</h3>
        <span className="flex items-center gap-3">
          {status && <span className={`rounded-full border border-current px-2.5 py-0.5 text-xs font-semibold tracking-wide ${tone}`}>{status}</span>}
          <span className="text-sm tabular-nums text-zinc-400">{timeLabel(game.kickoff_utc)}</span>
        </span>
      </div>
      <div className="grid grid-cols-[1fr_auto_auto] items-baseline gap-x-6 gap-y-1 text-sm tabular-nums">
        <span />
        <span />
        <span className="text-right text-xs uppercase tracking-wider text-zinc-500">{record ? 'Final' : ''}</span>
        <span className="text-zinc-200">{game.away}{game.away_record && <span className="block text-xs text-zinc-500">{game.away_record}</span>}</span>
        <span className="text-right text-2xl font-semibold text-zinc-100">{projected(lock.proj_away)}</span>
        <span className="text-right text-xl font-semibold text-zinc-300">{record && game.final ? one(game.final.away) : ''}</span>
        <span className="text-zinc-200">{game.home}{game.home_record && <span className="block text-xs text-zinc-500">{game.home_record}</span>}</span>
        <span className="text-right text-2xl font-semibold text-zinc-100">{projected(lock.proj_home)}</span>
        <span className="text-right text-xl font-semibold text-zinc-300">{record && game.final ? one(game.final.home) : ''}</span>
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-1 border-t border-zinc-800 pt-2 text-sm text-zinc-400">
        <span>ML lean <b className="font-medium text-zinc-100">{mlLean(game, lock)}</b></span>
        <span>ATS lean <b className="font-medium text-zinc-100">{pickSide(game, lock) || 'No line'}</b></span>
        <span>Total lean <b className="font-medium text-zinc-100">{totalLean(lock)}</b></span>
      </div>
      <div className="text-xs text-zinc-500">
        Wager · <b className="font-medium text-zinc-200">{wagerLabel(lock)}</b>
        {lock.wager && <span className="text-zinc-600"> · {lock.wager.policy}</span>}
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-zinc-400">
        <span>Line <b className="font-medium tabular-nums text-zinc-100">{lineSide(game.home, game.away, lock.line.spread)}</b></span>
        <span>Model line <b className="font-medium tabular-nums text-zinc-100">{modelSide(game.home, game.away, lock.margin)}</b></span>
        <span>Edge <b className="font-medium tabular-nums text-zinc-100">{edge(lock) == null ? '—' : `${one(edge(lock)!)} pts`}</b></span>
        <span>Total <b className="font-medium tabular-nums text-zinc-100">{lock.line.total == null ? '—' : one(lock.line.total)}</b></span>
        <span>Model total <b className="font-medium tabular-nums text-zinc-100">{lock.total == null ? '—' : one(lock.total)}</b></span>
        <span>Total edge <b className="font-medium tabular-nums text-zinc-100">{totalEdge(lock) == null ? '—' : `${signed(totalEdge(lock)!)} pts`}</b></span>
      </div>
      <p className="text-xs text-zinc-500">{lineCaptureLabel(lock)}</p>
    </article>
  )
}


function GameProjection({ game, lock }: { game: ModelGame; lock?: Lock }) {
  return (
    <article className="py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="font-semibold text-zinc-100">{game.away} {game.neutral ? 'vs' : '@'} {game.home}</h3>
        {!game.final && <span className="text-sm tabular-nums text-zinc-400">{timeLabel(game.kickoff_utc)}</span>}
      </div>
      {!lock ? <p className="mt-2 text-sm text-amber-400">No locked projection for this game.</p> : (
        <>
          <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-6 xl:grid-cols-9">
            <Metric label="Line" value={lineSide(game.home, game.away, lock.line.spread)} />
            <Metric label="Model line" value={modelSide(game.home, game.away, lock.margin)} />
            <Metric label="ML lean" value={mlLean(game, lock)} />
            <Metric label="ATS lean" value={pickSide(game, lock) || 'No line'} />
            <Metric label="Total lean" value={totalLean(lock)} />
            <Metric label="Wager" value={wagerLabel(lock)} />
            <Metric label="Edge" value={edge(lock) == null ? '—' : `${one(edge(lock)!)} pts`} emphasis />
            <Metric label="Total" value={lock.line.total == null ? '—' : one(lock.line.total)} />
            <Metric label="Model total" value={lock.total == null ? '—' : one(lock.total)} />
            <Metric label="Total edge" value={totalEdge(lock) == null ? '—' : `${signed(totalEdge(lock)!)} pts`} />
            <div className="min-w-0">
              <div className="text-xs text-zinc-500">Final</div>
              <div className="mt-0.5 truncate text-sm font-normal tabular-nums text-zinc-200">
                {game.final ? `${game.away} ${one(game.final.away)} · ${game.home} ${one(game.final.home)}` : 'Pending'}
              </div>
            </div>
            <div className="min-w-0">
              <div className="text-xs text-zinc-500">Result</div>
              <div className={`mt-0.5 truncate text-sm tabular-nums ${statusClass(lock)}`}>{statusLabel(lock)}</div>
            </div>
          </div>
          <p className="mt-2 text-xs text-zinc-500">{lineCaptureLabel(lock)}</p>
          {lock.proj_home == null || lock.proj_away == null ? (
            <p className="mt-2 text-xs text-zinc-500">Projected score unavailable for this lock.</p>
          ) : (
            <p className="mt-2 text-xs text-zinc-500">
              Projected {game.away} {one(lock.proj_away)} · {game.home} {one(lock.proj_home)}
            </p>
          )}
        </>
      )}
    </article>
  )
}

function Metric({ label, value, emphasis, resultClass }: { label: string; value: string; emphasis?: boolean; resultClass?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className={`mt-0.5 truncate tabular-nums ${emphasis ? 'text-lg font-semibold text-zinc-100' : 'text-sm text-zinc-200'} ${resultClass || ''}`}>{value}</div>
    </div>
  )
}

function RecordCards({ games, version, threshold }: { games: ModelGame[]; version: string; threshold: EdgeFilter }) {
  const rows = games.flatMap(game => {
    const lock = game.locks[version]
    if (!lock) return []
    const pointEdge = edge(lock)
    if (threshold !== 'all' && (pointEdge == null || pointEdge < Number(threshold))) return []
    return [{ game, lock }]
  }).sort((a, b) => (a.game.kickoff_utc || '').localeCompare(b.game.kickoff_utc || ''))

  if (!rows.length) return <p className="text-sm text-zinc-400">No picks match this filter for this week.</p>
  return (
    <div className="divide-y divide-zinc-800 rounded-2xl bg-zinc-900 px-4">
      {rows.map(({ game, lock }) => <GameProjection key={game.game_id} game={game} lock={lock} />)}
    </div>
  )
}

function TeamRatings({ payload }: { payload: RatingsPayload }) {
  const teams = [...payload.teams].sort((a, b) => (b.overall ?? -Infinity) - (a.overall ?? -Infinity))
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-lg font-semibold text-zinc-100">Team ratings</h2>
        <p className="text-xs text-zinc-500">{payload.season} · {payload.model_version}{payload.as_of ? ` · as of ${new Date(payload.as_of).toLocaleDateString()}` : ''}</p>
      </div>
      <div className="overflow-x-auto rounded-2xl bg-zinc-900 px-4">
        <table className="w-full min-w-[620px] text-sm">
          <thead className="text-xs text-zinc-500"><tr className="border-b border-zinc-800 text-left"><th className="py-2 font-medium">Team</th><th className="py-2 text-right font-medium">Offense</th><th className="py-2 text-right font-medium">Defense</th><th className="py-2 text-right font-medium">Overall</th><th className="py-2 text-right font-medium">Games</th></tr></thead>
          <tbody className="divide-y divide-zinc-800">
            {teams.map(team => <tr key={team.team} className="text-zinc-300"><th className="py-2 text-left font-medium text-zinc-100">{team.team} <span className="font-normal text-zinc-500">{team.team_name}</span></th><td className="py-2 text-right tabular-nums">{team.off == null ? '—' : signed(team.off)}</td><td className="py-2 text-right tabular-nums">{team.def == null ? '—' : signed(team.def)}</td><td className="py-2 text-right tabular-nums">{team.overall == null ? '—' : signed(team.overall)}</td><td className="py-2 text-right tabular-nums">{team.games}</td></tr>)}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function TallyLabel({ title, tally }: { title: string; tally: Tally | null }) {
  if (!tally) return <span>{title} —</span>
  const extras = (tally.push ?? tally.tie ?? 0) > 0 ? ` · ${tally.push ?? tally.tie} ${tally.push ? 'push' : 'tie'}` : ''
  return <span>{title} {tally.win}-{tally.loss}{extras}</span>
}

export default function NflModelTab() {
  const [view, setView] = useState<ModelView>('projections')
  const [week] = useState<number | null>(null)
  const [recordWeek, setRecordWeek] = useState<number | null>(null)
  const [version, setVersion] = useState('')
  const [threshold, setThreshold] = useState<EdgeFilter>('all')
  const [data, setData] = useState<Payload | null>(null)
  const [recordGames, setRecordGames] = useState<ModelGame[]>([])
  const [ratings, setRatings] = useState<RatingsPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [accuracyOpen, setAccuracyOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    fetch(`/api/nfl/model/locks${week ? `?week=${week}` : ''}`)
      .then(async response => {
        if (!response.ok) throw new Error(`The projections did not load (HTTP ${response.status}).`)
        return response.json() as Promise<Payload>
      })
      .then(payload => {
        if (cancelled) return
        setData(payload)
        const preferred = payload.models.find(model => model.adopted) || payload.models[0]
        setVersion(current => payload.models.some(model => model.version === current) ? current : preferred?.version || '')
      })
      .catch(reason => { if (!cancelled) setError(reason.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [week])

  useEffect(() => {
    if (view !== 'record' || !data) return
    let cancelled = false
    Promise.all(data.weeks.map(w => fetch(`/api/nfl/model/locks?week=${w}`).then(response => {
      if (!response.ok) throw new Error(`The record did not load (HTTP ${response.status}).`)
      return response.json() as Promise<Payload>
    }))).then(payloads => {
      if (!cancelled) setRecordGames(payloads.flatMap(payload => payload.games))
    }).catch(reason => { if (!cancelled) setError(reason.message) })
    return () => { cancelled = true }
  }, [view, data])

  useEffect(() => {
    if (view !== 'ratings' || !data) return
    let cancelled = false
    fetch(`/api/nfl/ratings?season=${data.season}`).then(async response => {
      if (!response.ok) throw new Error(`Team ratings did not load (HTTP ${response.status}).`)
      return response.json() as Promise<RatingsPayload>
    }).then(payload => { if (!cancelled) setRatings(payload) }).catch(reason => { if (!cancelled) setError(reason.message) })
    return () => { cancelled = true }
  }, [view, data])

  const selectedModel = data?.models.find(model => model.version === version)
  const selectedRecord = data?.record.find(record => record.version === version)
  const games = useMemo(() => {
    if (!data) return []
    const grouped = new Map<string, ModelGame[]>()
    for (const game of data.games) {
      if (!game.locks[version] || isMissedLock(game, version)) continue
      const day = dayLabel(game.kickoff_utc)
      grouped.set(day, [...(grouped.get(day) || []), game])
    }
    return Array.from(grouped.entries())
  }, [data, version])

  // The record's week defaults to the latest week with a graded pick, so an unplayed week's preview never opens it.
  const gradedWeeks = useMemo(() => Array.from(new Set(recordGames.filter(game => game.locks[version]?.grade).map(game => game.week))).sort((a, b) => a - b), [recordGames, version])
  const activeRecordWeek = (recordWeek != null && gradedWeeks.includes(recordWeek) ? recordWeek : null) ?? gradedWeeks[gradedWeeks.length - 1] ?? null
  const missedWeekGames = data?.games.filter(game => isMissedLock(game, version)) || []
  const recordWeekForMisses = activeRecordWeek ?? data?.week
  const missedRecordGames = recordGames.filter(game => game.week === recordWeekForMisses)
  const visibleRecordGames = recordGames.filter(game => game.week === activeRecordWeek
    && !game.locks[version]?.preview && !isMissedLock(game, version))

  if (error) return <div className="rounded-2xl bg-zinc-900 px-4 py-3 text-sm text-red-400">{error}</div>
  if (loading && !data) return <div className="h-40 animate-pulse rounded-2xl bg-zinc-800" />
  if (!data) return <p className="text-sm text-zinc-400">No NFL model data is available.</p>

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <nav className="flex gap-1 rounded-full bg-zinc-900 p-1" aria-label="NFL model views">
          {([['projections', 'Projections'], ['record', 'Record'], ['ratings', 'Team Ratings']] as [ModelView, string][]).map(([key, label]) => (
            <button key={key} type="button" onClick={() => { setView(key); setError(null) }} aria-current={view === key ? 'page' : undefined} className={`rounded-full px-3 py-1.5 text-sm ${view === key ? 'bg-zinc-100 text-zinc-900' : 'text-zinc-400 hover:text-zinc-100'}`}>{label}</button>
          ))}
        </nav>
        <label className="flex items-center gap-2 text-sm text-zinc-500">
          Model
          <ModelSelect value={version} onChange={event => setVersion(event.target.value)} className="max-w-[18rem]">
            {data.models.map(model => <option key={model.version} value={model.version}>{model.label}</option>)}
          </ModelSelect>
        </label>
        <div className="relative">
          <button type="button" aria-label="Model accuracy" aria-expanded={accuracyOpen}
            onClick={() => setAccuracyOpen(open => !open)}
            className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs font-medium text-zinc-200 hover:bg-zinc-800">
            Model accuracy
          </button>
          {accuracyOpen && <ModelAccuracy models={data.models} records={data.record} />}
        </div>
      </div>

      {view === 'projections' && <>
        <div>
          <h2 className="text-lg font-semibold text-zinc-100">{data.season} week {data.week} · {selectedModel?.label}</h2>
          <p className="text-sm text-zinc-400">One card per game. The record tab grades the locked projections.</p>
        </div>
        {!games.length && !missedWeekGames.length ? <p className="text-sm text-zinc-400">No projections for this week yet.</p> : games.map(([day, entries]) => (
          <section key={day} className="space-y-2">
            <h3 className="text-sm font-medium text-zinc-400">{day}</h3>
            <div className="grid gap-3 sm:grid-cols-2">{entries.map(game => <GameCard key={game.game_id} game={game} lock={game.locks[version]} mode="projection" />)}</div>
          </section>
        ))}
        <MissedLockList games={missedWeekGames} version={version} />
      </>}

      {view === 'record' && <section className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-lg font-semibold text-zinc-100">{data.season} record · {selectedModel?.label}</h2><p className="text-sm text-zinc-400">{!selectedRecord || selectedRecord.graded === 0 ? `No graded picks yet · ${selectedRecord?.awaiting ?? 0} awaiting a final` : <><span className="text-zinc-500">Leans · </span><TallyLabel title="Winner" tally={selectedRecord.su} /> <span className="mx-2 text-zinc-600">·</span><TallyLabel title="ATS" tally={selectedRecord.ats} /> <span className="mx-2 text-zinc-600">·</span><TallyLabel title="Total" tally={selectedRecord.total_lean ?? null} /> <span className="mx-2 text-zinc-600">·</span>{selectedRecord.graded} graded{selectedRecord.awaiting ? ` · ${selectedRecord.awaiting} awaiting` : ''}</>}</p><p className="mt-0.5 text-xs text-zinc-500">Wagers · {selectedRecord?.wager?.issued ?? 0} issued{selectedRecord?.wager?.priced ? ` · ${selectedRecord.wager.priced} priced pregame` : ''}{selectedRecord?.wager?.policy_note ? ` · ${selectedRecord.wager.policy_note}` : ''}</p></div>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-zinc-500">Week <ModelSelect value={activeRecordWeek ?? ''} onChange={event => setRecordWeek(event.target.value ? Number(event.target.value) : null)}>{gradedWeeks.map(w => <option key={w} value={w}>{w}</option>)}</ModelSelect></label>
            <div className="flex gap-1" aria-label="Filter by edge">{([['all', 'All'], ['3', 'Edge 3+'], ['6', 'Edge 6+']] as [EdgeFilter, string][]).map(([key, label]) => <button key={key} type="button" onClick={() => setThreshold(key)} aria-pressed={threshold === key} className={`rounded-full px-3 py-1.5 text-sm ${threshold === key ? 'bg-zinc-100 text-zinc-900' : 'bg-zinc-900 text-zinc-400 hover:text-zinc-100'}`}>{label}</button>)}</div>
          </div>
        </div>
        {recordGames.length === 0 ? <p className="text-sm text-zinc-400">{data.weeks.length ? 'Loading season picks…' : 'No season picks have been locked yet.'}</p> : <RecordCards games={visibleRecordGames} version={version} threshold={threshold} />}
        <MissedLockList games={missedRecordGames} version={version} />
        <p className="text-xs text-zinc-500">Leans are graded predictions, never wagers. Wagers are issued only by a validated policy (v1 is observe-only).</p>
      </section>}

      {view === 'ratings' && (ratings ? <TeamRatings payload={ratings} /> : <div className="h-40 animate-pulse rounded-2xl bg-zinc-800" />)}
    </div>
  )
}
