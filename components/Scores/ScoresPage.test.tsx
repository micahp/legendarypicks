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
    ;(SportsService.getAllGamesByLocalDate as jest.Mock).mockReset()
    ;(SportsService.getAllGamesByLocalDate as jest.Mock).mockResolvedValue([])
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

// Item 2: the live section is a fact about the present. It renders ABOVE the
// date control, ignores the selected date, and renders nothing at all — no
// header, no empty state — when nothing is live. Three defects this month were
// verified mid-slate and were wrong every morning; the empty case is tested
// here deterministically, not by eyeballing a busy evening.
describe('/scores live-above-the-date', () => {
  const today = new Date().toLocaleDateString('en-CA')

  function liveGame(gameId: string, name: string): Game {
    return {
      gameId,
      league: 'MLB',
      homeTeam: { teamId: 'HOME', name: `Live ${name} Home`, score: 3 },
      awayTeam: { teamId: 'AWAY', name: `Live ${name} Away`, score: 1 },
      startTime: new Date(`${today}T19:00:00`).toISOString(),
      status: 'LIVE',
    }
  }

  beforeEach(() => {
    getGames.mockReset()
    getNeighbour.mockReset()
    getNeighbour.mockResolvedValue(null)
    ;(SportsService.getAllGamesByLocalDate as jest.Mock).mockReset()
    ;(SportsService.getAllGamesByLocalDate as jest.Mock).mockResolvedValue([])
    ;(global as any).fetch = jest.fn(() =>
      Promise.resolve({ json: () => Promise.resolve({ matches: [] }) }),
    )
  })

  it('renders nothing at all in the empty window (no live games, no header)', async () => {
    getGames.mockImplementation((league: string, date: string) => {
      if (league !== 'mlb') return Promise.resolve([])
      return Promise.resolve(date === today ? [game('FIN-1', today), game('FIN-2', today)] : [])
    })

    render(<ScoresPage />)
    await waitFor(() => expect(screen.getByText('FIN-1')).toBeTruthy())

    // No live rail: no featured game, no "more live games", no jump link.
    expect(screen.queryByText(/more live game/)).toBeNull()
    expect(screen.queryByText('Jump to today →')).toBeNull()
    // And no empty-state header either — the rail is simply absent.
    expect(screen.queryByText('Live now')).toBeNull()
  })

  it('shows today live games above the date control even on a past date', async () => {
    const previous = shift(today, -1)
    getNeighbour.mockResolvedValue(previous)
    getGames.mockImplementation((league: string, date: string, options: any) => {
      if (league !== 'mlb') return Promise.resolve([])
      return Promise.resolve(date === today ? [game('TODAY-GAME', today)] : [game('PREVIOUS-GAME', previous)])
    })
    ;(SportsService.getAllGamesByLocalDate as jest.Mock).mockResolvedValue([liveGame('LIVE-1', 'Night')])

    render(<ScoresPage />)
    await waitFor(() => expect(screen.getByText('TODAY-GAME')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: 'Previous day' }))
    await waitFor(() => expect(screen.getByText('PREVIOUS-GAME')).toBeTruthy())

    // The past-date board is showing, and the live rail still says what is
    // live right now, with a quiet way back to today.
    await waitFor(() => expect(screen.getByText('Live Night Away')).toBeTruthy())
    expect(screen.getByText('Jump to today →')).toBeTruthy()
  })

  it('renders nothing when a past date is selected and nothing is live today', async () => {
    const previous = shift(today, -1)
    getNeighbour.mockResolvedValue(previous)
    getGames.mockImplementation((league: string, date: string, options: any) => {
      if (league !== 'mlb') return Promise.resolve([])
      return Promise.resolve(date === today ? [game('TODAY-GAME', today)] : [game('PREVIOUS-GAME', previous)])
    })
    ;(SportsService.getAllGamesByLocalDate as jest.Mock).mockResolvedValue([game('FIN-ONLY', today)])

    render(<ScoresPage />)
    await waitFor(() => expect(screen.getByText('TODAY-GAME')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: 'Previous day' }))
    await waitFor(() => expect(screen.getByText('PREVIOUS-GAME')).toBeTruthy())

    expect(screen.queryByText(/more live game/)).toBeNull()
    expect(screen.queryByText('Jump to today →')).toBeNull()
  })
})
