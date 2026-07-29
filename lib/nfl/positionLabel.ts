/* The database speaks the published vocabulary — nflverse/ESPN call a kicker
   "PK" and a defense "DEF". A drafter has never seen either string; every
   fantasy site on earth says "K" and "D/ST". So the code stays canonical
   everywhere it is stored, filtered, joined or sorted, and only the last inch
   before the eye is translated. Route every user-visible position string
   through here. */

const DISPLAY_POSITION: Record<string, string> = {
  PK: 'K',
  DEF: 'D/ST',
}

export function positionLabel(position: string | null | undefined): string {
  if (!position) return ''
  return DISPLAY_POSITION[position] ?? position
}

/** Positional rank, e.g. PK + 3 → "K3". Empty position yields "". */
export function positionRankLabel(
  position: string | null | undefined,
  rank: number | null | undefined,
): string {
  const label = positionLabel(position)
  if (!label) return ''
  return rank != null ? `${label}${rank}` : label
}

/* Nobody says "D/ST1" or "K3" out loud, and ESPN prints no positional rank for
   either. One kicker starts and one defense starts, so the rank carries no
   decision the position chip has not already made. It is a display rule, so it
   lives with the display map instead of being reinvented as an inline
   `position !== 'PK'` at each of three call sites. */
const RANKLESS_POSITIONS = new Set(['PK', 'DEF'])

export function showsPositionalRank(position: string | null | undefined): boolean {
  return !!position && !RANKLESS_POSITIONS.has(position)
}

/* ── The order a drafter reads ──────────────────────────────────────────────
   The mock draft's position filter used to read All · D/ST · K · QB · RB · TE ·
   WR — defense and kicker ahead of the quarterback. Nobody authored that: it
   was `[...new Set(pool.map(p => p.position))].sort()`, which is DEF, PK, QB,
   RB, TE, WR alphabetically, and the display map then hid *why* the order was
   wrong while leaving it wrong.

   A drafter reads this control in draft order, so the order is authored here
   and imported by every surface that renders it: skill positions in the order
   they come off the board, FLEX where it sits in a lineup, then the two
   positions nobody drafts before round 13 — last. */
export const POSITION_ORDER = ['QB', 'RB', 'WR', 'TE', 'FB', 'FLEX', 'PK', 'DEF'] as const

/**
 * The stored position codes a surface actually has, in canonical order.
 *
 * Positions the caller does not have are omitted; positions we have never heard
 * of are appended rather than dropped, because silently losing a filter option
 * is how an entire position disappears from a board with nothing raising.
 */
export function orderPositions(codes: Iterable<string>): string[] {
  const present = Array.from(new Set(Array.from(codes).filter(Boolean)))
  const known = POSITION_ORDER.filter(p => present.includes(p))
  const unknown = present.filter(p => !(POSITION_ORDER as readonly string[]).includes(p)).sort()
  return [...known, ...unknown]
}
