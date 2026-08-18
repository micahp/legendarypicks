import type { KnockoutRound, StandingGroup, TeamStats } from './types'

interface StandingsTabProps {
  error: string | null
  loading: boolean
  isWorldCup: boolean
  knockout: KnockoutRound[]
  groups: StandingGroup[]
  teams: TeamStats[]
  season?: number | null
  availableSeasons?: number[]
  onSelectSeason?: (season: number) => void
  leagueName: string
  league: string
}

export default function StandingsTab({
  error,
  loading,
  isWorldCup,
  knockout,
  groups,
  teams,
  season,
  availableSeasons,
  onSelectSeason,
  leagueName,
  league,
}: StandingsTabProps) {
  // A soccer league's standings are the P W D L GF GA GD Pts table. The World
  // Cup keeps its own branch (knockout bracket / group tables); MLS is soccer
  // without the knockout stage — rendered through an isSoccer branch, not by
  // bolting mls onto the World Cup condition.
  const isSoccer = league === 'mls'
  // A grouped table is the signature for the World Cup, MLS (Eastern/Western
  // conferences) and NCAAF (conferences). The loading skeleton follows it.
  const grouped = isWorldCup || isSoccer || league === 'ncaaf'

  return (
    <>
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 text-red-400 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <StandingsSkeleton grouped={grouped} />
      ) : isWorldCup ? (
        knockout.length > 0 ? (
          <WorldCupKnockout rounds={knockout} />
        ) : groups.length > 0 ? (
          <SoccerStandings groups={groups} />
        ) : (
          <div className="text-zinc-500 text-sm">No standings available.</div>
        )
      ) : groups.length > 0 ? (
        <>
          <SeasonPicker
            season={season}
            seasons={availableSeasons}
            onSelect={onSelectSeason}
          />
          {isSoccer ? (
            <SoccerStandings groups={groups} />
          ) : (
            <ConferenceStandings groups={groups} />
          )}
        </>
      ) : teams.length > 0 ? (
        <TeamSportStandings teams={teams} />
      ) : (
        <div className="text-zinc-500 text-sm">No data available for {leagueName}.</div>
      )}
    </>
  )
}

/**
 * Year selector. 25 published MLS seasons is too many for a button row, so this
 * is a select. Renders nothing unless the endpoint offered more than one year,
 * which keeps it off NCAAF and the World Cup — they send no season list.
 *
 * The options are the publisher's own `available_seasons`, never a generated
 * range, so a year that cannot be served is never offered.
 */
