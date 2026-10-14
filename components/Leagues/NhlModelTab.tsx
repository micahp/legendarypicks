import { useEffect, useMemo, useState } from 'react'
import ModelSelect from './ModelSelect'

type View = 'projections' | 'record' | 'ratings'
type ModelName = 'B3_elo' | 'B5_xg_poisson' | 'B7_elo_xg_poisson'

interface Forecast {
  forecast_id: string
  model_version?: string
  locked_at_utc?: string
  home_expected_goals: number
  away_expected_goals: number
  projected_total_goals: number
  projected_goal_differential_home: number
  home_win_probability: number
  'p_over_5.5': number
  'p_over_6.5': number
  grade?: {
    official_home_goals: number
    official_away_goals: number
    statistical_home_goals: number
    statistical_away_goals: number
    official_winner: 'home' | 'away'
    shootout_decided: boolean
    home_win_brier: number
    home_win_logloss: number
    home_goal_error: number
    away_goal_error: number
    graded_at_utc: string
  } | null
}

interface NhlGame {
  game_id: number
  game_date: string
  scheduled_start_utc: string
  home_team: string
  away_team: string
  forecasted_at_utc: string
  locked_at_utc: string
  feature_snapshot: {
    elo_pre_game: { home: number; away: number }
    xg_features: Record<string, number>
  }
  models: Record<ModelName, Forecast>
  result: Forecast['grade']
  markets: {
    source: string
    usable: boolean
    comparison_usable_at_lock?: boolean
    sides: { team: string; captured_at_utc: string; spread: number | null; quote_quality: string }[]
  }
}

interface Payload {
  model_version: string
  model_versions?: Partial<Record<ModelName, string>>
  default_model: ModelName
  frozen_at_utc: string | null
  source: string
  state?: 'available' | 'awaiting_first_lock' | 'missed_locks'
  games: NhlGame[]
  previews?: NhlPreview[]
  lines?: Record<string, BovadaLine>
  standings?: Record<string, NhlStanding>
  missed_locks?: { game_id: string; home_team: string; away_team: string; model_key: ModelName; model_version: string; observed_at_utc: string; scheduled_start_utc: string }[]
}

interface NhlStanding {
  games_played: number
  wins: number
  losses: number
  overtime_losses: number
  points: number
  standings_date: string
}

interface BovadaLine {
  home_team: string
  away_team: string
  captured_at_utc: string
  home_puck_line: number | null
  total_line: number | null
  home_moneyline: number | null
  away_moneyline: number | null
  over_price: number | null
  under_price: number | null
}

interface NhlPreview {
  game_id: number
  game_date: string
  scheduled_start_utc: string
  home_team: string
  away_team: string
  models: Record<ModelName, Forecast & { forecasted_at_utc: string; previewed_at_utc: string; preview: true }>
}

const MODEL_LABELS: Record<ModelName, string> = {
  B3_elo: 'Elo',
  B5_xg_poisson: 'xG Poisson',
  B7_elo_xg_poisson: 'Elo + xG',
}

const one = (value: number) => value.toFixed(1)
const pct = (value: number) => `${Math.round(value * 100)}%`
const signed = (value: number) => `${value > 0 ? '+' : ''}${one(value)}`

function dateLabel(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })
}

function timeLabel(iso: string) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

function recordLine(standings: Payload['standings'], team: string) {
  const row = standings?.[team]
  return row ? `${row.wins}-${row.losses}-${row.overtime_losses} · ${row.points} pts` : undefined
}

function cardLines(home: string, away: string, forecast: Forecast, line?: BovadaLine) {
  const margin = forecast.projected_goal_differential_home
  const homeLine = line?.home_puck_line ?? null
  const vegas = homeLine == null ? 'n/a' : homeLine < 0 ? `${home} ${signed(homeLine)}` : `${away} ${signed(-homeLine)}`
  return [
    { label: 'Vegas line', value: vegas },
    { label: 'Model line', value: margin > 0 ? `${home} ${signed(-margin)}` : `${away} ${signed(margin)}` },
    { label: 'Edge', value: homeLine == null ? 'n/a' : `${signed(-homeLine - margin)} pts` },
  ]
}

function impliedProbability(price: number) {
  return price < 0 ? -price / (-price + 100) : 100 / (price + 100)
}

function noVigPair(first: number, second: number) {
  const a = impliedProbability(first)
  const b = impliedProbability(second)
  return [a / (a + b), b / (a + b)]
}

