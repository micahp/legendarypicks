import Head from 'next/head'
import { useCallback, useEffect, useState } from 'react'

// /live-discounts — the buy-only markdown board, on its own route.
//
// This is deliberately NOT /plays: next.config.js redirects /plays -> /props, which is why
// the live surface effectively disappeared. This route is unaffected by that redirect.
//
// Data: GET /api/live/swing-board, published by swing_board.py in the trading repo from the
// Kalshi tape. The score ranks *fadeable markdowns* — a side marked down hard that still has
// resting bids under it and whose sell flow has stopped. It is not a win probability, and it
// is buy-only; no card is ever a short.

const POLL_MS = 20000

// Sort options. Each names the field it orders by and how a card MISSING that field is
// treated — always last, never as a zero, because "this model had nothing to say" and
// "this model scored it zero" are different statements and collapsing them would quietly
// promote unscored cards into the middle of the board.
const SORTS = [
  { id: 'wyckoff', label: 'Wyckoff', desc: 'book structure — absorption, test, demand, exit liquidity',
    get: (c: Card) => c.wyckoff_score },
  { id: 'turn', label: 'Turn', desc: 'price turned back up off its window low', get: (c: Card) => c.turn_score },
  { id: 'fade', label: 'Fade', desc: 'size of the markdown from the window high', get: (c: Card) => c.fade_score },
  { id: 'context', label: 'Game context', desc: 'reversibility, momentum, break point — tennis only',
    get: (c: Card) => c.context_score ?? null },
  { id: 'liquidity', label: 'Exit liquidity', desc: 'resting bid depth — who buys when you sell',
    get: (c: Card) => c.yes_depth ?? null },
  { id: 'cheapest', label: 'Cheapest', desc: 'lowest ask first', get: (c: Card) => (c.price != null ? -c.price : null) },
  { id: 'breakpoint', label: 'Break point', desc: 'a break is pending — the market is about to move',
    get: (c: Card) => (c.context_flags?.break_point_pending ? (c.context_score ?? 1) : null) },
] as const
type SortId = (typeof SORTS)[number]['id']

type TurnComponents = { rise: number; at_high: number; band: number; support: number; flow: number }
type FadeComponents = { drop: number; band: number; support: number; exhaust: number }
type UsOpen = {
  match_id: string
  event: string
  round: string
  court: string
  opponent: string
  sets_mine: number | null
  sets_theirs: number | null
  point_score: { mine: string | null; theirs: string | null }
  momentum: { mine: string | null; theirs: string | null } | null
  last_break: {
    set: string; game: string; seconds_ago: number
    for_this_player: boolean; sentence: string
  } | null
  last_point: string | null
  duration: string | null
  best_of: number
}
type Card = {
  ticker: string
  series: string
  sport: string
  event: string
  model: 'wyckoff' | 'turn' | 'fade'
  wyckoff_score: number | null
  wyckoff_components: { absorption: number; test: number; demand: number; exit_liquidity: number; holding_range: number } | null
  wyckoff_reason: string | null
  wyckoff_facts?: Record<string, number | string | null>
  name: string | null
  opponent: string | null
  matchup: string | null
  market_title: string | null
  score: number
  turn_score: number | null
  turn_components: TurnComponents | null
  fade_score: number | null
  fade_components: FadeComponents | null
  price: number
  bid: number
  spread: number
  window_low: number | null
  window_high: number | null
  rise_pct_off_low: number | null
  markdown: number | null
  yes_depth: number
  no_depth: number
  imbalance: number | null
  volume: number | null
  open_interest: number | null
  samples: number
  window_min: number
  tape_age_s: number
  usopen?: UsOpen | null
  context_score?: number | null
  context_components?: { reversibility: number; momentum: number; break_point: number } | null
  context_flags?: {
    break_point_pending?: boolean
    break_point_for_me?: boolean
    break_point_against_me?: boolean
    serving?: boolean
    sets_deficit?: number
    best_of?: number
    move_imminent?: boolean
    point_state?: string | null
  } | null
}
type Board = {
  available: boolean
  reason?: string
  generated_at?: string
  stale?: boolean
  age_seconds?: number | null
  window_min?: number
  tickers_live?: number
  candidates?: number
  ranked_by?: string
  usopen_matched?: number
  usopen_unmatched?: number
  cards?: Card[]
  by_sport?: Record<string, number>
  weights?: Record<string, number>
  limitations?: string[]
}