function SeasonPicker({
  season,
  seasons,
  onSelect,
}: {
  season?: number | null
  seasons?: number[]
  onSelect?: (season: number) => void
}) {
  if (!seasons || seasons.length < 2 || !onSelect) return null
  return (
    <div className="mb-4 flex items-center gap-2">
      <label htmlFor="standings-season" className="text-xs uppercase tracking-wider text-zinc-500">
        Season
      </label>
      <select
        id="standings-season"
        value={season ?? seasons[0]}
        onChange={event => onSelect(Number(event.target.value))}
        className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-sm font-medium text-zinc-200 hover:text-white focus:border-emerald-500/30 focus:outline-none"
      >
        {seasons.map(year => (
          <option key={year} value={year}>{year}</option>
        ))}
      </select>
    </div>
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

/**
 * Soccer P W D L table — the World Cup group table, reused for MLS, whose
 * Eastern/Western conferences map 1:1 onto the group shape. Points are the
 * published value; this component never derives them from a 3/1/0 rule.
 */
function SoccerStandings({ groups }: { groups: StandingGroup[] }) {
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
                    <td className="py-3 px-3 text-zinc-500">{standingsValue(row.rank)}</td>
                    <td className="py-3 px-3">
                      <span className="font-semibold text-zinc-200">{row.abbrev}</span>
                      <span className="text-zinc-500 ml-2">{row.name}</span>
                    </td>
                    <td className="py-3 px-2 text-center text-zinc-300">{standingsValue(row.played)}</td>
                    <td className="py-3 px-2 text-center text-zinc-300">{standingsValue(row.wins)}</td>
                    <td className="py-3 px-2 text-center text-zinc-300">{standingsValue(row.draws)}</td>
                    <td className="py-3 px-2 text-center text-zinc-300">{standingsValue(row.losses)}</td>
                    <td className="py-3 px-2 text-center text-zinc-300">{standingsValue(row.gf)}</td>
                    <td className="py-3 px-2 text-center text-zinc-300">{standingsValue(row.ga)}</td>
                    <td className="py-3 px-2 text-center">
                      <span className={row.gd != null && row.gd > 0 ? 'text-emerald-400' : row.gd != null && row.gd < 0 ? 'text-red-400' : 'text-zinc-400'}>
                        {row.gd != null && row.gd > 0 ? '+' : ''}{standingsValue(row.gd)}
                      </span>
                    </td>
                    <td className="py-3 px-2 text-center font-bold text-white">{standingsValue(row.points)}</td>
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

/**
 * Per-conference standings for NCAAF — 146 teams is not one table. Same
 * structure as the soccer tables, football columns only: rank, team, games
 * played, wins, losses. No GF/GA/GD/Pts: those are soccer stats, and no
 * points column exists in published college-football standings, so rendering
 * one would be a fabricated zero (honest-data-ui: dash ≠ zero).
 */
function ConferenceStandings({ groups }: { groups: StandingGroup[] }) {
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
                  <th className="text-center py-3 px-2">GP</th>
                  <th className="text-center py-3 px-2">W</th>
                  <th className="text-center py-3 px-2">L</th>
                </tr>
              </thead>
              <tbody>
                {group.rows.map(row => (
                  <tr key={row.abbrev} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                    <td className="py-3 px-3 text-zinc-500">{standingsValue(row.rank)}</td>
                    <td className="py-3 px-3">
                      <span className="font-semibold text-zinc-200">{row.abbrev}</span>
                      <span className="text-zinc-500 ml-2">{row.name}</span>
                    </td>
                    <td className="py-3 px-2 text-center text-zinc-300">{standingsValue(row.played)}</td>
                    <td className="py-3 px-2 text-center text-zinc-300">{standingsValue(row.wins)}</td>
                    <td className="py-3 px-2 text-center text-zinc-300">{standingsValue(row.losses)}</td>
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

function standingsValue(value: number | null): string | number {
  return value == null ? '—' : value
}

/**
 * Loading state that matches the component's own signature — a standings card
 * of shimmer bars, two cards for the grouped leagues. Never a bare spinner,
 * never a silent null.
 */
function StandingsSkeleton({ grouped }: { grouped: boolean }) {
  return (
    <div className="space-y-8 animate-pulse" role="status" aria-label="Loading standings">
      {grouped ? (
        <>
          {[0, 1].map(i => (
            <div key={i}>
              <div className="h-5 w-48 bg-zinc-800 rounded mb-3" />
              <TableSkeleton />
            </div>
          ))}
        </>
      ) : (
        <TableSkeleton />
      )}
    </div>
  )
}

function TableSkeleton() {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900">
      <div className="flex items-center gap-4 border-b border-zinc-800 px-3 py-3">
        <div className="h-3 w-6 bg-zinc-800 rounded" />
        <div className="h-3 w-28 bg-zinc-800 rounded" />
        <div className="ml-auto h-3 w-16 bg-zinc-800 rounded" />
      </div>
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 border-b border-zinc-800/50 px-3 py-3">
          <div className="h-3 w-6 bg-zinc-800 rounded" />
          <div className="h-3 w-24 bg-zinc-800 rounded" />
          <div className="h-3 w-20 bg-zinc-800/70 rounded" />
          <div className="ml-auto h-3 w-24 bg-zinc-800/70 rounded" />
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
