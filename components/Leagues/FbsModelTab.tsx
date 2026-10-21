import { useEffect, useMemo, useState } from 'react'
import ModelSelect from './ModelSelect'

type View = 'projections' | 'record' | 'ratings'

interface ModelForecast {
  p_home: number
  p_away: number
  fair_home: number | null
  fair_away: number | null
  model_version: string
  fitted_through: string | null
  locked_at_utc?: string | null
  previewed_at_utc?: string | null
}

// preview: display-only, replaced each run. locked: frozen inside the T-90 window.
// missed: kickoff passed with no lock. legacy: stored before the lock protocol, not official.
type GameStatus = 'preview' | 'locked' | 'missed' | 'legacy'

interface FbsGame {
  game_id: string
  kickoff_utc: string
  home_team: string
  away_team: string
  status: GameStatus
  locked_at_utc: string | null
  late: boolean
  result: { home_score: number; away_score: number; home_win: boolean } | null
  models: Record<string, ModelForecast>
}

interface ModelInfo { id: string; label: string; note: string }

interface ModelRecord {
  graded: number
  forecasts: number
  late: number
  legacy: number
  missed: number
  brier: number | null
  log_loss: number | null
  accuracy: number | null
}

interface Rating {
  season: number
  team_id: string
  team: string
  conference: string | null
  rating: number | null
  games_used: number | null
  as_of_utc: string
}

interface Payload {
  league: string
  default_model: string
  models: ModelInfo[]
  records: Record<string, ModelRecord>
  season: number
  games: FbsGame[]
  ratings: Rating[]
  meta: Record<string, unknown>
  state: 'available' | 'awaiting_first_lock'
  source: string
}

const pct = (value: number | null | undefined) =>
  value == null ? '—' : `${(value * 100).toFixed(1)}%`

const price = (value: number | null | undefined) =>
  value == null ? '—' : value > 0 ? `+${value}` : `${value}`

