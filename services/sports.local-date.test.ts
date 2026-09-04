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

  it('keeps a LIVE game on today\'s board even when its start instant falls on the prior local day', async () => {
    // Reported by Micah 2026-08-31: Venus Williams vs Sofia Kenin, US Open,
    // started 2026-08-31T04:10Z -- 2026-08-30 23:10 in any US timezone west of
    // Eastern. The local-day bucket computed that correctly as "the 30th" and
    // silently dropped a match that was live, right now, from "today"'s board.
    jest.useFakeTimers().setSystemTime(new Date('2026-08-31T15:00:00Z'))
    get.mockImplementation((_url: string, config: any) => {
      const date = config?.params?.date
      return Promise.resolve({
        data: date === '2026-08-31'
          ? [{
              game_id: '182618',
              date: '2026-08-31T04:10Z',
              state: 'in',
              status_detail: '2nd',
              home: { abbrev: 'V. Williams', name: 'Venus Williams', score: 0 },
              away: { abbrev: 'S. Kenin', name: 'Sofia Kenin', score: 1 },
            }]
          : [],
      })
    })

    const games = await SportsService.getGamesByLocalDate('wta', '2026-08-31')

    expect(games.map(game => game.gameId)).toEqual(['182618'])
    expect(games[0].status).toBe('LIVE')
    jest.useRealTimers()
  })

  it('does not leak a live game onto a date the viewer is browsing that is not today', async () => {
    jest.useFakeTimers().setSystemTime(new Date('2026-09-05T15:00:00Z'))
    get.mockImplementation((_url: string, config: any) => {
      const date = config?.params?.date
      // Mid-day UTC, unambiguous across any timezone -- this test is about the
      // "not today" gate, not the local-day boundary the first test covers.
      return Promise.resolve({
        data: date === '2026-08-20'
          ? [{
              game_id: '182618',
              date: '2026-08-20T12:00:00Z',
              state: 'in',
              home: { abbrev: 'V. Williams', name: 'Venus Williams', score: 0 },
              away: { abbrev: 'S. Kenin', name: 'Sofia Kenin', score: 1 },
            }]
          : [],
      })
    })

    // Browsing 08-20 from a vantage point of 09-05 -- "today" is no longer 08-20,
    // so the live-exemption must not apply and the local-day filter decides alone.
    const games = await SportsService.getGamesByLocalDate('wta', '2026-08-19')

    expect(games.map(game => game.gameId)).toEqual([])
    jest.useRealTimers()
  })
})
