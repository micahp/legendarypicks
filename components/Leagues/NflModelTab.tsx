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

interface Lock {
  proj_home: number | null
  proj_away: number | null
  margin: number
  total: number
  p_home_win: number
  locked_at: string | null
  preview: boolean
  previewed_at: string | null
  line: Line
  grade: { brier: number | null; margin_err: number; total_err: number; ats: string; su: string | null } | null
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
  const homePick = lock.margin > marketMargin
  const spread = Math.abs(marketMargin)
  if (marketMargin === 0) return `${homePick ? game.home : game.away} Pick`
  if (homePick) return `${game.home} ${marketMargin > 0 ? `-${one(spread)}` : `+${one(spread)}`}`
  return `${game.away} ${marketMargin < 0 ? `-${one(spread)}` : `+${one(spread)}`}`
}

function edge(lock: Lock) {
  return lock.line.spread == null ? null : Math.abs(lock.margin - lock.line.spread)
}

function statusLabel(lock: Lock) {
  if (lock.preview) return 'NOT LOCKED'
  if (!lock.grade) return 'AWAITING'
  return { win: 'WIN', loss: 'LOSS', push: 'PUSH', no_pick: 'NO PICK', no_line: 'NO LINE' }[lock.grade.ats] || lock.grade.ats.toUpperCase()
}

function statusClass(lock: Lock) {
  if (lock.preview) return 'text-amber-300'
  if (!lock.grade) return 'text-zinc-500'
  if (lock.grade.ats === 'win') return 'text-emerald-400'
  if (lock.grade.ats === 'loss') return 'text-rose-400'
  return 'text-zinc-300'
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
          <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-6">
            <Metric label="Vegas line" value={lineSide(game.home, game.away, lock.line.spread)} />
            <Metric label="Model line" value={modelSide(game.home, game.away, lock.margin)} />
            <Metric label="Model pick" value={pickSide(game, lock) || 'No line'} />
            <Metric label="Edge" value={edge(lock) == null ? '—' : `${one(edge(lock)!)} pts`} emphasis />
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

function RecordList({ games, version, threshold }: { games: ModelGame[]; version: string; threshold: EdgeFilter }) {
  const rows = games.flatMap(game => {
    const lock = game.locks[version]
    if (!lock) return []
    const pointEdge = edge(lock)
    if (threshold !== 'all' && (pointEdge == null || pointEdge < Number(threshold))) return []
    return [{ game, lock }]
  }).sort((a, b) => (b.game.kickoff_utc || '').localeCompare(a.game.kickoff_utc || ''))

  if (!rows.length) return <p className="text-sm text-zinc-400">No picks match this filter yet.</p>
  return (
    <div className="divide-y divide-zinc-800 rounded-2xl bg-zinc-900 px-4">
      {rows.map(({ game, lock }) => (
        <article key={game.game_id} className="py-3">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
            <div className="font-semibold text-zinc-100">{game.away} {game.neutral ? 'vs' : '@'} {game.home}</div>
            <div className={`text-xs font-semibold tracking-wide ${statusClass(lock)}`}>{statusLabel(lock)}</div>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm tabular-nums text-zinc-400">
            <span>Pick {pickSide(game, lock) || 'No line'}</span>
            <span>Edge {edge(lock) == null ? '—' : `${one(edge(lock)!)} pts`}</span>
            <span>Projected {lock.proj_away == null || lock.proj_home == null ? '—' : `${one(lock.proj_away)}–${one(lock.proj_home)}`}</span>
            <span>Final {game.final ? `${one(game.final.away)}–${one(game.final.home)}` : 'Pending'}</span>
          </div>
        </article>
      ))}
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
  const [week, setWeek] = useState<number | null>(null)
  const [version, setVersion] = useState('')
  const [threshold, setThreshold] = useState<EdgeFilter>('all')
  const [data, setData] = useState<Payload | null>(null)
  const [recordGames, setRecordGames] = useState<ModelGame[]>([])
  const [ratings, setRatings] = useState<RatingsPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

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
      if (!game.locks[version]) continue
      const day = dayLabel(game.kickoff_utc)
      grouped.set(day, [...(grouped.get(day) || []), game])
    }
    return Array.from(grouped.entries())
  }, [data, version])

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
      </div>

      {view === 'projections' && <>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><h2 className="text-lg font-semibold text-zinc-100">{data.season} projections · {selectedModel?.label}</h2></div>
          <label className="flex items-center gap-2 text-sm text-zinc-500">Week <ModelSelect value={week ?? data.week ?? ''} onChange={event => setWeek(event.target.value ? Number(event.target.value) : null)}>{data.weeks.map(w => <option key={w} value={w}>{w}</option>)}</ModelSelect></label>
        </div>
        {!games.length ? <p className="text-sm text-zinc-400">No projections have been locked for this week.</p> : games.map(([day, entries]) => (
          <section key={day} className="space-y-1"><h3 className="text-sm font-medium text-zinc-400">{day}</h3><div className="divide-y divide-zinc-800 rounded-2xl bg-zinc-900 px-4">{entries.map(game => <GameProjection key={game.game_id} game={game} lock={game.locks[version]} />)}</div></section>
        ))}
      </>}

      {view === 'record' && <section className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-lg font-semibold text-zinc-100">{data.season} record · {selectedModel?.label}</h2><p className="text-sm text-zinc-400">{!selectedRecord || selectedRecord.graded === 0 ? `No graded picks yet · ${selectedRecord?.awaiting ?? 0} awaiting a final` : <><TallyLabel title="ATS" tally={selectedRecord.ats} /> <span className="mx-2 text-zinc-600">·</span><TallyLabel title="Winner" tally={selectedRecord.su} /> <span className="mx-2 text-zinc-600">·</span>{selectedRecord.graded} graded{selectedRecord.awaiting ? ` · ${selectedRecord.awaiting} awaiting` : ''}</>}</p></div>
          <div className="flex gap-1" aria-label="Filter by edge">{([['all', 'All'], ['3', 'Edge 3+'], ['6', 'Edge 6+']] as [EdgeFilter, string][]).map(([key, label]) => <button key={key} type="button" onClick={() => setThreshold(key)} aria-pressed={threshold === key} className={`rounded-full px-3 py-1.5 text-sm ${threshold === key ? 'bg-zinc-100 text-zinc-900' : 'bg-zinc-900 text-zinc-400 hover:text-zinc-100'}`}>{label}</button>)}</div>
        </div>
        {recordGames.length === 0 ? <p className="text-sm text-zinc-400">{data.weeks.length ? 'Loading season picks…' : 'No season picks have been locked yet.'}</p> : <RecordList games={recordGames} version={version} threshold={threshold} />}
        <p className="text-xs text-zinc-500">ATS counts include graded picks only. Pending games are not counted.</p>
      </section>}

      {view === 'ratings' && (ratings ? <TeamRatings payload={ratings} /> : <div className="h-40 animate-pulse rounded-2xl bg-zinc-800" />)}
    </div>
  )
}
