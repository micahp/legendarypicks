export function SkeletonList() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 animate-pulse">
          <div className="h-3 w-24 bg-zinc-800 rounded mb-3" />
          <div className="h-5 w-2/3 bg-zinc-800 rounded mb-2" />
          <div className="h-5 w-1/2 bg-zinc-800 rounded" />
        </div>
      ))}
    </div>
  )
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-red-500/40 bg-red-950/40 text-red-200 px-4 py-3">
      {message}
    </div>
  )
}

export function EmptyState({ leagueFilter, onViewAll }: { leagueFilter?: string; onViewAll?: () => void }) {
  const isFiltered = leagueFilter && leagueFilter !== 'All'
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-6 text-zinc-300 space-y-4">
      <p>No games scheduled for this date{isFiltered ? ` in ${leagueFilter}` : ''}.</p>
      {isFiltered && onViewAll && (
        <button
          onClick={onViewAll}
          className="px-4 py-2 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-sm font-medium hover:bg-emerald-500/20 transition-colors"
        >
          View All Leagues
        </button>
      )}
    </div>
  )
}


