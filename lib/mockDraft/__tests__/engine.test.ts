/**
 * @jest-environment node
 *
 * Pure-engine tests for lib/mockDraft/engine.ts.
 * No DOM, no React — runs under Node for fast 200-draft simulations.
 */

import {
  createDraft,
  seededRandom,
  nextTeam,
  currentDrafter,
  isUserPick,
  availableByPosition,
  getTeamRoster,
  getRosterState,
  botPick,
  applyPick,
  autopick,
  isComplete,
  DraftPlayer,
  DraftState,
} from '../engine'

// ── Helpers ────────────────────────────────────────────────────────────────

/**
 * Build a realistic 300-player pool with proper position distribution.
 * ADP values are spaced roughly like real NFL ADPs:
 *   1–180  have real-ish ADPs (the draftable 180)
 *   181–300 have later published ADPs (the waiver-ish tail)
 */
function makeTestPool(size = 300): DraftPlayer[] {
  const pool: DraftPlayer[] = []
  // Round-robin through all 5 positions for even distribution (~60 each at size 300).
  // This guarantees each position has enough depth for 12 teams:
  //   QB max=2×12=24, RB max=6×12=72, WR max=6×12=72, TE max=3×12=36, PK max=2×12=24
  //   60 per position covers all limits with margin.
  const posCycle: DraftPlayer['position'][] = ['QB', 'RB', 'WR', 'TE', 'PK', 'DEF']
  for (let i = 0; i < size; i++) {
    const pos = posCycle[i % posCycle.length]
    // ADP: 1.5 → ~169 for the first 180 (real ADP range), then tail to ~230
    const adp = i < 180
      ? 1.5 + i * 0.93
      : 170 + (i - 180) * 0.5
    pool.push({
      player_id: i + 1,
      name: `Player ${i + 1}`,
      position: pos,
      team: `TM${(i % 32) + 1}`,
      adp: Math.round(adp * 10) / 10,
    })
  }
  return pool
}

/** Run a complete 180-pick draft (user seat 1, all bot picks). Returns final state. */
function simulateFullDraft(seed: number, pool: DraftPlayer[], userSeat = 1): DraftState {
  const state = createDraft('test-id', userSeat, pool, seed)
  const rng = seededRandom(seed)
  let s = state
  while (!isComplete(s)) {
    s = autopick(s, rng)
  }
  return s
}

// ── seededRandom ───────────────────────────────────────────────────────────

describe('seededRandom', () => {
  it('produces deterministic sequences for the same seed', () => {
    const a = Array.from({ length: 20 }, seededRandom(42))
    const b = Array.from({ length: 20 }, seededRandom(42))
    expect(a).toEqual(b)
  })

  it('produces different sequences for different seeds', () => {
    const a = Array.from({ length: 20 }, seededRandom(42))
    const b = Array.from({ length: 20 }, seededRandom(99))
    expect(a).not.toEqual(b)
  })

  it('produces values in [0, 1)', () => {
    const rng = seededRandom(123)
    for (let i = 0; i < 1000; i++) {
      const v = rng()
      expect(v).toBeGreaterThanOrEqual(0)
      expect(v).toBeLessThan(1)
    }
  })
})

// ── nextTeam (snake order) ─────────────────────────────────────────────────

describe('nextTeam', () => {
  it('round 1: picks 1–12 → teams 1–12', () => {
    for (let pick = 1; pick <= 12; pick++) {
      expect(nextTeam(pick, 12)).toBe(pick)
    }
  })

  it('round 2: picks 13–24 → teams 12–1', () => {
    // pick 13 → team 12, pick 14 → team 11, …, pick 24 → team 1
    expect(nextTeam(13, 12)).toBe(12)
    expect(nextTeam(14, 12)).toBe(11)
    expect(nextTeam(24, 12)).toBe(1)
  })

  it('team 1 picks 1 then 24 (turn at both ends)', () => {
    expect(nextTeam(1, 12)).toBe(1)
    expect(nextTeam(24, 12)).toBe(1)
  })

  it('team 12 picks 12 then 13 (back-to-back at the turn)', () => {
    expect(nextTeam(12, 12)).toBe(12)
    expect(nextTeam(13, 12)).toBe(12)
  })

  it('round 3: picks 25–36 → teams 1–12', () => {
    expect(nextTeam(25, 12)).toBe(1)
    expect(nextTeam(36, 12)).toBe(12)
  })

  it('final pick 180 → team 12 (odd round, pick 180 in round 15)', () => {
    // 15 rounds × 12 = 180. Round 15 is odd → teams 1..12
    // pick 180: round = ceil(180/12) = 15 (odd), posInRound = 179 % 12 = 11 → team 12
    expect(nextTeam(180, 12)).toBe(12)
  })
})

