import Link from 'next/link'
import { useCoverage } from './hooks/useCoverage'
import { leagueLabel, orderLeagues } from './presentation'

export default function LeagueSwitcher({ activeLeague }: { activeLeague: string }) {
  // Use the verified coverage list. Keep the current league reachable while it loads
  // or when its coverage entry is not part of the list yet.
  const { loading, offeredLeagues } = useCoverage()
  const leagues = orderLeagues(
    offeredLeagues.includes(activeLeague) || !activeLeague
      ? offeredLeagues
      : [...offeredLeagues, activeLeague],
  )

  if (loading || !leagues.length) return <nav aria-label="Leagues" className="h-5" />

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
          {leagueLabel(league)}
        </Link>
      ))}
    </nav>
  )
}
