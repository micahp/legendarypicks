import type { StatChange, StatMetric, TeamColumn } from './types'

export const LEAGUE_NAMES: Record<string, string> = {
  mlb: 'MLB',
  nba: 'NBA',
  nhl: 'NHL',
  nfl: 'NFL',
  mls: 'MLS',
  lcup: 'Leagues Cup',
  ccc: 'Concacaf Champions Cup',
  campeones: 'Campeones Cup',
  usoc: 'U.S. Open Cup',
  ncaaf: 'NCAAF',
  wc: 'FIFA World Cup',
  ufc: 'UFC',
}

export const LEAGUE_EMOJIS: Record<string, string> = {
  mlb: '⚾',
  nba: '🏀',
  nhl: '🏒',
  nfl: '🏈',
  mls: '⚽',
  ncaaf: '🏈',
  wc: '⚽',
  ufc: '🥊',
}

// Presentation order. Which of these are actually OFFERED is decided by the coverage
// registry at runtime (`useLeagueSwitcher`), not by this list — see
// docs/DATA-COVERAGE-CONTRACT.md §4. This array only says how to sort and what to call
// them; a league missing from it still renders, under its uppercased slug.
// `wc` is deliberately absent. The World Cup keeps its API, its ingest, and its place
// on /scores — it just stops being a league hub. Removing it from the ORDER is not what
// hides it (an unlisted league still renders, under its uppercased slug); the
// `offerable` check in useLeagueRouteState is. This only stops it being sorted first.
export const LEAGUE_ORDER = ['mlb', 'nba', 'nhl', 'nfl', 'mls', 'ncaaf', 'ufc'] as const

export function leagueLabel(league: string): string {
  return LEAGUE_NAMES[league] || league.toUpperCase()
}

export function leagueEmoji(league: string): string {
  return LEAGUE_EMOJIS[league] || '🏆'
}

// Leagues whose season crosses a calendar year, and which every publisher — ESPN
// included — therefore names with both: `2025-26`, never `2026`.
const SPLIT_YEAR_LEAGUES = new Set(['nhl', 'nba'])

// MLS is a calendar-year season and NCAAF a start-year season — both stored and
// published under the bare season key (`2025`) — so neither joins the split-year
// set; both display the bare key.

/**
 * Render a stored season key the way the league publishes it.
 *
 * The STORAGE keys are deliberately left alone. NHL game logs are keyed `20252026`
 * because that is the NHL's own vocabulary, and `player_stats` is keyed `2026`
 * because that is ESPN's — both are correct, and migrating either would be changing
 * a publisher's answer to make our display easier. What was actually wrong is that
 * the player page printed both raw, so one header read
 * `NHL · 20252026 · 82 games` directly above `SEASON STATS · 2026`: two labels for
 * one season, neither of them the one a hockey fan uses.
 *
 * So this is display-only. An 8-digit key takes its last four digits as the ending
 * year; a 4-digit key already is the ending year. MLB and NFL seasons sit inside one
 * calendar year and keep the bare number. Anything unparseable returns unchanged —
 * never `NaN`, never an empty string in place of something the caller was given.
 */
export function seasonLabel(
  league: string,
  season: number | string | null | undefined,
): string {
  if (season == null || season === '') return ''
  const raw = String(season).trim()
  if (!SPLIT_YEAR_LEAGUES.has(league?.toLowerCase())) return raw
  const end = /^\d{8}$/.test(raw)
    ? Number(raw.slice(4))
    : /^\d{4}$/.test(raw)
      ? Number(raw)
      : null
  if (end == null || !Number.isFinite(end)) return raw
  return `${end - 1}-${String(end).slice(2)}`
}

/**
 * Order a set of league slugs for display.
 *
 * Leagues we have a curated position for come first, in that order; anything new sorts
 * alphabetically after them. This is what stops a newly-ingested league from being
 * invisible because someone forgot to add it to an array — the old LEAGUE_SWITCHER
 * const was the single hardcoded list that decided what existed.
 */
export function orderLeagues(leagues: string[]): string[] {
  const rank = (l: string) => {
    const i = (LEAGUE_ORDER as readonly string[]).indexOf(l)
    return i === -1 ? LEAGUE_ORDER.length : i
  }
  return [...leagues].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
}

export const WEIGHT_CLASS_LBS: Record<string, number> = {
  Flyweight: 125,
  Bantamweight: 135,
  Featherweight: 145,
  Lightweight: 155,
  Welterweight: 170,
  Middleweight: 185,
  'Light Heavyweight': 205,
  Heavyweight: 265,
  "Women's Strawweight": 115,
  "Women's Flyweight": 125,
  "Women's Bantamweight": 135,
}

export function formatMetric(
  metric: StatMetric,
  value: number | string | null | undefined,
): string {
  if (value == null) return '—'
  if (metric.format === 'time') return String(value)
  const numeric = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(numeric)) return '—'
  if (metric.format === 'integer') return numeric.toFixed(0)
  if (metric.format === 'decimal_3') return numeric.toFixed(3)
  if (metric.format === 'percent_1') return `${numeric.toFixed(1)}%`
  return numeric.toFixed(1)
}

export function formatTeamMetric(
  column: TeamColumn,
  value: number | string | null | undefined,
): string {
  if (value == null) return '—'
  const numeric = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(numeric)) return '—'
  if (column.format === 'percent') return `${(numeric * 100).toFixed(1)}%`
  if (column.format === 'decimal') return numeric.toFixed(1)
  return Number.isInteger(numeric) ? numeric.toFixed(0) : numeric.toFixed(1)
}

export function formatSignedMetric(metric: StatMetric, value: number): string {
  const formatted = formatMetric(metric, value)
  return value > 0 ? `+${formatted}` : formatted
}

export function directionDisplay(direction: StatChange['direction']) {
  if (direction === 'rising') {
    return { glyph: '↑', label: 'Rising', className: 'text-emerald-400' }
  }
  if (direction === 'falling') {
    return { glyph: '↓', label: 'Falling', className: 'text-amber-400' }
  }
  return { glyph: '→', label: 'Flat', className: 'text-zinc-400' }
}

const DATE_PARAM = /^\d{4}-\d{2}-\d{2}$/

export function localToday(): string {
  return new Date().toLocaleDateString('en-CA')
}

export function validScheduleDate(value: unknown): value is string {
  if (typeof value !== 'string' || !DATE_PARAM.test(value)) return false
  const parsed = new Date(`${value}T12:00:00`)
  return !Number.isNaN(parsed.getTime()) && parsed.toLocaleDateString('en-CA') === value
}

export function formatScheduleDate(date: string): string {
  return new Date(`${date}T12:00:00`).toLocaleDateString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}
