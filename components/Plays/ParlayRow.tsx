import { useEffect, useState } from 'react'

// Parlay row — collapsed by default, above Set Watch.
//
// Micah asked for it. It ships with its own record visible rather than hidden,
// because that record is the most important thing on the panel: multi-leg is
// 5 winners from 33 all time, net -$198.58, and the tickets quote 0.00/1.00 so
// there is no exit. Collapsed is the honest default for a surface whose measured
// history is that bad.
//
// What it does surface correctly: SAME-MATCH combos first. Kalshi prices every
// leg independently and charges nothing to combine them, so correlated legs
// inside one match can cost far less than the joint outcome is worth. Legs in
// different matches are already priced at the product — fair by construction,
// no edge. No joint probability is shown for a correlated combo, deliberately:
// the product understates it and sorting on it would rank the most correlated
// rows as the best value.

type Leg = {
  ticker: string
  name: string
  title: string
  kind: string
  ask: number
  spread: number
  hold_pct: number | null
  hold_served: number
  hold_verdict: string
}
type Combo = {
  legs: Leg[]
  n: number
  correlation: 'SAME_MATCH' | 'CROSS_MATCH'
  cost: number
  max_return: number
  max_profit: number
  independent_p: number | null
  note: string
  worst_spread: number
}
type Payload = {
  available: boolean
  reason?: string
  combos?: Combo[]
  size_contracts?: number
  stale?: boolean
  age_seconds?: number | null
  record?: {
    settled: number
    won: number
    staked: number
    returned: number
    net: number
    note: string
    where_the_edge_is?: string
  }
}

export default function ParlayRow() {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<Payload | null>(null)

  useEffect(() => {
    if (!open) return
    let dead = false
    const load = async () => {
      try {
        const r = await fetch('/api/live/parlay', { cache: 'no-store' })
        const j = await r.json()
        if (!dead) setData(j)
      } catch {
        if (!dead) setData({ available: false, reason: 'Parlay board unreachable.' })
      }
    }
    load()
    const t = setInterval(load, 30000)
    return () => {
      dead = true
      clearInterval(t)
    }
  }, [open])

  const combos = data?.combos ?? []
  const rec = data?.record

  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/60">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left focus:outline-none focus-visible:ring-1 focus-visible:ring-zinc-400"
      >
        <span className="text-sm font-bold uppercase tracking-wider text-zinc-200">Parlay</span>
        <span className="text-[11px] text-zinc-500">
          multi-leg combinations, correlated first
        </span>
        <span className="ml-auto text-[11px] text-zinc-500">{open ? 'Hide' : 'Show'}</span>
        <span className={`text-zinc-500 transition-transform ${open ? 'rotate-90' : ''}`}>›</span>
      </button>

      {open && (
        <div className="border-t border-zinc-800 p-3">
          {/* The record leads. It is the single most decision-relevant fact here. */}
          {rec && (
            <p className="mb-3 rounded border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[12px] leading-snug text-amber-200">
              <span className="font-bold">
                {rec.won} winners from {rec.settled} all time, net ${rec.net.toFixed(2)}.
              </span>{' '}
              {rec.note}
              {rec.where_the_edge_is && (
                <>
                  {' '}
                  <span className="text-amber-300/80">{rec.where_the_edge_is}</span>
                </>
              )}
            </p>
          )}

          {!data ? (
            <p className="text-[13px] text-zinc-500">Loading…</p>
          ) : !data.available ? (
            <p className="text-[13px] text-amber-300">{data.reason}</p>
          ) : combos.length === 0 ? (
            <p className="text-[13px] text-zinc-500">
              No combination is currently worth showing — every candidate is priced at or
              near full value.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {combos.map((c, i) => (
                <li key={i} className="rounded-md border border-zinc-800 bg-zinc-900 p-2.5">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <span className="text-lg font-extrabold tabular-nums text-emerald-300">
                      ${c.cost.toFixed(2)}
                    </span>
                    <span className="text-[12px] tabular-nums text-zinc-400">
                      to win ${c.max_profit.toFixed(2)}
                    </span>
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                        c.correlation === 'SAME_MATCH'
                          ? 'bg-sky-500/15 text-sky-300'
                          : 'bg-zinc-800 text-zinc-500'
                      }`}
                    >
                      {c.correlation === 'SAME_MATCH' ? 'one match' : 'separate matches'}
                    </span>
                    <span className="ml-auto text-[11px] tabular-nums text-zinc-600">
                      {c.independent_p != null
                        ? `implied ${(c.independent_p * 100).toFixed(1)}%`
                        : 'no joint probability — legs are correlated'}
                    </span>
                  </div>

                  <ul className="mt-1.5 flex flex-col gap-0.5 border-t border-zinc-800 pt-1.5">
                    {c.legs.map((l) => (
                      <li
                        key={l.ticker}
                        className="flex items-baseline justify-between gap-3 text-[13px]"
                      >
                        {/* title, not name: two legs on the same player are a match
                            market and a set market, and only the title says which. */}
                        <span className="min-w-0 truncate text-zinc-300">
                          {l.title || l.name}
                        </span>
                        <span className="shrink-0 tabular-nums text-zinc-400">
                          {Math.round(l.ask * 100)}¢
                          {l.hold_pct != null && l.hold_served > 0 && (
                            <span
                              className={`ml-2 ${
                                l.hold_verdict === 'INSUFFICIENT'
                                  ? 'text-amber-300'
                                  : 'text-zinc-600'
                              }`}
                            >
                              hold {Math.round(l.hold_pct)}% {l.hold_served}g
                            </span>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-[11px] text-zinc-600">
            Costs shown for {data?.size_contracts ?? 10} contracts. Paper research, not a
            recommendation.
          </p>
        </div>
      )}
    </section>
  )
}
