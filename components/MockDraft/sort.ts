/* ── Ordering the board ─────────────────────────────────────────────────────
   ESPN now publishes both inputs the executable 2026 plan required: PPR draft
   rank and a projected stat line. Rank is the default board order; projected
   PPR is a visible value and an explicit sort. Prior-season actual and xFP stay
   available as secondary sorts, not as the decision columns.

   Two rules the comparator must never break:

     · Nulls sort last, always, in both directions. A `a.adp - b.adp` coerces
       null to 0 and floats all 32 D/ST above pick 1; that shipped once.
     · A null is never a zero. It is missing, and the row renders an em dash.

   Sorting by last season's points under All Pos WILL float kickers above most
   WR2s, because the column resolves to three different series: PPR/game for
   skill positions (5–22), kicking points/game for K (7–9), D/ST points/game
   (4–9). That is not a sort bug. It is a true property of last season's actuals,
   and it is exactly why ESPN sorts by a projection-and-scarcity rank instead.
   We will not invent a projection to hide it — the position chip on every row
   says a kicker is a kicker. */

import type { DraftPlayer } from '../../lib/mockDraft/engine'
import type { PoolPlayer } from '../Leagues/types'
import { headlineValue, availabilityValue } from './columns'

export type SortKey = 'rank' | 'proj' | 'adp' | 'avail' | 'bye' | 'pts' | 'xfp'

export interface SortOption {
  key: SortKey
  label: string
  direction: 'asc' | 'desc'
}

export const DEFAULT_SORT: SortKey = 'rank'

/** Authored order, default first — never alphabetical, for the same reason the
 *  position filter is authored. The season comes from the payload. */
export function sortOptions(referenceSeason?: number | null): SortOption[] {
  const season = referenceSeason != null ? `${referenceSeason} ` : ''
  return [
    { key: 'rank', label: 'Rank', direction: 'asc' },
    { key: 'proj', label: 'Proj Pts', direction: 'desc' },
    { key: 'adp', label: 'ADP', direction: 'asc' },
    { key: 'avail', label: 'Availability', direction: 'desc' },
    { key: 'bye', label: 'Bye', direction: 'asc' },
    { key: 'pts', label: `${season}Pts/G`, direction: 'desc' },
    { key: 'xfp', label: `${season}xFP/G`, direction: 'desc' },
  ]
}

interface Context {
  playerMap: Map<number, PoolPlayer>
  byeMap: Map<string, number | null>
}

function valueOf(key: SortKey, dp: DraftPlayer, ctx: Context): number | null {
  const pp = ctx.playerMap.get(dp.player_id)
  if (key === 'rank') return pp?.espn_ppr_rank ?? null
  if (key === 'proj') return pp?.proj_ppr_points ?? null
  if (key === 'adp') return dp.adp ?? null
  if (key === 'bye') return ctx.byeMap.get(dp.team) ?? null
  if (!pp) return null
  if (key === 'pts') return headlineValue(pp)
  if (key === 'xfp') return pp.xfp_per_game ?? null
  if (key === 'avail') return availabilityValue(pp)
  return null
}

/**
 * A stable sort: ties keep the order they came in, which is ADP ascending, so
 * "the best available of the ones that tie" is still the one on top.
 */
export function sortPool(pool: DraftPlayer[], key: SortKey, ctx: Context): DraftPlayer[] {
  const option = sortOptions().find(o => o.key === key)
  const descending = option?.direction === 'desc'

  return pool
    .map((dp, i) => ({ dp, i, v: valueOf(key, dp, ctx) }))
    .sort((a, b) => {
      if (a.v == null && b.v == null) return a.i - b.i
      if (a.v == null) return 1      // missing sorts last
      if (b.v == null) return -1     // in both directions
      if (a.v !== b.v) return descending ? b.v - a.v : a.v - b.v
      return a.i - b.i
    })
    .map(x => x.dp)
}
