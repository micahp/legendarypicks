import { render, screen } from '@testing-library/react'

import PlayerGameLog from './PlayerGameLog'


function response(body: unknown, ok = true, status = 200): Response {
  return { ok, status, json: async () => body } as Response
}

describe('PlayerGameLog', () => {
  beforeEach(() => {
    ;(global as typeof globalThis & { fetch: jest.Mock }).fetch = jest
      .fn((url: string) => {
        if (url.endsWith('/game-log')) {
          return Promise.resolve(response({
            contract: 'nfl-player-game-log-v1',
            player_id: 469,
            name: 'Josh Allen',
            position: 'QB',
            reference_season: 2025,
            fields: ['cmp', 'att', 'carries'],
            team_games: 3,
            games_played: 3,
            games: [
              { week: 1, played: true, opponent: 'BAL', team: 'BUF', stats: { cmp: 22, att: 31, carries: 8 } },
              { week: 2, played: true, opponent: 'NYJ', team: 'BUF', stats: { cmp: 24, att: 35, carries: 10 } },
              { week: 3, played: true, opponent: 'NE', team: 'BUF', stats: { cmp: 20, att: 28, carries: 6 } },
            ],
          }))
        }
        return Promise.resolve(response({
          season: 2025,
          nfl_schedule_games: [
            { week: 1, phase: 'regular', opponent: 'BAL', home: true },
            { week: 2, phase: 'regular', opponent: 'NYJ', home: false },
          ],
        }))
      })
  })

  afterEach(() => {
    jest.restoreAllMocks()
    delete (global as Partial<typeof globalThis>).fetch
  })

  it('uses readable count labels and marks only published away games', async () => {
    render(<PlayerGameLog playerId={469} />)

    expect(await screen.findByText('@ NYJ')).toBeTruthy()
    expect(screen.getByText('Comp')).toBeTruthy()
    expect(screen.getByText('Att')).toBeTruthy()
    expect(screen.getByText('Car')).toBeTruthy()
    expect(screen.getByText('BAL')).toBeTruthy()
    expect(screen.queryByText('@ BAL')).toBeNull()
    expect(screen.getByText('NE')).toBeTruthy()
    expect(screen.queryByText('@ NE')).toBeNull()
  })
})
