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
    getNeighbourGameDate: jest.fn(),
  },
}))

jest.mock('./GameCard', () => ({ gameId }: { gameId: string }) => (
  <div data-testid="score-game">{gameId}</div>
))
jest.mock('../ListenLive', () => () => null)
jest.mock('../LiveDiscounts', () => () => null)

const getGames = SportsService.getGamesByLocalDate as jest.Mock
const getNeighbour = SportsService.getNeighbourGameDate as jest.Mock

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
    getNeighbour.mockReset()
    getNeighbour.mockResolvedValue(null)
    ;(global as any).fetch = jest.fn(() =>
      Promise.resolve({ json: () => Promise.resolve({ matches: [] }) }),
    )
  })

  it('replaces today with the previous day slate after clicking the arrow', async () => {
    const today = new Date().toLocaleDateString('en-CA')
    const previous = shift(today, -1)
    getNeighbour.mockResolvedValue(previous)
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

  // W3 regression gate: the Previous arrow must jump to the neighbouring date
  // that actually has games (schedule-dates contract) — not calendar -1. The
  // gate is what keeps the fix honest: without the schedule-dates wiring the
  // board loads the naive calendar neighbour and this test goes red.
  it('skips empty calendar days: jumps to the schedule-dates neighbour, not calendar -1', async () => {
    const today = new Date().toLocaleDateString('en-CA')
    const gamePrev = shift(today, -3)   // the neighbouring date with games
    const naivePrev = shift(today, -1)  // what calendar arithmetic would pick
    getNeighbour.mockResolvedValue(gamePrev)
    getGames.mockImplementation((league: string, date: string, options: any) => {
      expect(options).toEqual({ strict: true })
      if (league !== 'mlb') return Promise.resolve([])
      return Promise.resolve(date === today ? [game('TODAY-GAME', today)] : [game('GAME-DAY', date)])
    })

    render(<ScoresPage />)
    await waitFor(() => expect(screen.getByText('TODAY-GAME')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: 'Previous day' }))

    await waitFor(() => expect(screen.getByText('GAME-DAY')).toBeTruthy())
    expect(screen.queryByText('TODAY-GAME')).toBeNull()
    expect(getNeighbour).toHaveBeenCalled()
    // The board loaded the real game day, and never the naive calendar -1.
    expect(getGames.mock.calls.some((call: any[]) => call[1] === gamePrev)).toBe(true)
    expect(getGames.mock.calls.some((call: any[]) => call[1] === naivePrev)).toBe(false)
  })

  // W3 honesty gate: with no neighbour (null) the arrow is an honest no-op —
  // the board stays on the anchor and no calendar date is fabricated.
  it('does not fabricate a calendar date when schedule discovery finds no neighbour', async () => {
    const today = new Date().toLocaleDateString('en-CA')
    getNeighbour.mockResolvedValue(null)
    getGames.mockImplementation((league: string, date: string, options: any) => {
      expect(options).toEqual({ strict: true })
      if (league !== 'mlb') return Promise.resolve([])
      return Promise.resolve(date === today ? [game('TODAY-GAME', today)] : [game('FABRICATED-DAY', date)])
    })

    render(<ScoresPage />)
    await waitFor(() => expect(screen.getByText('TODAY-GAME')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: 'Previous day' }))

    // The anchor board stays; no day change is requested.
    await waitFor(() => expect(getNeighbour).toHaveBeenCalled())
    expect(screen.getByText('TODAY-GAME')).toBeTruthy()
    expect(screen.queryByText('FABRICATED-DAY')).toBeNull()
    expect(getGames.mock.calls.every((call: any[]) => call[1] === today)).toBe(true)
  })
})
