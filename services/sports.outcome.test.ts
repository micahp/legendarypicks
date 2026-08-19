import { normalizeGame } from './sports'

// The backend computes a finish display soccer's raw shortDetail does not
// carry ("FT (Pens)" / "FT (AET)" / "Suspended" — espn_client soccer branch).
// It must survive the anti-corruption layer so the card badge can show it.
describe('normalizeGame method of victory passthrough', () => {
  it('surfaces the backend soccer pens status as the badge detail', () => {
    const g = normalizeGame({
      game_id: '401863611',
      league: 'lcup',
      date: '2026-08-12T00:00:00Z',
      state: 'post',
      status: 'FT (Pens)',
      status_detail: 'FT-Pens',
      home: { abbrev: 'CLB', name: 'Columbus Crew', score: 1, winner: true },
      away: { abbrev: 'UNAM', name: 'UNAM', score: 1, winner: false },
    }, 'lcup')
    expect(g.status).toBe('FINAL')
    expect(g.statusDetail).toBe('FT-Pens')
  })

  it('does not invent a detail for a plain final', () => {
    const g = normalizeGame({
      game_id: 'x', league: 'mls', date: '2026-08-15T20:00:00Z',
      state: 'post', status: 'FT', status_detail: 'FT',
      home: { abbrev: 'ATL', name: 'Atlanta United', score: 2, winner: true },
      away: { abbrev: 'RBNY', name: 'NY Red Bulls', score: 1, winner: false },
    }, 'mls')
    expect(g.statusDetail).toBe('FT')
  })

  it('passes the UFC finish through to the card', () => {
    const g = normalizeGame({
      game_id: '600059185', league: 'ufc', date: '2026-08-16T01:00:00Z',
      state: 'post', status: 'Final', status_detail: 'Final',
      outcome_method: 'Submission', outcome_round: 3, outcome_clock: '1:24',
      home: { abbrev: 'J. Wells', name: 'Jeremiah Wells', winner: true },
      away: { abbrev: 'M. Orolbai', name: 'Myktybek Orolbai', winner: false },
    }, 'ufc')
    expect(g.outcomeMethod).toBe('Submission')
    expect(g.outcomeRound).toBe(3)
    expect(g.outcomeClock).toBe('1:24')
  })
})
