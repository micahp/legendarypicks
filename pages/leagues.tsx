import Head from 'next/head'
import Link from 'next/link'

const LEAGUES = [
  { key: 'mlb', name: 'MLB', desc: 'Major League Baseball, batting leaders, pitching stars, division standings', emoji: '⚾' },
  { key: 'nba', name: 'NBA', desc: 'National Basketball Association, scoring leaders, team standings, game schedule', emoji: '🏀' },
  { key: 'nhl', name: 'NHL', desc: 'National Hockey League, points leaders, goalie stats, division races', emoji: '🏒' },
  { key: 'nfl', name: 'NFL', desc: 'National Football League, passing, rushing, receiving leaders, team power rankings', emoji: '🏈' },
  { key: 'mls', name: 'MLS', desc: 'Major League Soccer, standings, schedules, and player game logs', emoji: '⚽' },
  { key: 'ncaaf', name: 'NCAAF', desc: 'College Football, FBS teams, conference standings, player game logs', emoji: '🏈' },
  { key: 'ufc', name: 'UFC', desc: 'Ultimate Fighting Championship, pound-for-pound rankings, division champions', emoji: '🥊' },
  // World Cup card hidden 2026-08-04 (Micah): it stays on /scores and keeps its API
  // and ingest — it just is not a league hub. See useLeagueRouteState's `offerable`.
  // Esports card hidden 2026-07-22 (Micah): tab defaulting/content-awareness unresolved,
  // leagues surface needs organization before esports goes back up here.
]

export default function LeaguesPage() {
  return (
    <>
      <Head>
        <title>Leagues — Legendary Picks</title>
      </Head>

      <div className="space-y-6">
        <h1 className="text-3xl font-extrabold tracking-tight">Leagues</h1>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {LEAGUES.map((lg) => (
            <Link
              key={lg.key}
              href={`/leagues/${lg.key}`}
              className="group bg-zinc-900 border border-zinc-800 rounded-xl p-5 transition-colors hover:border-emerald-500/30 hover:bg-zinc-900/80"
            >
              <div className="flex items-start gap-3">
                <span className="text-2xl shrink-0">{lg.emoji}</span>
                <div className="min-w-0">
                  <h2 className="text-lg font-bold text-zinc-200 group-hover:text-emerald-400 transition-colors">
                    {lg.name}
                  </h2>
                  <p className="text-sm text-zinc-500 mt-1 leading-relaxed">
                    {lg.desc}
                  </p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </>
  )
}
