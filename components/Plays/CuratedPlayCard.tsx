import type { CuratedPlay } from '../../services/plays'
import { cents, money, ageFromSeconds, localTime, categoryLabel, confidenceLabel } from './format'

function QuotePill({ status, age }: { status: CuratedPlay['quote_status']; age: number | null }) {
  const map = {
    current: 'bg-emerald-500/15 text-emerald-300',
    stale: 'bg-amber-500/15 text-amber-300',
    unavailable: 'bg-zinc-700/40 text-zinc-400',
  } as const
  const label = status === 'current' ? 'Current quote' : status === 'stale' ? 'Stale quote' : 'No quote'
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${map[status]}`}>
      {label}
      {status !== 'unavailable' && age != null ? ` · ${ageFromSeconds(age)}` : ''}
    </span>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">{label}</div>
      <p className="mt-0.5 text-sm leading-snug text-zinc-300">{children}</p>
    </div>
  )
}

export default function CuratedPlayCard({ p }: { p: CuratedPlay }) {
  const isYes = p.side === 'YES'
  const expired = p.event_status === 'expired'
  const noStop = p.stop_price === 0

  return (
    <article
      className={`rounded-xl border bg-zinc-900/70 p-4 ${expired ? 'border-zinc-800 opacity-70' : 'border-zinc-800'}`}
    >
      {/* header */}
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-zinc-300">
            {categoryLabel(p.category)}
          </span>
          <span
            className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
              isYes ? 'bg-emerald-500/15 text-emerald-300' : 'bg-rose-500/15 text-rose-300'
            }`}
          >
            {p.side}
          </span>
        </div>
        <span className="text-right text-[10px] font-medium uppercase tracking-wider text-zinc-400">
          {confidenceLabel(p.confidence)}
        </span>
      </div>

      <h3 className="text-base font-semibold text-zinc-100">{p.title}</h3>
      <div className="mt-0.5 font-mono text-[10px] uppercase tracking-wider text-zinc-500">{p.ticker}</div>

      {/* conditional banner — this is never a pregame buy */}
      <div className="mt-3 rounded-lg border border-amber-500/25 bg-amber-500/5 px-2.5 py-1.5 text-[11px] leading-snug text-amber-200/90">
        Conditional — wait for the exact trigger below. No pregame buy; paper research only.
      </div>

      {/* quote row */}
      <div className="mt-3 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-bold tabular-nums text-zinc-100">{cents(p.current_price)}</span>
          <span className="text-xs text-zinc-500">
            bid {cents(p.current_bid)} / ask {cents(p.current_ask)}
          </span>
        </div>
        <QuotePill status={p.quote_status} age={p.quote_age_seconds} />
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 text-[11px] text-zinc-500">
        <span>depth {money(p.current_bid_depth)} / {money(p.current_ask_depth)}</span>
        <span>as of {localTime(p.price_as_of)}</span>
        {p.quote_source ? <span>via {p.quote_source === 'kalshi_shared_feed' ? 'shared feed' : p.quote_source}</span> : null}
      </div>

      {/* the plan — exact numbers */}
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Plan label="Entry ≤" value={cents(p.entry_price)} accent />
        <Plan label="Stop" value={noStop ? 'none' : cents(p.stop_price)} sub={noStop ? 'swing exit' : undefined} />
        <Plan label="Target" value={cents(p.target_price)} />
        <Plan label="Reward" value={`${p.r_target}R`} accent />
      </div>

      {/* the read */}
      <div className="mt-3 space-y-2.5 border-t border-zinc-800 pt-3">
        <Field label="Thesis">{p.thesis}</Field>
        <Field label="Entry trigger">{p.entry_condition}</Field>
        <Field label="No entry if">{p.invalidation}</Field>
        <Field label="Exit">{p.exit_rule}</Field>
      </div>

      {/* resolution */}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-zinc-800 pt-2 text-[11px]">
        <span className="text-zinc-500">
          Resolves {localTime(p.resolves_at)} — {p.resolves_at_note}
        </span>
        <span className="flex items-center gap-1.5">
          {p.market_status ? (
            <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-zinc-400">
              {p.market_status}
            </span>
          ) : null}
          {expired ? (
            <span className="rounded bg-rose-500/15 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-rose-300">
              Window passed
            </span>
          ) : (
            <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-300">
              Window open
            </span>
          )}
        </span>
      </div>
    </article>
  )
}

function Plan({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div className="rounded-lg bg-zinc-950/50 px-2 py-1.5 text-center">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">{label}</div>
      <div className={`text-sm font-bold tabular-nums ${accent ? 'text-emerald-300' : 'text-zinc-200'}`}>{value}</div>
      {sub ? <div className="text-[9px] uppercase tracking-wider text-zinc-600">{sub}</div> : null}
    </div>
  )
}
