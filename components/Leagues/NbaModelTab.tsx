import { useEffect, useState } from 'react'

type Metrics = {
  games: number
  winner_brier: number
  winner_log_loss: number
  winner_accuracy: number
  home_points_mae?: number
  away_points_mae?: number
  team_points_mae?: number
  spread_mae?: number
  total_mae?: number
  calibration?: { ece_10_bin: number }
  distribution?: {
    margin_crps: number
    total_crps: number
    joint_score_gaussian_nll: number
    margin_80pct_coverage: number
    total_80pct_coverage: number
  }
}

type Forecast = {
  model_version: string
  home_win_probability: number
  projected_home_points: number | null
  projected_away_points: number | null
  score_forecast_available: boolean
  locked?: boolean
  lock_protocol?: string
  grade?: { home_score: number; away_score: number; winner_brier: number } | null
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
type Payload = {
  state: string
  default_model: string
  models: Model[]
  records: Record<string, { locked: number; graded: number; awaiting: number; missed: number; winner_brier: number | null; winner_log_loss: number | null; unlocked?: { previewed: number; graded: number; winner_brier: number | null } }>
  games: Game[]
  benchmark: {
    eligible_games: { train: number; validation: number; test: number }
    metrics: { validation: Record<string, Metrics>; test: Record<string, Metrics> }
  }
}

const metric = (value: number | undefined, places = 3) => value == null ? '—' : value.toFixed(places)
const percent = (value: number | undefined) => value == null ? '—' : `${(value * 100).toFixed(1)}%`
const kickoff = (value: string) => new Date(value).toLocaleString(undefined, {
  weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
})

function metricCell(value: number | undefined) {
  return <td className="px-3 py-2 text-right tabular-nums">{metric(value)}</td>
}

export default function NbaModelTab() {
  const [payload, setPayload] = useState<Payload | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = () => fetch('/api/nba/model/locks?season=2027')
      .then((response) => {
        if (!response.ok) throw new Error(`model feed returned ${response.status}`)
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
  if (!payload) return <div className="p-6 text-sm text-zinc-500">Loading NBA research models…</div>

  const upcoming = payload.games.filter((game) => new Date(game.scheduled_start_utc).getTime() > Date.now())
  const graded = payload.games.filter((game) => game.status === 'graded' && game.result)
    .slice(-10).reverse()
  const gradedPreviews = payload.games.filter((game) => game.status === 'unlocked' && game.result)
    .slice(-10).reverse()
  const test = payload.benchmark?.metrics?.test ?? {}
  const validation = payload.benchmark?.metrics?.validation ?? {}

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-400">NBA game model · 2026–27</p>
          <h2 className="mt-1 text-2xl font-semibold text-white">Research candidates</h2>
          <p className="mt-2 max-w-3xl text-sm text-zinc-400">
            Chronological historical evaluation and prospective forecasts. Every candidate is research only;
            previews are not locked forecasts, and no betting record is inferred from them.
          </p>
        </div>
        <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-xs font-semibold text-amber-200">
          Research only
        </span>
      </header>

      {error && <p role="status" className="text-xs text-amber-300">Refresh failed; showing the last successful feed. {error}</p>}
      {payload.state === 'awaiting_history_import' && (
        <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-100">
          Historical NBA data has not been imported into the model store yet. The benchmark below is the
          reproducible research run; prospective previews will appear after the model store is initialized.
        </p>
      )}

      <section aria-labelledby="nba-candidate-benchmark" className="overflow-hidden rounded-xl border border-white/10 bg-zinc-950/50">
        <div className="border-b border-white/10 px-4 py-3">
          <h3 id="nba-candidate-benchmark" className="font-semibold text-white">Chronological holdout comparison</h3>
          <p className="mt-1 text-xs text-zinc-500">
            Train {payload.benchmark.eligible_games.train.toLocaleString()} · validation {payload.benchmark.eligible_games.validation.toLocaleString()} · untouched test {payload.benchmark.eligible_games.test.toLocaleString()} games
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-[900px] w-full text-sm">
            <thead className="text-xs uppercase tracking-wide text-zinc-500">
              <tr className="border-b border-white/10">
                <th className="px-3 py-2 text-left">Research candidate</th>
                <th className="px-3 py-2 text-right">Test Brier ↓</th>
                <th className="px-3 py-2 text-right">Log loss ↓</th>
                <th className="px-3 py-2 text-right">ECE10 ↓</th>
                <th className="px-3 py-2 text-right">Team points MAE ↓</th>
                <th className="px-3 py-2 text-right">Spread MAE ↓</th>
                <th className="px-3 py-2 text-right">Total MAE ↓</th>
                <th className="px-3 py-2 text-right">Prospective graded</th>
              </tr>
            </thead>
            <tbody>
              {payload.models.map((model) => {
                const score = test[model.id]
                const record = payload.records[model.id]
                return (
                  <tr key={model.id} className="border-b border-white/5 align-top last:border-0">
                    <th className="px-3 py-3 text-left font-medium text-white">
                      {model.label}
                      <span className="mt-1 block max-w-64 break-all font-mono text-[10px] font-normal text-zinc-500">{model.version}</span>
                      <span className="mt-1 block max-w-64 text-xs font-normal text-zinc-400">{model.projects_scores ? model.note : 'Win probability only. This model does not project scores.'}</span>
                    </th>
                    {metricCell(score?.winner_brier)}
                    {metricCell(score?.winner_log_loss)}
                    {metricCell(score?.calibration?.ece_10_bin)}
                    {metricCell(score?.team_points_mae)}
                    {metricCell(score?.spread_mae)}
                    {metricCell(score?.total_mae)}
                    <td className="px-3 py-2 text-right tabular-nums">
                      {record?.graded ?? 0} / {record?.locked ?? 0}
                      <span className="mt-1 block text-[10px] font-normal text-zinc-500">{record?.unlocked?.graded ?? 0} unlocked previews graded</span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div className="grid gap-3 border-t border-white/10 p-4 md:grid-cols-3">
          {payload.models.map((model) => {
            const score = test[model.id]
            const val = validation[model.id]
            const distribution = score?.distribution
            return (
              <div key={model.id} className="rounded-lg bg-white/[0.03] p-3 text-xs text-zinc-400">
                <div className="font-semibold text-zinc-200">{model.label} · validation / test</div>
                <div className="mt-2">Brier {metric(val?.winner_brier)} / {metric(score?.winner_brier)} · log loss {metric(val?.winner_log_loss)} / {metric(score?.winner_log_loss)}</div>
                {distribution && <div className="mt-1">G3 test distribution: margin CRPS {metric(distribution.margin_crps)}, total CRPS {metric(distribution.total_crps)}, joint score NLL {metric(distribution.joint_score_gaussian_nll)}; 80% interval coverage {percent(distribution.margin_80pct_coverage)} margin / {percent(distribution.total_80pct_coverage)} total.</div>}
              </div>
            )
          })}
        </div>
      </section>

      <section aria-labelledby="nba-upcoming-models" className="space-y-3">
        <div>
          <h3 id="nba-upcoming-models" className="font-semibold text-white">Upcoming forecasts</h3>
          <p className="mt-1 text-xs text-zinc-500">Previews refresh from information available before each game. Only forecasts captured in the T−90 lock window count toward prospective grading.</p>
        </div>
        {upcoming.length === 0 ? (
          <p className="rounded-lg border border-white/10 p-4 text-sm text-zinc-400">No upcoming NBA forecasts are available yet.</p>
        ) : upcoming.map((game) => (
          <article key={game.game_id} className="overflow-hidden rounded-xl border border-white/10 bg-zinc-950/50">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 px-4 py-3">
              <div className="font-medium text-white">{game.away_team} at {game.home_team}</div>
              <div className="text-xs text-zinc-400">{kickoff(game.scheduled_start_utc)} · {(game.status === 'locked' || game.status === 'graded') && Object.values(game.models).some((m) => m.lock_protocol === 'late-preview-v1') ? 'Late lock from the pregame preview' : game.status === 'locked' ? 'Locked before tipoff' : game.status === 'missed' ? 'Lock window missed' : game.status === 'graded' ? 'Graded' : 'Preview, not locked'}</div>
            </div>
            <div className="grid gap-px bg-white/10 md:grid-cols-3">
              {payload.models.map((model) => {
                const forecast = game.models[model.id]
                if (!forecast) return <div key={model.id} className="bg-zinc-950 p-4 text-xs text-zinc-500">{model.label}: forecast unavailable</div>
                const score = forecast.score_forecast_available
                  ? `${forecast.projected_away_points?.toFixed(1)} – ${forecast.projected_home_points?.toFixed(1)}`
                  : 'No score projection'
                return (
                  <div key={model.id} className="bg-zinc-950 p-4">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-semibold text-white">{model.label}</span>
                      <span className="text-xs text-cyan-300">Home win {percent(forecast.home_win_probability)}</span>
                    </div>
                    <div className="mt-2 text-sm tabular-nums text-zinc-200">Away – home: {score}</div>
                    <div className="mt-1 break-all font-mono text-[10px] text-zinc-500">{forecast.model_version}</div>
                    {forecast.grade && <div className="mt-2 text-xs text-emerald-300">Final {forecast.grade.home_score}–{forecast.grade.away_score} · Brier {metric(forecast.grade.winner_brier)}</div>}
                  </div>
                )
              })}
            </div>
          </article>
        ))}
      </section>

      <section aria-labelledby="nba-prospective-results" className="space-y-3">
        <div>
          <h3 id="nba-prospective-results" className="font-semibold text-white">Prospective grading</h3>
          <p className="mt-1 text-xs text-zinc-500">Only immutable pre-tipoff locks appear here, including late locks taken from a stored pregame preview. Historical backtest rows are reported separately above.</p>
        </div>
        {graded.length === 0 ? (
          <p className="rounded-lg border border-white/10 p-4 text-sm text-zinc-400">No prospective forecasts have been graded yet.</p>
        ) : graded.map((game) => (
          <article key={game.game_id} className="rounded-xl border border-white/10 bg-zinc-950/50 p-4">
            <div className="flex flex-wrap justify-between gap-2 text-sm font-medium text-white">
              <span>{game.away_team} at {game.home_team}</span>
              <span>Final {game.result?.away_score}–{game.result?.home_score}</span>
            </div>
            <div className="mt-3 grid gap-2 md:grid-cols-3">
              {payload.models.map((model) => {
                const forecast = game.models[model.id]
                return <div key={model.id} className="text-xs text-zinc-300">
                  {model.label}: home win {percent(forecast?.home_win_probability)} · Brier {metric(forecast?.grade?.winner_brier)}
                </div>
              })}
            </div>
          </article>
        ))}
      </section>

      <section aria-labelledby="nba-unlocked-results" className="space-y-3">
        <div>
          <h3 id="nba-unlocked-results" className="font-semibold text-white">Graded previews, not locked</h3>
          <p className="mt-1 text-xs text-zinc-500">The last pregame preview of games that tipped off without a T−90 lock, graded against the verified final. These are not part of the prospective record above.</p>
        </div>
        {gradedPreviews.length === 0 ? (
          <p className="rounded-lg border border-white/10 p-4 text-sm text-zinc-400">No unlocked previews have been graded yet.</p>
        ) : gradedPreviews.map((game) => (
          <article key={game.game_id} className="rounded-xl border border-white/10 bg-zinc-950/50 p-4">
            <div className="flex flex-wrap justify-between gap-2 text-sm font-medium text-white">
              <span>{game.away_team} at {game.home_team}</span>
              <span>Final {game.result?.away_score}–{game.result?.home_score} · Not locked</span>
            </div>
            <div className="mt-3 grid gap-2 md:grid-cols-3">
              {payload.models.map((model) => {
                const forecast = game.models[model.id]
                return <div key={model.id} className="text-xs text-zinc-300">
                  {model.label}: home win {percent(forecast?.home_win_probability)} · Brier {metric(forecast?.grade?.winner_brier)}
                </div>
              })}
            </div>
          </article>
        ))}
      </section>

      <p className="text-xs text-zinc-500">
        The 2017–18 through 2025–26 SportsDataverse releases supply historical training and evaluation data. No historical NBA pregame odds feed was available for a valid timestamped market benchmark. Current-season forecasts use completed games and official schedule rows only; no lineups or post-tipoff inputs are used.
      </p>
    </div>
  )
}