// Candidates are the moneyline sides and Over/Under at the 5.5 and 6.5 lines, the only totals the model prices.
// The pick is the candidate with the largest model probability minus the no-vig Bovada probability.
function modelPick(home: string, away: string, forecast: Forecast, line?: BovadaLine): { label: string; edge: number } | null {
  const candidates: { label: string; edge: number }[] = []
  if (line?.home_moneyline != null && line.away_moneyline != null) {
    const [homeMarket, awayMarket] = noVigPair(line.home_moneyline, line.away_moneyline)
    candidates.push({ label: `${home} ML`, edge: forecast.home_win_probability - homeMarket })
    candidates.push({ label: `${away} ML`, edge: 1 - forecast.home_win_probability - awayMarket })
  }
  const total = line?.total_line
  const overModel = total === 5.5 ? forecast['p_over_5.5'] : total === 6.5 ? forecast['p_over_6.5'] : null
  if (total != null && overModel != null && line?.over_price != null && line.under_price != null) {
    const [overMarket, underMarket] = noVigPair(line.over_price, line.under_price)
    candidates.push({ label: `Over ${one(total)}`, edge: overModel - overMarket })
    candidates.push({ label: `Under ${one(total)}`, edge: 1 - overModel - underMarket })
  }
  if (!candidates.length) return null
  return candidates.reduce((best, candidate) => (candidate.edge > best.edge ? candidate : best))
}

function totalLines(forecast: Forecast, line?: BovadaLine) {
  const vegas = line?.total_line ?? null
  return [
    { label: 'Vegas total', value: vegas == null ? 'n/a' : one(vegas) },
    { label: 'Model total', value: one(forecast.projected_total_goals) },
    { label: 'Edge', value: vegas == null ? 'n/a' : `${signed(forecast.projected_total_goals - vegas)} pts` },
  ]
}

function ProjectionCardView({ away, home, startUtc, forecast, status, lines, totals, pick, awayRecord, homeRecord }: {
  away: string
  home: string
  startUtc: string
  forecast: Forecast
  status: string | null
  lines: { label: string; value: string }[]
  totals: { label: string; value: string }[]
  pick: { label: string; edge: number } | null
  awayRecord?: string
  homeRecord?: string
}) {
  return (
    <article className="space-y-2 rounded-2xl border border-zinc-800 bg-zinc-900 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="font-semibold text-zinc-100">{away} @ {home}</h3>
        <span className="flex items-center gap-3">
          {status && <span className="rounded-full border border-current px-2.5 py-0.5 text-xs font-semibold tracking-wide text-emerald-400">{status}</span>}
          <span className="text-sm tabular-nums text-zinc-400">{timeLabel(startUtc)}</span>
        </span>
      </div>
      <div className="grid grid-cols-[1fr_auto] items-baseline gap-x-6 gap-y-1 text-sm tabular-nums">
        <span className="text-zinc-200">{away}{awayRecord && <span className="block text-xs text-zinc-500">{awayRecord}</span>}</span>
        <span className="text-right text-2xl font-semibold text-zinc-100">{one(forecast.away_expected_goals)}</span>
        <span className="text-zinc-200">{home}{homeRecord && <span className="block text-xs text-zinc-500">{homeRecord}</span>}</span>
        <span className="text-right text-2xl font-semibold text-zinc-100">{one(forecast.home_expected_goals)}</span>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-t border-zinc-800 pt-2 text-sm text-zinc-400">
        <div className="flex flex-wrap gap-x-6 gap-y-1">
          {lines.map(line => <span key={line.label}>{line.label} <b className="font-medium tabular-nums text-zinc-100">{line.value}</b></span>)}
        </div>
        <div className="text-right">
          <span className="block text-xs uppercase tracking-wider text-zinc-500">Model pick</span>
          <span className="block text-xl font-semibold text-zinc-100">{pick ? pick.label : 'n/a'}</span>
          {pick && <span className="block text-xs tabular-nums text-zinc-400">{signed(pick.edge * 100)}% edge</span>}
        </div>
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-zinc-400">
        {totals.map(line => <span key={line.label}>{line.label} <b className="font-medium tabular-nums text-zinc-100">{line.value}</b></span>)}
      </div>
    </article>
  )
}

