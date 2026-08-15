import React from 'react'
import axios from 'axios'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import ScoresPage from '../../pages/scores'

jest.mock('next/router', () => ({
  useRouter: () => ({ query: {} }),
}))

jest.mock('axios', () => ({
  __esModule: true,
  default: { get: jest.fn() },
}))

jest.mock('./GameCard', () => ({ gameId }: { gameId: string }) => (
  <div data-testid="score-game">{gameId}</div>
))
jest.mock('../ListenLive', () => () => null)
jest.mock('../LiveDiscounts', () => () => null)

const get = axios.get as jest.Mock

function shift(date: string, delta: number) {
  const value = new Date(`${date}T12:00:00`)
  value.setDate(value.getDate() + delta)
  return value.toLocaleDateString('en-CA')
}

describe('/scores partial date-window outage', () => {
  let consoleError: jest.SpyInstance

  beforeEach(() => {
    consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined)
    const today = new Date().toLocaleDateString('en-CA')
    const previous = shift(today, -1)
    get.mockImplementation((url: string, config: any) => {
      // W3 navigation resolves the neighbour via schedule-dates before loading
      // games; answer it so the arrow lands on `previous`, then the games
      // window for that day rejects below (the outage under test).
      if (url.includes('/schedule-dates')) {
        return Promise.resolve({
          data: {
            contract: 'league-schedule-dates-v1',
            league: 'mlb',
            anchor_date: today,
            event_start_timezone: 'UTC',
            available: true,
            source: 'espn',
            future_event_starts: [],
            past_event_starts: [new Date(`${previous}T12:00:00`).toISOString()],
            search: { future: [], past: [], max_horizon_days: 370 },
          },
        })
      }
      const league = url.match(/\/([^/]+)\/games$/)?.[1]
      const date = config?.params?.date
      if (date === previous) return Promise.reject(new Error('publisher refused'))
      return Promise.resolve({
        data: league === 'mlb' && date === today
          ? [{
              game_id: 'TODAY-GAME',
              date: new Date(`${today}T12:00:00`).toISOString(),
              state: 'post',
              completed: true,
              status: 'Final',
              home: { abbrev: 'HOME', score: 4 },
              away: { abbrev: 'AWAY', score: 2 },
            }]
          : [],
      })
    })
    ;(global as any).fetch = jest.fn(() =>
      Promise.resolve({ json: () => Promise.resolve({ matches: [] }) }),
    )
  })

  afterEach(() => consoleError.mockRestore())

  it('clears today and reports the failed previous-day window', async () => {
    render(<ScoresPage />)
    await waitFor(() => expect(screen.getByText('TODAY-GAME')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: 'Previous day' }))

    await waitFor(() => expect(
      screen.getByText('Unable to load games right now. Try another date.'),
    ).toBeTruthy())
    expect(screen.queryByText('TODAY-GAME')).toBeNull()
  })
})
