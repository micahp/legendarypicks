import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import TennisLeaguePage from './tennis'
import { SportsService } from '../../services/sports'

jest.mock('../../services/sports', () => ({
  SportsService: { getGamesByLocalDate: jest.fn() },
}))
jest.mock('../../components/Scores/GameCard', () => ({ gameId }: { gameId: string }) => <div>{gameId}</div>)
jest.mock('../../components/Leagues/NewsTab', () => () => <div>News feed</div>)
jest.mock('../../components/Leagues/hooks/useNewsData', () => ({
  useNewsData: () => ({ news: null, loading: false, error: null }),
}))

const getGames = SportsService.getGamesByLocalDate as jest.Mock

describe('Tennis league hub', () => {
  beforeEach(() => {
    getGames.mockReset()
    getGames.mockResolvedValue([])
    ;(global as any).fetch = jest.fn()
  })

  it('defaults to both tours and offers only the measured product tabs', async () => {
    await act(async () => { render(<TennisLeaguePage />) })

    expect(screen.getByText('Major tournament coverage')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Both' }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('button', { name: 'Scores' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Draws' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'News' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Stats' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Game Logs' })).toBeNull()
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
    fireEvent.click(screen.getByRole('button', { name: 'Draws' }))

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
    fireEvent.click(screen.getByRole('button', { name: 'Draws' }))

    expect(await screen.findByText('First Round')).toBeTruthy()
    expect(screen.getByText('Player One')).toBeTruthy()
    expect(screen.getByText('TBD')).toBeTruthy()
    expect(screen.getByRole('link', { name: /Official bracket/ }).getAttribute('href')).toContain('espn.com')
  })
})
