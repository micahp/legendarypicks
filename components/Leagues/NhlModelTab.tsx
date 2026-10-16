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
  /** Frozen at lock time by the backend and read straight from the payload. The browser
   *  never computes a pick, so the card and the record cannot disagree. */
  pick?: ModelPick | null
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
  price: number | null
  model_probability: number
  market_probability: number | null
  edge: number | null
  expected_value: number | null
  line_source: string | null
  line_captured_at_utc: string | null
  settlement_basis: string
  /** A quote was in force when this was frozen. False means no priced recommendation. */
  priced: boolean
  /** Priced and the expected value is positive: a recommendation, not just a lean. */
  qualifies: boolean
  rule_version?: string
  /** The market quote this was priced against, frozen at lock time. */
  quote?: BovadaLine | null
  selected_at_utc?: string
  provenance?: 'lock' | 'backfill' | 'preview'
  result: { won: boolean } | null
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

function spreadLabel(home: string, away: string, homePuckLine: number | null | undefined) {
  if (homePuckLine == null) return 'n/a'
  return homePuckLine < 0 ? `${home} ${signed(homePuckLine)}` : `${away} ${signed(-homePuckLine)}`
}

/** The three market rows for one quote. A locked card labels them as the locked basis so a
 *  reader can tell the line the pick was made on from a line that has since moved. */
function marketLines(home: string, away: string, forecast: Forecast, quote: BovadaLine | null | undefined, locked: boolean) {
  const margin = forecast.projected_goal_differential_home
  const homeLine = quote?.home_puck_line ?? null
  return [
    { label: locked ? 'Locked line' : 'Vegas line', value: spreadLabel(home, away, homeLine) },
    { label: 'Model line', value: margin > 0 ? `${home} ${signed(-margin)}` : `${away} ${signed(margin)}` },
    { label: 'Edge', value: homeLine == null ? 'n/a' : `${one(Math.abs(-homeLine - margin))} pts (${margin + homeLine > 0 ? home : away})` },
  ]
}

