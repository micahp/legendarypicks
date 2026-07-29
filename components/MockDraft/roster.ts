/* ── Roster construction, once ──────────────────────────────────────────────
   This existed twice: DraftRoom.tsx built the in-draft roster and
   ResultsScreen.tsx built the post-draft one, from the same picks, with the same
   slot order, in two separately maintained copies. On 2026-07-28 one of them
   stopped at K and padded the rest as bench, so a bot-drafted defense landed
   silently on a bench row while the engine's STARTER_COUNT had always included
   one. Both copies had to be found and fixed. There is one copy now.

   The 15-man roster: QB RB1 RB2 WR1 WR2 TE FLEX K D/ST = 9 starters, 6 bench. */

import type { DraftPlayer } from '../../lib/mockDraft/engine'
import type { PoolPlayer } from '../Leagues/types'

export const BENCH_SLOTS = 6

export interface RosterSlot {
  /** What the drafter reads — display vocabulary, so "K" and "D/ST". */
  label: string
  player: DraftPlayer | null
  poolPlayer: PoolPlayer | null
  isStarter: boolean
}

export function buildRosterSlots(
  players: DraftPlayer[],
  playerMap: Map<number, PoolPlayer>,
): RosterSlot[] {
  const byPos: Record<string, DraftPlayer[]> = {}
  for (const p of players) {
    if (!byPos[p.position]) byPos[p.position] = []
    byPos[p.position].push(p)
  }

  const slots: RosterSlot[] = []
  const used = new Set<number>()

  // `label` is what the drafter reads; `pos` is the stored code. Keeping them as
  // separate arguments is the whole reason the display vocabulary can change
  // without touching the engine.
  function addSlot(label: string, pos: string, isStarter: boolean) {
    const arr = byPos[pos] ?? []
    const player = arr.shift() ?? null
    if (player) used.add(player.player_id)
    slots.push({
      label,
      player,
      poolPlayer: player ? playerMap.get(player.player_id) ?? null : null,
      isStarter,
    })
  }

  addSlot('QB', 'QB', true)
  addSlot('RB1', 'RB', true)
  addSlot('RB2', 'RB', true)
  addSlot('WR1', 'WR', true)
  addSlot('WR2', 'WR', true)
  addSlot('TE', 'TE', true)

  // FLEX: next RB/WR/TE
  const flexPlayer =
    (byPos['RB'] ?? [])[0] ??
    (byPos['WR'] ?? [])[0] ??
    (byPos['TE'] ?? [])[0] ??
    null
  if (flexPlayer) {
    const flexArr = byPos[flexPlayer.position]
    if (flexArr) flexArr.shift()
    used.add(flexPlayer.player_id)
    slots.push({
      label: 'FLEX',
      player: flexPlayer,
      poolPlayer: playerMap.get(flexPlayer.player_id) ?? null,
      isStarter: true,
    })
  } else {
    slots.push({ label: 'FLEX', player: null, poolPlayer: null, isStarter: true })
  }

  addSlot('K', 'PK', true)
  addSlot('D/ST', 'DEF', true)

  // Bench — remaining players
  const remaining = players.filter(p => !used.has(p.player_id))
  remaining.forEach((p, i) => {
    slots.push({
      label: `BE${i + 1}`,
      player: p,
      poolPlayer: playerMap.get(p.player_id) ?? null,
      isStarter: false,
    })
  })

  // Empty bench rows keep the full roster construction visible while drafting,
  // and keep the 15-slot shape when a draft ends incomplete.
  for (let i = remaining.length; i < BENCH_SLOTS; i++) {
    slots.push({
      label: `BE${i + 1}`,
      player: null,
      poolPlayer: null,
      isStarter: false,
    })
  }

  return slots
}
