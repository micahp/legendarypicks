import { useCallback, useEffect, useState } from 'react'

// /upcoming — plays on matches that have NOT started yet.
//
// Separate from /live-discounts on purpose. That board ranks live markets off the tape;
// this one cannot, because before a match starts there is no tape and therefore no
// absorption, no turn and no game state. Publishing a score here would be inventing one.
//
// What it is instead: a watchlist of open, tradeable match markets with the tournament's
// own reasons attached — opponent's entry status (lucky loser, qualifier, wildcard) and the
// seed mismatch. Those say WHY a side is cheap. They do not say it is wrong.

const POLL_MS = 60000

type Row = {
  ticker: string
  name: string
  bid: number
  ask: number
  spread: number | null
  volume_24h: number
  seed: number | null
  entry: string | null
  entry_label: string | null
  name_match: 'ok' | 'weak' | 'none'
  starts: string
  opponent: string
  opponent_seed: number | null
  opponent_entry: string | null
  opponent_entry_label: string | null
  underdog_by_seed: boolean
  soft_opponent: boolean
  tradeable: boolean
  event: string
}
type Board = {
  available: boolean
  reason?: string
  generated_at?: string
  stale?: boolean
  age_seconds?: number | null
  count?: number
  tradeable?: number
  max_spread?: number
  rows?: Row[]
  limitations?: string[]
}

const cents = (n: number) => `${Math.round(n * 100)}¢`

function startsIn(iso: string) {
  const ms = new Date(iso).getTime() - Date.now()
  if (ms < 0) return 'now'
  const h = Math.floor(ms / 3600000)
  const m = Math.floor((ms % 3600000) / 60000)
  return h >= 24 ? `${Math.floor(h / 24)}d ${h % 24}h` : h > 0 ? `${h}h ${m}m` : `${m}m`
}

