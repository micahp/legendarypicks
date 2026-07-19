// Honest loading / error / unavailable states for the curated plays board.

export function PlaysSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-live="polite">
      <div className="h-10 w-full animate-pulse rounded-lg bg-zinc-900/70" />
      <div className="h-6 w-2/3 animate-pulse rounded bg-zinc-900/70" />
      <div className="grid gap-4 sm:grid-cols-2">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-56 animate-pulse rounded-xl border border-zinc-800 bg-zinc-900/50" />
        ))}
      </div>
    </div>
  )
}

// True transport failure (not a 503 board state) — the request itself did not complete.
export function PlaysNetworkError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm">
      <div className="font-semibold text-rose-300">Couldn’t load the plays board</div>
      <p className="mt-1 text-zinc-400">
        The request didn’t complete. This is a connection problem, not a market signal — nothing here is
        current.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 rounded-lg border border-zinc-700 px-3 py-1.5 text-xs font-medium text-zinc-200 hover:border-zinc-500"
      >
        Try again
      </button>
    </div>
  )
}

// 503 with a structured `unavailable` body — the publisher has no safe snapshot to serve.
export function PlaysUnavailable({ reason, code, onRetry }: { reason: string; code: string; onRetry: () => void }) {
  return (
    <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm">
      <div className="flex items-center gap-2">
        <span className="rounded bg-rose-500/15 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-rose-300">
          Unavailable
        </span>
        <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">{code}</span>
      </div>
      <p className="mt-2 text-zinc-300">{reason}</p>
      <p className="mt-1 text-zinc-500">No curated plays are being served right now. Do not treat any prior board as current.</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 rounded-lg border border-zinc-700 px-3 py-1.5 text-xs font-medium text-zinc-200 hover:border-zinc-500"
      >
        Check again
      </button>
    </div>
  )
}
