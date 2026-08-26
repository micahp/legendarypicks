import Head from 'next/head'
import Link from 'next/link'
import {
  leagueNavigationLabel,
  useSportNavigation,
} from '../components/Navigation/sports'

const LEAGUE_CARDS: Record<string, { desc: string; emoji: string }> = {
  mlb: { desc: 'Major League Baseball, batting leaders, pitching stars, division standings', emoji: '⚾' },
  nba: { desc: 'National Basketball Association, scoring leaders, team standings, game schedule', emoji: '🏀' },
  nhl: { desc: 'National Hockey League, points leaders, goalie stats, division races', emoji: '🏒' },
  nfl: { desc: 'National Football League, passing, rushing, receiving leaders, team power rankings', emoji: '🏈' },
  soccer: { desc: 'MLS and Leagues Cup scores, standings, bracket, leaders, and news', emoji: '⚽' },
  ncaaf: { desc: 'College Football, FBS teams, conference standings, player game logs', emoji: '🏈' },
  ufc: { desc: 'Ultimate Fighting Championship, pound-for-pound rankings, division champions', emoji: '🥊' },
  esports: { desc: 'Esports World Cup, Club Championship, cross-title schedule and results', emoji: '🎮' },
  tennis: { desc: 'Major tournament scores, singles draws, ATP/WTA world rankings, and news', emoji: '🎾' },
  // World Cup card hidden 2026-08-04 (Micah): it stays on /scores and keeps its API
  // and ingest — it just is not a league hub. See useLeagueRouteState's `offerable`.
}

export default function LeaguesPage() {
  const { groups, loading, error } = useSportNavigation('leagues')
  return (
    <>
      <Head>
        <title>Leagues — Legendary Picks</title>
      </Head>

      <div className="space-y-6">
        <h1 className="text-3xl font-extrabold tracking-tight">Leagues</h1>

        {loading ? (
          <div aria-label="Loading leagues" className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2].map(item => <div key={item} className="h-32 animate-pulse rounded-xl bg-zinc-800" />)}
          </div>
        ) : error ? (
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 px-5 py-12 text-center text-sm text-zinc-400">
            League coverage is unavailable right now.
          </div>
        ) : (
          <div className="space-y-8">
            {groups.map(group => (
              <section key={group.key} aria-labelledby={`sport-${group.key}`} className="space-y-3">
                <h2 id={`sport-${group.key}`} className="text-sm font-bold uppercase tracking-wider text-zinc-400">
                  {group.label}
                </h2>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {group.competitions.map(competition => {
                    const card = LEAGUE_CARDS[competition.league] || {
                      desc: `${leagueNavigationLabel(competition.league)} coverage and schedules`,
                      emoji: '🏆',
                    }
                    return (
                      <Link
                        key={competition.league}
                        href={`/leagues/${competition.league}`}
                        className="group rounded-xl border border-zinc-800 bg-zinc-900 p-5 transition-colors hover:border-emerald-500/30 hover:bg-zinc-900/80"
                      >
                        <div className="flex items-start gap-3">
                          <span className="shrink-0 text-2xl">{card.emoji}</span>
                          <div className="min-w-0">
                            <h3 className="text-lg font-bold text-zinc-200 transition-colors group-hover:text-emerald-400">
                              {leagueNavigationLabel(competition.league)}
                            </h3>
                            <p className="mt-1 text-sm leading-relaxed text-zinc-500">
                              {card.desc}
                            </p>
                          </div>
                        </div>
                      </Link>
                    )
                  })}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </>
  )
}
