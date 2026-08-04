import type { RecentGame } from './types'
import { statCell } from './format'

// Every non-NFL league rendered its game log as a run of key-value pairs —
// `goals 0 assists 0 points 0 shots 0 plusMinus -2 powerPlayGoals 0` — repeated
// down the page. Nothing lines up, so ranking two games against each other means
// reading both. Krug's first rule is that people scan; a log you have to read is
// a log nobody reads. NFL had columns. These are the same columns for everyone
// else, drawn from the keys each league's logs actually carry.
const LEAGUE_LOG_COLS: Record<string, { key: string; label: string }[]> = {
  nhl: [
    { key: 'goals', label: 'G' }, { key: 'assists', label: 'A' },
    { key: 'points', label: 'PTS' }, { key: 'shots', label: 'SOG' },
    { key: 'plusMinus', label: '+/-' }, { key: 'pim', label: 'PIM' },
    { key: 'powerPlayGoals', label: 'PPG' }, { key: 'powerPlayPoints', label: 'PPP' },
  ],
  nba: [
    { key: 'PTS', label: 'PTS' }, { key: 'REB', label: 'REB' },
    { key: 'AST', label: 'AST' }, { key: 'STL', label: 'STL' },
    { key: 'BLK', label: 'BLK' }, { key: 'TO', label: 'TO' },
    { key: 'FGM', label: 'FGM' }, { key: 'FGA', label: 'FGA' },
    { key: '3PM', label: '3PM' }, { key: 'MIN', label: 'MIN' },
  ],
  mlb: [
    { key: 'PA', label: 'PA' }, { key: 'H', label: 'H' },
    { key: 'R', label: 'R' }, { key: 'RBI', label: 'RBI' },
    { key: 'HR', label: 'HR' }, { key: '2B', label: '2B' },
    { key: '3B', label: '3B' }, { key: 'BB', label: 'BB' },
    { key: 'K', label: 'K' }, { key: 'TB', label: 'TB' },
  ],
  // Pitchers write a different set into the same table. `outs` is the published
  // key and thirds of an inning are what it means, so it is shown as outs rather
  // than converted to the 6.2-style notation, which is not a number.
  mlb_pitching: [
    { key: 'outs', label: 'Outs' }, { key: 'batters_faced', label: 'BF' },
    { key: 'hits_allowed', label: 'H' }, { key: 'BB', label: 'BB' },
    { key: 'K', label: 'K' },
  ],
}

export default function LeagueGameLog({ games, league, position }: {
  games: RecentGame[]
  league: string
  position?: string | null
}) {
  // A goalie's log holds `goals, assists, pim, toi` — his SKATER line. Rendering
  // it puts four true numbers on the page that answer none of the questions
  // anyone opens a goalie's page to ask, and a reader who sees a populated table
  // concludes we have his goaltending. Absence is a claim about us, not about
  // him, so it is stated rather than papered over.
  const isGoalie = league === 'nhl' && String(position || '').toUpperCase() === 'G'
  if (isGoalie) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-6 text-sm text-zinc-400">
        No goaltending stats on file — saves, shots against and goals allowed are
        not in this league&apos;s game logs yet.
        <span className="mt-1 block text-xs text-zinc-600">
          {games.length} game{games.length === 1 ? '' : 's'} recorded, skater stats only.
        </span>
      </div>
    )
  }

  const present = new Set<string>()
  games.forEach(g => Object.entries(g.stats).forEach(([k, v]) => {
    if (typeof v === 'number') present.add(k)
  }))
  const pitching = league === 'mlb' && present.has('outs') && !present.has('PA')
  const cols = (LEAGUE_LOG_COLS[pitching ? 'mlb_pitching' : league] || [])
    .filter(c => present.has(c.key))
  if (!cols.length) return null

  return (
    <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-900 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-800 text-[11px] uppercase tracking-wider text-zinc-500">
            <th className="px-3 py-2 text-left font-medium">Date</th>
            <th className="min-w-[4.5rem] whitespace-nowrap px-3 py-2 text-left font-medium">Opp</th>
            {cols.map(c => (
              <th key={c.key} className="px-3 py-2 text-right font-medium">{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {games.map((g, i) => (
            <tr key={i} className="border-b border-zinc-800/40 last:border-0">
              <td className="whitespace-nowrap px-3 py-2 text-xs text-zinc-500 tabular-nums">{g.date || '—'}</td>
              <td className="whitespace-nowrap px-3 py-2 text-xs text-zinc-400">
                {g.opponent ? `${g.home === false ? '@ ' : g.home === true ? 'vs ' : ''}${g.opponent}` : '—'}
              </td>
              {cols.map(c => {
                const v = g.stats[c.key]
                return (
                  <td key={c.key} className="px-3 py-2 text-right font-mono tabular-nums text-zinc-300">
                    {typeof v === 'number' ? statCell(c.key, v) : '—'}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
