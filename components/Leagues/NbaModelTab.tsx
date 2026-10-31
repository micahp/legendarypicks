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
  locked: number
  graded: number
  awaiting: number
  missed: number
  winner_brier: number | null
  winner_log_loss: number | null
  unlocked?: { previewed: number; graded: number; winner_brier: number | null }
}
type Payload = {
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

type View = 'projections' | 'record'

const metric = (value: number | null | undefined, places = 3) =>
  value == null || !Number.isFinite(value) ? '—' : value.toFixed(places)
const percent = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value) ? '—' : (value * 100).toFixed(1) + '%'

function dateLabel(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })
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

function ModelAccuracy({ payload, selectedModel }: { payload: Payload; selectedModel: string }) {
  const validation = payload.benchmark?.metrics?.validation ?? {}
  const test = payload.benchmark?.metrics?.test ?? {}

  return (
    <section aria-label="Model accuracy details" className="rounded-xl border border-zinc-700 bg-zinc-900 p-4 shadow-2xl">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-zinc-100">Model accuracy</h3>
        <p className="mt-1 text-xs text-zinc-400">
          Historical validation/test results and this season’s locked forecasts. Unlocked preview grades are excluded.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[850px] text-xs tabular-nums">
          <thead className="border-b border-zinc-700 text-zinc-500">
            <tr>
              <th className="px-2 py-2 text-left font-medium">Model · sample</th>
              <th className="px-2 py-2 text-right font-medium">Brier ↓</th>
              <th className="px-2 py-2 text-right font-medium">Log loss ↓</th>
              <th className="px-2 py-2 text-right font-medium">ECE10 ↓</th>
              <th className="px-2 py-2 text-right font-medium">Team points MAE ↓</th>
              <th className="px-2 py-2 text-right font-medium">Spread MAE ↓</th>
              <th className="px-2 py-2 text-right font-medium">Total MAE ↓</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {payload.models.flatMap((model) => {
              const historical = [
                { label: 'Validation', score: validation[model.id], count: payload.benchmark.eligible_games.validation },
                { label: 'Test', score: test[model.id], count: payload.benchmark.eligible_games.test },
              ]
              const liveRecord = payload.records[model.id]
              const rows = [
                ...historical.map((item) => ({
                  label: item.label,
                  score: item.score,
                  count: item.score?.games ?? item.count,
                })),
                {
                  label: 'Prospective locked',
                  score: {
                    winner_brier: liveRecord?.winner_brier,
                    winner_log_loss: liveRecord?.winner_log_loss,
                  } as Metrics,
                  count: liveRecord?.graded ?? 0,
                },
              ]
              return rows.map((row) => (
                <tr key={model.id + '-' + row.label} className={model.id === selectedModel ? 'bg-zinc-800/70' : ''}>
                  <th scope="row" className="px-2 py-2 text-left font-medium text-zinc-200">
                    {model.label} · {row.label} <span className="text-zinc-500">(n={row.count})</span>
                  </th>
                  <td className="px-2 py-2 text-right">{metric(row.score?.winner_brier, 4)}</td>
                  <td className="px-2 py-2 text-right">{metric(row.score?.winner_log_loss, 4)}</td>
                  <td className="px-2 py-2 text-right">{metric(row.score?.calibration?.ece_10_bin, 4)}</td>
                  <td className="px-2 py-2 text-right">{metric(row.score?.team_points_mae, 3)}</td>
                  <td className="px-2 py-2 text-right">{metric(row.score?.spread_mae, 3)}</td>
                  <td className="px-2 py-2 text-right">{metric(row.score?.total_mae, 3)}</td>
                </tr>
              ))
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs leading-relaxed text-zinc-500">
        Lower Brier and log loss are better. Historical sample sizes use the untouched chronological validation and test sets.
        The prospective row includes only locked forecasts that have been graded.
      </p>
    </section>
  )
}

function RecordView({ payload, model }: { payload: Payload; model: Model }) {
  const summary = payload.records[model.id]
  const lockedGames = payload.games
    .filter((game) => Boolean(game.models[model.id]?.locked_at_utc))
    .sort((a, b) => b.scheduled_start_utc.localeCompare(a.scheduled_start_utc))

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-lg font-semibold text-zinc-100">2026–27 record · {model.label}</h2>
        <p className="mt-1 text-xs text-zinc-500">
          Only this model’s forecasts with a recorded lock time appear here. Probabilities are forecasts; no win/loss pick is inferred.
          Unlocked preview grades are excluded.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          ['Locked', summary?.locked ?? 0],
          ['Graded', summary?.graded ?? 0],
          ['Awaiting result', summary?.awaiting ?? 0],
          ['Missed locks', summary?.missed ?? 0],
        ].map(([label, value]) => (
          <div key={label} className="rounded-xl border border-white/10 bg-zinc-950/50 px-3 py-2">
            <div className="text-xs text-zinc-500">{label}</div>
            <div className="mt-1 text-lg font-semibold tabular-nums text-zinc-100">{value}</div>
          </div>
        ))}
      </div>

      {lockedGames.length === 0 ? (
        <p className="rounded-xl border border-white/10 bg-zinc-950/50 p-4 text-sm text-zinc-400">
          No model-specific locked forecasts are available yet.
        </p>
      ) : (
        <div className="divide-y divide-zinc-800 rounded-xl border border-white/10 bg-zinc-950/50 px-4">
          {lockedGames.map((game) => {
            const forecast = game.models[model.id]
            const grade = forecast.grade
            const result = game.result ?? (grade ? { home_score: grade.home_score, away_score: grade.away_score } : null)
            const outcome = result == null
              ? null
              : result.home_score === result.away_score
                ? 'Tie'
                : (result.home_score > result.away_score ? game.home_team : game.away_team) + ' won'
            const projectedScore = forecast.score_forecast_available &&
              forecast.projected_away_points != null && forecast.projected_home_points != null
              ? game.away_team + ' ' + forecast.projected_away_points.toFixed(1) + ' – ' + game.home_team + ' ' + forecast.projected_home_points.toFixed(1)
              : null
            const status = grade
              ? 'Graded'
              : result
                ? 'Final · grading pending'
                : 'Pending'

            return (
              <article key={game.game_id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <h3 className="font-medium text-zinc-100">{game.away_team} at {game.home_team}</h3>
                  <p className="mt-1 text-xs text-zinc-500">
                    {new Date(game.scheduled_start_utc).toLocaleString()} · Locked {new Date(forecast.locked_at_utc as string).toLocaleString()}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-zinc-300">
                    <span>{game.home_team} win probability {percent(forecast.home_win_probability)}</span>
                    {projectedScore && <span>Projected score: {projectedScore}</span>}
                    {result && <span>Final {game.away_team} {result.away_score} – {game.home_team} {result.home_score} · {outcome}</span>}
                  </div>
                </div>
                <span className={grade ? 'shrink-0 text-xs text-emerald-300' : 'shrink-0 text-xs text-zinc-400'}>{status}</span>
              </article>
            )
          })}
        </div>
      )}
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
    const load = () => fetch('/api/nba/model/locks?season=2027')
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
          {([['projections', 'Projections'], ['record', 'Record']] as [View, string][]).map(([key, label]) => (
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
                  const score = hasScore
                    ? game.away_team + ' ' + forecast.projected_away_points.toFixed(1) + ' – ' + game.home_team + ' ' + forecast.projected_home_points.toFixed(1)
                    : forecast ? 'No score projection' : 'Forecast unavailable'
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
                          <div className="mt-2 text-sm tabular-nums text-zinc-200">{hasScore ? 'Projected score: ' : ''}{score}</div>
                        </div>
                      ) : (
                        <p className="p-4 text-sm text-zinc-500">{score}</p>
                      )}
                    </article>
                  )
                })}
              </div>
            </section>
          ))}
        </section>
      )}

      {view === 'record' && <RecordView payload={payload} model={selectedModel} />}

      <p className="text-xs text-zinc-500">
        The 2017–18 through 2025–26 SportsDataverse releases supply historical training and evaluation data. No historical NBA pregame odds feed was available for a valid timestamped market benchmark. Current-season forecasts use completed games and official schedule rows only; no lineups or post-tipoff inputs are used.
      </p>
    </div>
  )
}
