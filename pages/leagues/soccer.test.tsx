import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import SoccerLeaguePage from './soccer'
import MlsSoccerPage from './mls'
import LeaguesCupSoccerPage from './lcup'
import { SportsService } from '../../services/sports'

const mockRouter = { query: {} as Record<string, string> }
jest.mock('next/router', () => ({ useRouter: () => mockRouter }))

jest.mock('../../services/sports', () => ({
  SportsService: { getGamesByLocalDate: jest.fn() },
}))
jest.mock('../../components/Scores/GameCard', () => function MockGameCard({ gameId }: { gameId: string }) {
  return <div>{gameId}</div>
})
jest.mock('../../components/Leagues/NewsTab', () => function MockNewsTab() {
  return <div>News feed</div>
})
jest.mock('../../components/Leagues/StandingsTab', () => function MockStandingsTab() {
  return <div>MLS tables</div>
})
jest.mock('../../components/Leagues/StatsTab', () => function MockStatsTab() {
  return <div>MLS player and team stats</div>
})
jest.mock('../../components/Leagues/hooks/useNewsData', () => ({
  useNewsData: () => ({ news: null, loading: false, error: null }),
}))
jest.mock('../../components/Leagues/hooks/useStatsData', () => ({
  useStatsData: () => ({}),
}))
const getGames = SportsService.getGamesByLocalDate as jest.Mock

function clickLink(name: string) {
  const link = screen.getByRole('link', { name })
  link.addEventListener('click', event => event.preventDefault(), { once: true })
  fireEvent.click(link)
}

const mlsSnapshot = {
  available: true,
  season: 2026,
  groups: [{ group: 'Eastern Conference', rows: [{ rank: 1, abbrev: 'PHI', name: 'Philadelphia Union', played: 25, wins: 15, draws: 5, losses: 5, gf: 44, ga: 25, gd: 19, points: 50 }] }],
}

const lcupSnapshot = {
  available: true,
  season: 2026,
  fetched_at: '2026-08-25T12:00:00Z',
  rounds: [{
    key: 'quarterfinals', label: 'Quarterfinals',
    matches: [{
      game_id: 'qf1', date: '2026-08-26T00:30Z', state: 'pre', status: 'Scheduled',
      home: { id: '1', name: 'Monterrey' }, away: { id: '2', name: 'Chicago Fire FC' },
    }],
  }],
  leader_categories: [{
    key: 'goals', label: 'Goals',
    leaders: [{ rank: 1, espn_athlete_id: '195681', name: 'Ángel Correa', team: 'Tigres UANL', matches: 4, value: 5 }],
  }],
}

describe('Soccer league hub', () => {
  beforeEach(() => {
    mockRouter.query = {}
    getGames.mockReset()
    getGames.mockResolvedValue([])
    ;(global as any).fetch = jest.fn((url: string) => {
      if (url === '/api/soccer/competitions/mls') {
        return Promise.resolve({ ok: true, json: async () => mlsSnapshot })
      }
      if (url === '/api/soccer/competitions/lcup') {
        return Promise.resolve({ ok: true, json: async () => lcupSnapshot })
      }
      throw new Error(`unexpected fetch ${url}`)
    })
  })

  it('starts as the MLS hub and keeps Leagues Cup under Soccer', async () => {
    await act(async () => { render(<SoccerLeaguePage />) })

    expect(screen.getByRole('heading', { name: 'Soccer' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'MLS' }).getAttribute('aria-current')).toBe('page')
    expect(screen.getByRole('link', { name: 'Leagues Cup' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Standings' }).getAttribute('href')).toBe('/leagues/mls?tab=standings')
    await waitFor(() => expect(getGames).toHaveBeenCalledWith('mls', expect.any(String), { strict: true }))
  })

  it('renders the published Leagues Cup bracket and leaders with sample size', async () => {
    await act(async () => { render(<SoccerLeaguePage />) })
    clickLink('Leagues Cup')

    expect(await screen.findByText('Quarterfinals')).toBeTruthy()
    expect(screen.getByText('Monterrey')).toBeTruthy()
    expect(screen.getByText('Chicago Fire FC')).toBeTruthy()
    expect(screen.getByText('Semifinals')).toBeTruthy()
    expect(screen.getByText('Third Place')).toBeTruthy()
    expect(screen.getByText('Final')).toBeTruthy()
    expect(screen.getByText('Sep 1–2')).toBeTruthy()
    expect(screen.getAllByText('Sep 6')).toHaveLength(2)
    expect(screen.getAllByText('Matchups TBD')).toHaveLength(3)
    expect(screen.queryByText(/Only publisher-named rounds/)).toBeNull()
    expect(screen.getByText(new Date('2026-08-26T00:30Z').toLocaleString(undefined, {
      weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
    }))).toBeTruthy()

    clickLink('Leaders')
    expect(await screen.findByText('Ángel Correa')).toBeTruthy()
    expect(screen.getByText('4 matches')).toBeTruthy()
    expect(screen.getByLabelText('Goals').textContent).toBe('5')
  })

  it('keeps the existing MLS player and team stats surface', async () => {
    await act(async () => { render(<SoccerLeaguePage />) })
    clickLink('Stats')

    expect(await screen.findByText('MLS player and team stats')).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'Leaders' })).toBeNull()
  })

  it('keeps the existing MLS standings URL as the Soccer hub entry', async () => {
    mockRouter.query = { tab: 'standings' }
    await act(async () => { render(<MlsSoccerPage />) })

    expect(screen.getByRole('heading', { name: 'Soccer' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'MLS' }).getAttribute('aria-current')).toBe('page')
    expect(screen.getByText('MLS tables')).toBeTruthy()
  })

  it('honors the standings tab on the canonical Soccer route', async () => {
    mockRouter.query = { tab: 'standings' }
    await act(async () => { render(<SoccerLeaguePage />) })

    expect(screen.getByRole('link', { name: 'Standings' }).getAttribute('aria-current')).toBe('page')
    expect(screen.getByText('MLS tables')).toBeTruthy()
    expect(getGames).not.toHaveBeenCalled()
  })

  it('keeps the Leagues Cup route inside the same Soccer hub', async () => {
    await act(async () => { render(<LeaguesCupSoccerPage />) })

    expect(screen.getByRole('link', { name: 'Leagues Cup' }).getAttribute('aria-current')).toBe('page')
    expect(await screen.findByText('Quarterfinals')).toBeTruthy()
  })
})
