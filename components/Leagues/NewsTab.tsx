import { LeagueSection } from '../News/LeagueSection'
import type { LeagueNews } from '../News/LeagueSection'

/**
 * The league hub's News tab.
 *
 * This renders the News page's own `LeagueSection` — the same component that
 * page uses for its per-league tab — so the two surfaces are identical by
 * construction and cannot drift. Loading and error states are the hub's, since
 * the hub fetches; everything below them is the News page's.
 */
export default function NewsTab({
  league,
  news,
  loading,
  error,
}: {
  league: string
  news: LeagueNews | null
  loading: boolean
  error: string | null
}) {
  if (error) {
    return (
      <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-400">
        {error}
      </div>
    )
  }
  if (loading) return <NewsSkeleton />

  return (
    <LeagueSection
      league={league}
      data={news ?? { conversations: [], narratives: [], granular: [], other: 0 }}
    />
  )
}

function NewsSkeleton() {
  return (
    <div className="space-y-3">
      {[0, 1, 2].map(row => (
        <div key={row} className="rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-3">
          <div className="h-3 w-1/3 animate-pulse rounded bg-zinc-800" />
          <div className="mt-2 h-3 w-3/4 animate-pulse rounded bg-zinc-800" />
        </div>
      ))}
    </div>
  )
}
