import { useEffect, useState } from 'react'
import ModelSelect from './ModelSelect'

type Metrics = {
  games?: number
  winner_brier?: number | null
  winner_log_loss?: number | null
  winner_accuracy?: number | null
  home_points_mae?: number | null
  away_points_mae?: number | null
  team_points_mae?: number | null
  spread_mae?: number | null
  total_mae?: number | null
  calibration?: { ece_10_bin?: number | null }
}

type Forecast = {
  model_version: string
  home_win_probability: number | null
  projected_home_points: number | null
  projected_away_points: number | null
  score_forecast_available: boolean
  locked?: boolean
  locked_at_utc?: string | null
  lock_protocol?: string | null
  grade?: {
    home_score: number
    away_score: number
    home_win?: boolean
    winner_brier?: number
    winner_log_loss?: number
  } | null
}

type Model = { id: string; label: string; version: string; projects_scores: boolean; note: string }
type Game = {
  game_id: string
  scheduled_start_utc: string
  home_team: string
  away_team: string
  status: 'preview' | 'locked' | 'graded' | 'missed' | 'unlocked'
  locked_at_utc: string | null
  result: { home_score: number; away_score: number } | null
  models: Record<string, Forecast>
}
type RecordSummary = {
  pick: { win: number; loss: number; push: number }
  locked: number
  graded: number
  awaiting: number
  missed: number
  winner_brier: number | null
  winner_log_loss: number | null
  unlocked?: { previewed: number; graded: number; winner_brier: number | null }
}
type Payload = {
  season: number
  state: string
  default_model: string
  models: Model[]
  records: Record<string, RecordSummary>
  games: Game[]
  benchmark: {
    eligible_games: { train: number; validation: number; test: number }
    metrics: { validation: Record<string, Metrics>; test: Record<string, Metrics> }
  }
}
type RecordPage = {
  season: number
  model: string
  games: Game[]
  record: RecordSummary | null
  has_more: boolean
  next_before: string | null
}

type AlmanacValue = { value: string; rank: number | null; qualifier: string | null }
type AlmanacColumn = { key: string; label: string }
type AlmanacTeam = { team: string; conference: 'East' | 'West'; stats: Record<string, AlmanacValue> }
type AlmanacSectionSummary = { id: string; label: string; source_page: number | string }
type AlmanacSection = AlmanacSectionSummary & { columns: AlmanacColumn[]; teams: AlmanacTeam[] }
type AlmanacPayload = {
  edition: string
  season: string
  source: { title: string; compiled_by: string; pages: string; pdf_sha256: string; coverage: string; data_note: string }
  sections: AlmanacSectionSummary[]
  section: AlmanacSection
}

type View = 'projections' | 'record' | 'ratings'

const metric = (value: number | null | undefined, places = 3) =>
  value == null || !Number.isFinite(value) ? '—' : value.toFixed(places)
const percent = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value) ? '—' : (value * 100).toFixed(1) + '%'

function dateLabel(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })
}

function localDateKey(iso: string) {
  const date = new Date(iso)
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-')
}

function timeLabel(iso: string) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

function lockLabel(game: Game, forecast: Forecast | undefined) {
  if (forecast?.locked_at_utc) {
    return forecast.lock_protocol === 'late-preview-v1'
      ? 'Late lock from the pregame preview'
      : 'Locked before tipoff'
  }
  if (game.status === 'missed') return 'Lock window missed'
  return forecast ? 'Preview, not locked' : 'Forecast unavailable'
}

async function fetchRecordPage(season: number, model: string, timezone: string,
                               before?: string | null, signal?: AbortSignal) {
  const query = new URLSearchParams({ season: String(season), model, days: '7', timezone })
  if (before) query.set('before', before)
  const response = await fetch('/api/nba/model/record?' + query.toString(), { cache: 'no-store', signal })
  if (!response.ok) throw new Error('NBA record feed returned ' + response.status)
  return response.json() as Promise<RecordPage>
}

