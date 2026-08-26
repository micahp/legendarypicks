import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import TennisLeaguePage from './tennis'
import { SportsService } from '../../services/sports'

const mockRouter = { query: {} as Record<string, string> }
jest.mock('next/router', () => ({ useRouter: () => mockRouter }))

jest.mock('../../services/sports', () => ({
  SportsService: { getGamesByLocalDate: jest.fn() },
}))
jest.mock('../../components/Scores/GameCard', () => ({ gameId }: { gameId: string }) => <div>{gameId}</div>)
jest.mock('../../components/Leagues/NewsTab', () => () => <div>News feed</div>)
jest.mock('../../components/Leagues/hooks/useNewsData', () => ({
  useNewsData: () => ({ news: null, loading: false, error: null }),
}))

const getGames = SportsService.getGamesByLocalDate as jest.Mock

function clickLink(name: string) {
  const link = screen.getByRole('link', { name })
  link.addEventListener('click', event => event.preventDefault(), { once: true })
  fireEvent.click(link)
}

describe('Tennis league hub', () => {
  beforeEach(() => {
    mockRouter.query = {}
    getGames.mockReset()
    getGames.mockResolvedValue([])
    ;(global as any).fetch = jest.fn()
  })

  it('defaults to both tours and offers only the measured product tabs', async () => {
    await act(async () => { render(<TennisLeaguePage />) })

    expect(screen.getByText('Major tournament coverage')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Both' }).getAttribute('aria-current')).toBe('page')
    expect(screen.getByRole('link', { name: 'Scores' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Draws' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Rankings' }).getAttribute('href')).toBe('/leagues/tennis?tab=rankings&tour=all')
    expect(screen.getByRole('link', { name: 'News' })).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'Stats' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Game Logs' })).toBeNull()
    await waitFor(() => expect(getGames).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('No covered ATP or WTA matches were published for this date.')).toBeTruthy()
    expect(getGames.mock.calls.map(call => call[0]).sort()).toEqual(['atp', 'wta'])
  })

  it('shows the persisted unavailable reason instead of an empty bracket', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ available: false, tours: [], reason: 'No verified major draw has been published yet.' }),
    })
    await act(async () => { render(<TennisLeaguePage />) })
    await screen.findByText('No covered ATP or WTA matches were published for this date.')
    clickLink('Draws')

    expect(await screen.findByText('No verified major draw has been published yet.')).toBeTruthy()
  })

  it('renders published rounds, future TBD slots, and the official bracket link', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        available: true,
        tours: [{
          league: 'atp', event_name: 'US Open', draw_type: "Men's Singles",
          bracket_url: 'https://www.espn.com/tennis/bracket/test', fetched_at: '2026-08-24T12:00:00Z',
          matches: [{ game_id: 'm1', round: 'First Round', status: 'Scheduled', home: { name: 'Player One' } }],
        }],
      }),
    })
    await act(async () => { render(<TennisLeaguePage />) })
    await screen.findByText('No covered ATP or WTA matches were published for this date.')
    clickLink('Draws')

    expect(await screen.findByText('First Round')).toBeTruthy()
    expect(screen.getByText('Player One')).toBeTruthy()
    expect(screen.getByText('TBD')).toBeTruthy()
    expect(screen.getByRole('link', { name: /Official bracket/ }).getAttribute('href')).toContain('espn.com')
  })

  it('renders id-keyed world rankings separately from tournament seeds', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        available: true,
        tours: [{
          tour: 'atp', captured_at: '2026-08-25T12:00:00Z',
          rankings: [{
            espn_athlete_id: '3623', player_id: 7, player_name: 'Jannik Sinner',
            rank: 1, previous_rank: 2, points: 12800,
          }],
        }],
      }),
    })
    await act(async () => { render(<TennisLeaguePage />) })
    await screen.findByText('No covered ATP or WTA matches were published for this date.')
    clickLink('Rankings')

    expect(await screen.findByText('Jannik Sinner')).toBeTruthy()
    expect(screen.getByText('12,800 pts')).toBeTruthy()
    expect(screen.getByText(/tournament seeds are separate/i)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Jannik Sinner' }).getAttribute('href')).toContain('/player/7')
  })
})