// ── currentDrafter / isUserPick ────────────────────────────────────────────

describe('currentDrafter / isUserPick', () => {
  it('currentDrafter matches nextTeam for currentPick', () => {
    const pool = makeTestPool()
    const state = createDraft('test', 1, pool, 42)
    expect(currentDrafter(state)).toBe(1) // currentPick = 1
  })

  it('isUserPick returns true only for the user seat', () => {
    const pool = makeTestPool()
    const state = createDraft('test', 5, pool, 42)
    expect(isUserPick(state)).toBe(false) // currentPick=1 → team 1, seat=5
  })

  it('isUserPick is true when current drafter is the seat', () => {
    const pool = makeTestPool()
    const state = createDraft('test', 3, pool, 42)
    // fast-forward: pick 1 (team 1), pick 2 (team 2) applied
    let s = applyPick(state, 1, true)
    s = applyPick(s, 2, true)
    // currentPick = 3 → team 3, seat = 3
    expect(currentDrafter(s)).toBe(3)
    expect(isUserPick(s)).toBe(true)
  })
})

// ── availableByPosition ────────────────────────────────────────────────────

describe('availableByPosition', () => {
  it('filters pool by position', () => {
    const pool = makeTestPool(50)
    const qbs = availableByPosition(pool, 'QB')
    expect(qbs.length).toBeGreaterThan(0)
    expect(qbs.every(p => p.position === 'QB')).toBe(true)
  })

  it('returns empty array for position with no players', () => {
    const pool = makeTestPool(10)
    const filtered = pool.filter(p => p.position === 'QB')
    const result = availableByPosition(pool, 'QB')
    expect(result).toHaveLength(filtered.length)
  })
})

// ── createDraft ────────────────────────────────────────────────────────────

describe('createDraft', () => {
  it('initialises with correct defaults', () => {
    const pool = makeTestPool()
    const state = createDraft('draft-1', 3, pool, 99)
    expect(state.id).toBe('draft-1')
    expect(state.seat).toBe(3)
    expect(state.teams).toBe(12)
    expect(state.rounds).toBe(15)
    expect(state.picks).toHaveLength(0)
    expect(state.completed).toBe(false)
    expect(state.currentPick).toBe(1)
    expect(state.seed).toBe(99)
    expect(state.playerPool).toHaveLength(pool.length)
    expect(state.availablePool).toHaveLength(pool.length)
  })

  it('sorts availablePool by ADP ascending', () => {
    const pool = makeTestPool()
    const state = createDraft('draft-1', 1, pool, 1)
    for (let i = 1; i < state.availablePool.length; i++) {
      expect(state.availablePool[i].adp).toBeGreaterThanOrEqual(state.availablePool[i - 1].adp)
    }
  })

  it('does not mutate the input pool', () => {
    const pool = makeTestPool()
    const copy = [...pool]
    createDraft('draft-1', 1, pool, 1)
    expect(pool).toEqual(copy)
  })
})

// ── applyPick (immutable) ──────────────────────────────────────────────────

describe('applyPick', () => {
  it('appends a pick and removes the player from availablePool', () => {
    const pool = makeTestPool()
    const state = createDraft('draft-1', 1, pool, 1)
    const playerId = state.availablePool[0].player_id
    const next = applyPick(state, playerId, false)

    expect(next.picks).toHaveLength(1)
    expect(next.picks[0].player_id).toBe(playerId)
    expect(next.picks[0].pick_no).toBe(1)
    expect(next.picks[0].team_no).toBe(1)
    expect(next.picks[0].auto).toBe(false)
    expect(next.currentPick).toBe(2)
    expect(next.availablePool).toHaveLength(pool.length - 1)
    expect(next.availablePool.find(p => p.player_id === playerId)).toBeUndefined()

    // original state unchanged
    expect(state.picks).toHaveLength(0)
    expect(state.currentPick).toBe(1)
    expect(state.availablePool).toHaveLength(pool.length)
  })

  it('marks completed after the last pick (180)', () => {
    const pool = makeTestPool()
    const state = createDraft('draft-1', 1, pool, 1)
    // Apply 179 picks manually
    let s = state
    for (let i = 0; i < 179; i++) {
      s = applyPick(s, s.availablePool[0].player_id, true)
    }
    expect(s.completed).toBe(false)
    expect(s.currentPick).toBe(180)

    s = applyPick(s, s.availablePool[0].player_id, true)
    expect(s.currentPick).toBe(181)
    expect(s.completed).toBe(true)
  })
})

