import { useState } from 'react'

export interface FightResult {
  result: 'W' | 'L' | 'D' | 'NC'
  method: string
  opponent: string
  date: string
  event_id: string
  fight_id: string
}

interface FightFormResponse {
  player_id: number
  fighter: string
  espn_id?: string
  source: string
  fights: FightResult[]
}

const formCache = new Map<number, FightFormResponse>()
const pendingForms = new Map<number, Promise<FightFormResponse>>()

function loadForm(playerId: number): Promise<FightFormResponse> {
  const cached = formCache.get(playerId)
  if (cached) return Promise.resolve(cached)
  const pending = pendingForms.get(playerId)
  if (pending) return pending

  const request = fetch(`/api/ufc/fighter/${playerId}/form`)
    .then(response => {
      if (!response.ok) throw new Error(`Fight form request failed (${response.status})`)
      return response.json()
    })
    .then((data: FightFormResponse) => {
      const normalized = { ...data, fights: Array.isArray(data.fights) ? data.fights : [] }
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

function resultTone(result: FightResult['result']): string {
  if (result === 'W') return 'border-emerald-800/70 bg-emerald-950/35 text-emerald-300'
  if (result === 'L') return 'border-red-900/70 bg-red-950/30 text-red-300'
  return 'border-zinc-700 bg-zinc-800/60 text-zinc-300'
}

export default function FightForm({ playerId, fighter }: { playerId: number; fighter: string }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<FightFormResponse | null>(() => formCache.get(playerId) || null)
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
    <div data-fight-form data-fight-form-state={open ? loading ? 'loading' : 'open' : 'closed'}>
      <button
        type="button"
        onClick={() => void toggle()}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-zinc-900/60"
      >
        <span>
          <span className="block text-xs font-semibold uppercase tracking-wide text-zinc-300">Last 5 fights</span>
          <span className="mt-0.5 block text-[11px] text-zinc-600">Fight form for {fighter}</span>
        </span>
        <span className="shrink-0 text-sm text-zinc-500" aria-hidden="true">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div className="border-t border-zinc-800 px-3 py-3 sm:px-4">
          {loading ? (
            <div className="flex gap-2 overflow-hidden animate-pulse" aria-label="Loading recent fights">
              {[0, 1, 2, 3, 4].map(index => (
                <div key={index} className="h-20 min-w-[7.75rem] rounded-lg bg-zinc-800/70" />
              ))}
            </div>
          ) : error ? (
            <p className="text-xs text-zinc-500">Recent fight form could not be loaded.</p>
          ) : !data?.fights.length ? (
            <p className="text-xs text-zinc-500">No completed UFC fights are available.</p>
          ) : (
            <ol className="flex max-w-full gap-2 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" aria-label={`${fighter} recent fight form`}>
              {data.fights.map(fight => (
                <li
                  key={fight.fight_id}
                  data-fight-result={fight.result}
                  className={`min-w-[7.75rem] max-w-[9rem] shrink-0 rounded-lg border px-2.5 py-2 ${resultTone(fight.result)}`}
                >
                  <div className="flex items-center justify-between gap-1 text-xs font-bold">
                    <span>{fight.result} · {fight.method}</span>
                    <span className="font-normal tabular-nums opacity-65">{dateLabel(fight.date)}</span>
                  </div>
                  <div className="mt-2 truncate text-[11px] font-medium text-zinc-200" title={fight.opponent}>
                    {fight.opponent}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  )
}
