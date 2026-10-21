import { useEffect, useMemo, useState } from 'react'
import ModelSelect from './ModelSelect'

type View = 'projections' | 'record' | 'ratings'
type ModelName = 'B3_elo' | 'B5_xg_poisson' | 'B7_elo_xg_poisson'

interface Forecast {
  forecast_id: string
  model_version?: string
  locked_at_utc?: string
  home_expected_goals: number | null
  away_expected_goals: number | null
  projected_total_goals: number | null
  projected_goal_differential_home: number | null
  home_win_probability: number | null
  'p_over_5.5': number | null
  'p_over_6.5': number | null
  p_home_minus_1_5: number
  p_home_plus_1_5: number
  p_away_minus_1_5: number
  p_away_plus_1_5: number
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
  line_grades?: {
    version: string
    reference: Record<string, { probability: number; outcome: number; brier: number }>
    locked_market: Record<string, { brier?: number; market_brier?: number; graded?: boolean; line?: number }>
  } | null
  /** Frozen at lock time by the backend and read straight from the payload. The browser
   *  never computes a pick, so the card and the record cannot disagree. */
  pick?: ModelPick | null
  pick_status?: 'selected' | 'missing'
  locked_quote?: BovadaLine | null
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

interface ModelPick {
  market: 'ml' | 'spread' | 'total'
  side: 'home' | 'away' | 'over' | 'under'
  line: number | null
  model_probability: number | null
  push_probability?: number
  line_captured_at_utc: string | null
  settlement_basis: string
  rule_version?: string
  /** The market quote captured at lock time. */
  quote?: BovadaLine | null
  selected_at_utc?: string
  provenance?: 'lock' | 'backfill' | 'preview'
  result: { won: boolean | null; push?: boolean; settlement?: "won" | "lost" | "push" } | null
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
  home_puck_price: number | null
  away_puck_price: number | null
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

const one = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? 'n/a' : value.toFixed(1)
const pct = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? 'n/a' : `${Math.round(value * 100)}%`
const signed = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? 'n/a' : `${value > 0 ? '+' : ''}${one(value)}`

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

function spreadLabel(home: string, away: string, homePuckLine: number | null | undefined) {
  if (homePuckLine == null) return 'n/a'
  return homePuckLine < 0 ? `${home} ${signed(homePuckLine)}` : `${away} ${signed(-homePuckLine)}`
}

/** The three market rows for one quote. Pick-time labels distinguish frozen lines from live ones. */
function marketLines(home: string, away: string, forecast: Forecast, quote: BovadaLine | null | undefined, locked: boolean) {
  const margin = forecast.projected_goal_differential_home
  const homeLine = quote?.home_puck_line ?? null
  const modelLine = margin == null ? 'n/a' : margin > 0 ? `${home} ${signed(-margin)}` : `${away} ${signed(margin)}`
  return [
    { label: locked ? 'Pick-time puck line' : 'Puck line', value: spreadLabel(home, away, homeLine) },
    { label: 'Model line', value: modelLine },
    { label: 'Δ', value: homeLine == null || margin == null ? 'n/a' : `${one(Math.abs(-homeLine - margin))} goals (${margin + homeLine > 0 ? home : away})` },
  ]
}

function marketTotals(forecast: Forecast, quote: BovadaLine | null | undefined, locked: boolean) {
  const vegas = quote?.total_line ?? null
  return [
    { label: locked ? 'Pick-time total' : 'Vegas total', value: vegas == null ? 'n/a' : one(vegas) },
    { label: 'Model total', value: one(forecast.projected_total_goals) },
    { label: 'Δ', value: vegas == null || forecast.projected_total_goals == null ? 'n/a' : `${signed(forecast.projected_total_goals - vegas)} goals` },
  ]
}

// The pick rule lives in the backend (backend/nhl_model_store.py, model_pick) and is frozen
// at lock time. This renders the stored recommendation; it never recomputes one from a
// later line, so the card and the record cannot disagree.
function pickLabel(pick: ModelPick, home: string, away: string) {
  if (pick.market === 'ml') return `${pick.side === 'home' ? home : away} ML`
  if (pick.market === 'spread') return `${pick.side === 'home' ? home : away} ${signed(pick.line ?? 0)}`
  return `${pick.side === 'over' ? 'Over' : 'Under'} ${one(pick.line ?? 0)}`
}

function pickResultLabel(pick: ModelPick | null, graded: boolean) {
  if (!pick) return 'Missing'
  if (!graded) return 'Pending'
  if (pick.result?.push) return 'Push'
  if (pick.result?.won === true) return 'Win'
  if (pick.result?.won === false) return 'Loss'
  return 'Missing'
}

function ProjectionCardView({ away, home, startUtc, forecast, live, awayRecord, homeRecord, preview = false }: {
  away: string
  home: string
  startUtc: string
  forecast: Forecast
  live?: BovadaLine
  awayRecord?: string
  homeRecord?: string
  preview?: boolean
}) {
  const grade = forecast.grade
  const isGraded = grade != null
  const pick = forecast.pick ?? null
  const edgeClass = isGraded ? 'graded-edge' : ''
  // A locked card never falls back to today's line if the archived lock quote is absent.
  const frozen = forecast.locked_quote ?? pick?.quote ?? null
  const basis = preview ? live ?? null : frozen
  const locked = !preview
  const lines = marketLines(home, away, forecast, basis, locked)
  const totals = marketTotals(forecast, basis, locked)
  const moved = locked && frozen != null && live != null &&
    (live.home_puck_line !== frozen.home_puck_line || live.total_line !== frozen.total_line)

  return (
    <article className={`space-y-2 rounded-2xl border border-zinc-800 bg-zinc-900 p-4 ${edgeClass}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="font-semibold text-zinc-100">{away} @ {home}</h3>
        <span className="flex items-center gap-3">
          <span className="text-sm tabular-nums text-zinc-400">{timeLabel(startUtc)}</span>
        </span>
      </div>
      <div className="grid grid-cols-[1fr_auto] items-baseline gap-x-6 gap-y-1 text-sm tabular-nums">
        <span className="text-zinc-200">{away}{awayRecord && <span className="block text-xs text-zinc-500">{awayRecord}</span>}</span>
        <span className="text-right text-2xl font-semibold text-zinc-100">{one(forecast.away_expected_goals)}</span>
        <span className="text-zinc-200">{home}{homeRecord && <span className="block text-xs text-zinc-500">{homeRecord}</span>}</span>
        <span className="text-right text-2xl font-semibold text-zinc-100">{one(forecast.home_expected_goals)}</span>
      </div>
      <div className="flex flex-wrap items-end gap-x-12 gap-y-2 border-t border-zinc-800 pt-2 text-sm text-zinc-400">
        <div className="flex flex-wrap gap-x-6 gap-y-1">
          {lines.map(line => <span key={line.label}>{line.label} <b className="font-medium tabular-nums text-zinc-100">{line.value}</b></span>)}
        </div>
        <div className="flex flex-wrap gap-x-6 gap-y-1">
          {totals.map(line => <span key={line.label}>{line.label} <b className="font-medium tabular-nums text-zinc-100">{line.value}</b></span>)}
        </div>
      </div>
      <div className="text-right">
        <span className="block text-xs uppercase tracking-wider text-zinc-500">Model Pick</span>
        <span className="block text-xl font-semibold text-zinc-100">{pick ? pickLabel(pick, home, away) : 'Missing'}</span>
        {pick?.model_probability != null && <span className="block text-xs tabular-nums text-zinc-400">{pct(pick.model_probability)} model probability</span>}
      </div>
      {moved ? (
        <p className="border-t border-zinc-800 pt-2 text-xs text-zinc-500">
          Market has moved since this pick was frozen: now {spreadLabel(home, away, live?.home_puck_line)}
          {live?.total_line == null ? '' : ` · total ${one(live.total_line)}`}. The pick above uses
          the pick-time line.
        </p>
      ) : null}
    </article>
  )
}

function ProjectionCard({ game, model, line, standings }: { game: NhlGame; model: ModelName; line?: BovadaLine; standings?: Payload['standings'] }) {
  const forecast = game.models[model]
  return <ProjectionCardView away={game.away_team} home={game.home_team} startUtc={game.scheduled_start_utc} forecast={forecast} live={line} awayRecord={recordLine(standings, game.away_team)} homeRecord={recordLine(standings, game.home_team)} />
}

function PreviewCard({ game, model, line, standings }: { game: NhlPreview; model: ModelName; line?: BovadaLine; standings?: Payload['standings'] }) {
  const forecast = game.models[model]
  return <ProjectionCardView away={game.away_team} home={game.home_team} startUtc={game.scheduled_start_utc} forecast={forecast} preview live={line} awayRecord={recordLine(standings, game.away_team)} homeRecord={recordLine(standings, game.home_team)} />
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><div className="text-xs text-zinc-500">{label}</div><div className="mt-0.5 truncate tabular-nums text-sm text-zinc-100">{value}</div></div>
}

function RecordProjection({ game, model }: { game: NhlGame; model: ModelName }) {
  const forecast = game.models[model]
  const grade = forecast.grade
  const pick = forecast.pick ?? null
  const result = pickResultLabel(pick, grade != null)
  const resultClass = result === 'Win' ? 'text-emerald-400'
    : result === 'Loss' ? 'text-red-400' : 'text-zinc-400'
  return (
    <article className="py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="font-semibold text-zinc-100">{game.away_team} @ {game.home_team}</h3>
        <span className="text-sm tabular-nums text-zinc-400">{dateLabel(game.scheduled_start_utc)}</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-5">
        <Metric label="Model Pick" value={pick ? `${pickLabel(pick, game.home_team, game.away_team)}${pick.model_probability == null ? '' : ` ${pct(pick.model_probability)}`}` : 'Missing'} />
        <Metric label="Projected" value={`${one(forecast.away_expected_goals)}–${one(forecast.home_expected_goals)}`} />
        <Metric label="Final" value={grade ? `${grade.official_away_goals}–${grade.official_home_goals}` : 'Pending'} />
        <Metric label="Winner" value={grade ? `${grade.official_winner === 'home' ? game.home_team : game.away_team}${grade.shootout_decided ? ' · SO' : ''}` : 'Awaiting final'} />
        <div className="min-w-0">
          <div className="text-xs text-zinc-500">Result</div>
          <div className={`mt-0.5 truncate text-sm tabular-nums ${resultClass}`}>{result}</div>
        </div>
      </div>
      <div className="mt-3 text-xs text-zinc-500">
        Locked {new Date(forecast.locked_at_utc || game.locked_at_utc).toLocaleString()}
        {pick?.line_captured_at_utc ? ` · line captured ${new Date(pick.line_captured_at_utc).toLocaleString()}` : ''}
      </div>
    </article>
  )
}

type GradedForecast = NonNullable<Forecast['grade']>

function modelPerformance(games: NhlGame[], model: ModelName) {
  // Include every graded forecast, even when its frozen selection is missing.
  const grades = games
    .map(game => game.models[model]?.grade)
    .filter((grade): grade is GradedForecast => grade != null)
  const count = grades.length
  const average = (value: (grade: GradedForecast) => number) =>
    count ? grades.reduce((sum, grade) => sum + value(grade), 0) / count : null

  return {
    count,
    brier: average(grade => grade.home_win_brier),
    logLoss: average(grade => grade.home_win_logloss),
    goalMae: average(grade => (Math.abs(grade.home_goal_error) + Math.abs(grade.away_goal_error)) / 2),
  }
}

type LineMetric = 'home_minus_1_5' | 'away_minus_1_5' | 'over_5_5' | 'over_6_5'
const LINE_METRICS: { key: LineMetric; label: string }[] = [
  { key: 'home_minus_1_5', label: 'Home −1.5' },
  { key: 'away_minus_1_5', label: 'Away −1.5' },
  { key: 'over_5_5', label: 'Over 5.5' },
  { key: 'over_6_5', label: 'Over 6.5' },
]

function linePerformance(games: NhlGame[], model: ModelName, key: LineMetric) {
  const results = games.map(game => game.models[model]?.line_grades?.reference?.[key])
    .filter((result): result is { probability: number; outcome: number; brier: number } =>
      result != null && Number.isFinite(result.brier))
  return { n: results.length, brier: results.length
    ? results.reduce((sum, result) => sum + result.brier, 0) / results.length : null }
}

function frozenLinePerformance(games: NhlGame[], model: ModelName, key: string) {
  const values = games.map(game => game.models[model]?.line_grades?.locked_market?.[key])
    .filter((value): value is { brier: number; market_brier: number } =>
      value != null && Number.isFinite(value.brier) && Number.isFinite(value.market_brier))
  const average = (field: 'brier' | 'market_brier') => values.length
    ? values.reduce((sum, value) => sum + value[field], 0) / values.length : null
  return { n: values.length, modelBrier: average('brier'), marketBrier: average('market_brier') }
}

const MODEL_ORDER: ModelName[] = ['B3_elo', 'B5_xg_poisson', 'B7_elo_xg_poisson']

function ModelPerformanceSummary({ games, selectedModel }: { games: NhlGame[]; selectedModel: ModelName }) {
  const score = (value: number | null, decimals: number) => value == null ? '—' : value.toFixed(decimals)

  return (
    <section aria-label="2026–27 prospective model performance" className="rounded-xl border border-zinc-700 bg-zinc-900 p-4 shadow-2xl">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-zinc-100">Model accuracy</h3>
        <p className="mt-1 text-xs text-zinc-400">2026–27 live · all graded forecasts · same metrics for every model</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[450px] text-sm tabular-nums">
          <thead className="border-b border-zinc-700 text-xs text-zinc-500">
            <tr>
              <th className="px-2 py-2 text-left font-medium">Model</th>
              <th className="px-2 py-2 text-right font-medium">Brier ↓</th>
              <th className="px-2 py-2 text-right font-medium">Log loss ↓</th>
              <th className="px-2 py-2 text-right font-medium">Goal MAE ↓</th>
              <th className="px-2 py-2 text-right font-medium">Games</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {MODEL_ORDER.map(key => {
              const result = modelPerformance(games, key)
              return (
                <tr key={key} className={key === selectedModel ? 'bg-zinc-800/70' : ''}>
                  <th scope="row" className="px-2 py-3 text-left font-medium text-zinc-200">
                    {MODEL_LABELS[key]}{key === selectedModel ? <span className="ml-1 text-xs text-emerald-400">· Selected</span> : null}
                  </th>
                  <td className="px-2 py-3 text-right font-semibold text-zinc-100">{score(result.brier, 4)}</td>
                  <td className="px-2 py-3 text-right text-zinc-300">{score(result.logLoss, 4)}</td>
                  <td className="px-2 py-3 text-right text-zinc-300">{score(result.goalMae, 3)}</td>
                  <td className="px-2 py-3 text-right text-zinc-300">{result.count}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="mt-4 border-t border-zinc-700 pt-3">
        <h4 className="text-sm font-semibold text-zinc-100">Game lines · Brier scores</h4>
        <p className="mt-1 text-xs text-zinc-400">Fixed reference thresholds, graded for every completed forecast.</p>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[450px] text-xs tabular-nums">
            <thead className="text-zinc-500"><tr className="border-b border-zinc-700">
              <th className="px-2 py-2 text-left font-medium">Market</th>
              {MODEL_ORDER.map(key => <th key={key} className="px-2 py-2 text-right font-medium">{MODEL_LABELS[key]}</th>)}
            </tr></thead>
            <tbody className="divide-y divide-zinc-800">
              {LINE_METRICS.map(line => <tr key={line.key}>
                <th scope="row" className="px-2 py-2 text-left font-medium text-zinc-300">{line.label}</th>
                {MODEL_ORDER.map(key => {
                  const value = linePerformance(games, key, line.key)
                  return <td key={key} className="px-2 py-2 text-right text-zinc-200">
                    {score(value.brier, 4)} <span className="text-zinc-500">({value.n})</span>
                  </td>
                })}
              </tr>)}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-zinc-500">Fixed totals use regulation and OT goals, excluding shootout-deciding goals. The ±1.5 lines grade official final margins.</p>
        <h4 className="mt-4 text-xs font-semibold text-zinc-200">Archived market comparison</h4>
        <p className="mt-1 text-xs text-zinc-500">Model vs no-vig market Brier on games with a complete archived quote. Totals with pushes are excluded.</p>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[450px] text-xs tabular-nums">
            <thead className="text-zinc-500"><tr className="border-b border-zinc-700">
              <th className="px-2 py-2 text-left font-medium">Model / market</th>
              <th className="px-2 py-2 text-right font-medium">Model Brier</th>
              <th className="px-2 py-2 text-right font-medium">Market Brier</th>
              <th className="px-2 py-2 text-right font-medium">Games</th>
            </tr></thead>
            <tbody className="divide-y divide-zinc-800">
              {MODEL_ORDER.flatMap(key => [
                { key: 'puck_home_cover', label: 'Puck line' },
                { key: 'total_over', label: 'Game total' },
              ].map(market => {
                const value = frozenLinePerformance(games, key, market.key)
                return <tr key={key + market.key}>
                  <th scope="row" className="px-2 py-2 text-left font-medium text-zinc-300">{MODEL_LABELS[key]} · {market.label}</th>
                  <td className="px-2 py-2 text-right">{score(value.modelBrier, 4)}</td>
                  <td className="px-2 py-2 text-right">{score(value.marketBrier, 4)}</td>
                  <td className="px-2 py-2 text-right">{value.n}</td>
                </tr>
              }))}
            </tbody>
          </table>
        </div>
      </div>
      <p className="mt-3 text-xs leading-relaxed text-zinc-500">
        Lower Brier is better. 0 is perfect; 0.2500 is a constant 50% forecast. All eligible graded games count.
      </p>
    </section>
  )
}

function RecordView({ games, model, missedLocks }: { games: NhlGame[]; model: ModelName; missedLocks: NonNullable<Payload['missed_locks']> }) {
  const ordered = games.filter(game => game.models[model] != null).sort((a, b) => b.scheduled_start_utc.localeCompare(a.scheduled_start_utc))
  const missed = missedLocks.filter(row => row.model_key === model)
  if (!ordered.length && !missed.length) return <p className="text-sm text-zinc-400">No locked NHL model picks yet.</p>
  return (
    <section className="space-y-3">
      <div><h2 className="text-lg font-semibold text-zinc-100">2026–27 record · {MODEL_LABELS[model]}</h2><p className="text-sm text-zinc-400">Frozen picks grade from official NHL results. Unfinished games remain pending.</p></div>
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
      <div><h2 className="text-lg font-semibold text-zinc-100">Team ratings</h2><p className="text-xs text-zinc-500">Teams with a saved upcoming forecast · Elo and score/venue-adjusted 5-on-5 expected goals per game · last 10 games</p></div>
      <div className="overflow-x-auto rounded-2xl bg-zinc-900 px-4">
        <table className="w-full min-w-[540px] text-sm">
          <thead className="text-xs text-zinc-500"><tr className="border-b border-zinc-800 text-left"><th className="py-2 font-medium">Team</th><th className="py-2 text-right font-medium">Elo</th><th className="py-2 text-right font-medium">xGF/gm</th><th className="py-2 text-right font-medium">xGA/gm</th></tr></thead>
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
  const [accuracyHovered, setAccuracyHovered] = useState(false)
  const [accuracyPinned, setAccuracyPinned] = useState(false)
  const showAccuracy = accuracyHovered || accuracyPinned
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
  const ungradedGames = games.filter(game => !game.models[model]?.grade)
  const previews = [...(payload.previews || [])].sort((a, b) => a.scheduled_start_utc.localeCompare(b.scheduled_start_utc))
  const items = [
    ...ungradedGames.map(game => ({ start: game.scheduled_start_utc, node: <ProjectionCard key={`locked-${game.game_id}`} game={game} model={model} line={payload.lines?.[String(game.game_id)]} standings={payload.standings} /> })),
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
        <div className="flex items-center gap-2">
          <div className="relative"
            onMouseEnter={() => setAccuracyHovered(true)}
            onMouseLeave={() => setAccuracyHovered(false)}
            onFocus={() => setAccuracyHovered(true)}
            onBlur={event => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                setAccuracyHovered(false)
                setAccuracyPinned(false)
              }
            }}
            onKeyDown={event => {
              if (event.key === 'Escape') {
                setAccuracyHovered(false)
                setAccuracyPinned(false)
                event.currentTarget.querySelector('button')?.blur()
              }
            }}>
            <button type="button" aria-label="Model accuracy" aria-describedby={showAccuracy ? 'nhl-model-accuracy-tooltip' : undefined}
              aria-expanded={showAccuracy} onClick={() => setAccuracyPinned(open => !open)}
              className="flex items-center gap-2 whitespace-nowrap rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs font-medium text-zinc-200 hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400">
              <span aria-hidden="true" className="text-zinc-400">ⓘ</span> Model accuracy
            </button>
            {accuracyPinned && <button type="button" tabIndex={-1} aria-label="Close model accuracy tooltip"
              onClick={() => { setAccuracyPinned(false); setAccuracyHovered(false) }}
              className="fixed inset-0 z-40 cursor-default" />}
            {showAccuracy && <div id="nhl-model-accuracy-tooltip" role="tooltip"
              className="absolute right-0 top-full z-50 mt-2 max-h-[min(78vh,700px)] w-[min(92vw,560px)] overflow-y-auto overscroll-contain rounded-xl">
              <ModelPerformanceSummary games={games} selectedModel={model} />
            </div>}
          </div>
          <label className="flex items-center gap-2 text-sm text-zinc-500">Model <ModelSelect value={model} onChange={event => setModel(event.target.value as ModelName)}>{(Object.keys(MODEL_LABELS) as ModelName[]).map(key => <option key={key} value={key}>{MODEL_LABELS[key]}</option>)}</ModelSelect></label>
        </div>
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
