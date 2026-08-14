import axios from 'axios'
import { SportsService } from './sports'

jest.mock('axios', () => ({
  __esModule: true,
  default: { get: jest.fn() },
}))

const get = axios.get as jest.Mock

describe('viewer-local scoreboard dates', () => {
  beforeEach(() => get.mockReset())

  it('keeps a DB fallback with day precision in the requested date bucket', async () => {
    get.mockImplementation((_url: string, config: any) => {
      const date = config?.params?.date
      return Promise.resolve({
        data: date === '2026-07-20'
          ? [{
              game_id: '401816186',
              date: '2026-07-20',
              state: 'post',
              completed: true,
              status: 'completed',
              home: { abbrev: 'BOS', score: 6 },
              away: { abbrev: 'BAL', score: 5 },
            }]
          : [],
      })
    })

    const games = await SportsService.getGamesByLocalDate('mlb', '2026-07-20')

    expect(games.map(game => game.gameId)).toEqual(['401816186'])
  })
})