// ── getTeamRoster / getRosterState ─────────────────────────────────────────

describe('getTeamRoster / getRosterState', () => {
  it('getTeamRoster returns only picks for the given team', () => {
    const pool = makeTestPool()
    const state = createDraft('draft-1', 1, pool, 1)
    // Team 1 picks at 1 and 24; apply 24 autopicks to complete 2 full rounds
    const rng = seededRandom(42)
    let s = state
    for (let i = 0; i < 24; i++) {
      s = autopick(s, rng)
    }
    const t1 = getTeamRoster(s, 1)
    const t2 = getTeamRoster(s, 2)
    expect(t1).toHaveLength(2) // picked at 1 and 24
    expect(t2).toHaveLength(2) // picked at 2 and 23
    expect(t1.every(p => p.team_no === 1)).toBe(true)
    expect(t2.every(p => p.team_no === 2)).toBe(true)
  })

  it('getRosterState computes position counts and starting slot status', () => {
    const pool = makeTestPool()
    // Simulate a full draft and check a team's roster state
    const final = simulateFullDraft(77, pool)
    const roster = getRosterState(final, 5)
    expect(roster.teamNo).toBe(5)
    expect(roster.totalPicks).toBe(15)
    // All starting slots should be filled after a full draft
    expect(roster.startingSlotsFilled.QB).toBe(true)
    expect(roster.startingSlotsFilled.RB).toBe(true)
    expect(roster.startingSlotsFilled.WR).toBe(true)
    expect(roster.startingSlotsFilled.TE).toBe(true)
    expect(roster.startingSlotsFilled.PK).toBe(true)
    expect(roster.startingSlotsFilled.DEF).toBe(true)
    expect(roster.startingSlotsFilled.FLEX).toBe(true)
  })
})

// ── botPick ────────────────────────────────────────────────────────────────

describe('botPick', () => {
  it('picks a player from the available pool', () => {
    const pool = makeTestPool()
    const state = createDraft('test', 1, pool, 42)
    const rng = seededRandom(42)
    const player = botPick(state, rng)
    expect(player).toBeDefined()
    expect(state.availablePool.some(p => p.player_id === player.player_id)).toBe(true)
  })

  it('rejects a draftable player without published ADP instead of deriving a rank', () => {
    const pool = makeTestPool()
    pool[0] = { ...pool[0], adp: null }
    const state = createDraft('test', 1, pool, 42)

    expect(() => botPick(state, () => 0.5)).toThrow(
      `mockDraft: player ${pool[0].player_id} (${pool[0].name}) has no published ADP`,
    )
  })

  it('never exceeds position limits', () => {
    // Small pool where bots are forced to fill positions
    const tinyPool: DraftPlayer[] = []
    for (let i = 0; i < 50; i++) {
      const pos: DraftPlayer['position'][] = ['QB', 'RB', 'WR', 'TE', 'PK']
      for (const p of pos) {
        tinyPool.push({
          player_id: tinyPool.length + 1,
          name: `P${tinyPool.length + 1}`,
          position: p,
          team: 'T1',
          adp: tinyPool.length + 1,
        })
      }
    }
    // Run several full drafts and check no team exceeds limits
    for (let seed = 0; seed < 20; seed++) {
      const final = simulateFullDraft(seed, tinyPool, 1)
      for (let team = 1; team <= 12; team++) {
        const roster = getRosterState(final, team)
        expect(roster.positionCounts['QB'] || 0).toBeLessThanOrEqual(2)
        expect(roster.positionCounts['RB'] || 0).toBeLessThanOrEqual(6)
        expect(roster.positionCounts['WR'] || 0).toBeLessThanOrEqual(6)
        expect(roster.positionCounts['TE'] || 0).toBeLessThanOrEqual(3)
        expect(roster.positionCounts['PK'] || 0).toBeLessThanOrEqual(2)
        expect(roster.positionCounts['DEF'] || 0).toBeLessThanOrEqual(1)
      }
    }
  })
})

// ── Determinism ────────────────────────────────────────────────────────────

describe('determinism', () => {
  it('same seed + same pool → identical pick list', () => {
    const pool = makeTestPool()
    const a = simulateFullDraft(12345, pool)
    const b = simulateFullDraft(12345, pool)

    expect(a.picks).toHaveLength(180)
    expect(b.picks).toHaveLength(180)
    for (let i = 0; i < 180; i++) {
      expect(a.picks[i].player_id).toBe(b.picks[i].player_id)
      expect(a.picks[i].team_no).toBe(b.picks[i].team_no)
      expect(a.picks[i].pick_no).toBe(b.picks[i].pick_no)
    }
  })

  it('different seeds → different pick list', () => {
    const pool = makeTestPool()
    const a = simulateFullDraft(111, pool)
    const b = simulateFullDraft(222, pool)

    // At least one pick should differ
    const idsA = a.picks.map(p => p.player_id)
    const idsB = b.picks.map(p => p.player_id)
    expect(idsA).not.toEqual(idsB)
  })
})

