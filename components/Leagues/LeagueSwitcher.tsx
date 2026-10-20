import Link from 'next/link'
import { leagueNavigationLabel, useSportNavigation } from '../Navigation/sports'
import { orderLeagues } from './presentation'

export default function LeagueSwitcher({ activeLeague }: { activeLeague: string }) {
  // The directory registry decides which league hubs are offered. Team-stat season
  // certification is a separate contract and omits rollup hubs like tennis.
  const { groups, loading, error } = useSportNavigation('leagues')
  const offeredLeagues = groups.flatMap(group => group.competitions.map(item => item.league))
  const leagues = orderLeagues(
    offeredLeagues.includes(activeLeague) || !activeLeague
      ? offeredLeagues
      : [...offeredLeagues, activeLeague],
  )

  if (loading) return <nav aria-label="Leagues" className="h-5" />
  if (error || !offeredLeagues.length) {
    return (
      <nav aria-label="Leagues" className="h-5">
        <span role="status" className="text-xs text-zinc-500">League navigation is unavailable right now.</span>
      </nav>
    )
  }

  return (
    <nav
      aria-label="Leagues"
      className="-mx-4 flex items-center gap-3 overflow-x-auto overflow-y-hidden px-4 text-sm sm:gap-4 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    >
      {leagues.map(league => (
        <Link
          key={league}
          href={`/leagues/${league}`}
          aria-current={activeLeague === league ? 'page' : undefined}
          className="whitespace-nowrap text-zinc-500 transition-colors hover:text-emerald-400"
        >
          {leagueNavigationLabel(league)}
        </Link>
      ))}
    </nav>
  )
}
