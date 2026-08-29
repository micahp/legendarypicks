import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import TennisLeaguePage from './tennis'
import { SportsService } from '../../services/sports'

const mockRouter = { query: {} as Record<string, string>, push: jest.fn() }
jest.mock('next/router', () => ({ useRouter: () => mockRouter }))

jest.mock('../../services/sports', () => ({
  SportsService: { getGamesByLocalDate: jest.fn() },
}))
jest.mock('../../components/Scores/GameCard', () => function MockGameCard({ gameId }: { gameId: string }) { return <div>{gameId}</div> })
jest.mock('../../components/Leagues/NewsTab', () => function MockNewsTab() { return <div>News feed</div> })
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
    mockRouter.push.mockReset()
    getGames.mockReset()
    getGames.mockResolvedValue([])
    ;(global as any).fetch = jest.fn()
  })

  it('defaults to all tours and offers only the measured product tabs', async () => {
    await act(async () => { render(<TennisLeaguePage />) })

    expect(screen.queryByText('Major tournament coverage')).toBeNull()
    expect(screen.queryByText(/ATP and WTA scores/)).toBeNull()
    const tour = screen.getByRole('combobox', { name: 'Tour' }) as HTMLSelectElement
    expect(tour.value).toBe('all')
    expect(screen.getByRole('option', { name: 'All' })).toBeTruthy()
    expect(screen.getByRole('option', { name: 'ATP' })).toBeTruthy()
    expect(screen.getByRole('option', { name: 'WTA' })).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'Both' })).toBeNull()
    expect(screen.getByRole('link', { name: 'Scores' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Draws' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Rankings' }).getAttribute('href')).toBe('/leagues/tennis?tab=rankings&tour=all')
    expect(screen.getByRole('link', { name: 'News' })).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'Stats' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Game Logs' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Previous day' }).className).toContain('h-10 w-10')
    expect(screen.getByRole('button', { name: 'Next day' }).className).toContain('h-10 w-10')
    expect(screen.queryByRole('button', { name: 'Jump to today' })).toBeNull()
    await waitFor(() => expect(getGames).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('No covered ATP or WTA matches were published for this date.')).toBeTruthy()
    expect(getGames.mock.calls.map(call => call[0]).sort()).toEqual(['atp', 'wta'])
    await act(async () => { fireEvent.change(tour, { target: { value: 'atp' } }) })
    await waitFor(() => expect(getGames).toHaveBeenCalledTimes(3))
    expect(mockRouter.push).toHaveBeenCalledWith(
      { pathname: '/leagues/tennis', query: { tab: 'scores', tour: 'atp' } },
      undefined,
      { shallow: true },
    )
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
          matches: [{ game_id: 'm1', round: 'First Round', status: 'Scheduled', home: { athlete_id: '1001', name: 'Player One', seed: 12 }, away: { athlete_id: '1002', name: 'Player Two' } }],
        }],
      }),
    })
    await act(async () => { render(<TennisLeaguePage />) })
    await screen.findByText('No covered ATP or WTA matches were published for this date.')
    clickLink('Draws')

    expect(await screen.findByText('First Round')).toBeTruthy()
    expect(screen.getByText('(12) Player One')).toBeTruthy()
    expect(screen.getByText('Player Two')).toBeTruthy()
    expect(screen.queryByText('(undefined) Player Two')).toBeNull()
    expect(screen.queryByText(/Snapshot 8\/24\/2026/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Previous draw rounds' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Next draw rounds' })).toBeTruthy()
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
