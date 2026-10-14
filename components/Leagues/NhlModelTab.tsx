import { useEffect, useMemo, useState } from 'react'

type View = 'projections' | 'record' | 'ratings'
type ModelName = 'B3_elo' | 'B5_xg_poisson' | 'B7_elo_xg_poisson'

interface Forecast {
  forecast_id: string
  home_expected_goals: number
  away_expected_goals: number
  projected_total_goals: number
  projected_goal_differential_home: number
  home_win_probability: number
  'p_over_5.5': number
  'p_over_6.5': number
}

interface NhlGame {
  game_id: number
  game_date: string
  scheduled_start_utc: string
  home_team: string
  away_team: string
  forecasted_at_utc: string
  feature_snapshot: {
    elo_pre_game: { home: number; away: number }
    xg_features: Record<string, number>
  }
  models: Record<ModelName, Forecast>
  markets: {
    source: string
    usable: boolean
    sides: { team: string; captured_at_utc: string; spread: number | null; quote_quality: string }[]
  }
}

interface Payload {
  model_version: string
  default_model: ModelName
  frozen_at_utc: string
  source: string
  games: NhlGame[]
}

const MODEL_LABELS: Record<ModelName, string> = {
  B3_elo: 'B3 Elo',
  B5_xg_poisson: 'B5 xG Poisson',
  B7_elo_xg_poisson: 'B7 Elo + xG',
}

const one = (value: number) => value.toFixed(1)
const pct = (value: number) => `${Math.round(value * 100)}%`

function dateLabel(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })
}

function timeLabel(iso: string) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

function modelRole(model: ModelName) {
  if (model === 'B3_elo') return 'Moneyline incumbent'
  if (model === 'B5_xg_poisson') return 'Expected-goals baseline'
  return 'Experimental score-model challenger'
}

function latestMarketCapture(game: NhlGame) {
  return [...game.markets.sides].sort((a, b) => b.captured_at_utc.localeCompare(a.captured_at_utc))[0]
}

