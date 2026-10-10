import SportIcon from '../SportIcon'
import LiveDot from '../LiveDot'

/**
 * The scoreboard's sport filter: a row of pills, one per sport, replacing the
 * native league <select> it used to sit beside.
 *
 * Why sports and not leagues: the old dropdown offered sixteen leagues, most
 * of which are really the same sport to a reader deciding what to watch
 * (five soccer entries, two tennis, two football). A sport pill maps onto
 * what the board actually does — fetch every league of that sport, show each
 * league's section as before. `All` keeps meaning "every league we carry".
 *
 * The mapping is explicit and exported so the URL contract can keep its
 * promise: `?league=` still accepts every legacy league value (and now also
 * the sport names) and resolves to the same sport the reader picked. Selecting
 * a sport writes the sport name; a shared link with `?league=NCAAF` still
 * lands on Football with both fetches made.
 *
 * Each pill is a real <button> with `aria-pressed`, so keyboard users tab to
 * it and press Enter/Space, and assistive tech hears the on/off state —
 * the native select's affordances without its popup. Icons come from the
 * shared components/SportIcon (inline Material Design paths, no new
 * dependency) and are aria-hidden: the visible label is the accessible name.
 */
export type SportFilter =
  | 'All' | 'Basketball' | 'Baseball' | 'Hockey' | 'Football'
  | 'Soccer' | 'Tennis' | 'MMA' | 'Esports'

export const SPORTS: { name: SportFilter }[] = [
  { name: 'All' },
  { name: 'Basketball' },
  { name: 'Baseball' },
  { name: 'Hockey' },
  { name: 'Football' },
  { name: 'Soccer' },
  { name: 'Tennis' },
  { name: 'MMA' },
  { name: 'Esports' },
]

// Every legacy league value the URL ever carried, resolved to its sport.
// The keys are the old <select> options (the LEAGUES list this file replaces).
export const LEAGUE_TO_SPORT: Record<string, SportFilter> = {
  'All': 'All',
  'NBA': 'Basketball',
  'MLB': 'Baseball',
  'NHL': 'Hockey',
  'NFL': 'Football',
  'NCAAF': 'Football',
  'UEFA Nations League': 'Soccer',
  'International Friendlies': 'Soccer',
  'Leagues Cup': 'Soccer',
  'MLS': 'Soccer',
  'Liga MX': 'Soccer',
  'FIFA World Cup': 'Soccer',
  'ATP': 'Tennis',
  'WTA': 'Tennis',
  'UFC': 'MMA',
  'Call of Duty': 'Esports',
}

// `?league=` accepts both the sport names this control writes and every
// legacy league value; anything else was and stays ignored (no silent
// default — an unknown value must not flip the board to All).
export function sportForQuery(value: string): SportFilter | null {
  if ((SPORTS as { name: string }[]).some((s) => s.name === value)) return value as SportFilter
  return LEAGUE_TO_SPORT[value] ?? null
}

// API keys (the LEAGUE_KEYS vocabulary on the page) fetched for each sport.
// `All` is expanded by the page against its own LEAGUE_KEYS, so this map
// carries only the concrete sports.
export const SPORT_FETCH_KEYS: Record<Exclude<SportFilter, 'All'>, string[]> = {
  'Basketball': ['nba'],
  'Baseball': ['mlb'],
  'Hockey': ['nhl'],
  'Football': ['nfl', 'ncaaf'],
  'Soccer': ['unl', 'friendlies', 'lcup', 'mls', 'ligamx', 'wc'],
  'Tennis': ['atp', 'wta'],
  'MMA': ['ufc'],
  'Esports': ['cod'],
}

// The raw league codes the API stamps on games (Game.league), per sport —
// what the live-score poll needs to know which board sections belong to the
// selected sport.
export const SPORT_LEAGUE_CODES: Record<Exclude<SportFilter, 'All'>, string[]> = {
  'Basketball': ['NBA'],
  'Baseball': ['MLB'],
  'Hockey': ['NHL'],
  'Football': ['NFL', 'NCAAF'],
  'Soccer': ['UNL', 'FRIENDLIES', 'LCUP', 'MLS', 'LIGAMX', 'WC'],
  'Tennis': ['ATP', 'WTA'],
  'MMA': ['UFC'],
  'Esports': ['COD'],
}

// A Live pill ahead of the sports, replacing the rail that used to sit above the date control
// (Micah, 2026-10-08). It narrows whatever sport is picked to what is in progress right now;
// the page passes it only while something is live (or the filter is on, so it can be turned off).
export interface LivePill {
  count: number
  active: boolean
  onToggle: () => void
}

export default function LeagueFilterPills({
  value,
  onChange,
  live,
}: {
  value: string
  onChange: (sport: SportFilter) => void
  live?: LivePill
}) {
  return (
    <div
      role="group"
      aria-label="Filter scoreboard by sport"
      /* One scrolling line on a phone (no squashing, no clipping — the pills
         keep their size and the row scrolls), wrapped rows on wider screens. */
      className="flex gap-2 overflow-x-auto pb-1 md:flex-wrap md:overflow-x-visible md:pb-0"
    >
      {live ? (
        <button
          type="button"
          aria-pressed={live.active}
          onClick={live.onToggle}
          className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3 py-1.5 text-sm font-medium transition-colors ${
            live.active
              ? 'border-red-500/40 bg-red-500/15 text-red-300'
              : 'border-zinc-800 bg-zinc-900/60 text-zinc-300 hover:border-red-500/40 hover:text-red-300'
          }`}
        >
          <LiveDot />
          Live
          {live.count > 0 ? <span className="tabular-nums text-xs opacity-80">{live.count}</span> : null}
        </button>
      ) : null}
      {SPORTS.map((sport) => {
        const active = value === sport.name
        return (
          <button
            type="button"
            key={sport.name}
            aria-pressed={active}
            onClick={() => onChange(sport.name)}
            className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3 py-1.5 text-sm font-medium transition-colors ${
              active
                ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                : 'border-zinc-800 bg-zinc-900/60 text-zinc-500 hover:border-zinc-700 hover:text-zinc-300'
            }`}
          >
            <SportIcon league={sport.name} className="h-4 w-4" />
            {sport.name}
          </button>
        )
      })}
    </div>
  )
}
