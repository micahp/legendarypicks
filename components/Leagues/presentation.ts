import type { StatChange, StatMetric, TeamColumn } from './types'

export const LEAGUE_NAMES: Record<string, string> = {
  mlb: 'MLB',
  nba: 'NBA',
  nhl: 'NHL',
  nfl: 'NFL',
  wc: 'FIFA World Cup',
  ufc: 'UFC',
}

export const LEAGUE_EMOJIS: Record<string, string> = {
  mlb: '⚾',
  nba: '🏀',
  nhl: '🏒',
  nfl: '🏈',
  wc: '⚽',
  ufc: '🥊',
}

// Presentation order. Which of these are actually OFFERED is decided by the coverage
// registry at runtime (`useLeagueSwitcher`), not by this list — see
// docs/DATA-COVERAGE-CONTRACT.md §4. This array only says how to sort and what to call
// them; a league missing from it still renders, under its uppercased slug.
export const LEAGUE_ORDER = ['mlb', 'nba', 'nhl', 'nfl', 'wc', 'ufc'] as const

export function leagueLabel(league: string): string {
  return LEAGUE_NAMES[league] || league.toUpperCase()
}

export function leagueEmoji(league: string): string {
  return LEAGUE_EMOJIS[league] || '🏆'
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