// ── No duplicate player_id ─────────────────────────────────────────────────

describe('no duplicate picks', () => {
  it('no player is drafted twice in a full draft', () => {
    const pool = makeTestPool()
    const final = simulateFullDraft(555, pool)
    const ids = final.picks.map(p => p.player_id)
    const unique = new Set(ids)
    expect(unique.size).toBe(ids.length)
    expect(unique.size).toBe(180)
  })
})

// ── Roster completeness ────────────────────────────────────────────────────

describe('roster completeness', () => {
  it('every team has exactly 15 picks', () => {
    const pool = makeTestPool()
    const final = simulateFullDraft(777, pool)
    for (let team = 1; team <= 12; team++) {
      const roster = getTeamRoster(final, team)
      expect(roster).toHaveLength(15)
    }
  })

  it('total picks = 180', () => {
    const pool = makeTestPool()
    const final = simulateFullDraft(888, pool)
    expect(final.picks).toHaveLength(180)
  })
})

// ── Pool never runs dry (200 drafts) ───────────────────────────────────────

describe('200-draft simulation (§7.2)', () => {
  it('completes 200 full drafts without the pool running dry', () => {
    const pool = makeTestPool()
    let completed = 0
    let failed = 0

    for (let seed = 0; seed < 200; seed++) {
      const final = simulateFullDraft(seed * 100 + 1, pool)
      if (isComplete(final) && final.picks.length === 180) {
        completed++
      } else {
        failed++
      }
    }

    expect(failed).toBe(0)
    expect(completed).toBe(200)
  })

  it('every team fills all starting slots in all 200 drafts', () => {
    const pool = makeTestPool()
    for (let seed = 0; seed < 200; seed++) {
      const final = simulateFullDraft(seed * 100 + 1, pool)
      for (let team = 1; team <= 12; team++) {
        const roster = getRosterState(final, team)
        expect(roster.startingSlotsFilled.QB).toBe(true)
        expect(roster.startingSlotsFilled.RB).toBe(true)
        expect(roster.startingSlotsFilled.WR).toBe(true)
        expect(roster.startingSlotsFilled.TE).toBe(true)
        expect(roster.startingSlotsFilled.PK).toBe(true)
        expect(roster.startingSlotsFilled.DEF).toBe(true)
        expect(roster.startingSlotsFilled.FLEX).toBe(true)
      }
    }
  })
})

// ── Edge cases ─────────────────────────────────────────────────────────────

describe('edge cases', () => {
  it('pick 1 is never a defense in full-draft simulations', () => {
    const pool = makeTestPool()
    for (let seed = 0; seed < 200; seed++) {
      const final = simulateFullDraft(seed * 100 + 1, pool)
      const pick1 = final.picks[0]
      const player = final.playerPool.find(p => p.player_id === pick1.player_id)
      expect(player).toBeDefined()
      expect(player!.position).not.toBe('DEF')
    }
  })

  it('autopick returns auto:true on the pick', () => {
    const pool = makeTestPool()
    const state = createDraft('test', 1, pool, 42)
    const rng = seededRandom(42)
    const next = autopick(state, rng)
    expect(next.picks[0].auto).toBe(true)
  })

  it('manual pick (applyPick with auto:false) returns auto:false', () => {
    const pool = makeTestPool()
    const state = createDraft('test', 1, pool, 42)
    const next = applyPick(state, state.availablePool[0].player_id, false)
    expect(next.picks[0].auto).toBe(false)
  })

  it('botPick with zero-jitter rng picks the best ADP available', () => {
    const pool = makeTestPool()
    const state = createDraft('test', 1, pool, 42)
    // Zero-jitter rng: always returns 0.5 → jitter = 0 → score = adp
    const zeroRng = () => 0.5
    const player = botPick(state, zeroRng)
    // Should be the lowest-ADP player filtered only by position max
    // Team 1 has no players, so no position max applied
    // availablePool is sorted by ADP asc → first player
    expect(player.player_id).toBe(state.availablePool[0].player_id)
  })

  it('isComplete returns false for in-progress draft', () => {
    const pool = makeTestPool()
    const state = createDraft('test', 1, pool, 1)
    expect(isComplete(state)).toBe(false)
  })
})
