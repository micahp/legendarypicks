import { render, screen } from '@testing-library/react'
import PlayerPage from '../pages/player/[id]'

const mockRouter = {
  query: { id: '59339' },
  pathname: '/player/[id]',
  replace: jest.fn(),
}
jest.mock('next/router', () => ({ useRouter: () => mockRouter }))
jest.mock('../lib/analytics', () => ({
  trackPlayerViewed: jest.fn(),
  trackUsageTrendViewed: jest.fn(),
}))

describe('tennis player profile', () => {
  it('renders the stored world ranking reached from search', async () => {
    ;(global as any).fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        id: 59339,
        name: 'Jannik Sinner',
        team: null,
        league: 'atp',
        selected_league: 'atp',
        position: null,
        position_group: null,
        season: null,
        log_contexts: [],
        injury_status: null,
        last_news_date: null,
        regular_season_games: 0,
        postseason_games: 0,
        preseason_games: 0,
        recent_games: [],
        postseason_recent_games: [],
        preseason_recent_games: [],
        nfl_schedule_games: [],
        projections: {},
        stat_ranks: {},
        stat_rank_season: null,
        stat_rank_games: null,
        props: [],
        season_stats: null,
        tennis_ranking: {
          tour: 'atp', rank: 1, previous_rank: 1, points: 12800,
          captured_at: '2026-08-30T14:20:15+00:00', source: 'espn_world_rankings',
        },
        coverage: { game_logs: false, props: false, season_stats: false, rankings: true },
        data_status: 'ready',
      }),
    })

    render(<PlayerPage />)

    expect(await screen.findByRole('heading', { name: 'Jannik Sinner' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'World Ranking' })).toBeTruthy()
    expect(screen.getByText('#1')).toBeTruthy()
    expect(screen.getByText(/12,800 points · ESPN world rankings/)).toBeTruthy()
    expect(screen.queryByText(/No stats, game logs, props, or ranking/)).toBeNull()
  })
})
