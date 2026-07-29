// Pure TS mock-draft engine — no React, no fetch, no DOM.
// Seeded PRNG, bot ADP logic, snake order.
// Spec: docs/SPEC-slice-D-mock-draft.md §3–4

export interface DraftPlayer {
  player_id: number
  name: string
  position: 'QB' | 'RB' | 'WR' | 'TE' | 'PK' | 'DEF'
  team: string
  adp: number | null
}

export interface DraftPick {
  pick_no: number   // 1..(teams x rounds) absolute
  team_no: number   // 1..teams
  player_id: number
  auto: boolean     // bot pick or timeout autopick
}

export interface RosterState {
  teamNo: number
  picks: DraftPick[]
  players: DraftPlayer[]
  positionCounts: Record<string, number>
  totalPicks: number
  startingSlotsFilled: {
    QB: boolean
    RB: boolean
    WR: boolean
    TE: boolean
    PK: boolean
    DEF: boolean
    FLEX: boolean
  }
}

export interface DraftState {
  id: string
  seat: number       // 1..teams, which team the user controls
  teams: number      // 10, 12 or 14
  rounds: number     // 15
  playerPool: DraftPlayer[]  // full reference pool
  availablePool: DraftPlayer[] // subset not yet picked, sorted by ADP
  picks: DraftPick[]
  completed: boolean
  currentPick: number  // next pick_no to be made (1..teams x rounds)
  seed: number
}

/** The league sizes the mock draft offers. Must match the backend's
 *  _LEAGUE_SIZES — a size the server rejects would create a draft on screen
 *  that no row exists for. */
export const LEAGUE_SIZES = [10, 12, 14] as const
export type LeagueSize = typeof LEAGUE_SIZES[number]
export const DEFAULT_TEAMS: LeagueSize = 12
export const ROUNDS = 15

// ── Position limits for bots (bench-inclusive ceilings) ──
const POSITION_MAX: Record<string, number> = {
  QB: 2,
  RB: 6,
  WR: 6,
  TE: 3,
  PK: 2,
  DEF: 1,
}

// ── Starting slot requirements ──
//   QB(1)  RB(2)  WR(2)  TE(1)  FLEX(RB/WR/TE, 1)  PK(1)  DEF(1)  + 6 BE
const STARTER_COUNT: Record<string, number> = {
  QB: 1,
  RB: 2,
  WR: 2,
  TE: 1,
  PK: 1,
  DEF: 1,
}
// FLEX: need total RB+WR+TE >= 6 (2+2+1 dedicated + 1 flex)
const FLEX_TOTAL_NEED = 6

