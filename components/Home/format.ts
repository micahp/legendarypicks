const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export const marketLabel = (m: string) => m.replace(/_/g, ' ')

export const unitWord = (m: string) => marketLabel(m).split(' ').pop() || ''

export const pct = (p: number, digits = 0) => `${(p * 100).toFixed(digits)}%`

export function gameDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (!match) return iso
  const [, year, month, day] = match
  const name = MONTHS[Number(month) - 1]
  return name ? `${name} ${Number(day)}, ${year}` : iso
}

/** One side of a spread: positive spread means the home team is favoured (nflverse). */
export function spreadText(home: string, away: string, spread: number): string {
  if (Math.abs(spread) < 0.05) return 'Even'
  return spread > 0 ? `${home} -${spread.toFixed(1)}` : `${away} -${Math.abs(spread).toFixed(1)}`
}

export function signed(n: number): string {
  return `${n >= 0 ? '+' : '-'}${Math.abs(n).toFixed(1)}`
}

const fmt = (o: Intl.DateTimeFormatOptions, d: Date) =>
  new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', ...o }).format(d)

export function kickoffText(iso: string | null): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return `${fmt({ weekday: 'long', month: 'short', day: 'numeric' }, d)} · ${fmt({ hour: 'numeric', minute: '2-digit' }, d)} ET`
}

export const weekdayText = (iso: string | null) => {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : fmt({ weekday: 'long' }, d)
}

export const shortDate = (iso: string | null) => {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : fmt({ month: 'short', day: 'numeric' }, d)
}

export const asOfText = (iso?: string | null) => {
  const s = shortDate(iso ?? null)
  return s ? `as of ${s}` : null
}
