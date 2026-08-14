import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import ScoresPage from '../../pages/scores'
import { SportsService, type Game } from '../../services/sports'

jest.mock('next/router', () => ({
  useRouter: () => ({ query: {} }),
}))

jest.mock('../../services/sports', () => ({
  SportsService: {
    getGamesByLocalDate: jest.fn(),
    getAllGamesByLocalDate: jest.fn(),
  },
}))

jest.mock('./GameCard', () => ({ gameId }: { gameId: string }) => (
  <div data-testid="score-game">{gameId}</div>
))
jest.mock('../ListenLive', () => () => null)
jest.mock('../LiveDiscounts', () => () => null)

const getGames = SportsService.getGamesByLocalDate as jest.Mock

function shift(date: string, delta: number) {
  const value = new Date(`${date}T12:00:00`)
  value.setDate(value.getDate() + delta)
  return value.toLocaleDateString('en-CA')
}

function game(gameId: string, date: string): Game {
  return {
    gameId,
    league: 'MLB',
    homeTeam: { teamId: 'HOME', name: 'Home', score: 4 },
    awayTeam: { teamId: 'AWAY', name: 'Away', score: 2 },
    startTime: new Date(`${date}T12:00:00`).toISOString(),
    status: 'FINAL',
  }
}

describe('/scores day navigation', () => {
  beforeEach(() => {
    getGames.mockReset()
    ;(global as any).fetch = jest.fn(() =>
      Promise.resolve({ json: () => Promise.resolve({ matches: [] }) }),
    )
  })

  it('replaces today with the previous day slate after clicking the arrow', async () => {
    const today = new Date().toLocaleDateString('en-CA')
    const previous = shift(today, -1)
    getGames.mockImplementation((league: string, date: string, options: any) => {
      expect(options).toEqual({ strict: true })
      if (league !== 'mlb') return Promise.resolve([])
      return Promise.resolve(date === today ? [game('TODAY-GAME', today)] : [game('PREVIOUS-GAME', previous)])
    })

    render(<ScoresPage />)
    await waitFor(() => expect(screen.getByText('TODAY-GAME')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: 'Previous day' }))

    await waitFor(() => expect(screen.getByText('PREVIOUS-GAME')).toBeTruthy())
    expect(screen.queryByText('TODAY-GAME')).toBeNull()
    expect(getGames.mock.calls.some((call: any[]) => call[1] === previous)).toBe(true)
  })
})
