import { seasonLabel } from './presentation'

// The bug this exists to prevent is not a crash. It is one header printing
// `NHL · 20252026 · 82 games` above `SEASON STATS · 2026` — two labels, one season,
// neither of them what a hockey fan says out loud. The keys stay as the publishers
// write them; only the rendering is ours.
describe('seasonLabel', () => {
  it("renders the NHL's own 8-digit key the way ESPN prints it", () => {
    expect(seasonLabel('nhl', 20252026)).toBe('2025-26')
    expect(seasonLabel('nhl', '20252026')).toBe('2025-26')
  })

  it('renders the ESPN 4-digit key for the same season identically', () => {
    // Both keys are live in prod for NHL — `player_game_logs` is on 20252026 and
    // `player_stats` is on 2026. They are the same season and must read the same.
    expect(seasonLabel('nhl', 2026)).toBe('2025-26')
  })

  it('splits NBA seasons too, including the stale one still being served', () => {
    expect(seasonLabel('nba', 2026)).toBe('2025-26')
    expect(seasonLabel('nba', 2023)).toBe('2022-23')
  })

  it('leaves single-calendar-year leagues alone', () => {
    expect(seasonLabel('nfl', 2025)).toBe('2025')
    expect(seasonLabel('mlb', 2026)).toBe('2026')
  })

  it('is case-insensitive about the league', () => {
    expect(seasonLabel('NHL', 20252026)).toBe('2025-26')
  })

  it('returns the input rather than NaN when it cannot parse', () => {
    // A gap must never render as `NaN-aN`, and a value we were handed must never
    // come back as an empty string — that would be inventing an absence.
    expect(seasonLabel('nhl', 'preseason')).toBe('preseason')
    expect(seasonLabel('nhl', 202)).toBe('202')
  })

  it('renders nothing for nothing', () => {
    expect(seasonLabel('nhl', null)).toBe('')
    expect(seasonLabel('nhl', undefined)).toBe('')
    expect(seasonLabel('nhl', '')).toBe('')
  })
})