function marketTotals(forecast: Forecast, quote: BovadaLine | null | undefined, locked: boolean) {
  const vegas = quote?.total_line ?? null
  return [
    { label: locked ? 'Locked total' : 'Vegas total', value: vegas == null ? 'n/a' : one(vegas) },
    { label: 'Model total', value: one(forecast.projected_total_goals) },
    { label: 'Edge', value: vegas == null ? 'n/a' : `${signed(forecast.projected_total_goals - vegas)} pts` },
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

function ProjectionCardView({ away, home, startUtc, forecast, status, live, awayRecord, homeRecord }: {
  away: string
  home: string
  startUtc: string
  forecast: Forecast
  status: string | null
  live?: BovadaLine
  awayRecord?: string
  homeRecord?: string
}) {
  const grade = forecast.grade
  const isGraded = grade != null
  const pick = forecast.pick ?? null
  const pickResult = pick?.result ?? null
  const edgeClass = isGraded ? 'graded-edge' : ''
  // A locked pick carries the quote it was priced against. That is the basis this card shows;
  // the live quote appears separately and is never folded back into the edge, so the market
  // columns and the recommendation cannot point at different lines.
  const frozen = pick?.quote ?? null
  const basis = frozen ?? live ?? null
  const locked = frozen != null
  const lines = marketLines(home, away, forecast, basis, locked)
  const totals = marketTotals(forecast, basis, locked)
  const moved = locked && live != null &&
    (live.home_puck_line !== frozen.home_puck_line || live.total_line !== frozen.total_line)

  // Determine status badge
  let statusBadge = status
  let statusColorClass = 'text-emerald-400'
  if (isGraded && grade) {
    const won = pickResult?.won
    const so = grade.shootout_decided ? ' · SO' : ''
    if (won == null) {
      statusBadge = `GRADED${so}`
      statusColorClass = 'text-emerald-400'
    } else if (won) {
      statusBadge = `✓ GRADED${so}`
      statusColorClass = 'text-emerald-400'
    } else {
      statusBadge = `✗ GRADED${so}`
      statusColorClass = 'text-zinc-400'
    }
  }

  return (
    <article className={`space-y-2 rounded-2xl border border-zinc-800 bg-zinc-900 p-4 ${edgeClass}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="font-semibold text-zinc-100">{away} @ {home}</h3>
        <span className="flex items-center gap-3">
          {statusBadge && <span className={`rounded-full border border-current px-2.5 py-0.5 text-xs font-semibold tracking-wide ${statusColorClass}`}>{statusBadge}</span>}
          <span className="text-sm tabular-nums text-zinc-400">{timeLabel(startUtc)}</span>
        </span>
      </div>
      <div className="grid grid-cols-[1fr_auto] items-baseline gap-x-6 gap-y-1 text-sm tabular-nums">
        <span className="text-zinc-200">{away}{awayRecord && <span className="block text-xs text-zinc-500">{awayRecord}</span>}</span>
        <span className="text-right text-2xl font-semibold text-zinc-100">{one(forecast.away_expected_goals)}</span>
        <span className="text-zinc-200">{home}{homeRecord && <span className="block text-xs text-zinc-500">{homeRecord}</span>}</span>
        <span className="text-right text-2xl font-semibold text-zinc-100">{one(forecast.home_expected_goals)}</span>
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-1 border-t border-zinc-800 pt-2 text-sm text-zinc-400">
        {lines.map(line => <span key={line.label}>{line.label} <b className="font-medium tabular-nums text-zinc-100">{line.value}</b></span>)}
      </div>
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2 text-sm text-zinc-400">
        <div className="flex flex-wrap gap-x-6 gap-y-1">
          {totals.map(line => <span key={line.label}>{line.label} <b className="font-medium tabular-nums text-zinc-100">{line.value}</b></span>)}
        </div>
        <div className="text-right">
          <span className="block text-xs uppercase tracking-wider text-zinc-500">
            {pick ? (pick.qualifies ? 'Model pick' : 'Model lean') : 'Recommendation'}
          </span>
          <span className="block text-xl font-semibold text-zinc-100">
            {pick ? (
              <>
                {pickLabel(pick, home, away)}
                {isGraded && pickResult && (
                  <span className={`ml-1 ${pickResult.won ? 'text-emerald-400' : 'text-red-400'}`}>
                    {pickResult.won ? '✓' : '✗'}
                  </span>
                )}
              </>
            ) : 'n/a'}
          </span>
          {pick && !pick.qualifies && (
            <span className="block text-xs text-amber-300">No qualifying bet</span>
          )}
          {pick && pick.edge != null && (
            <span className="block text-xs tabular-nums text-zinc-400">
              {signed(pick.edge * 100)}% edge
              {isGraded && pickResult && <span className="text-zinc-500"> · {pickResult.won ? 'Won' : 'Lost'}</span>}
            </span>
          )}
          {pick && pick.expected_value != null && (
            <span className="block text-xs tabular-nums text-zinc-500">{signed(pick.expected_value * 100)}% EV</span>
          )}
          {!pick && (
            <span className="block text-xs text-zinc-500">
              {isGraded ? 'Not recommended' : 'No priced recommendation yet'}
            </span>
          )}
        </div>
      </div>
      {moved ? (
        <p className="border-t border-zinc-800 pt-2 text-xs text-zinc-500">
          Market has moved since the lock: now {spreadLabel(home, away, live?.home_puck_line)}
          {live?.total_line == null ? '' : ` · total ${one(live.total_line)}`}. The pick above is
          graded on the locked line.
        </p>
      ) : null}
    </article>
  )
}

function ProjectionCard({ game, model, line, standings }: { game: NhlGame; model: ModelName; line?: BovadaLine; standings?: Payload['standings'] }) {
  const forecast = game.models[model]
  return (
    <ProjectionCardView away={game.away_team} home={game.home_team} startUtc={game.scheduled_start_utc} forecast={forecast} status={null} live={line} awayRecord={recordLine(standings, game.away_team)} homeRecord={recordLine(standings, game.home_team)} />
  )
}

function PreviewCard({ game, model, line, standings }: { game: NhlPreview; model: ModelName; line?: BovadaLine; standings?: Payload['standings'] }) {
  const forecast = game.models[model]
  return (
    <ProjectionCardView away={game.away_team} home={game.home_team} startUtc={game.scheduled_start_utc} forecast={forecast} status="UNLOCKED" live={line} awayRecord={recordLine(standings, game.away_team)} homeRecord={recordLine(standings, game.home_team)} />
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><div className="text-xs text-zinc-500">{label}</div><div className="mt-0.5 truncate tabular-nums text-sm text-zinc-100">{value}</div></div>
}

function RecordProjection({ game, model }: { game: NhlGame; model: ModelName }) {
  const forecast = game.models[model]
  const grade = forecast.grade
  // The record grades the pick that was frozen at lock, not a moneyline guessed from win
  // probability. Before this, a card could show a puck line or total while the record
  // graded whichever team had the higher moneyline probability.
  const pick = forecast.pick ?? null
  const pickWon = pick?.result?.won ?? null
  return (
    <article className="py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="font-semibold text-zinc-100">{game.away_team} @ {game.home_team}</h3>
        <span className="text-sm tabular-nums text-zinc-400">{dateLabel(game.scheduled_start_utc)}</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-5">
        <Metric label={pick && !pick.qualifies ? 'Model lean' : 'Model pick'}
                value={pick ? `${pickLabel(pick, game.home_team, game.away_team)} ${pct(pick.model_probability)}` : 'n/a'} />
        <Metric label="Projected" value={`${one(forecast.away_expected_goals)}–${one(forecast.home_expected_goals)}`} />
        <Metric label="Final" value={grade ? `${grade.official_away_goals}–${grade.official_home_goals}` : 'Pending'} />
        <Metric label="Winner" value={grade ? `${grade.official_winner === 'home' ? game.home_team : game.away_team}${grade.shootout_decided ? ' · SO' : ''}` : 'Awaiting final'} />
        <div className="min-w-0">
          <div className="text-xs text-zinc-500">Result</div>
          {/* A lean with a negative expected value is not a priced recommendation, so it is
              reported as such rather than counted as a win or a loss. */}
          <div className={`mt-0.5 truncate text-sm tabular-nums ${pick?.qualifies ? (pickWon ? 'text-emerald-400' : 'text-red-400') : 'text-zinc-500'}`}>
            {pick == null || !pick.qualifies ? (pickWon == null ? 'Not recommended' : 'No qualifying bet')
              : pickWon == null ? 'Pending' : pickWon ? 'Pick ✓' : 'Pick ✗'}
          </div>
        </div>
      </div>
      <div className="mt-3 text-xs text-zinc-500">
        Locked {new Date(forecast.locked_at_utc || game.locked_at_utc).toLocaleString()}
        {pick?.line_captured_at_utc ? ` · line ${new Date(pick.line_captured_at_utc).toLocaleString()}` : ''}
        {pick?.price != null ? ` · ${pick.price > 0 ? '+' : ''}${pick.price}` : ''}
      </div>
    </article>
  )
}

type GradedForecast = NonNullable<Forecast['grade']>

function modelPerformance(games: NhlGame[], model: ModelName) {
  // A model's accuracy includes every graded forecast, whether or not it generated a bet.
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
      <p className="mt-3 text-xs leading-relaxed text-zinc-500">
        Lower is better. Brier 0 is perfect; 0.2500 is a constant 50% forecast. Every graded game counts, including unpriced games. Historical backtests and betting ROI are separate.
      </p>
    </section>
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
  const [showAccuracy, setShowAccuracy] = useState(false)
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
          <div className="relative">
            <button type="button" aria-expanded={showAccuracy} aria-controls="nhl-model-accuracy"
              onClick={() => setShowAccuracy(open => !open)}
              className="flex items-center gap-2 whitespace-nowrap rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs font-medium text-zinc-200 hover:bg-zinc-800">
              <span aria-hidden="true">▥</span> Model accuracy <span aria-hidden="true">{showAccuracy ? '▴' : '▾'}</span>
            </button>
            {showAccuracy && <>
              <button type="button" aria-label="Close model accuracy" onClick={() => setShowAccuracy(false)}
                className="fixed inset-0 z-40 cursor-default" />
              <div id="nhl-model-accuracy" className="absolute right-0 top-full z-50 mt-2 w-[min(92vw,610px)]">
                <ModelPerformanceSummary games={games} selectedModel={model} />
              </div>
            </>}
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
