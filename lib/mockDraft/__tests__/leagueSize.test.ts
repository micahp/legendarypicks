/**
 * @jest-environment node
 *
 * A draft is 10, 12 or 14 teams, and the seat the drafter chose.
 *
 * EXPECTED VALUES WRITTEN 2026-07-28, BEFORE THE CODE. `createDraft` hardcoded
 * `teams: 12` in the returned state while taking a `playerPool` sized for any
 * league, so a 10- or 14-team draft could not be expressed at all -- the snake
 * order, the pick total, the round boundary and "your next pick" all read off
 * that literal.
 *
 * Every number below is asserted, not observed:
 *   - total picks = teams x 15 -> 150 / 180 / 210
 *   - the snake reverses at the end of every round, at whatever width
 *   - a full draft still drafts each player at most once at every width
 */

import {
  createDraft,
  seededRandom,
  nextTeam,
  currentDrafter,
  isUserPick,
  userNextPick,
  autopick,
  isComplete,
  DraftPlayer,
} from '../engine'

const ROUNDS = 15
const SIZES = [10, 12, 14]

function makeTestPool(size = 400): DraftPlayer[] {
  const posCycle: DraftPlayer['position'][] = ['QB', 'RB', 'WR', 'TE', 'PK', 'DEF']
  const pool: DraftPlayer[] = []
  for (let i = 0; i < size; i++) {
    pool.push({
      player_id: i + 1,
      name: `Player ${i + 1}`,
      position: posCycle[i % posCycle.length],
      team: `TM${(i % 32) + 1}`,
      adp: Math.round((1.5 + i * 0.7) * 10) / 10,
    })
  }
  return pool
}

describe('createDraft carries the chosen league size', () => {
  it.each(SIZES)('a %i-team draft reports %i teams, not 12', teams => {
    const state = createDraft('d', 1, makeTestPool(), 42, teams)
    expect(state.teams).toBe(teams)
    expect(state.rounds).toBe(ROUNDS)
  })

  it('defaults to 12 when no size is given, so existing callers are unchanged', () => {
    expect(createDraft('d', 1, makeTestPool(), 42).teams).toBe(12)
  })
})

describe('the snake reverses at every league width', () => {
  it.each(SIZES)('%i teams: round 1 runs 1..N and round 2 runs N..1', teams => {
    for (let i = 0; i < teams; i++) {
      expect(nextTeam(i + 1, teams)).toBe(i + 1)
      expect(nextTeam(teams + i + 1, teams)).toBe(teams - i)
    }
  })

  it.each(SIZES)('%i teams: the turn team picks back-to-back', teams => {
    // Last pick of round 1 and first pick of round 2 are the same team.
    expect(nextTeam(teams, teams)).toBe(teams)
    expect(nextTeam(teams + 1, teams)).toBe(teams)
  })

  it.each(SIZES)('%i teams: every team gets exactly 15 picks', teams => {
    const counts = new Map<number, number>()
    for (let p = 1; p <= teams * ROUNDS; p++) {
      const t = nextTeam(p, teams)
      counts.set(t, (counts.get(t) ?? 0) + 1)
    }
    expect(counts.size).toBe(teams)
    for (const n of Array.from(counts.values())) expect(n).toBe(ROUNDS)
  })
})

describe('a full draft at each width', () => {
  it.each(SIZES)('%i teams: completes at teams x 15 picks with no duplicates', teams => {
    const rng = seededRandom(7)
    let s = createDraft('d', 1, makeTestPool(), 7, teams)
    let guard = 0
    while (!isComplete(s) && guard++ < 1000) s = autopick(s, rng)

    expect(s.picks.length).toBe(teams * ROUNDS)
    expect(new Set(s.picks.map(p => p.player_id)).size).toBe(teams * ROUNDS)
    expect(s.currentPick).toBe(teams * ROUNDS + 1)
  })
})

describe('the seat the drafter chose is the seat they get', () => {
  it.each(SIZES)('%i teams: the last seat is on the clock at pick N', teams => {
    const state = createDraft('d', teams, makeTestPool(), 42, teams)
    expect(state.seat).toBe(teams)
    // Pick 1 belongs to seat 1; the last seat's first turn is pick N.
    expect(isUserPick(state)).toBe(teams === 1)
    expect(userNextPick(state)).toBe(teams)
  })

  it.each(SIZES)('%i teams: currentDrafter tracks the width, not a constant 12', teams => {
    let s = createDraft('d', 1, makeTestPool(), 42, teams)
    const rng = seededRandom(3)
    const seen: number[] = []
    for (let i = 0; i < teams * 2; i++) {
      seen.push(currentDrafter(s))
      s = autopick(s, rng)
    }
    expect(seen.slice(0, teams)).toEqual(
      Array.from({ length: teams }, (_, i) => i + 1),
    )
    expect(seen.slice(teams)).toEqual(
      Array.from({ length: teams }, (_, i) => teams - i),
    )
  })
})
