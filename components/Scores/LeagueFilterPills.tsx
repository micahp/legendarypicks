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
 * the native select's affordances without its popup. Icons are inline
 * Material Design paths (no new dependency) and aria-hidden: the visible
 * label is the accessible name.
 */
export type SportFilter =
  | 'All' | 'Basketball' | 'Baseball' | 'Hockey' | 'Football'
  | 'Soccer' | 'Tennis' | 'MMA' | 'Esports'

export const SPORTS: { name: SportFilter; icon: string[] }[] = [
  { name: 'All', icon: ['M4 8h4V4H4v4zm6 12h4v-4h-4v4zm-6 0h4v-4H4v4zm0-6h4v-4H4v4zm6 0h4v-4h-4v4zm6-10v4h4V4h-4zm-6 4h4V4h-4v4zm6 6h4v-4h-4v4zm0 6h4v-4h-4v4z'] },
  { name: 'Basketball', icon: ['M17.09,11h4.86c-0.16-1.61-0.71-3.11-1.54-4.4C18.68,7.43,17.42,9.05,17.09,11z', 'M6.91,11C6.58,9.05,5.32,7.43,3.59,6.6C2.76,7.89,2.21,9.39,2.05,11H6.91z', 'M15.07,11c0.32-2.59,1.88-4.79,4.06-6c-1.6-1.63-3.74-2.71-6.13-2.95V11H15.07z', 'M8.93,11H11V2.05C8.61,2.29,6.46,3.37,4.87,5C7.05,6.21,8.61,8.41,8.93,11z', 'M15.07,13H13v8.95c2.39-0.24,4.54-1.32,6.13-2.95C16.95,17.79,15.39,15.59,15.07,13z', 'M3.59,17.4c1.72-0.83,2.99-2.46,3.32-4.4H2.05C2.21,14.61,2.76,16.11,3.59,17.4z', 'M17.09,13c0.33,1.95,1.59,3.57,3.32,4.4c0.83-1.29,1.38-2.79,1.54-4.4H17.09z', 'M8.93,13c-0.32,2.59-1.88,4.79-4.06,6c1.6,1.63,3.74,2.71,6.13,2.95V13H8.93z'] },
  { name: 'Baseball', icon: ['M3.81,6.28C2.67,7.9,2,9.87,2,12s0.67,4.1,1.81,5.72C6.23,16.95,8,14.68,8,12S6.23,7.05,3.81,6.28z', 'M20.19,6.28C17.77,7.05,16,9.32,16,12s1.77,4.95,4.19,5.72C21.33,16.1,22,14.13,22,12S21.33,7.9,20.19,6.28z', 'M14,12c0-3.28,1.97-6.09,4.79-7.33C17.01,3.02,14.63,2,12,2S6.99,3.02,5.21,4.67C8.03,5.91,10,8.72,10,12 s-1.97,6.09-4.79,7.33C6.99,20.98,9.37,22,12,22s5.01-1.02,6.79-2.67C15.97,18.09,14,15.28,14,12z'] },
  { name: 'Hockey', icon: ['M2,17v3l2,0v-4H3C2.45,16,2,16.45,2,17z', 'M9,16H5v4l4.69-0.01c0.38,0,0.72-0.21,0.89-0.55l0.87-1.9l-1.59-3.48L9,16z', 'M21.71,16.29C21.53,16.11,21.28,16,21,16h-1v4l2,0v-3C22,16.72,21.89,16.47,21.71,16.29z', 'M13.6,12.84L17.65,4H14.3l-1.76,3.97l-0.49,1.1L12,9.21L9.7,4H6.35l4.05,8.84l1.52,3.32L12,16.34l1.42,3.1 c0.17,0.34,0.51,0.55,0.89,0.55L19,20v-4h-4L13.6,12.84z'] },
  { name: 'Football', icon: ['M3.02,15.62c-0.08,2.42,0.32,4.34,0.67,4.69s2.28,0.76,4.69,0.67L3.02,15.62z', 'M13.08,3.28C10.75,3.7,8.29,4.62,6.46,6.46s-2.76,4.29-3.18,6.62l7.63,7.63c2.34-0.41,4.79-1.34,6.62-3.18 s2.76-4.29,3.18-6.62L13.08,3.28z M9.9,15.5l-1.4-1.4l5.6-5.6l1.4,1.4L9.9,15.5z', 'M20.98,8.38c0.08-2.42-0.32-4.34-0.67-4.69s-2.28-0.76-4.69-0.67L20.98,8.38z'] },
  { name: 'Soccer', icon: ['M12,2C6.48,2,2,6.48,2,12c0,5.52,4.48,10,10,10s10-4.48,10-10C22,6.48,17.52,2,12,2z M13,5.3l1.35-0.95 c1.82,0.56,3.37,1.76,4.38,3.34l-0.39,1.34l-1.35,0.46L13,6.7V5.3z M9.65,4.35L11,5.3v1.4L7.01,9.49L5.66,9.03L5.27,7.69 C6.28,6.12,7.83,4.92,9.65,4.35z M7.08,17.11l-1.14,0.1C4.73,15.81,4,13.99,4,12c0-0.12,0.01-0.23,0.02-0.35l1-0.73L6.4,11.4 l1.46,4.34L7.08,17.11z M14.5,19.59C13.71,19.85,12.87,20,12,20s-1.71-0.15-2.5-0.41l-0.69-1.49L9.45,17h5.11l0.64,1.11 L14.5,19.59z M14.27,15H9.73l-1.35-4.02L12,8.44l3.63,2.54L14.27,15z M18.06,17.21l-1.14-0.1l-0.79-1.37l1.46-4.34l1.39-0.47 l1,0.73C19.99,11.77,20,11.88,20,12C20,13.99,19.27,15.81,18.06,17.21z'] },
  { name: 'Tennis', icon: ['M19.52,2.49c-2.34-2.34-6.62-1.87-9.55,1.06c-1.6,1.6-2.52,3.87-2.54,5.46c-0.02,1.58,0.26,3.89-1.35,5.5l-4.24,4.24 l1.42,1.42l4.24-4.24c1.61-1.61,3.92-1.33,5.5-1.35s3.86-0.94,5.46-2.54C21.38,9.11,21.86,4.83,19.52,2.49z M10.32,11.68 c-1.53-1.53-1.05-4.61,1.06-6.72s5.18-2.59,6.72-1.06c1.53,1.53,1.05,4.61-1.06,6.72S11.86,13.21,10.32,11.68z', 'M18,17c0.53,0,1.04,0.21,1.41,0.59c0.78,0.78,0.78,2.05,0,2.83C19.04,20.79,18.53,21,18,21s-1.04-0.21-1.41-0.59 c-0.78-0.78-0.78-2.05,0-2.83C16.96,17.21,17.47,17,18,17 M18,15c-1.02,0-2.05,0.39-2.83,1.17c-1.56,1.56-1.56,4.09,0,5.66 C15.95,22.61,16.98,23,18,23s2.05-0.39,2.83-1.17c1.56-1.56,1.56-4.09,0-5.66C20.05,15.39,19.02,15,18,15L18,15z'] },
  { name: 'MMA', icon: ['M7,20c0,0.55,0.45,1,1,1h8c0.55,0,1-0.45,1-1v-3H7V20z', 'M18,7c-0.55,0-1,0.45-1,1V5c0-1.1-0.9-2-2-2H7C5.9,3,5,3.9,5,5v5.8c0,0.13,0.01,0.26,0.04,0.39l0.8,4 c0.09,0.47,0.5,0.8,0.98,0.8h10.36c0.45,0,0.89-0.36,0.98-0.8l0.8-4C18.99,11.06,19,10.93,19,10.8V8C19,7.45,18.55,7,18,7z M15,10 H7V7h8V10z'] },
  { name: 'Esports', icon: ['M21.58,16.09l-1.09-7.66C20.21,6.46,18.52,5,16.53,5H7.47C5.48,5,3.79,6.46,3.51,8.43l-1.09,7.66 C2.2,17.63,3.39,19,4.94,19h0c0.68,0,1.32-0.27,1.8-0.75L9,16h6l2.25,2.25c0.48,0.48,1.13,0.75,1.8,0.75h0 C20.61,19,21.8,17.63,21.58,16.09z M11,11H9v2H8v-2H6v-1h2V8h1v2h2V11z M15,10c-0.55,0-1-0.45-1-1c0-0.55,0.45-1,1-1s1,0.45,1,1 C16,9.55,15.55,10,15,10z M17,13c-0.55,0-1-0.45-1-1c0-0.55,0.45-1,1-1s1,0.45,1,1C18,12.55,17.55,13,17,13z'] },
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

export default function LeagueFilterPills({
  value,
  onChange,
}: {
  value: string
  onChange: (sport: SportFilter) => void
}) {
  return (
    <div
      role="group"
      aria-label="Filter scoreboard by sport"
      /* One scrolling line on a phone (no squashing, no clipping — the pills
         keep their size and the row scrolls), wrapped rows on wider screens. */
      className="flex gap-2 overflow-x-auto pb-1 md:flex-wrap md:overflow-x-visible md:pb-0"
    >
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
            <svg
              viewBox="0 0 24 24"
              fill="currentColor"
              className="h-4 w-4"
              aria-hidden="true"
              focusable="false"
            >
              {sport.icon.map((d, i) => (
                <path key={i} d={d} />
              ))}
            </svg>
            {sport.name}
          </button>
        )
      })}
    </div>
  )
}
