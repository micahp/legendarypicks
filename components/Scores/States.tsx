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

export function EmptyState() {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-6 text-zinc-300">
      No games scheduled for this date.
    </div>
  )
}