function ProjectionCard({ game, model }: { game: NhlGame; model: ModelName }) {
  const forecast = game.models[model]
  const homePick = forecast.home_win_probability >= 0.5
  const market = latestMarketCapture(game)
  return (
    <article className="py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="font-semibold text-zinc-100">{game.away_team} @ {game.home_team}</h3>
        <span className="text-sm tabular-nums text-zinc-400">{timeLabel(game.scheduled_start_utc)}</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-5">
        <Metric label={game.away_team} value={`${one(forecast.away_expected_goals)} goals`} />
        <Metric label={game.home_team} value={`${one(forecast.home_expected_goals)} goals`} />
        <Metric label="Projected total" value={`${one(forecast.projected_total_goals)} goals`} />
        <Metric label="Model pick" value={`${homePick ? game.home_team : game.away_team} ${pct(homePick ? forecast.home_win_probability : 1 - forecast.home_win_probability)}`} />
        <Metric label="Over 5.5" value={pct(forecast['p_over_5.5'])} />
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-zinc-500">
        <span>Forecast saved {new Date(game.forecasted_at_utc).toLocaleString()}</span>
        {game.markets.usable ? (
          <span>Kalshi quote captured · line comparison available</span>
        ) : (
          <span>Kalshi line unavailable · {market ? `${Math.round((market.spread ?? 0) * 100)}¢ spread at capture` : 'no usable quote'}</span>
        )}
      </div>
    </article>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><div className="text-xs text-zinc-500">{label}</div><div className="mt-0.5 truncate tabular-nums text-sm text-zinc-100">{value}</div></div>
}

function RecordView({ games, model }: { games: NhlGame[]; model: ModelName }) {
  const ordered = [...games].sort((a, b) => b.scheduled_start_utc.localeCompare(a.scheduled_start_utc))
  if (!ordered.length) return <p className="text-sm text-zinc-400">No prospective NHL forecasts have been saved.</p>
  return (
    <section className="space-y-3">
      <div><h2 className="text-lg font-semibold text-zinc-100">2026–27 record · {MODEL_LABELS[model]}</h2><p className="text-sm text-zinc-400">No graded games yet · {ordered.length} forecasts awaiting finals. Results are not collected automatically yet.</p></div>
      <div className="divide-y divide-zinc-800 rounded-2xl bg-zinc-900 px-4">
        {ordered.map(game => {
          const forecast = game.models[model]
          const pickHome = forecast.home_win_probability >= 0.5
          return <article key={game.game_id} className="py-3">
            <div className="flex flex-wrap items-center justify-between gap-3"><div className="font-semibold text-zinc-100">{game.away_team} @ {game.home_team}</div><span className="text-xs text-zinc-500">AWAITING FINAL</span></div>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm tabular-nums text-zinc-400">
              <span>Pick {pickHome ? game.home_team : game.away_team} moneyline</span>
              <span>Win probability {pct(pickHome ? forecast.home_win_probability : 1 - forecast.home_win_probability)}</span>
              <span>Projected {one(forecast.away_expected_goals)}–{one(forecast.home_expected_goals)}</span>
              <span>Final pending</span>
            </div>
          </article>
        })}
      </div>
    </section>
  )
}

interface RatingRow { team: string; elo: number; xgf: number; xga: number }

function TeamRatings({ games }: { games: NhlGame[] }) {
  const rows = useMemo(() => {
    const teams = new Map<string, RatingRow>()
    for (const game of games) {
      const f = game.feature_snapshot
      for (const [side, team] of [['home', game.home_team], ['away', game.away_team]] as const) {
        const xgf = f.xg_features[`${side}_rolling10_5v5_score_venue_xgf`]
        const xga = f.xg_features[`${side}_rolling10_5v5_score_venue_xga`]
        if (xgf == null || xga == null || f.elo_pre_game[side] == null) continue
        teams.set(team, { team, elo: f.elo_pre_game[side], xgf, xga })
      }
    }
    return Array.from(teams.values()).sort((a, b) => b.elo - a.elo)
  }, [games])

  return (
    <section className="space-y-3">
      <div><h2 className="text-lg font-semibold text-zinc-100">Team ratings</h2><p className="text-xs text-zinc-500">Teams with a saved upcoming forecast · Elo and score/venue-adjusted 5-on-5 expected goals per 60 · last 10 games</p></div>
      <div className="overflow-x-auto rounded-2xl bg-zinc-900 px-4">
        <table className="w-full min-w-[540px] text-sm">
          <thead className="text-xs text-zinc-500"><tr className="border-b border-zinc-800 text-left"><th className="py-2 font-medium">Team</th><th className="py-2 text-right font-medium">Elo</th><th className="py-2 text-right font-medium">xGF/60</th><th className="py-2 text-right font-medium">xGA/60</th></tr></thead>
          <tbody className="divide-y divide-zinc-800">{rows.map(row => <tr key={row.team} className="text-zinc-300"><th className="py-2 text-left font-medium text-zinc-100">{row.team}</th><td className="py-2 text-right tabular-nums">{row.elo.toFixed(0)}</td><td className="py-2 text-right tabular-nums">{row.xgf.toFixed(2)}</td><td className="py-2 text-right tabular-nums">{row.xga.toFixed(2)}</td></tr>)}</tbody>
        </table>
      </div>
    </section>
  )
}

export default function NhlModelTab() {
  const [payload, setPayload] = useState<Payload | null>(null)
  const [model, setModel] = useState<ModelName>('B7_elo_xg_poisson')
  const [view, setView] = useState<View>('projections')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch('/data/nhl/prospective-2026-27.json')
      .then(async response => {
        if (!response.ok) throw new Error(`NHL forecasts did not load (HTTP ${response.status}).`)
        return response.json() as Promise<Payload>
      })
      .then(data => { if (!cancelled) { setPayload(data); setModel(data.default_model) } })
      .catch(reason => { if (!cancelled) setError(reason.message) })
    return () => { cancelled = true }
  }, [])

  if (error) return <div className="rounded-2xl bg-zinc-900 px-4 py-3 text-sm text-red-400">{error}</div>
  if (!payload) return <div className="h-40 animate-pulse rounded-2xl bg-zinc-800" />

  const games = [...payload.games].sort((a, b) => a.scheduled_start_utc.localeCompare(b.scheduled_start_utc))
  const groups = games.reduce<Record<string, NhlGame[]>>((result, game) => {
    const label = dateLabel(game.scheduled_start_utc)
    result[label] = [...(result[label] || []), game]
    return result
  }, {})
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <nav className="flex gap-1 rounded-full bg-zinc-900 p-1" aria-label="NHL model views">
          {([['projections', 'Projections'], ['record', 'Record'], ['ratings', 'Team Ratings']] as [View, string][]).map(([key, label]) => <button key={key} type="button" onClick={() => setView(key)} aria-current={view === key ? 'page' : undefined} className={`rounded-full px-3 py-1.5 text-sm ${view === key ? 'bg-zinc-100 text-zinc-900' : 'text-zinc-400 hover:text-zinc-100'}`}>{label}</button>)}
        </nav>
        <label className="flex items-center gap-2 text-sm text-zinc-500">Model <select value={model} onChange={event => setModel(event.target.value as ModelName)} className="rounded-lg bg-zinc-900 px-3 py-2 text-zinc-100">{(Object.keys(MODEL_LABELS) as ModelName[]).map(key => <option key={key} value={key}>{MODEL_LABELS[key]}</option>)}</select></label>
      </div>

      {view === 'projections' && <>
        <div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-lg font-semibold text-zinc-100">2026–27 projections · {MODEL_LABELS[model]}</h2><p className="text-xs text-zinc-500">{modelRole(model)} · {games.length} saved games · frozen {new Date(payload.frozen_at_utc).toLocaleDateString()} · forecasts are not collected automatically yet</p></div>{model === 'B7_elo_xg_poisson' && <span className="rounded-full bg-amber-500/10 px-2.5 py-1 text-xs text-amber-300">Experimental</span>}</div>
        {games.length === 0 ? <p className="text-sm text-zinc-400">No prospective NHL forecasts have been saved.</p> : Object.entries(groups).map(([day, entries]) => <section key={day} className="space-y-1"><h3 className="text-sm font-medium text-zinc-400">{day}</h3><div className="divide-y divide-zinc-800 rounded-2xl bg-zinc-900 px-4">{entries.map(game => <ProjectionCard key={game.game_id} game={game} model={model} />)}</div></section>)}
      </>}
      {view === 'record' && <RecordView games={games} model={model} />}
      {view === 'ratings' && <TeamRatings games={games} />}
      <p className="text-xs text-zinc-500">Win probability includes overtime and shootouts. Goal projections exclude the shootout-deciding goal. Regulation win probability is not available in this model version.</p>
    </div>
  )
}