function pct(n: number) {
  return `${Math.round(n * 100)}%`
}

function cents(n: number) {
  return `${Math.round(n * 100)}¢`
}

// Kalshi publishes the real name on every market (yes_sub_title), resolved server-side into
// name/opponent. Never decode the ticker for a label — "SHEHUR-HUR" is not readable, and
// splitting player codes out of a ticker mis-resolves the moment two players share a prefix.
// The ticker stays on the card, but as provenance underneath, not as the headline.
function label(card: Card) {
  const side = card.name || card.ticker.split('-').pop() || card.ticker
  return { side, opponent: card.opponent || null }
}

function Bar({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-16 shrink-0 text-[11px] uppercase tracking-wider text-zinc-500">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-zinc-800">
        <div
          className="h-full rounded-full bg-emerald-500/70"
          style={{ width: `${Math.max(2, Math.min(100, value * 100))}%` }}
        />
      </div>
      <span className="w-8 shrink-0 text-right text-[11px] tabular-nums text-zinc-400">
        {Math.round(value * 100)}
      </span>
    </div>
  )
}

export default function LiveDiscountsPage() {
  const [board, setBoard] = useState<Board | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lastFetch, setLastFetch] = useState<Date | null>(null)
  const [sortId, setSortId] = useState<SortId>('wyckoff')

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/live/swing-board', { cache: 'no-store' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setBoard(json)
      setError(null)
      setLastFetch(new Date())
    } catch (e) {
      // Keep the last good board on screen rather than blanking it; say the refresh failed.
      setError('Refresh failed — showing the last board received.')
    }
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, POLL_MS)
    return () => clearInterval(id)
  }, [load])

  const sort = SORTS.find((s) => s.id === sortId) ?? SORTS[0]
  const raw = board?.cards ?? []
  // Cards with no value for the active sort keep their server order and sit at the end.
  const scored = raw.filter((c) => sort.get(c) != null)
  const unscored = raw.filter((c) => sort.get(c) == null)
  const cards = [...scored].sort((a, b) => (sort.get(b) as number) - (sort.get(a) as number)).concat(unscored)
  const top = cards[0]

  return (
    <>
      <Head>
        <title>Live Discounts — Legendary Picks</title>
        <meta
          name="description"
          content="Buy-only markdown fades ranked live off the Kalshi tape. Paper research only."
        />
      </Head>

      <div className="space-y-6">
        <header className="space-y-3">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-100">Live Discounts</h1>
            <div className="flex items-center gap-2 text-xs">
              {board?.stale ? (
                <span className="rounded-full border border-red-500/40 bg-red-500/10 px-2 py-0.5 font-semibold text-red-300">
                  STALE — tape stopped
                </span>
              ) : board?.available ? (
                <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 font-semibold text-emerald-300">
                  LIVE
                </span>
              ) : null}
              {typeof board?.age_seconds === 'number' && (
                <span className="tabular-nums text-zinc-500">board {Math.round(board.age_seconds)}s old</span>
              )}
              {lastFetch && (
                <span className="tabular-nums text-zinc-600">
                  polled {lastFetch.toLocaleTimeString()}
                </span>
              )}
            </div>
          </div>

          <p className="max-w-3xl text-sm leading-relaxed text-zinc-400">
            Buy-only markdown fades, ranked off the live Kalshi tape. A card means one thing: this side
            has just been marked down hard, there are still resting bids under it, and the selling that
            caused the markdown has stopped. Fade the overreaction, exit into the swing. Nothing here is
            a short, and nothing here is a pregame buy.
          </p>

          <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[13px] text-amber-200">
            <span className="font-semibold">Paper research only.</span> Scores rank fadeable markdowns —
            they are not win probabilities. Depth is resting size, not a guaranteed fill.
          </div>
        </header>

        {/* Sort controls. The active sort is stated in words below the row, not left to be
            inferred from the order — three models publish three different scales, so "what
            is this ranked by" is a question the page must answer outright. */}
        <div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
              Sort
            </span>
            {SORTS.map((s) => (
              <button
                key={s.id}
                onClick={() => setSortId(s.id)}
                aria-pressed={sortId === s.id}
                title={s.desc}
                className={`rounded-full border px-2.5 py-1 text-xs font-semibold transition-colors ${
                  sortId === s.id
                    ? 'border-emerald-500/60 bg-emerald-500/15 text-emerald-300'
                    : 'border-zinc-700 bg-zinc-900 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200'
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[13px] text-zinc-400">
            Sorted by <span className="font-semibold text-emerald-300">{sort.label}</span>
            <span className="text-zinc-500"> — {sort.desc}.</span>{' '}
            {unscored.length > 0 && (
              <span className="text-zinc-500">
                {scored.length} card{scored.length === 1 ? '' : 's'} scored;{' '}
                <span className="text-amber-300/90">{unscored.length}</span> with no{' '}
                {sort.label.toLowerCase()} read {unscored.length === 1 ? 'is' : 'are'} listed
                last, not ranked as zero.
              </span>
            )}
          </p>
        </div>

        {/* scoreboard strip */}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            ['Candidates', board?.candidates ?? 0],
            ['Markets on tape', board?.tickers_live ?? 0],
            ['Window', `${board?.window_min ?? 25} min`],
            ['Top score', top ? top.score.toFixed(1) : '—'],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2">
              <div className="text-[11px] uppercase tracking-wider text-zinc-500">{label}</div>
              <div className="text-lg font-bold tabular-nums text-zinc-100">{value}</div>
            </div>
          ))}
        </div>

        {board?.by_sport && Object.keys(board.by_sport).length > 0 && (
          <div className="flex flex-wrap gap-2">
            {Object.entries(board.by_sport).map(([sport, n]) => (
              <span
                key={sport}
                className="rounded-full border border-zinc-700 bg-zinc-900 px-2.5 py-0.5 text-xs text-zinc-400"
              >
                {sport} <span className="tabular-nums text-zinc-200">{n}</span>
              </span>
            ))}
          </div>
        )}

        {error && (
          <p className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </p>
        )}

        {board && !board.available && (
          <p className="rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-6 text-sm text-zinc-500">
            No board published yet. {board.reason}
          </p>
        )}

        {board?.available && cards.length === 0 && (
          <p className="rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-6 text-sm text-zinc-500">
            No markdown clears the bar right now across {board.tickers_live ?? 0} markets on tape. This is
            an honest empty — a market with no recent tape is omitted, not scored as calm.
          </p>
        )}

        <div className="space-y-3">
          {cards.map((card, i) => {
            const { side, opponent } = label(card)
            return (
              <article
                key={card.ticker}
                className={`rounded-lg border bg-zinc-900 p-4 ${
                  i === 0 ? 'border-emerald-500/40' : 'border-zinc-800'
                }`}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
                        {card.sport}
                      </span>
                      <span
                        className={`rounded px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider ${
                          card.model === 'turn'
                            ? 'bg-sky-500/15 text-sky-300'
                            : 'bg-zinc-700/40 text-zinc-400'
                        }`}
                        title={
                          card.model === 'turn'
                            ? 'Markdown that has bottomed and turned back up — the shape the account actually trades'
                            : 'Markdown only. v1 model, kept for comparison; it missed the reference trade.'
                        }
                      >
                        {card.model}
                      </span>
                      {i === 0 && (
                        <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-emerald-400">
                          Best on board
                        </span>
                      )}
                    </div>
                    <h2 className="mt-1.5 text-base font-bold leading-snug text-zinc-100">
                      {side}
                      {opponent && (
                        <span className="font-normal text-zinc-500"> vs {opponent}</span>
                      )}
                    </h2>
                    {card.market_title && (
                      <p className="mt-0.5 text-[12px] text-zinc-500">{card.market_title}</p>
                    )}
                    <p className="mt-0.5 font-mono text-[10px] text-zinc-700">{card.ticker}</p>
                  </div>
                  <div className="text-right">
                    {/* All three technical models, always. Which one is ranking the board is
                        highlighted; a model with nothing to say shows a dash, never a zero. */}
                    {(
                      [
                        ['wyckoff', 'Wyckoff', card.wyckoff_score],
                        ['turn', 'Turn', card.turn_score],
                        ['fade', 'Fade', card.fade_score],
                      ] as const
                    ).map(([id, lbl, val]) => {
                      const active = sortId === id
                      return (
                        <div
                          key={id}
                          className={`flex items-baseline justify-end gap-2 ${active ? '' : 'opacity-55'}`}
                        >
                          <span className="text-[10px] uppercase tracking-wider text-zinc-500">
                            {lbl}
                          </span>
                          <span
                            className={`tabular-nums ${
                              active
                                ? 'text-xl font-extrabold text-emerald-400'
                                : 'text-sm font-semibold text-zinc-400'
                            }`}
                          >
                            {val == null ? '—' : val.toFixed(1)}
                          </span>
                        </div>
                      )
                    })}
                    {/* Context is its own axis, never averaged into the technical score:
                        the tape can look clean in a decided match, and a match can be
                        poised with no bid to sell into. A blend hides which you have. */}
                    {card.context_score != null && (
                      <div className="mt-2 border-t border-zinc-800 pt-1.5">
                        <div className="text-xl font-extrabold tabular-nums text-sky-300">
                          {card.context_score.toFixed(1)}
                        </div>
                        <div className="text-[11px] uppercase tracking-wider text-zinc-500">
                          game context
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* the trade, in the terms it is actually taken */}
                <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-sm">
                  <span className="text-zinc-300">
                    Buy <span className="font-bold tabular-nums text-zinc-100">{cents(card.price)}</span>
                  </span>
                  {card.model === 'turn' && card.window_low != null ? (
                    <>
                      <span className="text-zinc-500">
                        bottomed at{' '}
                        <span className="tabular-nums text-zinc-300">{cents(card.window_low)}</span>, turning
                        back up over {card.window_min}m
                      </span>
                      <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-xs font-semibold tabular-nums text-emerald-300">
                        +{card.rise_pct_off_low}% off the low
                      </span>
                    </>
                  ) : (
                    <span className="text-zinc-500">
                      marked down from{' '}
                      <span className="tabular-nums text-zinc-300">
                        {card.window_high != null ? cents(card.window_high) : '—'}
                      </span>{' '}
                      in {card.window_min}m
                    </span>
                  )}
                  <span className="text-xs tabular-nums text-zinc-500">spread {cents(card.spread)}</span>
                </div>

                {/* WHY it moved. The tape says a price fell; only match state says whether
                    that is reversible. A break at 4-4 is recoverable inside the set; two
                    sets down in a best-of-three is not — and best-of-five is the whole
                    reason the US Open is the richest venue for this. */}
                {/* THE leading signal. Everything else on this card describes what already
                    happened; a pending break point describes what is about to. A serve break
                    is the largest reversible price event in tennis, so the market moves at
                    the moment a break becomes possible, not after it lands. ~5% of points. */}
                {card.context_flags?.break_point_pending && (
                  <div
                    className={`mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2 ${
                      card.context_flags.break_point_for_me
                        ? 'border-emerald-400/50 bg-emerald-500/10'
                        : 'border-red-400/50 bg-red-500/10'
                    }`}
                  >
                    <span
                      className={`text-[11px] font-bold uppercase tracking-widest ${
                        card.context_flags.break_point_for_me ? 'text-emerald-300' : 'text-red-300'
                      }`}
                    >
                      ⚡ Break point {card.context_flags.break_point_for_me ? 'FOR' : 'AGAINST'}
                    </span>
                    <span className="text-[13px] text-zinc-200">
                      {card.context_flags.break_point_for_me
                        ? 'Favourite is about to be broken — the market moves here.'
                        : 'This player is about to be broken — adverse move imminent.'}
                    </span>
                    {card.context_flags.point_state && (
                      <span className="text-[11px] tabular-nums text-zinc-400">
                        {card.context_flags.point_state}
                      </span>
                    )}
                  </div>
                )}

                {card.usopen && (
                  <div className="mt-3 rounded-md border border-sky-500/25 bg-sky-500/5 px-3 py-2">
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
                      <span className="font-semibold text-sky-300">
                        Sets {card.usopen.sets_mine}–{card.usopen.sets_theirs}
                      </span>
                      {card.usopen.point_score?.mine != null && (
                        <span className="text-zinc-300">
                          Point{' '}
                          <span className="font-bold tabular-nums text-zinc-100">
                            {card.usopen.point_score.mine}–{card.usopen.point_score.theirs}
                          </span>
                        </span>
                      )}
                      {card.usopen.momentum?.mine != null && (
                        <span
                          className="text-zinc-400"
                          title="IBM SlamTracker momentum, published per point"
                        >
                          Momentum{' '}
                          <span
                            className={`font-bold tabular-nums ${
                              Number(card.usopen.momentum.mine) >=
                              Number(card.usopen.momentum.theirs)
                                ? 'text-emerald-400'
                                : 'text-red-400'
                            }`}
                          >
                            {card.usopen.momentum.mine}
                          </span>
                          <span className="text-zinc-600"> vs {card.usopen.momentum.theirs}</span>
                        </span>
                      )}
                      <span className="text-[11px] uppercase tracking-wider text-zinc-500">
                        Best of {card.usopen.best_of}
                      </span>
                      {card.usopen.duration && (
                        <span className="text-[11px] tabular-nums text-zinc-600">
                          {card.usopen.duration}
                        </span>
                      )}
                    </div>

                    {card.usopen.last_break && (
                      <p
                        className={`mt-1.5 text-[12px] ${
                          card.usopen.last_break.for_this_player
                            ? 'text-emerald-300'
                            : 'text-red-300'
                        }`}
                      >
                        Break {Math.round(card.usopen.last_break.seconds_ago / 60)}m ago (set{' '}
                        {card.usopen.last_break.set}, game {card.usopen.last_break.game}) —{' '}
                        {card.usopen.last_break.sentence}
                      </p>
                    )}
                    {card.usopen.last_point && !card.usopen.last_break && (
                      <p className="mt-1.5 text-[12px] text-zinc-500">
                        {card.usopen.last_point}
                      </p>
                    )}
                  </div>
                )}

                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    {card.wyckoff_components ? (
                      <>
                        <Bar label="Absorb" value={card.wyckoff_components.absorption} />
                        <Bar label="Test" value={card.wyckoff_components.test} />
                        <Bar label="Demand" value={card.wyckoff_components.demand} />
                        <Bar label="Exit liq" value={card.wyckoff_components.exit_liquidity} />
                        <Bar label="In range" value={card.wyckoff_components.holding_range} />
                      </>
                    ) : card.turn_components ? (
                      <>
                        <Bar label="Rise" value={card.turn_components.rise} />
                        <Bar label="At high" value={card.turn_components.at_high} />
                        <Bar label="Band" value={card.turn_components.band} />
                        <Bar label="Support" value={card.turn_components.support} />
                        <Bar label="Flow" value={card.turn_components.flow} />
                      </>
                    ) : card.fade_components ? (
                      <>
                        <Bar label="Drop" value={card.fade_components.drop} />
                        <Bar label="Band" value={card.fade_components.band} />
                        <Bar label="Support" value={card.fade_components.support} />
                        <Bar label="Exhaust" value={card.fade_components.exhaust} />
                      </>
                    ) : null}
                    {!card.wyckoff_components && card.wyckoff_reason && (
                      <p className="pt-1 text-[11px] leading-snug text-zinc-600">
                        No Wyckoff read: {card.wyckoff_reason}
                      </p>
                    )}
                  </div>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                    <div className="flex justify-between border-b border-zinc-800/70 pb-1">
                      <dt className="text-zinc-500">Bid depth</dt>
                      <dd className="tabular-nums text-zinc-300">
                        {Math.round(card.yes_depth).toLocaleString()}
                      </dd>
                    </div>
                    <div className="flex justify-between border-b border-zinc-800/70 pb-1">
                      <dt className="text-zinc-500">Other side</dt>
                      <dd className="tabular-nums text-zinc-300">
                        {Math.round(card.no_depth).toLocaleString()}
                      </dd>
                    </div>
                    <div className="flex justify-between border-b border-zinc-800/70 pb-1">
                      <dt className="text-zinc-500">Support</dt>
                      <dd className="tabular-nums text-zinc-300">
                        {pct(
                          card.turn_components?.support ?? card.fade_components?.support ?? 0
                        )}
                      </dd>
                    </div>
                    <div className="flex justify-between border-b border-zinc-800/70 pb-1">
                      <dt className="text-zinc-500">Open int.</dt>
                      <dd className="tabular-nums text-zinc-300">
                        {card.open_interest ? Math.round(card.open_interest).toLocaleString() : '—'}
                      </dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-zinc-500">Tape age</dt>
                      <dd className="tabular-nums text-zinc-300">{card.tape_age_s}s</dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-zinc-500">Samples</dt>
                      <dd className="tabular-nums text-zinc-300">{card.samples}</dd>
                    </div>
                  </dl>
                </div>
              </article>
            )
          })}
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