function ProjectionCard({ game, model, line, standings }: { game: NhlGame; model: ModelName; line?: BovadaLine; standings?: Payload['standings'] }) {
  const forecast = game.models[model]
  return (
    <ProjectionCardView away={game.away_team} home={game.home_team} startUtc={game.scheduled_start_utc} forecast={forecast} status="LOCKED" awayRecord={recordLine(standings, game.away_team)} homeRecord={recordLine(standings, game.home_team)}
      lines={cardLines(game.home_team, game.away_team, forecast, line)} totals={totalLines(forecast, line)} pick={modelPick(game.home_team, game.away_team, forecast, line)} />
  )
}

function PreviewCard({ game, model, line, standings }: { game: NhlPreview; model: ModelName; line?: BovadaLine; standings?: Payload['standings'] }) {
  const forecast = game.models[model]
  return (
    <ProjectionCardView away={game.away_team} home={game.home_team} startUtc={game.scheduled_start_utc} forecast={forecast} status={null} awayRecord={recordLine(standings, game.away_team)} homeRecord={recordLine(standings, game.home_team)}
      lines={cardLines(game.home_team, game.away_team, forecast, line)} totals={totalLines(forecast, line)} pick={modelPick(game.home_team, game.away_team, forecast, line)} />
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><div className="text-xs text-zinc-500">{label}</div><div className="mt-0.5 truncate tabular-nums text-sm text-zinc-100">{value}</div></div>
}

function RecordProjection({ game, model }: { game: NhlGame; model: ModelName }) {
  const forecast = game.models[model]
  const grade = forecast.grade
  const pickHome = forecast.home_win_probability >= 0.5
  const pickWon = grade ? (pickHome ? grade.official_winner === 'home' : grade.official_winner === 'away') : null
  return (
    <article className="py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="font-semibold text-zinc-100">{game.away_team} @ {game.home_team}</h3>
        <span className="text-sm tabular-nums text-zinc-400">{dateLabel(game.scheduled_start_utc)}</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-5">
        <Metric label="Model pick" value={`${pickHome ? game.home_team : game.away_team} ${pct(pickHome ? forecast.home_win_probability : 1 - forecast.home_win_probability)}`} />
        <Metric label="Projected" value={`${one(forecast.away_expected_goals)}–${one(forecast.home_expected_goals)}`} />
        <Metric label="Final" value={grade ? `${grade.official_away_goals}–${grade.official_home_goals}` : 'Pending'} />
        <Metric label="Winner" value={grade ? `${grade.official_winner === 'home' ? game.home_team : game.away_team}${grade.shootout_decided ? ' · SO' : ''}` : 'Awaiting final'} />
        <div className="min-w-0">
          <div className="text-xs text-zinc-500">Result</div>
          <div className={`mt-0.5 truncate text-sm tabular-nums ${pickWon ? 'text-emerald-400' : 'text-red-400'}`}>{pickWon == null ? 'Pending' : pickWon ? 'Pick ✓' : 'Pick ✗'}</div>
        </div>
      </div>
      <div className="mt-3 text-xs text-zinc-500">Locked {new Date(forecast.locked_at_utc || game.locked_at_utc).toLocaleString()}</div>
    </article>
  )
}

function RecordView({ games, model, missedLocks }: { games: NhlGame[]; model: ModelName; missedLocks: NonNullable<Payload['missed_locks']> }) {
  const ordered = games.filter(game => game.models[model].grade).sort((a, b) => b.scheduled_start_utc.localeCompare(a.scheduled_start_utc))
  const missed = missedLocks.filter(row => row.model_key === model)
  if (!ordered.length && !missed.length) return <p className="text-sm text-zinc-400">No graded NHL projections yet.</p>
  return (
    <section className="space-y-3">
      <div><h2 className="text-lg font-semibold text-zinc-100">2026–27 record · {MODEL_LABELS[model]}</h2><p className="text-sm text-zinc-400">Per-model forecasts lock 90 minutes before puck drop and grade from official NHL results.</p></div>
      {ordered.length > 0 && <div className="divide-y divide-zinc-800 rounded-2xl bg-zinc-900 px-4">
        {ordered.map(game => <RecordProjection key={game.game_id} game={game} model={model} />)}
      </div>}
      {missed.length > 0 && <section className="space-y-2"><h3 className="text-sm font-medium text-zinc-400">Missed lock window</h3><div className="divide-y divide-zinc-800 rounded-2xl bg-zinc-900 px-4">{missed.map(row => <article key={`${row.game_id}-${row.model_version}`} className="flex flex-wrap justify-between gap-2 py-3 text-sm"><span className="font-medium text-zinc-200">{row.away_team} @ {row.home_team}</span><span className="text-zinc-500">No forecast locked · {new Date(row.scheduled_start_utc).toLocaleString()}</span></article>)}</div></section>}
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
    const loadLocks = (first: boolean) => fetch('/api/nhl/model/locks?season=2026')
      .then(async response => {
        if (!response.ok) throw new Error(`NHL forecasts did not load (HTTP ${response.status}).`)
        return response.json() as Promise<Payload>
      })
      .then(data => { if (!cancelled) { setPayload(data); if (first) setModel(data.default_model) } })
      .catch(reason => { if (!cancelled) setError(reason.message) })
    loadLocks(true)
    fetch('/api/nhl/model/lines/refresh', { method: 'POST' })
      .then(async response => (response.ok ? response.json() : null))
      .then(result => { if (!cancelled && result?.refreshed) loadLocks(false) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  if (error) return <div className="rounded-2xl bg-zinc-900 px-4 py-3 text-sm text-red-400">{error}</div>
  if (!payload) return <div className="h-40 animate-pulse rounded-2xl bg-zinc-800" />

  const games = [...payload.games].sort((a, b) => a.scheduled_start_utc.localeCompare(b.scheduled_start_utc))
  const previews = [...(payload.previews || [])].sort((a, b) => a.scheduled_start_utc.localeCompare(b.scheduled_start_utc))
  const items = [
    ...games.map(game => ({ start: game.scheduled_start_utc, node: <ProjectionCard key={`locked-${game.game_id}`} game={game} model={model} line={payload.lines?.[String(game.game_id)]} standings={payload.standings} /> })),
    ...previews.map(game => ({ start: game.scheduled_start_utc, node: <PreviewCard key={`preview-${game.game_id}`} game={game} model={model} line={payload.lines?.[String(game.game_id)]} standings={payload.standings} /> })),
  ].sort((a, b) => a.start.localeCompare(b.start))
  const groups = items.reduce<Record<string, typeof items>>((result, item) => {
    const label = dateLabel(item.start)
    result[label] = [...(result[label] || []), item]
    return result
  }, {})
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <nav className="flex gap-1 rounded-full bg-zinc-900 p-1" aria-label="NHL model views">
          {([['projections', 'Projections'], ['record', 'Record'], ['ratings', 'Team Ratings']] as [View, string][]).map(([key, label]) => <button key={key} type="button" onClick={() => setView(key)} aria-current={view === key ? 'page' : undefined} className={`rounded-full px-3 py-1.5 text-sm ${view === key ? 'bg-zinc-100 text-zinc-900' : 'text-zinc-400 hover:text-zinc-100'}`}>{label}</button>)}
        </nav>
        <label className="flex items-center gap-2 text-sm text-zinc-500">Model <ModelSelect value={model} onChange={event => setModel(event.target.value as ModelName)}>{(Object.keys(MODEL_LABELS) as ModelName[]).map(key => <option key={key} value={key}>{MODEL_LABELS[key]}</option>)}</ModelSelect></label>
      </div>

      {view === 'projections' && <>
        <div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-lg font-semibold text-zinc-100" title="Models lock 90 mins before kickoff">2026–27 projections · {MODEL_LABELS[model]}</h2></div>{model === 'B7_elo_xg_poisson' && <span className="rounded-full bg-amber-500/10 px-2.5 py-1 text-xs text-amber-300">Experimental</span>}</div>
        {items.length === 0 ? <p className="text-sm text-zinc-400">{payload.state === 'missed_locks' ? 'No forecasts were locked for games that missed the T−90 window. Check the Record tab for details.' : 'No NHL projections have reached their T−90 lock time yet.'}</p> : Object.entries(groups).map(([day, entries]) => <section key={day} className="space-y-2"><h3 className="text-sm font-medium text-zinc-400">{day}</h3><div className="grid gap-3 sm:grid-cols-2">{entries.map(item => item.node)}</div></section>)}
      </>}
      {view === 'record' && <RecordView games={games} model={model} missedLocks={payload.missed_locks || []} />}
      {view === 'ratings' && <TeamRatings games={games} />}
      <p className="text-xs text-zinc-500">Win probability includes overtime and shootouts. Goal projections exclude the shootout-deciding goal. Regulation win probability is not available in this model version.</p>
    </div>
  )
}
