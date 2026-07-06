import { useEffect, useState } from 'react'
import Link from 'next/link'

// "Cheap Quality, Live" — the trading strategy as a surface (docs/SPEC-live-discounts-widget.md).
// DISCOUNT = quality team in an early reversible dip; WITCHING_HOUR = close game, late.
// Live Kalshi prices vs pregame; knife tag = still falling vs stabilizing (entry-timing lesson).

type Card = {
  cls: 'DISCOUNT' | 'WITCHING_HOUR' | 'PREPRICED'
  league: string; game_id: string; matchup: string
  team: string; opp: string; team_name?: string
  score: string; inning: number; status_detail?: string
  price: number; pregame?: number | null; spark: number[]
  knife: 'falling' | 'stabilizing'
  rank?: number | null; opp_rank?: number | null; last10?: string | null; streak?: string | null
  evidence?: string | null
  wp?: number | null; edge?: number | null
  level?: number | null; level_k?: number | null
}
type Payload = {
  cards: Card[]
  upcoming: { matchup: string; start: string; fav?: string | null; fav_price?: number | null }[]
}

const POLL_MS = 45_000
const cents = (p?: number | null) => (p == null ? '—' : `${Math.round(p * 100)}¢`)

function Spark({ pts }: { pts: number[] }) {
  if (pts.length < 2) return null
  const min = Math.min(...pts), max = Math.max(...pts), span = max - min || 0.01
  const d = pts.map((p, i) =>
    `${i === 0 ? 'M' : 'L'}${(i / (pts.length - 1)) * 60},${18 - ((p - min) / span) * 16}`).join(' ')
  return (
    <svg width="60" height="20" className="shrink-0 opacity-80" aria-hidden>
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  )
}

function DiscountCard({ c }: { c: Card }) {
  const isDip = c.cls === 'DISCOUNT'
  const isPre = c.cls === 'PREPRICED'
  return (
    <Link href={`/game/${c.league.toLowerCase()}/${c.game_id}`}
          className="block min-w-[240px] flex-1 rounded-xl border border-zinc-800 bg-zinc-900/70 p-3 transition-colors hover:border-zinc-600">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
          isDip ? 'bg-emerald-500/15 text-emerald-300'
          : isPre ? 'bg-amber-500/15 text-amber-300' : 'bg-violet-500/15 text-violet-300'}`}>
          {isDip ? 'Discount' : isPre ? 'Pre-priced' : 'Witching hour'}
        </span>
        <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">
          {c.league} · {c.status_detail || `inning ${c.inning}`}
        </span>
      </div>
      <div className="flex items-baseline justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate font-semibold text-zinc-100">{c.team_name || c.team}</div>
          <div className="font-mono text-xs tabular-nums text-zinc-400">{c.matchup} · {c.score}</div>
        </div>
        <div className="text-right">
          <div className="font-mono text-2xl font-bold tabular-nums text-zinc-50">{cents(c.price)}</div>
          {c.wp != null ? (
            <div className="font-mono text-[11px] tabular-nums text-emerald-300">live WP {Math.round(c.wp * 100)}%</div>
          ) : null}
          {c.pregame != null ? (
            <div className="font-mono text-[11px] tabular-nums text-zinc-500">was {cents(c.pregame)}</div>
          ) : null}
        </div>
      </div>
      {c.evidence ? (
        <div className="mt-1.5 text-[12px] font-medium text-emerald-300">🔥 {c.evidence}</div>
      ) : null}
      {c.cls === 'PREPRICED' && c.level != null ? (
        <div className="mt-1.5 text-[12px] font-medium text-amber-300">
          touched the {cents(c.level)} level set pregame{c.level_k && c.pregame != null ? ` (${c.level_k}× of ${cents(c.pregame)})` : ''}
        </div>
      ) : null}
      <div className="mt-2 flex items-center justify-between gap-2 text-[11px]">
        <span className={c.knife === 'falling' ? 'font-medium text-red-400' : 'text-zinc-500'}>
          {c.knife === 'falling' ? '▼ still falling' : '· stabilizing'}
        </span>
        <span className={c.knife === 'falling' ? 'text-red-400/70' : 'text-zinc-600'}>
          <Spark pts={c.spark} />
        </span>
        {c.rank && c.opp_rank ? (
          <span className="font-mono text-zinc-500">
            #{c.rank} vs #{c.opp_rank}{c.last10 ? ` · L10 ${c.last10}` : ''}{c.streak ? ` · ${c.streak}` : ''}
          </span>
        ) : null}
      </div>
    </Link>
  )
}

export default function LiveDiscounts({ league = 'mlb,wc' }: { league?: string }) {
  const [data, setData] = useState<Payload | null>(null)
  useEffect(() => {
    let ignore = false
    const load = async () => {
      try {
        const r = await fetch(`/api/live/discounts?league=${league}`, { cache: 'no-store' })
        if (r.ok && !ignore) setData(await r.json())
      } catch { /* keep last */ }
    }
    load()
    const t = setInterval(load, POLL_MS)
    return () => { ignore = true; clearInterval(t) }
  }, [league])

  if (!data) return null
  const { cards, upcoming } = data

  // No live cards -> render NOTHING (Micah 2026-07-06): an empty-state bar is noise on a
  // scoreboard; the widget earns its space only when it has something to say.
  if (cards.length === 0) return null

  return (
    <div className="space-y-3 rounded-2xl border border-amber-500/20 bg-amber-500/[0.04] p-4 sm:p-5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-amber-400">
          ⚡ Cheap quality, live
        </span>
        <span className="hidden text-[11px] text-zinc-500 sm:block">
          quality teams at a discount · close games late · live Kalshi prices
        </span>
      </div>
      <div className="flex flex-wrap gap-3">
        {cards.map((c) => <DiscountCard key={`${c.game_id}-${c.cls}-${c.team}`} c={c} />)}
      </div>
    </div>
  )
}
