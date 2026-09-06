// Where a price is real, and how to write one.
//
// Shared because two copies of this rule would drift, and the drift would be a number on a
// card that nobody can act on.

// pick'em products: you choose over or under and the payout comes from the ENTRY's
// multiplier (2-pick, 3-pick, flex), not from a price on the leg.
//
// RotoWire populates the field anyway with a constant. Verified in its raw payload
// 2026-08-26: across every archived prop, `prizepicks` and `underdog` each carry exactly ONE
// (over, under) pair -- (-137, -137) -- while sleeper has 231 distinct pairs,
// draftkings-sb 351 and fanduel-sb 88. In our own table the same shows as 2,688 prizepicks
// rows and 1,870 underdog rows with a single distinct odds value.
//
// -137 is roughly 57.8% implied, about what a pick'em leg needs to break even at standard
// multipliers. It is a sensible convention and it is not a price: it never varies, and it is
// identical on both sides, which no real book does. Shown as a number it invites a
// comparison that cannot mean anything -- so it is not shown. A blank is honest; a
// placeholder rendered as a measurement is not.
export const PICKEM_SOURCES = /^(rotowire:)?(prizepicks|underdog|sleeper|pick6)(-demon|-goblin)?$/

export function isPickem(source: string | undefined): boolean {
  return PICKEM_SOURCES.test((source || '').trim().toLowerCase())
}

// American odds carry their sign as meaning, so a positive price must show its "+".
// Returns null for anything that is not a real price, including a pick'em constant, so a
// caller that renders the result can only ever render something true.
export function realOdds(source: string | undefined, odds: number | null | undefined): string | null {
  if (isPickem(source)) return null
  if (odds === null || odds === undefined || !Number.isFinite(odds)) return null
  return odds > 0 ? `+${odds}` : String(odds)
}
