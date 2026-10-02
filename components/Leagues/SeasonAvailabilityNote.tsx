import type { LeagueReadiness } from '../../lib/leagueReadiness'
import { seasonLabel } from './presentation'

export default function SeasonAvailabilityNote({
  league,
  readiness,
}: {
  league: string
  readiness: LeagueReadiness | null
}) {
  const stats = readiness?.checks?.player_stats
  if (
    league !== 'nhl'
    || !readiness
    || !['preseason', 'upcoming'].includes(readiness.phase)
    || stats?.status !== 'pending'
  ) return null

  const season = seasonLabel(league, readiness.expected_season)
  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/40 px-4 py-3">
      <p className="text-sm font-medium text-zinc-200">
        {season} regular-season stats are not available yet.
      </p>
      <p className="mt-1 text-xs text-zinc-500">
        Historical seasons remain available below.
      </p>
    </section>
  )
}
