import { isPreseasonGame, normalizeGame } from './sports'

describe('preseason by the publisher\'s own phase', () => {
  it('reads ESPN season_slug on every league that files one', () => {
    for (const league of ['nba', 'nfl', 'nhl', 'mlb', 'ncaaf']) {
      expect(normalizeGame({ game_id: '1', season_slug: 'preseason', season_type: 1, home: {}, away: {} }, league).isPreseason).toBe(true)
      expect(normalizeGame({ game_id: '2', season_slug: 'regular-season', season_type: 2, home: {}, away: {} }, league).isPreseason).toBe(false)
    }
  })

  it('trusts the slug over the number, and the number only when no slug was stored', () => {
    expect(isPreseasonGame({ season_slug: 'post-season', season_type: 1 })).toBe(false)
    expect(isPreseasonGame({ season_type: 1 })).toBe(true)
    expect(isPreseasonGame({ season_type: 3 })).toBe(false)
  })

  it('never guesses for a league that publishes no phase (soccer, tennis, UFC)', () => {
    expect(isPreseasonGame({ status_detail: 'FT', stage: 'regular' })).toBe(false)
    expect(isPreseasonGame({})).toBe(false)
    expect(isPreseasonGame({ stage: 'preseason' })).toBe(true)
  })
})
