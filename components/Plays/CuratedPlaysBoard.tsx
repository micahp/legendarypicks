import { useCallback, useEffect, useState } from 'react'
import {
  fetchPlaysBoard,
  isBoardAvailable,
  type PlaysBoardAvailable,
  type PlaysBoardResponse,
  type PlaysCategoryStatus,
} from '../../services/plays'
import { ageFromSeconds, localTime, categoryLabel, titleCase } from './format'
import CuratedPlayCard from './CuratedPlayCard'
import { PlaysSkeleton, PlaysNetworkError, PlaysUnavailable } from './States'

const BOARD_PILL: Record<PlaysBoardAvailable['board_status'], string> = {
  current: 'bg-emerald-500/15 text-emerald-300',
  stale: 'bg-amber-500/15 text-amber-300',
  archived: 'bg-zinc-700/40 text-zinc-300',
}

// A loud banner whenever the board is not `current` — the quotes are not executable.
function StalenessBanner({ b }: { b: PlaysBoardAvailable }) {
  if (b.board_status === 'current') return null
  const archived = b.board_status === 'archived'
  return (
    <div
      className={`rounded-lg border px-3 py-2 text-sm ${
        archived ? 'border-zinc-700 bg-zinc-800/40 text-zinc-300' : 'border-amber-500/30 bg-amber-500/5 text-amber-200'
      }`}
    >
      <span className="font-semibold">{archived ? 'Archived board' : 'Stale board'}</span> — {b.status_reason} Prices
      shown are indicative only; recheck the live quote at the trigger.
    </div>
  )
}

function CategoryRow({ c }: { c: PlaysCategoryStatus }) {
  const noPlay = c.status.startsWith('no_play')
  return (
    <div
      className={`flex flex-col gap-0.5 rounded-lg border px-3 py-2 sm:flex-row sm:items-baseline sm:gap-3 ${
        noPlay ? 'border-zinc-800/70 bg-zinc-900/30' : 'border-zinc-800 bg-zinc-900/60'
      }`}
    >
      <div className="flex min-w-[8.5rem] items-center gap-2">
        <span className={`text-sm font-semibold ${noPlay ? 'text-zinc-400' : 'text-zinc-100'}`}>
          {categoryLabel(c.category)}
        </span>
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
            noPlay ? 'bg-zinc-700/40 text-zinc-400' : 'bg-emerald-500/15 text-emerald-300'
          }`}
        >
          {noPlay ? 'No play' : titleCase(c.status)}
        </span>
      </div>
      <p className="text-[13px] leading-snug text-zinc-500">{c.note}</p>
    </div>
  )
}

function AvailableBoard({ b }: { b: PlaysBoardAvailable }) {
  const q = b.quote_status_counts
  const e = b.event_status_counts
  return (
    <div className="space-y-4">
      {/* status header */}
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className={`rounded px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider ${BOARD_PILL[b.board_status]}`}>
              {b.board_status}
            </span>
            <span className="text-sm font-semibold text-zinc-200">{b.scope.label}</span>
          </div>
          <span className="text-[11px] text-zinc-500">
            as of {localTime(b.as_of)} · published {localTime(b.published_at)} · {ageFromSeconds(b.board_age_seconds)}
          </span>
        </div>
        <p className="mt-2 text-[13px] text-zinc-400">{b.status_reason}</p>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-500">
          <span>{b.plays.length} conditional {b.plays.length === 1 ? 'play' : 'plays'}</span>
          <span>quotes: {q.current} current · {q.stale} stale · {q.unavailable} none</span>
          <span>windows: {e.open_window} open · {e.expired} passed</span>
          <span>
            freshness: quote {b.freshness_policy.quote_stale_after_seconds}s · board{' '}
            {Math.round(b.freshness_policy.board_stale_after_seconds / 60)}m
          </span>
        </div>
        {b.quote_refresh ? (
          <p className="mt-2 text-[11px] text-emerald-400/80">
            Quotes refreshed {localTime(b.quote_refresh.refreshed_at)} from the shared feed —{' '}
            {b.quote_refresh.refreshed} updated
            {b.quote_refresh.unavailable ? `, ${b.quote_refresh.unavailable} unavailable` : ''}. Selection
            analysis is unchanged.
          </p>
        ) : null}
      </div>

      <StalenessBanner b={b} />

      {/* category status incl. explicit no-play rows */}
      {b.category_status.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Category read</h2>
          <div className="space-y-1.5">
            {b.category_status.map((c) => (
              <CategoryRow key={c.category} c={c} />
            ))}
          </div>
        </section>
      )}

      {/* conditional plays */}
      <section className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Conditional plays — {b.risk_definition}
        </h2>
        {b.plays.length === 0 ? (
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-400">
            No conditional plays on the board for this window. That is a legitimate no-play result, not an error.
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {b.plays.map((p) => (
              <CuratedPlayCard key={p.ticker} p={p} />
            ))}
          </div>
        )}
      </section>

      {/* limitations */}
      {b.limitations.length > 0 && (
        <details className="rounded-lg border border-zinc-800 bg-zinc-900/30 px-3 py-2 text-[12px] text-zinc-500">
          <summary className="cursor-pointer font-medium text-zinc-400">Limitations &amp; caveats</summary>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {b.limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

export default function CuratedPlaysBoard() {
  const [board, setBoard] = useState<PlaysBoardResponse | null>(null)
  const [status, setStatus] = useState<'loading' | 'error' | 'ready'>('loading')

  const load = useCallback((signal?: AbortSignal) => {
    setStatus('loading')
    fetchPlaysBoard({ signal })
      .then((b) => {
        setBoard(b)
        setStatus('ready')
      })
      .catch((err) => {
        if (signal?.aborted || err?.name === 'CanceledError' || err?.name === 'AbortError') return
        setStatus('error')
      })
  }, [])

  useEffect(() => {
    const ac = new AbortController()
    load(ac.signal)
    return () => ac.abort()
  }, [load])

  if (status === 'loading') return <PlaysSkeleton />
  if (status === 'error' || !board) return <PlaysNetworkError onRetry={() => load()} />
  if (!isBoardAvailable(board)) {
    return <PlaysUnavailable reason={board.status_reason} code={board.error_code} onRetry={() => load()} />
  }
  return <AvailableBoard b={board} />
}