export default function UpcomingBoard() {
  const [board, setBoard] = useState<Board | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [onlyCheap, setOnlyCheap] = useState(false)
  const [onlyMismatch, setOnlyMismatch] = useState(false)

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/live/upcoming-board', { cache: 'no-store' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setBoard(await res.json())
      setError(null)
    } catch {
      setError('Refresh failed — showing the last board received.')
    }
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, POLL_MS)
    return () => clearInterval(id)
  }, [load])

  const all = board?.rows ?? []
  const rows = all.filter(
    (r) =>
      (!onlyCheap || r.ask <= 0.35) &&
      (!onlyMismatch || r.underdog_by_seed || r.soft_opponent)
  )

  return (
    <>

      <div className="space-y-6">
        <header className="space-y-3">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-100">Upcoming</h1>
            <div className="flex items-center gap-2 text-xs">
              {board?.stale ? (
                <span className="rounded-full border border-red-500/40 bg-red-500/10 px-2 py-0.5 font-semibold text-red-300">
                  STALE
                </span>
              ) : board?.available ? (
                <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 font-semibold text-emerald-300">
                  LIVE
                </span>
              ) : null}
              {typeof board?.age_seconds === 'number' && (
                <span className="tabular-nums text-zinc-500">
                  {Math.round(board.age_seconds)}s old
                </span>
              )}
            </div>
          </div>

          <p className="max-w-3xl text-sm leading-relaxed text-zinc-400">
            Match markets that are open and tradeable but have not started. There is{' '}
            <span className="text-zinc-300">no score on this page</span> — before a match
            begins there is no tape, so absorption, turn and game state do not exist, and a
            score here would be invented. What is shown instead is why a price may be cheap:
            the opponent&apos;s entry route and the seed mismatch, both straight from the
            tournament draw.
          </p>

          <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[13px] text-amber-200">
            <span className="font-semibold">Paper research only.</span> A lucky loser or a
            seed gap tells you why a side is cheap, not that the price is wrong. The base case
            is still that the seed wins.
          </div>
        </header>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            ['Markets', board?.count ?? 0],
            ['Tradeable', board?.tradeable ?? 0],
            ['Max spread', board?.max_spread != null ? cents(board.max_spread) : '—'],
            ['Showing', rows.length],
          ].map(([l, v]) => (
            <div key={String(l)} className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2">
              <div className="text-[11px] uppercase tracking-wider text-zinc-500">{l}</div>
              <div className="text-lg font-bold tabular-nums text-zinc-100">{v}</div>
            </div>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
            Filter
          </span>
          {[
            ['Cheap side only (≤35¢)', onlyCheap, () => setOnlyCheap((v) => !v)],
            ['Seed / entry mismatch', onlyMismatch, () => setOnlyMismatch((v) => !v)],
          ].map(([label, on, fn]) => (
            <button
              key={String(label)}
              onClick={fn as () => void}
              aria-pressed={on as boolean}
              className={`rounded-full border px-2.5 py-1 text-xs font-semibold transition-colors ${
                on
                  ? 'border-emerald-500/60 bg-emerald-500/15 text-emerald-300'
                  : 'border-zinc-700 bg-zinc-900 text-zinc-400 hover:text-zinc-200'
              }`}
            >
              {label as string}
            </button>
          ))}
        </div>

        {error && (
          <p className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </p>
        )}

        {board?.available && rows.length === 0 && (
          <p className="rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-6 text-sm text-zinc-500">
            Nothing matches these filters right now.
          </p>
        )}

        <div className="space-y-2">
          {rows.map((r) => (
            <article
              key={r.ticker}
              className="rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-3"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <div className="min-w-0">
                  <h2 className="text-base font-bold text-zinc-100">
                    {r.name}
                    {r.seed && <span className="ml-1 text-zinc-500">[{r.seed}]</span>}
                    <span className="font-normal text-zinc-500"> vs {r.opponent}</span>
                    {r.opponent_seed && (
                      <span className="ml-1 text-zinc-600">[{r.opponent_seed}]</span>
                    )}
                  </h2>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                    {r.underdog_by_seed && (
                      <span className="rounded bg-amber-500/15 px-1.5 py-0.5 font-semibold uppercase tracking-wider text-amber-300">
                        Unseeded vs [{r.opponent_seed}]
                      </span>
                    )}
                    {r.opponent_entry_label && (
                      <span className="rounded bg-sky-500/15 px-1.5 py-0.5 font-semibold uppercase tracking-wider text-sky-300">
                        Opponent is a {r.opponent_entry_label}
                      </span>
                    )}
                    {r.name_match !== 'ok' && (
                      <span
                        className="rounded bg-zinc-700/50 px-1.5 py-0.5 text-zinc-400"
                        title="Joined to the draw on surname alone, or not at all. Two players can share a surname — treat the seed and entry status here as unconfirmed."
                      >
                        draw join: {r.name_match}
                      </span>
                    )}
                    <span className="tabular-nums text-zinc-500">
                      starts in {startsIn(r.starts)}
                    </span>
                  </div>
                </div>

                <div className="text-right">
                  <div className="text-xl font-extrabold tabular-nums text-zinc-100">
                    {cents(r.ask)}
                  </div>
                  <div className="text-[11px] tabular-nums text-zinc-500">
                    bid {cents(r.bid)} · spread {r.spread != null ? cents(r.spread) : '—'}
                  </div>
                  <div className="text-[11px] tabular-nums text-zinc-600">
                    {Math.round(r.volume_24h).toLocaleString()} vol
                  </div>
                </div>
              </div>
              <p className="mt-1.5 font-mono text-[10px] text-zinc-700">{r.ticker}</p>
            </article>
          ))}
        </div>

        {board?.limitations && (
          <footer className="border-t border-zinc-800 pt-4">
            <h2 className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
              What this board does not claim
            </h2>
            <ul className="mt-2 space-y-1 text-xs text-zinc-500">
              {board.limitations.map((l) => (
                <li key={l}>· {l}</li>
              ))}
            </ul>
          </footer>
        )}
      </div>
    </>
  )
}
