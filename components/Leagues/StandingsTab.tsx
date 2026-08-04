import type { KnockoutRound, StandingGroup, TeamStats } from './types'

interface StandingsTabProps {
  error: string | null
  loading: boolean
  isWorldCup: boolean
  knockout: KnockoutRound[]
  groups: StandingGroup[]
  teams: TeamStats[]
  leagueName: string
}

export default function StandingsTab({
  error,
  loading,
  isWorldCup,
  knockout,
  groups,
  teams,
  leagueName,
}: StandingsTabProps) {
  return (
    <>
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 text-red-400 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-zinc-500 text-sm py-8 text-center">Loading standings...</div>
      ) : isWorldCup ? (
        knockout.length > 0 ? (
          <WorldCupKnockout rounds={knockout} />
        ) : groups.length > 0 ? (
          <WorldCupGroups groups={groups} />
        ) : (
          <div className="text-zinc-500 text-sm">No standings available.</div>
        )
      ) : teams.length > 0 ? (
        <TeamSportStandings teams={teams} />
      ) : (
        <div className="text-zinc-500 text-sm">No data available for {leagueName}.</div>
      )}
    </>
  )
}

function WorldCupKnockout({ rounds }: { rounds: KnockoutRound[] }) {
  return (
    <div className="space-y-8">
      {rounds.map(round => (
        <div key={round.round}>
          <div className="flex items-center gap-3 mb-3">
            <span className="text-[10px] text-emerald-500/60 bg-emerald-500/10 px-2 py-0.5 rounded font-bold uppercase tracking-widest">
              {round.round}
            </span>
          </div>
          <div className="space-y-2">
            {round.matches.map((match, index) => {
              const isFinal = match.state === 'post'
              const homeWon = isFinal && match.winner === match.home.abbrev
              const awayWon = isFinal && match.winner === match.away.abbrev
              return (
                <div
                  key={index}
                  className="bg-zinc-900 border border-zinc-800 rounded-lg px-4 py-3 flex items-center justify-between gap-3"
                >
                  <div className="flex-1 min-w-0">
                    <span className={`font-semibold text-sm ${isFinal ? (homeWon ? 'text-white' : 'text-zinc-500') : 'text-zinc-200'}`}>
                      {match.home.name || match.home.abbrev}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {isFinal ? (
                      <span className="font-mono tabular-nums text-lg font-bold text-zinc-100">
                        {match.homeScore ?? '—'} – {match.awayScore ?? '—'}
                      </span>
                    ) : (
                      <span className="text-xs text-zinc-500">{match.status || 'Upcoming'}</span>
                    )}
                  </div>
                  <div className="flex-1 min-w-0 text-right">
                    <span className={`font-semibold text-sm ${isFinal ? (awayWon ? 'text-white' : 'text-zinc-500') : 'text-zinc-200'}`}>
                      {match.away.name || match.away.abbrev}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

function WorldCupGroups({ groups }: { groups: StandingGroup[] }) {
  return (
    <div className="space-y-8">
      {groups.map(group => (
        <div key={group.group}>
          <h2 className="text-lg font-bold text-white mb-3">{group.group}</h2>
          <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-900 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-800 text-zinc-400 text-xs uppercase tracking-wider">
                  <th className="text-left py-3 px-3">#</th>
                  <th className="text-left py-3 px-3">Team</th>
                  <th className="text-center py-3 px-2">P</th>
                  <th className="text-center py-3 px-2">W</th>
                  <th className="text-center py-3 px-2">D</th>
                  <th className="text-center py-3 px-2">L</th>
                  <th className="text-center py-3 px-2">GF</th>
                  <th className="text-center py-3 px-2">GA</th>
                  <th className="text-center py-3 px-2">GD</th>
                  <th className="text-center py-3 px-2 font-bold">Pts</th>
                </tr>
              </thead>
              <tbody>
                {group.rows.map(row => (
                  <tr key={row.abbrev} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                    <td className="py-3 px-3 text-zinc-500">{row.rank}</td>
                    <td className="py-3 px-3">
                      <span className="font-semibold text-zinc-200">{row.abbrev}</span>
                      <span className="text-zinc-500 ml-2">{row.name}</span>
                    </td>
                    <td className="py-3 px-2 text-center text-zinc-300">{row.played}</td>
                    <td className="py-3 px-2 text-center text-zinc-300">{row.wins}</td>
                    <td className="py-3 px-2 text-center text-zinc-300">{row.draws}</td>
                    <td className="py-3 px-2 text-center text-zinc-300">{row.losses}</td>
                    <td className="py-3 px-2 text-center text-zinc-300">{row.gf}</td>
                    <td className="py-3 px-2 text-center text-zinc-300">{row.ga}</td>
                    <td className="py-3 px-2 text-center">
                      <span className={row.gd > 0 ? 'text-emerald-400' : row.gd < 0 ? 'text-red-400' : 'text-zinc-400'}>
                        {row.gd > 0 ? '+' : ''}{row.gd}
                      </span>
                    </td>
                    <td className="py-3 px-2 text-center font-bold text-white">{row.points}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  )
}

function TeamSportStandings({ teams }: { teams: TeamStats[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-900 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-800 text-zinc-400 text-xs uppercase tracking-wider">
            <th className="text-left py-3 pr-4 pl-4">#</th>
            <th className="text-left py-3 pr-4">Team</th>
            <th className="text-right py-3 px-3">W</th>
            <th className="text-right py-3 px-3">L</th>
            <th className="text-right py-3 px-3">Win%</th>
            <th className="text-right py-3 px-3">Diff</th>
            <th className="text-right py-3 px-3">Streak</th>
            <th className="text-right py-3 pl-3 pr-4">L10</th>
          </tr>
        </thead>
        <tbody>
          {teams.map((team, index) => (
            <tr key={team.abbrev} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
              <td className="py-3 pr-4 pl-4 text-zinc-500">{index + 1}</td>
              <td className="py-3 pr-4">
                <span className="font-semibold text-zinc-200">{team.abbrev}</span>
                <span className="text-zinc-500 ml-2">{team.name}</span>
              </td>
              <td className="py-3 px-3 text-right text-zinc-200">{team.wins}</td>
              <td className="py-3 px-3 text-right text-zinc-200">{team.losses}</td>
              <td className="py-3 px-3 text-right text-zinc-200 font-mono tabular-nums">
                {(team.win_pct * 100).toFixed(1)}%
              </td>
              <td className="py-3 px-3 text-right">
                <span className={team.differential > 0 ? 'text-emerald-400' : team.differential < 0 ? 'text-red-400' : 'text-zinc-400'}>
                  {team.differential > 0 ? '+' : ''}{team.differential}
                </span>
              </td>
              <td className="py-3 px-3 text-right">
                <span className={team.streak?.startsWith('W') ? 'text-emerald-400' : 'text-red-400'}>
                  {team.streak}
                </span>
              </td>
              {/* NHL's L10 is three parts (`7-2-1`) where every other league's is two,
                  so it is the one that wraps to a second line on a phone. */}
              <td className="py-3 pl-3 pr-4 text-right text-zinc-400 font-mono tabular-nums whitespace-nowrap">
                {team.last10}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
