import { useEffect, useState } from 'react'

// Set Watch — who is up a break in the set being played RIGHT NOW.
//
// Micah, 2026-09-03: "a roll at the top of the plays page for set watch, for
// people who have broken and we are expecting them to win the set. That's a
// play in itself."
//
// It is its own play and a different one from the match card below. Up a break
// in the current set says a lot about that set and much less about the match,
// so every row prices the SET contract, not the match contract.
//
// Deliberately a strip, not cards. It sits above a board that is already dense,
// so it earns its space by being scannable in one pass: price first, then who,
// then the evidence. Nothing here is a projection and the copy never implies one.

type Row = {
  player: string
  opponent: string
  set_no: string | number
  net_breaks: number
  breaks_made: number
  breaks_conceded: number
  hold_pct: number | null
  hold_held: number
  hold_served: number
  verdict: 'PASS' | 'WEAK' | 'REJECT' | 'INSUFFICIENT'
  why: string
  games: string
  sets_mine: number | null
  sets_theirs: number | null
  round: string | null
  court: string | null
  set_ticker: string | null
  set_bid: number | null
  set_ask: number | null
  set_market_note: string | null
  room: number | null
  priced_out: boolean
  match_ticker: string | null
  match_bid: number | null
  match_ask: number | null
  match_price_note: string | null
  set_room: number | null
}
type Payload = {
  available: boolean
  reason?: string
  rows?: Row[]
  generated_at?: string
  age_seconds?: number | null
  stale?: boolean
  live_matches?: number
}

const cents = (v: number | null | undefined) =>
  v == null ? '—' : `${Math.round(v * 100)}¢`

export default function SetWatch() {
  const [data, setData] = useState<Payload | null>(null)

  useEffect(() => {
    let dead = false
    const load = async () => {
      try {
        const r = await fetch('/api/live/set-watch', { cache: 'no-store' })
        const j = await r.json()
        if (!dead) setData(j)
      } catch {
        if (!dead) setData({ available: false, reason: 'Set watch unreachable.' })
      }
    }
    load()
    const t = setInterval(load, 20000)
    return () => {
      dead = true
      clearInterval(t)
    }
  }, [])

  if (!data) return null

  const rows = data.rows ?? []

  // An empty strip states WHY it is empty. "Nobody is up a break" and "the feed
  // died" look identical if the surface just renders nothing, and only one of
  // them means there is no trade.
  const empty = !data.available
    ? data.reason || 'Set watch unavailable.'
    : data.stale
      ? `Last updated ${data.age_seconds != null ? Math.round(data.age_seconds) : '?'}s ago — a set can turn over in that time. Treat as stale.`
      : rows.length === 0
        ? `Nobody is up a break right now${data.live_matches ? ` across ${data.live_matches} live matches` : ''}.`
        : null

  return (
    <section
      aria-label="Set watch"
      className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-bold uppercase tracking-wider text-zinc-200">
          Set watch
        </h2>
        <p className="text-[11px] text-zinc-500">
          Up a break in the set being played now. Price is the{' '}
          <span className="text-zinc-400">set</span> contract, not the match.
        </p>
      </div>

      {empty ? (
        <p
          className={`mt-2 text-[13px] ${
            data.stale || !data.available ? 'text-amber-300' : 'text-zinc-500'
          }`}
        >
          {empty}
        </p>
      ) : (
        // Scrolls inside its own track, never the page. Snap so a swipe lands on
        // a whole card rather than halfway through a price.
        <ul className="-mx-1 mt-2 flex snap-x snap-mandatory gap-2 overflow-x-auto px-1 pb-1">
          {rows.map((r) => (
            <li
              key={`${r.set_ticker ?? r.player}-${r.set_no}`}
              className={`w-[248px] shrink-0 snap-start rounded-md border p-2.5 ${
                r.priced_out
                  ? 'border-zinc-800/60 bg-zinc-900/40'
                  : 'border-zinc-700 bg-zinc-900'
              }`}
            >
              <div className="flex items-baseline gap-2">
                {/* Room left is the number that decides whether this is a trade.
                    A break at 1-0 priced 0.69 and ran to 0.99; a break at 5-1
                    priced 0.98. Both are true, only one is buyable, so the ask
                    goes quiet once there is nothing left in it. */}
                <span
                  className={`text-2xl font-extrabold tabular-nums ${
                    r.priced_out ? 'text-zinc-600' : 'text-emerald-300'
                  }`}
                >
                  {cents(r.match_ask)}
                </span>
                <span className="text-[11px] uppercase tracking-wider text-zinc-600">
                  match
                </span>
                <span className="ml-auto text-[12px] font-semibold tabular-nums text-zinc-400">
                  +{r.net_breaks}
                </span>
              </div>
              {r.priced_out ? (
                <div className="mt-0.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-600">
                  Priced out
                </div>
              ) : (
                <div className="mt-0.5 text-[11px] tabular-nums text-zinc-500">
                  {r.room != null ? `${Math.round(r.room * 100)}¢ of room` : ''}
                  <span className="ml-2 text-zinc-600">
                    set {r.set_no} @ {cents(r.set_ask)}
                  </span>
                </div>
              )}

              <div className="mt-1 truncate text-[14px] font-bold text-zinc-100">
                {r.player}
              </div>
              <div className="truncate text-[12px] text-zinc-500">vs {r.opponent}</div>

              <div className="mt-1.5 flex items-baseline justify-between gap-2 border-t border-zinc-800 pt-1.5">
                <span className="text-[12px] tabular-nums text-zinc-500">{r.games}</span>
                {/* Sample size always rides with the percentage, and a thin one is
                    marked in the accent rather than dressed up as a good number. */}
                <span
                  className={`text-[12px] tabular-nums ${
                    r.verdict === 'INSUFFICIENT' ? 'text-amber-300' : 'text-zinc-400'
                  }`}
                  title={r.why}
                >
                  {r.hold_pct == null || r.hold_served === 0
                    ? 'hold —'
                    : `hold ${Math.round(r.hold_pct)}%`}
                  <span className="ml-1 text-zinc-600">
                    {r.hold_held}/{r.hold_served}
                  </span>
                </span>
              </div>

              {r.match_ask == null && (
                <div className="mt-1 text-[11px] leading-snug text-amber-300">
                  {r.match_price_note}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