function ModelAccuracy({ payload, selectedModel }: { payload: Payload; selectedModel: string }) {
  const test = payload.benchmark?.metrics?.test ?? {}

  return (
    <section aria-label="Model accuracy details" className="rounded-xl border border-zinc-700 bg-zinc-900 p-4 shadow-2xl">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-zinc-100">Model accuracy</h3>
        <p className="mt-1 text-xs text-zinc-400">
          Historical benchmark scores from held-out games. Current-season locked forecasts are shown in Record.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[850px] text-xs tabular-nums">
          <thead className="border-b border-zinc-700 text-zinc-500">
            <tr>
              <th className="px-2 py-2 text-left font-medium">Model</th>
              <th className="px-2 py-2 text-right font-medium">Brier ↓</th>
              <th className="px-2 py-2 text-right font-medium">Log loss ↓</th>
              <th className="px-2 py-2 text-right font-medium">ECE10 ↓</th>
              <th className="px-2 py-2 text-right font-medium">Team points MAE ↓</th>
              <th className="px-2 py-2 text-right font-medium">Spread MAE ↓</th>
              <th className="px-2 py-2 text-right font-medium">Total MAE ↓</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {payload.models.map((model) => {
              const score = test[model.id]
              return (
                <tr key={model.id} className={model.id === selectedModel ? 'bg-zinc-800/70' : ''}>
                  <th scope="row" className="px-2 py-2 text-left font-medium text-zinc-200">{model.label}</th>
                  <td className="px-2 py-2 text-right">{metric(score?.winner_brier, 4)}</td>
                  <td className="px-2 py-2 text-right">{metric(score?.winner_log_loss, 4)}</td>
                  <td className="px-2 py-2 text-right">{metric(score?.calibration?.ece_10_bin, 4)}</td>
                  <td className="px-2 py-2 text-right">{metric(score?.team_points_mae, 3)}</td>
                  <td className="px-2 py-2 text-right">{metric(score?.spread_mae, 3)}</td>
                  <td className="px-2 py-2 text-right">{metric(score?.total_mae, 3)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs leading-relaxed text-zinc-500">
        Lower Brier and log loss are better. Score and error metrics use the held-out benchmark games.
      </p>
    </section>
  )
}

function RecordView({ payload, model }: { payload: Payload; model: Model }) {
  const [page, setPage] = useState<RecordPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reload, setReload] = useState(0)
  const timezone = typeof Intl === 'undefined' ? 'UTC' : Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  const summary = page?.record ?? payload.records[model.id]

  useEffect(() => {
    const controller = new AbortController()
    setPage(null)
    setLoading(true)
    setError(null)
    const refreshFirstPage = (initial: boolean) => {
      fetchRecordPage(payload.season, model.id, timezone, null, controller.signal)
        .then((fresh) => {
          if (controller.signal.aborted) return
          setPage((current) => {
            if (initial || !current || !fresh.next_before) return fresh
            const retainedOlder = current.games.filter(
              (game) => localDateKey(game.scheduled_start_utc) < (fresh.next_before as string),
            )
            if (!retainedOlder.length) return fresh
            const freshIds = new Set(fresh.games.map((game) => game.game_id))
            return {
              ...fresh,
              games: [...fresh.games, ...retainedOlder.filter((game) => !freshIds.has(game.game_id))],
              has_more: current.has_more,
              next_before: current.next_before,
            }
          })
          setError(null)
        })
        .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message) })
        .finally(() => { if (initial && !controller.signal.aborted) setLoading(false) })
    }
    refreshFirstPage(true)
    const timer = window.setInterval(() => refreshFirstPage(false), 60_000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [payload.season, model.id, timezone, reload])

  const loadMore = async () => {
    if (!page?.next_before || loadingMore) return
    setLoadingMore(true)
    setError(null)
    try {
      const older = await fetchRecordPage(payload.season, model.id, timezone, page.next_before)
      setPage((current) => current
        ? {
            ...older,
            games: [...current.games, ...older.games.filter(
              (game) => !current.games.some((currentGame) => currentGame.game_id === game.game_id),
            )],
          }
        : older)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'NBA record feed did not load.')
    } finally {
      setLoadingMore(false)
    }
  }

  const gamesByDay = (page?.games ?? []).reduce<Record<string, Game[]>>((groups, game) => {
    const day = dateLabel(game.scheduled_start_utc)
    groups[day] = [...(groups[day] ?? []), game]
    return groups
  }, {})

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-lg font-semibold text-zinc-100">2026–27 record · {model.label}</h2>
        <p className="mt-1 text-sm text-zinc-400">
          <span className="font-semibold text-zinc-100">{summary?.pick.win ?? 0}-{summary?.pick.loss ?? 0}-{summary?.pick.push ?? 0}</span>
        </p>
      </div>

      {error && <p role="status" className="text-sm text-amber-300">{error}</p>}
      {loading && <p role="status" className="text-sm text-zinc-400">Loading record…</p>}
      {!loading && !page && error && (
        <button type="button" onClick={() => setReload((value) => value + 1)}
          className="text-sm text-cyan-300 hover:text-cyan-200">Retry loading record</button>
      )}
      {!loading && page && page.games.length === 0 ? (
        <p className="rounded-xl border border-white/10 bg-zinc-950/50 p-4 text-sm text-zinc-400">
          No model-specific locked forecasts are available yet.
        </p>
      ) : (
        <>
          {page && <div className="space-y-4">
            {Object.entries(gamesByDay).map(([day, games]) => (
              <section key={day} className="space-y-2">
                <h3 className="text-sm font-medium text-zinc-400">{day}</h3>
                <div className="divide-y divide-zinc-800 rounded-xl border border-white/10 bg-zinc-950/50 px-4">
                  {games.map((game) => {
                  const forecast = game.models[model.id]
                  const grade = forecast.grade
                  const result = game.result ?? (grade ? { home_score: grade.home_score, away_score: grade.away_score } : null)
                  const finalWinner = result == null || result.home_score === result.away_score
                    ? null
                    : result.home_score > result.away_score ? 'home' : 'away'
                  const awayFinalClass = result == null ? 'text-zinc-200'
                    : finalWinner === 'away' ? 'font-semibold text-zinc-100' : 'text-zinc-400'
                  const homeFinalClass = result == null ? 'text-zinc-200'
                    : finalWinner === 'home' ? 'font-semibold text-zinc-100' : 'text-zinc-400'
                  const projectedScore = forecast.score_forecast_available &&
                    forecast.projected_away_points != null && forecast.projected_home_points != null
                    ? { away: forecast.projected_away_points.toFixed(1), home: forecast.projected_home_points.toFixed(1) }
                    : null
                  const status = grade
                    ? forecast.home_win_probability != null && result && result.home_score !== result.away_score
                      ? ((forecast.home_win_probability >= 0.5) === (result.home_score > result.away_score) ? 'Won' : 'Lost')
                      : 'Graded'
                    : result
                      ? 'Final · grading pending'
                      : 'Pending'
                  const statusClass = status === 'Won'
                    ? 'shrink-0 text-xs text-emerald-300'
                    : status === 'Lost'
                      ? 'shrink-0 text-xs text-red-300'
                      : 'shrink-0 text-xs text-zinc-400'

                  return (
                    <article key={game.game_id} className="flex flex-wrap items-start gap-x-6 gap-y-6 py-4">
                      <div className="w-full min-w-48 sm:w-52 sm:flex-none">
                        <h3 className="font-medium text-zinc-100">{game.away_team} at {game.home_team}</h3>
                        <p className="mt-2 text-xs text-zinc-400">
                          {game.home_team} win probability {percent(forecast.home_win_probability)}
                        </p>
                      </div>
                      <section role="group" aria-label="Projected" className="w-full sm:w-52 sm:flex-none">
                        <h4 className="mb-1 text-xs font-medium text-zinc-500">Projected</h4>
                        <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-y-1 pr-2 text-sm tabular-nums">
                          <span className="truncate text-zinc-200">{game.away_team}</span>
                          <span className="text-right font-semibold text-zinc-100">{projectedScore?.away ?? '—'}</span>
                          <span className="truncate text-zinc-200">{game.home_team}</span>
                          <span className="text-right font-semibold text-zinc-100">{projectedScore?.home ?? '—'}</span>
                        </div>
                      </section>
                      <section role="group" aria-label="Final" className="w-full sm:ml-[9.5rem] sm:w-52 sm:flex-none">
                        <h4 className="mb-1 text-xs font-medium text-zinc-500">
                          Final{!result ? ' · Pending' : finalWinner == null ? ' · Tie' : ''}
                        </h4>
                        <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-y-1 pr-2 text-sm tabular-nums">
                          <span className={`truncate ${awayFinalClass}`}>{game.away_team}</span>
                          <span className={`text-right ${awayFinalClass}`}>{result?.away_score ?? '—'}</span>
                          <span className={`truncate ${homeFinalClass}`}>{game.home_team}</span>
                          <span className={`text-right ${homeFinalClass}`}>{result?.home_score ?? '—'}</span>
                        </div>
                      </section>
                      <div className="flex w-full items-center justify-between gap-3 text-xs sm:ml-auto sm:w-auto sm:flex-col sm:items-end">
                        <span className={statusClass}>{status}</span>
                      </div>
                    </article>
                  )
                  })}
                </div>
              </section>
            ))}
          </div>}
          {page?.has_more && <button type="button" onClick={loadMore} disabled={loadingMore}
            className="rounded-lg border border-zinc-700 px-4 py-2 text-sm text-zinc-200 hover:bg-zinc-900 disabled:opacity-50">
            {loadingMore ? 'Loading older dates…' : 'Load older dates'}
          </button>}
        </>
      )}
    </section>
  )
}

function TeamRatingsView() {
  const [sectionId, setSectionId] = useState('efficiency')
  const [sectionOptions, setSectionOptions] = useState<AlmanacSectionSummary[]>([])
  const [payload, setPayload] = useState<AlmanacPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setPayload(null)
    setLoading(true)
    setError(null)
    fetch('/api/nba/model/team-ratings?section=' + encodeURIComponent(sectionId), {
      cache: 'no-store', signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => ({}))
          throw new Error(body.detail || 'NBA Almanac team stats returned ' + response.status)
        }
        return response.json() as Promise<AlmanacPayload>
      })
      .then((data) => {
        if (controller.signal.aborted) return
        setPayload(data)
        setSectionOptions(data.sections)
      })
      .catch((reason: Error) => {
        if (!controller.signal.aborted) setError(reason.message)
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [sectionId])

  const currentSection = payload?.section.id === sectionId ? payload.section : null

  return (
    <section aria-label="NBA Almanac team ratings" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-zinc-100">2025–26 team stats</h2>
        </div>
        <label className="flex items-center gap-2 text-sm text-zinc-500">
          Stat group
          <select aria-label="Almanac stat group" value={sectionId} onChange={(event) => setSectionId(event.target.value)}
            className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-400">
            {sectionOptions.map((section) => <option key={section.id} value={section.id}>{section.label}</option>)}
          </select>
        </label>
      </div>

      {currentSection && <p className="text-xs text-zinc-500">
        {currentSection.label} · 30 teams
      </p>}
      {loading && <p role="status" className="text-sm text-zinc-400">Loading Almanac team stats…</p>}
      {error && <p role="alert" className="text-sm text-red-300">Almanac team stats unavailable: {error}</p>}
      {currentSection && <div className="overflow-x-auto rounded-lg border border-zinc-800">
        <table className="w-full min-w-[900px] text-left text-xs tabular-nums">
          <thead className="bg-zinc-900 text-zinc-400">
            <tr>
              <th scope="col" className="sticky left-0 bg-zinc-900 px-3 py-2">Team</th>
              {currentSection.columns.map((column) => (
                <th key={column.key} scope="col" className="whitespace-nowrap px-3 py-2 text-right font-medium">{column.label}</th>
              ))}
            </tr>
          </thead>
          {(['East', 'West'] as const).map((conference) => (
            <tbody key={conference} className="divide-y divide-zinc-800">
              <tr className="bg-zinc-900/60">
                <th scope="rowgroup" colSpan={currentSection.columns.length + 1}
                  className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wide text-zinc-500">
                  {conference === 'East' ? 'Eastern' : 'Western'} Conference
                </th>
              </tr>
              {currentSection.teams.filter((team) => team.conference === conference).map((team) => (
                <tr key={team.team}>
                  <th scope="row" className="sticky left-0 whitespace-nowrap bg-ink-900 px-3 py-2 text-left font-medium text-zinc-100">{team.team}</th>
                  {currentSection.columns.map((column) => {
                    const value = team.stats[column.key]
                    const shown = value?.value == null ? '—' : value.value + (value.qualifier ? ' (' + value.qualifier + ')' : '')
                    return (
                      <td key={column.key} className="whitespace-nowrap px-3 py-2 text-right text-zinc-200">
                        {shown}{value?.rank != null && <span className="text-zinc-500"> ({value.rank})</span>}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>}
      {currentSection && <p className="text-[11px] leading-relaxed text-zinc-600">
        Source: {payload?.source.title}, compiled by {payload?.source.compiled_by}. Season: {payload?.season}. Values retain the Almanac&apos;s published precision and ranks.
      </p>}
      {payload?.source.data_note && <p className="text-[11px] leading-relaxed text-zinc-600">{payload.source.data_note}</p>}
    </section>
  )
}

export default function NbaModelTab() {
  const [payload, setPayload] = useState<Payload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [modelId, setModelId] = useState<string | null>(null)
  const [view, setView] = useState<View>('projections')
  const [accuracyHovered, setAccuracyHovered] = useState(false)
  const [accuracyPinned, setAccuracyPinned] = useState(false)
  const showAccuracy = accuracyHovered || accuracyPinned

  useEffect(() => {
    let cancelled = false
    const load = () => fetch('/api/nba/model/locks?season=2027&view=projections')
      .then((response) => {
        if (!response.ok) throw new Error('model feed returned ' + response.status)
        return response.json()
      })
      .then((data: Payload) => {
        if (cancelled) return
        setPayload(data)
        setError(null)
      })
      .catch((err: Error) => !cancelled && setError(err.message))
    load()
    const timer = window.setInterval(load, 60_000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [])

  if (error && !payload) return <div className="p-6 text-sm text-red-400">NBA model feed unavailable — {error}</div>
  if (!payload) return <div className="p-6 text-sm text-zinc-500">Loading NBA projections…</div>

  const selectedModelId = payload.models.some((model) => model.id === modelId)
    ? modelId as string
    : payload.models.find((model) => model.id === payload.default_model)?.id ?? payload.models[0]?.id
  const selectedModel = payload.models.find((model) => model.id === selectedModelId)

  if (!selectedModel) return <div className="p-6 text-sm text-zinc-500">No NBA models are available.</div>

  const upcoming = payload.games
    .filter((game) => new Date(game.scheduled_start_utc).getTime() > Date.now())
    .sort((a, b) => a.scheduled_start_utc.localeCompare(b.scheduled_start_utc))
  const groups = upcoming.reduce<Record<string, Game[]>>((result, game) => {
    const day = dateLabel(game.scheduled_start_utc)
    result[day] = [...(result[day] ?? []), game]
    return result
  }, {})

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <nav className="flex gap-1 rounded-full bg-zinc-900 p-1" aria-label="NBA model views">
          {([['projections', 'Projections'], ['record', 'Record'], ['ratings', 'Team Ratings']] as [View, string][]).map(([key, label]) => (
            <button key={key} type="button" onClick={() => setView(key)} aria-current={view === key ? 'page' : undefined}
              className={view === key ? 'rounded-full bg-zinc-100 px-3 py-1.5 text-sm text-zinc-900' : 'rounded-full px-3 py-1.5 text-sm text-zinc-400 hover:text-zinc-100'}>
              {label}
            </button>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <div className="relative"
            onMouseEnter={() => setAccuracyHovered(true)}
            onMouseLeave={() => setAccuracyHovered(false)}
            onFocus={() => setAccuracyHovered(true)}
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                setAccuracyHovered(false)
                setAccuracyPinned(false)
              }
            }}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                setAccuracyHovered(false)
                setAccuracyPinned(false)
                event.currentTarget.querySelector('button')?.blur()
              }
            }}>
            <button type="button" aria-label="Model accuracy"
              aria-describedby={showAccuracy ? 'nba-model-accuracy-tooltip' : undefined}
              aria-expanded={showAccuracy} onClick={() => setAccuracyPinned((open) => !open)}
              className="flex items-center gap-2 whitespace-nowrap rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs font-medium text-zinc-200 hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-400">
              <span aria-hidden="true" className="text-zinc-400">ⓘ</span> Model accuracy
            </button>
            {accuracyPinned && <button type="button" tabIndex={-1} aria-label="Close model accuracy tooltip"
              onClick={() => { setAccuracyPinned(false); setAccuracyHovered(false) }}
              className="fixed inset-0 z-40 cursor-default" />}
            {showAccuracy && <div id="nba-model-accuracy-tooltip" role="tooltip"
              className="absolute right-0 top-full z-50 mt-2 max-h-[min(78vh,700px)] w-[min(94vw,900px)] overflow-y-auto overscroll-contain rounded-xl">
              <ModelAccuracy payload={payload} selectedModel={selectedModel.id} />
            </div>}
          </div>

          <label className="flex items-center gap-2 text-sm text-zinc-500">
            Model
            <ModelSelect aria-label="Model" value={selectedModel.id} onChange={(event) => setModelId(event.target.value)}>
              {payload.models.map((model) => <option key={model.id} value={model.id}>{model.label}</option>)}
            </ModelSelect>
          </label>
        </div>
      </div>

      {error && <p role="status" className="text-xs text-amber-300">Refresh failed; showing the last successful feed. {error}</p>}
      {payload.state === 'awaiting_history_import' && (
        <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-100">
          Historical NBA data has not been imported into the model store yet. Current-season forecasts will appear after the model store is initialized.
        </p>
      )}

      {view === 'projections' && (
        <section aria-labelledby="nba-projections-heading" className="space-y-3">
          <h2 id="nba-projections-heading" className="text-lg font-semibold text-zinc-100">
            Projections · {selectedModel.label}
          </h2>
          {upcoming.length === 0 ? (
            <p className="rounded-xl border border-white/10 bg-zinc-950/50 p-4 text-sm text-zinc-400">
              No upcoming NBA projections are available yet.
            </p>
          ) : Object.entries(groups).map(([day, games]) => (
            <section key={day} className="space-y-2">
              <h3 className="text-sm font-medium text-zinc-400">{day}</h3>
              <div className="grid gap-3 sm:grid-cols-2">
                {games.map((game) => {
                  const forecast = game.models[selectedModel.id]
                  const hasScore = forecast?.score_forecast_available &&
                    forecast.projected_away_points != null && forecast.projected_home_points != null
                  const projectedScore = hasScore && forecast
                    ? { away: forecast.projected_away_points!.toFixed(1), home: forecast.projected_home_points!.toFixed(1) }
                    : null
                  return (
                    <article key={game.game_id} className="overflow-hidden rounded-xl border border-white/10 bg-zinc-950/50">
                      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 px-4 py-3">
                        <h4 className="font-medium text-white">{game.away_team} at {game.home_team}</h4>
                        <div className="text-xs text-zinc-400">{timeLabel(game.scheduled_start_utc)} · {lockLabel(game, forecast)}</div>
                      </div>
                      {forecast ? (
                        <div className="p-4">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="text-sm font-semibold text-white">{selectedModel.label}</span>
                            <span className="text-xs text-cyan-300">{game.home_team} win probability {percent(forecast.home_win_probability)}</span>
                          </div>
                          {projectedScore ? (
                            <div role="group" aria-label="Projected score" className="mt-3">
                              <h5 className="mb-1 text-xs font-medium text-zinc-500">Projected</h5>
                              <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-y-1 pr-2 text-base tabular-nums text-zinc-200">
                                <span className="truncate">{game.away_team}</span>
                                <span className="text-right font-semibold text-zinc-100">{projectedScore.away}</span>
                                <span className="truncate">{game.home_team}</span>
                                <span className="text-right font-semibold text-zinc-100">{projectedScore.home}</span>
                              </div>
                            </div>
                          ) : (
                            <div className="mt-2 text-sm text-zinc-400">{forecast ? 'No score projection' : 'Forecast unavailable'}</div>
                          )}
                        </div>
                      ) : (
                        <p className="p-4 text-sm text-zinc-500">Forecast unavailable</p>
                      )}
                    </article>
                  )
                })}
              </div>
            </section>
          ))}
        </section>
      )}

      {view === 'record' && <RecordView key={selectedModel.id} payload={payload} model={selectedModel} />}
      {view === 'ratings' && <TeamRatingsView />}
    </div>
  )
}
