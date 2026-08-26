import { useState } from 'react'

// Mirrors FightForm deliberately: same click-to-load contract, same module-level
// cache and in-flight dedupe, same closed-by-default posture. A cold click costs
// ESPN 1 + 2N requests, so it must never fire on render.
export interface MatchStatLine {
  date: string
  event_id: string
  matchup: string
  home: boolean | null
  minutes: number | null
  goals: number | null
  assists: number | null
  shots: number | null
  shots_on_target: number | null
  tackles: number | null
  clearances: number | null
  crosses: number | null
  passes_attempted: number | null
  fouls_committed: number | null
}

interface MatchFormResponse {
  player_id: number
  player: string
  team: string
  league: string
  source: string
  matches: MatchStatLine[]
  stored: number
  note?: string
}

const formCache = new Map<number, MatchFormResponse>()
const pendingForms = new Map<number, Promise<MatchFormResponse>>()

function loadForm(playerId: number): Promise<MatchFormResponse> {
  const cached = formCache.get(playerId)
  if (cached) return Promise.resolve(cached)
  const pending = pendingForms.get(playerId)
  if (pending) return pending

  const request = fetch(`/api/soccer/player/${playerId}/form`)
    .then(response => {
      if (!response.ok) throw new Error(`Match form request failed (${response.status})`)
      return response.json()
    })
    .then((data: MatchFormResponse) => {
      const normalized = { ...data, matches: Array.isArray(data.matches) ? data.matches : [] }
      formCache.set(playerId, normalized)
      return normalized
    })
    .finally(() => pendingForms.delete(playerId))
  pendingForms.set(playerId, request)
  return request
}

function dateLabel(date: string): string {
  const match = /^\d{4}-(\d{2})-(\d{2})/.exec(date || '')
  return match ? `${match[1]}/${match[2]}` : '—'
}

// A player who did not come off the bench has no stat line to read. Showing
// eleven zeroes would look like a measured performance rather than an absence.
function didNotPlay(m: MatchStatLine): boolean {
  return !m.minutes
}

function stat(value: number | null): string {
  return value === null || value === undefined ? '—' : String(value)
}

export default function MatchForm({ playerId, player }: { playerId: number; player: string }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<MatchFormResponse | null>(() => formCache.get(playerId) || null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)

  const toggle = async () => {
    if (open) {
      setOpen(false)
      return
    }
    setOpen(true)
    if (data) return
    setLoading(true)
    setError(false)
    try {
      setData(await loadForm(playerId))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div data-match-form data-match-form-state={open ? (loading ? 'loading' : 'open') : 'closed'}>
      <button
        type="button"
        onClick={() => void toggle()}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-zinc-900/60"
      >
        <span>
          <span className="block text-xs font-semibold uppercase tracking-wide text-zinc-300">Last 5 matches</span>
          <span className="mt-0.5 block text-[11px] text-zinc-600">ESPN form for {player}</span>
        </span>
        <span className="shrink-0 text-sm text-zinc-500" aria-hidden="true">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div className="border-t border-zinc-800 px-3 py-3 sm:px-4">
          {loading ? (
            <div className="flex gap-2 overflow-hidden animate-pulse" aria-label="Loading recent matches">
              {[0, 1, 2, 3, 4].map(index => (
                <div key={index} className="h-24 min-w-[8.5rem] rounded-lg bg-zinc-800/70" />
              ))}
            </div>
          ) : error ? (
            <p className="text-xs text-zinc-500">Recent match form could not be loaded.</p>
          ) : !data?.matches.length ? (
            <p className="text-xs text-zinc-500">No completed Liga MX matches are available from ESPN.</p>
          ) : (
            <ol
              className="flex max-w-full gap-2 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
              aria-label={`${player} recent match form`}
            >
              {data.matches.map(m => (
                <li
                  key={m.event_id}
                  data-match-form-item
                  className="min-w-[8.5rem] rounded-lg border border-zinc-800 bg-zinc-900/60 px-2.5 py-2"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-[11px] font-semibold text-zinc-300">{m.matchup || '—'}</span>
                    <span className="shrink-0 text-[10px] tabular-nums text-zinc-600">{dateLabel(m.date)}</span>
                  </div>
                  {didNotPlay(m) ? (
                    <p className="mt-2 text-[11px] text-zinc-600">Did not play</p>
                  ) : (
                    <dl className="mt-1.5 grid grid-cols-2 gap-x-2 gap-y-0.5 text-[11px] tabular-nums text-zinc-400">
                      <dt className="text-zinc-600">Sh</dt><dd className="text-right">{stat(m.shots)}</dd>
                      <dt className="text-zinc-600">SOT</dt><dd className="text-right">{stat(m.shots_on_target)}</dd>
                      <dt className="text-zinc-600">Tkl</dt><dd className="text-right">{stat(m.tackles)}</dd>
                      <dt className="text-zinc-600">Pas</dt><dd className="text-right">{stat(m.passes_attempted)}</dd>
                      <dt className="text-zinc-600">Clr</dt><dd className="text-right">{stat(m.clearances)}</dd>
                      <dt className="text-zinc-600">Min</dt><dd className="text-right">{stat(m.minutes)}</dd>
                    </dl>
                  )}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  )
}
