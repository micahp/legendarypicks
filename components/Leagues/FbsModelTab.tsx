import { useEffect, useMemo, useState } from 'react'
import ModelSelect from './ModelSelect'

type View = 'projections' | 'record' | 'ratings'

// One projection per model and game. The backend fixes it at the T-90 cutoff. The card does not show when.
interface ModelProjection {
  p_home: number
  p_away: number
  fair_home: number | null
  fair_away: number | null
  model_version: string
  fitted_through: string | null
  projected_at_utc: string | null
  frozen_at_utc: string | null
}

interface FbsGame {
  game_id: string
  kickoff_utc: string
  home_team: string
  away_team: string
  neutral_site: boolean
  home_record?: string | null
  away_record?: string | null
  result: { home_score: number; away_score: number; home_win: boolean } | null
  models: Record<string, ModelProjection>
}

interface ModelInfo { id: string; label: string; note: string }

interface HistoryRow {
  game_id: string
  kickoff_utc: string
  p_home: number
  home_win: boolean
  home_score: number
  away_score: number
  graded: number
  accuracy: number
  brier: number
}

interface ModelRecord {
  frozen: number
  graded: number
  accuracy: number | null
  brier: number | null
  log_loss: number | null
  history: HistoryRow[]
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
  state: 'available' | 'awaiting_first_projection' | 'migration_required'
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
    () => (payload?.games ?? [])
      .filter((game) => new Date(game.kickoff_utc).getTime() > now && game.models[model])
      .sort((a, b) => a.kickoff_utc.localeCompare(b.kickoff_utc)),
    [payload, model, now],
  )

  if (error) {
    return <div className="p-6 text-sm text-red-400">Model feed unavailable — {error}</div>
  }
  if (!payload) {
    return <div className="p-6 text-sm text-zinc-500">Loading FBS model…</div>
  }

  const record = payload.records[model]
  const selected = payload.models.find((entry) => entry.id === model)
  const recent = [...(record?.history ?? [])].reverse().slice(0, 25)

  return (
    <div className="space-y-5">
      <nav className="flex w-fit gap-1 rounded-full bg-zinc-900 p-1" aria-label="NCAAF model views">
        {([['projections', 'Projections'], ['record', 'Record'], ['ratings', 'Team Ratings']] as [View, string][]).map(([key, label]) => (
          <button key={key} type="button" onClick={() => setView(key)} aria-current={view === key ? 'page' : undefined} className={`rounded-full px-3 py-1.5 text-sm ${view === key ? 'bg-zinc-100 text-zinc-900' : 'text-zinc-400 hover:text-zinc-100'}`}>{label}</button>
        ))}
      </nav>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-zinc-100">FBS model</h2>
          <p className="mt-1 max-w-2xl text-sm text-zinc-500">{selected?.note}</p>
        </div>
        <label className="flex items-center gap-2 text-sm text-zinc-500">
          Model
          <ModelSelect value={model} onChange={(event) => setModel(event.target.value)} className="max-w-[18rem]">
            {payload.models.map((entry) => (
              <option key={entry.id} value={entry.id}>{entry.label}</option>
            ))}
          </ModelSelect>
        </label>
      </div>

      {payload.state !== 'available' ? (
        <p className="py-10 text-sm text-zinc-500">No projections for {payload.season} yet.</p>
      ) : null}

      {view === 'projections' ? (
        <section className="divide-y divide-zinc-800 border-t border-zinc-800">
          {upcoming.length === 0 ? (
            <p className="py-8 text-sm text-zinc-500">No upcoming games with a projection.</p>
          ) : upcoming.map((game) => {
            const forecast = game.models[model]
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
                    record={game.away_record}
                    probability={forecast.p_away}
                    fair={forecast.fair_away}
                    favoured={!homeFavoured}
                  />
                  <Side
                    team={game.home_team}
                    record={game.home_record}
                    probability={forecast.p_home}
                    fair={forecast.fair_home}
                    favoured={homeFavoured}
                  />
                  <Metric label="Lean" value={`${homeFavoured ? game.home_team : game.away_team}`} />
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
            <Metric label="Projections" value={record ? `${record.frozen}` : '—'} />
            <Metric label="Graded" value={record ? `${record.graded}` : '—'} />
            <Metric label="Brier" value={record?.brier != null ? record.brier.toFixed(4) : '—'} />
            <Metric label="Winner accuracy" value={pct(record?.accuracy)} />
          </div>
          <p className="text-xs text-zinc-500">
            Brier is mean (p − outcome)² over graded projections; lower is better and 0.2500 is a coin flip.
            Only {record?.graded ?? 0} graded projections so far. Until that is in the hundreds, treat the
            number as an early read, not a validated score.
          </p>
          {recent.length === 0 ? (
            <p className="py-6 text-sm text-zinc-500">No graded projections yet.</p>
          ) : (
            <div className="divide-y divide-zinc-800 border-t border-zinc-800">
              {recent.map((row) => {
                const pickedHome = row.p_home >= 0.5
                const picked = pickedHome ? 'home' : 'away'
                const won = pickedHome ? row.home_win : !row.home_win
                const lean = pickedHome ? row.p_home : 1 - row.p_home
                return (
                  <article key={row.game_id} className="grid grid-cols-2 gap-x-6 gap-y-2 py-3 sm:grid-cols-4">
                    <Metric label="Kickoff" value={kickoffLabel(row.kickoff_utc)} />
                    <Metric label="Lean" value={`${pct(lean)} ${picked}`} />
                    <Metric label="Final" value={`${row.away_score}–${row.home_score}`} />
                    <Metric label="Result" value={won ? '✓ Won' : '✗ Lost'} />
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

function Side({ team, record, probability, fair, favoured }: {
  team: string; record?: string | null; probability: number; fair: number | null; favoured: boolean
}) {
  return (
    <div className="min-w-0">
      <div className="truncate text-sm text-zinc-200">{team}{record && <span className="ml-1.5 text-xs text-zinc-500">{record}</span>}</div>
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
