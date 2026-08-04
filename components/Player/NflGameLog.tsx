import type { RecentGame, NflScheduleGame } from './types'
import { statCell } from './format'

// ESPN groups an NFL game log into phase bands under a two-row header and keeps
// one table for every position rather than swapping columns per position — an
// all-zero Rushing band just sits there on a TE page. Same structure here, with
// one deviation: a band no game in the window touched is dropped rather than
// rendered as a column of zeros. A receiver does not need five passing columns,
// and the whole point of this pass is that the page shows too much.
const NFL_GAMELOG_BANDS: { label: string; cols: { key: string; label: string }[] }[] = [
  { label: 'Passing', cols: [
    { key: 'cmp', label: 'Comp' }, { key: 'att', label: 'Att' },
    { key: 'pass_yds', label: 'Yds' }, { key: 'pass_td', label: 'TD' },
    { key: 'intc', label: 'Int' }, { key: 'sacks_taken', label: 'Sk' }] },
  { label: 'Rushing', cols: [
    { key: 'carries', label: 'Car' }, { key: 'rush_yds', label: 'Yds' },
    { key: 'rush_td', label: 'TD' }] },
  { label: 'Receiving', cols: [
    { key: 'targets', label: 'Tgt' }, { key: 'rec', label: 'Rec' },
    { key: 'rec_yds', label: 'Yds' }, { key: 'rec_td', label: 'TD' }] },
  { label: 'Kicking', cols: [
    { key: 'fg_made', label: 'FGM' }, { key: 'fg_att', label: 'FGA' },
    { key: 'fg_long', label: 'Long' },
    { key: 'pat_made', label: 'XPM' }, { key: 'pat_att', label: 'XPA' }] },
  // `intc`, not `interceptions` — the backend normalizes that key on the way out
  // (`_NFL_KEY_NORMALIZE`), and a column naming the raw key renders every pick as an
  // em dash, which reads as "we did not look" rather than "zero".
  { label: 'Defense', cols: [
    { key: 'sacks', label: 'Sck' }, { key: 'intc', label: 'Int' },
    { key: 'fumble_rec', label: 'FR' }, { key: 'def_td', label: 'TD' },
    { key: 'safeties', label: 'Sfty' }, { key: 'points_allowed', label: 'PA' }] },
  { label: 'Fantasy', cols: [
    { key: 'fpts', label: 'Fpts' }, { key: 'fpts_ppr', label: 'PPR' }] },
]

// Two positions do not survive "keep the bands somebody put a non-zero number in".
// A kicker's stat line carries `carries` and `targets` like everyone else's, so
// Brandon Aubrey's one designed carry in week 15 was the only non-zero value in the
// four bands that existed, and his page rendered a 17-row RUSHING log. Andy
// Borregales never touched the ball, matched no band, and got no table at all. For
// PK and DEF the position IS the answer, so it is asked first and the value scan
// never runs — a kicker who missed every kick still gets a kicking log.
// First entry is the band the position ALWAYS gets, even if every number in it is
// zero — a kicker who missed everything still has a kicking log, and a shutout is a
// defense's best game. The rest still have to earn their place, so a kicker whose
// fantasy line is zeros all season is not shown two columns of nothing.
const NFL_POSITION_BANDS: Record<string, string[]> = {
  PK: ['Kicking', 'Fantasy'],
  K: ['Kicking', 'Fantasy'],
  DEF: ['Defense', 'Fantasy'],
  DST: ['Defense', 'Fantasy'],
}

// These two are reachable ONLY by pinning, never by the value scan. A defense's
// interception and a quarterback's are the same normalized key (`intc`), so a scan
// that merely asks "is this column non-zero" hands every QB who threw a pick a
// Defense band — six columns of em dashes next to his passing line.
const NFL_POSITION_ONLY_BANDS = new Set(['Kicking', 'Defense'])

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

