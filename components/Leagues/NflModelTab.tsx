import { useEffect, useState } from 'react'

// Every projection here was locked before kickoff and is never rewritten
// (backend/nfl_lock.py). The page shows the locked row only, beside the line it
// was locked against, and the grade once nflverse publishes the final.

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
  locked_at: string
  line: Line
  grade: { brier: number | null; margin_err: number; total_err: number; ats: string } | null
}

interface ModelInfo {
  version: string
  family: 'v1' | 'v2'
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

interface Payload {
  season: number
  week: number | null
  weeks: number[]
  models: ModelInfo[]
  games: ModelGame[]
}

const one = (x: number) => x.toFixed(1)

function kickoffLabel(iso: string | null) {
  if (!iso) return 'Kickoff unknown'
  return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

function dayLabel(iso: string | null) {
  if (!iso) return 'Date unknown'
  return new Date(iso).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })
}

// nflverse spread_line is the home team's expected margin: positive means home favored.
function marketText(g: ModelGame, line: Line) {
  const parts: string[] = []
  if (line.spread != null) {
    if (line.spread === 0) parts.push('Pick')
    else parts.push(line.spread > 0 ? `${g.home} -${line.spread}` : `${g.away} -${Math.abs(line.spread)}`)
  }
  if (line.total != null) parts.push(`O/U ${line.total}`)
  return parts.length ? parts.join(' · ') : 'No line'
}

function winnerText(g: ModelGame, lock: Lock) {
  const homeFav = lock.p_home_win >= 0.5
  const p = homeFav ? lock.p_home_win : 1 - lock.p_home_win
  return `${homeFav ? g.home : g.away} ${Math.round(p * 100)}%`
}

function atsText(ats: string) {
  return { win: 'ATS W', loss: 'ATS L', push: 'Push', no_pick: 'No pick', no_line: 'No line' }[ats] || ats
}

function LockRow({ game, model, lock }: { game: ModelGame; model: ModelInfo; lock?: Lock }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-baseline gap-x-4 py-1 text-sm">
      <span className={`truncate ${model.adopted ? 'text-zinc-100' : 'text-zinc-400'}`} title={model.version}>
        {model.label}
      </span>
      {!lock ? (
        // Absence gets the accent: this model has no locked projection for this game.
        <span className="col-span-2 text-right text-amber-400">Not locked</span>
      ) : (
        <>
          <span className="text-right tabular-nums text-zinc-200">
            {lock.proj_home == null || lock.proj_away == null
              ? <span className="text-zinc-500">{lock.margin >= 0 ? game.home : game.away} by {one(Math.abs(lock.margin))}</span>
              : <>{game.away} {one(lock.proj_away)} · {game.home} {one(lock.proj_home)}</>}
          </span>
          <span className="w-28 text-right tabular-nums text-zinc-400">
            {lock.grade
              ? <>off {one(Math.abs(lock.grade.margin_err))} · {atsText(lock.grade.ats)}</>
              : winnerText(game, lock)}
          </span>
        </>
      )}
    </div>
  )
}

function GameRow({ game, models }: { game: ModelGame; models: ModelInfo[] }) {
  const anyLock = Object.values(game.locks)[0]
  return (
    <div className="space-y-1 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-semibold text-zinc-100">
          {game.away} {game.neutral ? 'vs' : '@'} {game.home}
        </span>
        <span className="text-right text-sm tabular-nums text-zinc-400">
          {game.final ? `Final ${game.away} ${game.final.away} · ${game.home} ${game.final.home}` : kickoffLabel(game.kickoff_utc)}
        </span>
      </div>
      {models.map(m => <LockRow key={m.version} game={game} model={m} lock={game.locks[m.version]} />)}
      <div className="text-xs text-zinc-500">
        Line at lock: {anyLock ? marketText(game, game.locks[models.find(m => game.locks[m.version])!.version].line) : 'none'}
      </div>
    </div>
  )
}

export default function NflModelTab() {
  const [week, setWeek] = useState<number | null>(null)
  const [data, setData] = useState<Payload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetch(`/api/nfl/model/locks${week ? `?week=${week}` : ''}`)
      .then(async res => {
        if (!res.ok) throw new Error(`The projections did not load (HTTP ${res.status}).`)
        return res.json() as Promise<Payload>
      })
      .then(p => { if (!cancelled) setData(p) })
      .catch(e => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [week])

  if (error) {
    return <div className="rounded-2xl bg-zinc-900 px-4 py-3 text-sm text-red-400">{error}</div>
  }
  if (loading && !data) {
    return <div className="h-40 animate-pulse rounded-2xl bg-zinc-800" />
  }
  if (!data || data.week == null) {
    return <p className="text-sm text-zinc-400">No projections have been locked for this season yet.</p>
  }

  const groups: [string, ModelGame[]][] = []
  for (const g of data.games) {
    const day = dayLabel(g.kickoff_utc)
    const last = groups[groups.length - 1]
    if (last && last[0] === day) last[1].push(g)
    else groups.push([day, [g]])
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <p className="max-w-prose text-sm text-zinc-400">
          Each projection is locked before kickoff and never changed. v1 points is the model in use;
          v2 EPA is on trial beside it and is graded on the same games.
        </p>
        <div className="flex flex-wrap gap-2">
          {data.weeks.map(w => (
            <button
              key={w}
              type="button"
              onClick={() => setWeek(w)}
              className={`rounded-full px-3 py-1 text-sm tabular-nums ${
                w === data.week ? 'bg-zinc-100 text-zinc-900' : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200'
              }`}
            >
              Week {w}
            </button>
          ))}
        </div>
      </div>

      {groups.map(([day, games]) => (
        <section key={day} className="space-y-2">
          <h2 className="text-lg font-semibold text-zinc-100">{day}</h2>
          <div className="divide-y divide-zinc-800 rounded-2xl bg-zinc-900 px-4">
            {games.map(g => <GameRow key={g.game_id} game={g} models={data.models} />)}
          </div>
        </section>
      ))}

      <p className="text-xs text-zinc-500">
        Win % is the chance the named team wins. After a final, each row shows how far its margin was off
        and its result against the line it was locked with. Lines are nflverse&apos;s, copied at lock time.
      </p>
    </div>
  )
}
