import { createDraft, seededRandom, botPick, applyPick, isComplete, DraftPlayer, DraftState } from '../engine'
import realPool from './realpool.fixture.json'

function sim(seed: number, pool: DraftPlayer[]): DraftState {
  let s = createDraft('t', 1, pool, seed)
  const rng = seededRandom(seed)
  let guard = 0
  while (!isComplete(s) && guard++ < 500) {
    const p = botPick(s, rng)
    if (p == null) break
    s = applyPick(s, p.player_id, true)
  }
  return s
}

describe('REAL pool distribution', () => {
  it('completes 200 drafts against the live pool shape', () => {
    const raw = realPool as unknown as { players: DraftPlayer[] }
    const pool = raw.players || (realPool as unknown as DraftPlayer[])
    let ok = 0
    const fails: number[] = []
    for (let seed = 0; seed < 200; seed++) {
      const f = sim(seed * 100 + 1, pool)
      if (isComplete(f) && f.picks.length === 180) ok++
      else fails.push(seed)
    }
    console.log('completed', ok, 'of 200; first failed seeds', fails.slice(0, 5))
    expect(ok).toBe(200)
  })
})