export function LeagueGameLog({ games, league, position }: {
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

export function NflGameLog({ games, scheduleGames = [], fillMissed = false, position }: {
  games: RecentGame[]
  scheduleGames?: NflScheduleGame[]
  fillMissed?: boolean
  position?: string | null
}) {
  const byWeek = new Map<number, RecentGame>()
  games.forEach(game => {
    const week = Number(game.game_no)
    if (Number.isInteger(week)) byWeek.set(week, game)
  })
  const scheduleByWeek = new Map(scheduleGames.map(game => [game.week, game]))
  const sortedGames = games.map(game => {
    const scheduled = scheduleByWeek.get(Number(game.game_no))
    return scheduled ? {
      ...game,
      opponent: scheduled.opponent,
      home: scheduled.home,
    } : game
  }).sort(
    (a, b) => Number(b.game_no ?? -1) - Number(a.game_no ?? -1),
  )
  const displayGames = fillMissed && scheduleGames.length > 0
    ? [...scheduleGames].sort((a, b) => b.week - a.week).map(scheduled => {
        const played = byWeek.get(scheduled.week)
        return played ? {
          ...played,
          opponent: scheduled.opponent,
          home: scheduled.home,
        } : {
          date: null,
          opponent: scheduled.opponent,
          home: scheduled.home,
          game_no: scheduled.week,
          stats: {},
        }
      })
    : sortedGames

  const num = (g: RecentGame, k: string) => (typeof g.stats[k] === 'number' ? (g.stats[k] as number) : null)
  const touched = (b: typeof NFL_GAMELOG_BANDS[number]) =>
    b.cols.some(c => displayGames.some(g => (num(g, c.key) ?? 0) !== 0))
  const pinned = NFL_POSITION_BANDS[String(position || '').toUpperCase()]
  const bands = pinned
    ? NFL_GAMELOG_BANDS.filter(b => pinned[0] === b.label || (pinned.includes(b.label) && touched(b)))
    : NFL_GAMELOG_BANDS.filter(b => !NFL_POSITION_ONLY_BANDS.has(b.label) && touched(b))
  if (!bands.length) return null

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-800/60 text-zinc-600 text-[10px] uppercase tracking-wider">
            <th colSpan={2} />
            {bands.map(b => (
              <th key={b.label} colSpan={b.cols.length}
                  className="text-center px-3 py-2 font-medium border-l border-zinc-800">{b.label}</th>
            ))}
          </tr>
          <tr className="border-b border-zinc-800 text-zinc-500 text-[11px] uppercase tracking-wider">
            <th className="text-left px-3 py-2 font-medium">Wk</th>
            <th className="text-left px-3 py-2 font-medium min-w-[5rem] whitespace-nowrap">Opp</th>
            {bands.map(b => b.cols.map((c, i) => (
              <th key={b.label + c.key}
                  className={`text-right px-3 py-2 font-medium ${i === 0 ? 'border-l border-zinc-800' : ''}`}>{c.label}</th>
            )))}
          </tr>
        </thead>
        <tbody>
          {displayGames.map((g, gi) => (
            <tr key={gi} className="border-b border-zinc-800/50 hover:bg-zinc-800/30 transition-colors">
              <td className="px-3 py-2.5 text-zinc-400 font-mono tabular-nums">{g.game_no ?? '—'}</td>
              <td className="px-3 py-2.5 text-zinc-300 min-w-[5rem] whitespace-nowrap">
                {g.opponent ? `${g.home === false ? '@ ' : ''}${g.opponent}` : '—'}
              </td>
              {bands.map(b => b.cols.map((c, ci) => {
                const v = num(g, c.key)
                return (
                  <td key={b.label + c.key}
                      className={`px-3 py-2.5 text-right font-mono tabular-nums ${v ? 'text-zinc-300' : 'text-zinc-600'} ${ci === 0 ? 'border-l border-zinc-800' : ''}`}>
                    {statCell(c.key, v)}
                  </td>
                )
              }))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
