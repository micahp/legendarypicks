import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import ScoresPage from '../../pages/scores'
import { SportsService, type Game } from '../../services/sports'

jest.mock('next/router', () => ({
  useRouter: () => mockRouter,
}))

const mockRouter = {
  query: {} as Record<string, string>,
  push: jest.fn(),
}

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
jest.mock('../LiveDot', () => () => null)

const getGames = SportsService.getGamesByLocalDate as jest.Mock
const getNeighbour = SportsService.getNeighbourGameDate as jest.Mock

function game(gameId: string, league: string, date: string): Game {
  return {
    gameId,
    league,
    homeTeam: { teamId: 'HOME', name: 'Home', score: 4 },
    awayTeam: { teamId: 'AWAY', name: 'Away', score: 2 },
    startTime: new Date(`${date}T12:00:00`).toISOString(),
    status: 'FINAL',
  }
}

// The league <select> became sport pills; the old URL contract has to keep
// working across the swap. Each test pins one side of that contract.
describe('/scores sport filter', () => {
  const today = new Date().toLocaleDateString('en-CA')

  beforeEach(() => {
    mockRouter.query = {}
    mockRouter.push.mockReset()
    getGames.mockReset()
    getNeighbour.mockReset()
    getNeighbour.mockResolvedValue(null)
    ;(global as any).fetch = jest.fn(() =>
      Promise.resolve({ json: () => Promise.resolve({ matches: [] }) }),
    )
  })

  it('fetches every league a sport covers when the sport pill is selected', async () => {
    getGames.mockImplementation((league: string, date: string) =>
      Promise.resolve(league === 'nfl' ? [game('NFL-GAME', 'NFL', date)] : []),
    )

    render(<ScoresPage />)
    // All on first paint fans out over every league.
    await waitFor(() => expect(getGames.mock.calls.some((c) => c[0] === 'cod')).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: 'Football' }))
    await waitFor(() => expect(getGames.mock.calls.some((c) => c[0] === 'nfl' && c[1] === today)).toBe(true))
    await waitFor(() => expect(getGames.mock.calls.some((c) => c[0] === 'ncaaf' && c[1] === today)).toBe(true))
    await waitFor(() => expect(screen.getByText('NFL-GAME')).toBeTruthy())

    // The URL carries the sport name, shallow, with the default left out.
    expect(mockRouter.push).toHaveBeenCalledWith(
      { pathname: '/scores', query: { league: 'Football' } },
      undefined,
      { shallow: true },
    )
  })

  it('shows both leagues of a sport as their own sections', async () => {
    getGames.mockImplementation((league: string, date: string) => {
      if (league === 'nfl') return Promise.resolve([game('NFL-GAME', 'NFL', date)])
      if (league === 'ncaaf') return Promise.resolve([game('NCAAF-GAME', 'NCAAF', date)])
      return Promise.resolve([])
    })

    render(<ScoresPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Football' }))
    await waitFor(() => expect(screen.getByText('NFL-GAME')).toBeTruthy())
    await waitFor(() => expect(screen.getByText('NCAAF-GAME')).toBeTruthy())
    expect(screen.getByText('NFL')).toBeTruthy()
    expect(screen.getByText('NCAAF')).toBeTruthy()
  })

  it('a legacy ?league= value selects the sport it used to filter', async () => {
    mockRouter.query = { league: 'ATP' }
    getGames.mockResolvedValue([])

    render(<ScoresPage />)
    const tennis = await screen.findByRole('button', { name: 'Tennis' })
    expect(tennis.getAttribute('aria-pressed')).toBe('true')
    // And it fetched the sport's mapped leagues, not just the one named.
    await waitFor(() => expect(getGames.mock.calls.some((c) => c[0] === 'atp')).toBe(true))
    await waitFor(() => expect(getGames.mock.calls.some((c) => c[0] === 'wta')).toBe(true))
    // Only the sport's leagues are fetched — no NBA call ever went out.
    expect(getGames.mock.calls.some((c) => c[0] === 'nba')).toBe(false)
  })

  it('a legacy soccer value selects Soccer and fetches all six soccer leagues', async () => {
    mockRouter.query = { league: 'International Friendlies' }
    getGames.mockResolvedValue([])

    render(<ScoresPage />)
    const soccer = await screen.findByRole('button', { name: 'Soccer' })
    expect(soccer.getAttribute('aria-pressed')).toBe('true')
    await waitFor(() => {
      const leagues = new Set(getGames.mock.calls.map((c: any[]) => c[0]))
      for (const key of ['unl', 'friendlies', 'lcup', 'mls', 'ligamx', 'wc']) {
        expect(leagues.has(key)).toBe(true)
      }
      expect(leagues.has('nba')).toBe(false)
    })
  })

  it('an unknown ?league= value changes nothing (stays on All)', async () => {
    mockRouter.query = { league: 'not-a-league' }
    getGames.mockResolvedValue([])

    render(<ScoresPage />)
    const all = await screen.findByRole('button', { name: 'All' })
    expect(all.getAttribute('aria-pressed')).toBe('true')
  })

  it('the empty state names the selected sport and View All resets it', async () => {
    mockRouter.query = { league: 'MLB' }
    getGames.mockResolvedValue([])

    render(<ScoresPage />)
    expect(await screen.findByText('No games scheduled for this date in Baseball.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'View All Leagues' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'All' }).getAttribute('aria-pressed')).toBe('true'))
    expect(mockRouter.push).toHaveBeenCalledWith(
      { pathname: '/scores', query: {} },
      undefined,
      { shallow: true },
    )
  })

  it('?live=1 still filters the board to live games with the pills present', async () => {
    mockRouter.query = { live: '1' }
    getGames.mockImplementation((league: string, date: string) => {
      if (league !== 'mlb') return Promise.resolve([])
      return Promise.resolve([
        { ...game('LIVE-GAME', 'MLB', date), status: 'LIVE' as const },
        game('FINAL-GAME', 'MLB', date),
      ])
    })

    render(<ScoresPage />)
    await waitFor(() => expect(screen.getByText('LIVE-GAME')).toBeTruthy())
    expect(screen.queryByText('FINAL-GAME')).toBeNull()
    expect(screen.getByRole('button', { name: 'All' }).getAttribute('aria-pressed')).toBe('true')
  })
})
