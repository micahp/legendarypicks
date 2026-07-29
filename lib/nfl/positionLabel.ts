/* The database speaks the published vocabulary — nflverse/ESPN call a kicker
   "PK". A drafter has never seen that string; every fantasy site on earth says
   "K". So the code stays canonical everywhere it is stored, filtered, joined or
   sorted, and only the last inch before the eye is translated. Route every
   user-visible position string through here. */

const DISPLAY_POSITION: Record<string, string> = {
  PK: 'K',
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