function kickoffLabel(iso: string) {
  const date = new Date(iso)
  return date.toLocaleString(undefined, {
    weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}

export default function FbsModelTab() {
  const [payload, setPayload] = useState<Payload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<View>('projections')
  const [model, setModel] = useState<string>('g2h')

  useEffect(() => {
    let cancelled = false
    fetch('/api/ncaaf/model/locks?season=2026')
      .then((response) => {
        if (!response.ok) throw new Error(`model feed returned ${response.status}`)
        return response.json()
      })
      .then((data: Payload) => {
        if (cancelled) return
        setPayload(data)
        if (data.default_model) setModel(data.default_model)
      })
      .catch((err: Error) => !cancelled && setError(err.message))
    return () => { cancelled = true }
  }, [])

  const now = Date.now()
  const upcoming = useMemo(
    () => (payload?.games ?? []).filter((game) => new Date(game.kickoff_utc).getTime() > now),
    [payload, now],
  )
  // The record is every stored forecast whose game has started.
  const recent = useMemo(
    () => (payload?.games ?? [])
      .filter((game) => (game.status === 'locked' || game.status === 'legacy')
        && new Date(game.kickoff_utc).getTime() <= now)
      .slice(-25).reverse(),
    [payload, now],
  )

  if (error) {
    return <div className="p-6 text-sm text-red-400">Model feed unavailable — {error}</div>
  }
  if (!payload) {
    return <div className="p-6 text-sm text-zinc-500">Loading FBS model…</div>
  }

  const record = payload.records[model]
  const selected = payload.models.find((entry) => entry.id === model)

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-zinc-100">FBS model</h2>
          <p className="mt-1 max-w-2xl text-sm text-zinc-500">
            {selected?.note}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ModelSelect value={model} onChange={(event) => setModel(event.target.value)} aria-label="Model">
            {payload.models.map((entry) => (
              <option key={entry.id} value={entry.id}>{entry.label}</option>
            ))}
          </ModelSelect>
          <nav className="flex gap-1 rounded-lg bg-zinc-900 p-1 text-sm">
            {(['projections', 'record', 'ratings'] as View[]).map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => setView(tab)}
                className={`rounded-md px-3 py-1.5 capitalize ${view === tab ? 'bg-zinc-800 text-zinc-100' : 'text-zinc-400 hover:text-zinc-200'}`}
              >
                {tab}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <p className="text-xs text-zinc-500">
        Predictions only — no NCAAF moneyline or spread price feed is captured yet, so nothing here is
        a qualifying wager. Win probabilities and model fair odds. Only forecasts locked before kickoff
        count toward the record; previews do not.
      </p>

      {payload.state === 'awaiting_first_lock' ? (
        <p className="py-10 text-sm text-zinc-500">No forecasts locked for {payload.season} yet.</p>
      ) : null}

      {view === 'projections' ? (
        <section className="divide-y divide-zinc-800 border-t border-zinc-800">
          {upcoming.length === 0 ? (
            <p className="py-8 text-sm text-zinc-500">No upcoming games in the locked window.</p>
          ) : upcoming.map((game) => {
            const forecast = game.models[model]
            if (!forecast) return null
            const homeFavoured = forecast.p_home >= forecast.p_away
            return (
              <article key={game.game_id} className="py-4">
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                  <h3 className="font-semibold text-zinc-100">
                    {game.away_team} <span className="text-zinc-500">@</span> {game.home_team}
                  </h3>
                  <span className="text-sm tabular-nums text-zinc-400">{kickoffLabel(game.kickoff_utc)}</span>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
                  <Side
                    team={game.away_team}
                    probability={forecast.p_away}
                    fair={forecast.fair_away}
                    favoured={!homeFavoured}
                  />
                  <Side
                    team={game.home_team}
                    probability={forecast.p_home}
                    fair={forecast.fair_home}
                    favoured={homeFavoured}
                  />
                  <Metric label="Lean" value={`${homeFavoured ? game.home_team : game.away_team}`} />
                </div>
                <div className="mt-3 text-xs text-zinc-500">
                  {forecast.fitted_through ? ` · fitted through ${forecast.fitted_through}` : ''}
                </div>
              </article>
            )
          })}
        </section>
      ) : null}

      {view === 'ratings' ? (
        <section className="space-y-3">
          <p className="text-xs text-zinc-500">
            Current saved G2h team-season ratings. Relative strength values, not projected points.
            Rating timestamps reflect the last model run.
          </p>
          {payload.ratings.length === 0 ? (
            <p className="py-6 text-sm text-zinc-500">No team ratings available.</p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-zinc-800">
              <table className="w-full min-w-[460px] text-left text-sm">
                <thead className="bg-zinc-900 text-xs text-zinc-400">
                  <tr><th className="px-3 py-2">Team</th><th className="px-3 py-2">Conference</th><th className="px-3 py-2 text-right">Rating</th><th className="px-3 py-2 text-right">Games</th></tr>
                </thead>
                <tbody className="divide-y divide-zinc-800">
                  {payload.ratings.map((rating) => (
                    <tr key={rating.team_id}>
                      <td className="px-3 py-2 text-zinc-100">{rating.team}</td>
                      <td className="px-3 py-2 text-zinc-400">{rating.conference || '—'}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-zinc-100">{rating.rating == null ? '—' : rating.rating.toFixed(3)}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-zinc-400">{rating.games_used ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      {view === 'record' ? (
        <section className="space-y-6">
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 border-t border-zinc-800 pt-4 sm:grid-cols-4">
            <Metric label="Forecasts" value={record ? `${record.forecasts}` : '—'} />
            <Metric label="Graded" value={record ? `${record.graded}` : '—'} />
            <Metric label="Brier" value={record?.brier != null ? record.brier.toFixed(4) : '—'} />
            <Metric label="Winner accuracy" value={pct(record?.accuracy)} />
          </div>
          <p className="text-xs text-zinc-500">
            Brier is mean (p − outcome)² on graded forecasts; lower is better and 0.2500 is a
            coin flip. Only {record?.graded ?? 0} graded forecasts — until that is in the hundreds,
            treat the number as an early read, not a validated score.
          </p>
          {recent.length === 0 ? (
            <p className="py-6 text-sm text-zinc-500">No games have started yet in the locked window.</p>
          ) : (
            <div className="divide-y divide-zinc-800 border-t border-zinc-800">
              {recent.map((game) => {
                const forecast = game.models[model]
                if (!forecast) return null
                const pickedHome = forecast.p_home >= forecast.p_away
                const picked = pickedHome ? 'home' : 'away'
                const won = game.result ? (picked === 'home' ? game.result.home_win : !game.result.home_win) : null
                return (
                  <article key={game.game_id} className="grid grid-cols-2 gap-x-6 gap-y-2 py-3 sm:grid-cols-5">
                    <Metric label="Game" value={`${game.away_team} @ ${game.home_team}`} />
                    <Metric label="Lean" value={`${pct(Math.max(forecast.p_home, forecast.p_away))} ${picked === 'home' ? game.home_team : game.away_team}`} />
                    <Metric label="Final" value={game.result ? `${game.result.away_score}–${game.result.home_score}` : 'Pending'} />
                    <Metric label="Result" value={won == null ? 'Pending' : won ? '✓ Won' : '✗ Lost'} />
                    <Metric label="Kickoff" value={kickoffLabel(game.kickoff_utc)} />
                  </article>
                )
              })}
            </div>
          )}
        </section>
      ) : null}

    </div>
  )
}

function Side({ team, probability, fair, favoured }: {
  team: string; probability: number; fair: number | null; favoured: boolean
}) {
  return (
    <div className="min-w-0">
      <div className="truncate text-sm text-zinc-200">{team}</div>
      <div className="mt-0.5 tabular-nums text-zinc-100">
        <span className={favoured ? 'font-semibold' : 'text-zinc-400'}>{pct(probability)}</span>
        <span className="ml-2 text-xs text-zinc-500">{price(fair)}</span>
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="mt-0.5 truncate tabular-nums text-sm text-zinc-100">{value}</div>
    </div>
  )
}