// ── mulberry32 seeded PRNG (8 lines) ──
export function seededRandom(seed: number): () => number {
  let state = seed | 0
  return function (): number {
    state = (state + 0x6D2B79F5) | 0
    let t = Math.imul(state ^ (state >>> 15), 1 | state)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

// ── Snake order ──
//   Round 1: 1..N  →  Round 2: N..1  →  Round 3: 1..N  …  at any league width
export function nextTeam(pickNo: number, teams: number): number {
  const round = Math.ceil(pickNo / teams)
  const posInRound = (pickNo - 1) % teams
  if (round % 2 === 1) {
    return posInRound + 1
  }
  return teams - posInRound
}

export function currentDrafter(state: DraftState): number {
  return nextTeam(state.currentPick, state.teams)
}

export function isUserPick(state: DraftState): boolean {
  return currentDrafter(state) === state.seat
}

/** Return the user's next pick number, or null if no picks remain. */
export function userNextPick(state: DraftState): number | null {
  if (state.completed) return null
  for (let p = state.currentPick; p <= state.teams * state.rounds; p++) {
    if (nextTeam(p, state.teams) === state.seat) return p
  }
  return null
}

// ── Pool helpers ──
export function availableByPosition(pool: DraftPlayer[], position: string): DraftPlayer[] {
  return pool.filter(p => p.position === position)
}

// ── Roster queries ──
export function getTeamRoster(state: DraftState, teamNo: number): DraftPick[] {
  return state.picks.filter(p => p.team_no === teamNo)
}

export function getRosterState(state: DraftState, teamNo: number): RosterState {
  const picks = getTeamRoster(state, teamNo)
  // Build a lookup for O(1) player resolution
  const playerMap = new Map(state.playerPool.map(p => [p.player_id, p]))
  const players: DraftPlayer[] = []
  for (const pick of picks) {
    const player = playerMap.get(pick.player_id)
    if (player) players.push(player)
  }
  const positionCounts: Record<string, number> = {}
  for (const pl of players) {
    positionCounts[pl.position] = (positionCounts[pl.position] || 0) + 1
  }
  const rbWrTe =
    (positionCounts['RB'] || 0) + (positionCounts['WR'] || 0) + (positionCounts['TE'] || 0)
  return {
    teamNo,
    picks,
    players,
    positionCounts,
    totalPicks: picks.length,
    startingSlotsFilled: {
      QB: (positionCounts['QB'] || 0) >= STARTER_COUNT['QB'],
      RB: (positionCounts['RB'] || 0) >= STARTER_COUNT['RB'],
      WR: (positionCounts['WR'] || 0) >= STARTER_COUNT['WR'],
      TE: (positionCounts['TE'] || 0) >= STARTER_COUNT['TE'],
      PK: (positionCounts['PK'] || 0) >= STARTER_COUNT['PK'],
      DEF: (positionCounts['DEF'] || 0) >= STARTER_COUNT['DEF'],
      FLEX: rbWrTe >= FLEX_TOTAL_NEED,
    },
  }
}

// ── Bot picking logic (§3) ──
//   Rules (in order):
//     1. Never draft a position already filled to max
//     2. From round 12+, if a starting slot is still empty, restrict to positions that fill it
//     3. Otherwise best available by jittered ADP
//   Candidate score = adp * (1 + jitter), jitter ~ uniform(-0.10, +0.10)
export function botPick(state: DraftState, rng: () => number): DraftPlayer {
  const teamNo = currentDrafter(state)
  const roster = getRosterState(state, teamNo)
  const currentRound = Math.ceil(state.currentPick / state.teams)

  // Rule 1: filter out positions at max
  let candidates = state.availablePool.filter(p => {
    const count = roster.positionCounts[p.position] || 0
    const max = POSITION_MAX[p.position]
    return !max || count < max
  })

  // Rule 2: from round 12, restrict to positions that fill empty starting slots
  if (currentRound >= 12) {
    const needs: string[] = []
    if (!roster.startingSlotsFilled.QB) needs.push('QB')
    if (!roster.startingSlotsFilled.RB) needs.push('RB')
    if (!roster.startingSlotsFilled.WR) needs.push('WR')
    if (!roster.startingSlotsFilled.TE) needs.push('TE')
    if (!roster.startingSlotsFilled.PK) needs.push('PK')
    if (!roster.startingSlotsFilled.DEF) needs.push('DEF')
    if (!roster.startingSlotsFilled.FLEX) {
      needs.push('RB', 'WR', 'TE')
    }

    // Only restrict if there are specific needs (if every slot is empty, something is wrong)
    if (needs.length > 0) {
      const needSet = new Set(needs)
      const restricted = candidates.filter(p => needSet.has(p.position))
      // Fallback: if restriction yields no candidates, keep the unfiltered candidates
      if (restricted.length > 0) {
        candidates = restricted
      }
    }
  }

  // Safety net: should never happen with a properly-sized pool
  if (candidates.length === 0) {
    // eslint-disable-next-line no-console
    console.warn(
      `mockDraft: no candidates for team ${teamNo} at pick ${state.currentPick} (round ${currentRound}) — falling back to full availablePool`,
    )
    candidates = state.availablePool
  }

  // Rule 3: score by published ADP (lower = better).
  // The pool contract requires every draftable player to carry a copied ADP.
  // Fail closed if that contract regresses instead of inventing a replacement.
  let best = candidates[0]
  let bestScore = Infinity
  for (const p of candidates) {
    if (p.adp == null) {
      throw new Error(
        `mockDraft: player ${p.player_id} (${p.name}) has no published ADP`,
      )
    }
    // Map rng() ∈ [0,1) to jitter ∈ [-0.10, +0.10]
    const jitter = (rng() - 0.5) * 0.2
    const score = p.adp * (1 + jitter)
    if (score < bestScore) {
      bestScore = score
      best = p
    }
  }
  return best
}

// ── State transitions (immutable) ──
export function applyPick(
  state: DraftState,
  playerId: number,
  auto: boolean,
): DraftState {
  const pick: DraftPick = {
    pick_no: state.currentPick,
    team_no: currentDrafter(state),
    player_id: playerId,
    auto,
  }
  const newAvailablePool = state.availablePool.filter(p => p.player_id !== playerId)
  const newCurrentPick = state.currentPick + 1
  const maxPicks = state.teams * state.rounds

  return {
    ...state,
    picks: [...state.picks, pick],
    availablePool: newAvailablePool,
    currentPick: newCurrentPick,
    completed: newCurrentPick > maxPicks,
  }
}

// autopick uses botPick + applyPick. The caller controls jitter via the rng param —
// for user timeout, pass a zero-jitter rng (always returns 0.5 → jitter = 0).
export function autopick(state: DraftState, rng: () => number): DraftState {
  const player = botPick(state, rng)
  return applyPick(state, player.player_id, true)
}

export function isComplete(state: DraftState): boolean {
  return state.completed
}

// ── Factory ──
export function createDraft(
  id: string,
  seat: number,
  playerPool: DraftPlayer[],
  seed: number,
  // Optional so every pre-league-size caller keeps its 12-team draft. The rest
  // of the engine already reads state.teams -- nextTeam, userNextPick, applyPick
  // and botPick's round arithmetic all take it as a parameter -- so this literal
  // was the only thing pinning the whole engine to 12.
  teams: number = DEFAULT_TEAMS,
): DraftState {
  // availablePool is sorted by ADP ascending (lowest ADP = best, picked first).
  //   D/ST players have null ADP — sort them after all numeric ADPs.
  const sorted = [...playerPool].sort((a, b) => {
    if (a.adp === null && b.adp === null) return 0
    if (a.adp === null) return 1
    if (b.adp === null) return -1
    return a.adp - b.adp
  })
  return {
    id,
    seat,
    teams,
    rounds: ROUNDS,
    playerPool,
    availablePool: sorted,
    picks: [],
    completed: false,
    currentPick: 1,
    seed,
  }
}
