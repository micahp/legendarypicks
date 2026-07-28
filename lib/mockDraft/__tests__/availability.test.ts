import type { PoolPlayer } from '../../../components/Leagues/types'
import { poolTeamGames } from '../availability'
import { poolToDraftRow } from '../api'

function player(overrides: Partial<PoolPlayer> = {}): PoolPlayer {
  return {
    player_id: 1,
    name: 'Measured Player',
    position: 'RB',
    team: 'CHI',
    adp: 10,
    percent_owned: 50,
    sample: 'full',
    games_played: 2,
    games_missed: 1,
    weeks_played: [1, 3],
    team_weeks: [1, 2, 3],
    ...overrides,
  }
}

describe('pool availability denominators', () => {
  test('counts the published team schedule instead of assuming 17 games', () => {
    expect(poolTeamGames(player())).toBe(3)
  })

  test('returns unknown when the pool has no schedule evidence', () => {
    expect(poolTeamGames(player({ team_weeks: [] }))).toBeNull()
  })

  test('preserves the API games_missed value when adapting a pool row', () => {
    const row = poolToDraftRow(player(), 7)

    expect(row.team_games).toBe(3)
    expect(row.games_missed).toBe(1)
  })
})
