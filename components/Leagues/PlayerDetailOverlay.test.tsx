import { fireEvent, render, screen } from '@testing-library/react'

import PlayerDetailOverlay from './PlayerDetailOverlay'
import type { PlayerDetailResponse } from './types'


const STAT_LINE = {
  games: 17,
  pass_att: null,
  pass_cmp: null,
  pass_yds: null,
  pass_td: null,
  interceptions: null,
  completion_pct: null,
  sacks: null,
  rush_att: 16.9,
  rush_yds: 105.7,
  rush_td: 1.2,
  receptions: 123.0,
  targets: 174.3,
  rec_yds: 1589.9,
  rec_td: 9.8,
  fumbles: 2,
  fumbles_lost: 1,
  passing_first_downs: null,
  rushing_first_downs: null,
  receiving_first_downs: null,
  qbr: null,
  passer_rating: null,
  adj_qbr: null,
  fg_att: null,
  fg_made: null,
  xp_att: null,
  xp_made: null,
  def_td: null,
  def_int: null,
  def_sack: null,
  def_fumble_rec: null,
  def_points_allowed: null,
  def_yds_allowed: null,
}

const PLAYER: PlayerDetailResponse = {
  player_id: 16247,
  name: 'Puka Nacua',
  team: 'LAR',
  position: 'WR',
  active: true,
  adp: 3.1,
  percent_owned: 99.8,
  proj_2026_pts: 356.2,
  projection_2026: STAT_LINE,
  projection_source: 'espn',
  season_outlook: 'A published ESPN outlook for the upcoming season.',
  season_outlook_source: 'espn',
  season_totals: {
    ...STAT_LINE,
    season: 2025,
    games: 16,
    receptions: 129,
    targets: 166,
    rec_yds: 1715,
    rec_td: 10,
    receiving_first_downs: 80,
    ppr_points: 339.0,
  },
  season_totals_source: 'espn',
  sample: 'none',
  has_prior_nfl_sample: true,
  games_played: null,
  games_missed: null,
  team_games: null,
  weeks_played: [],
  team_weeks: [],
  ppr_per_game_played: null,
  ppr_per_team_game: null,
  snap_pct: null,
  target_share: null,
  xfp_per_game: null,
  dst_pts_total: null,
  dst_pts_per_game: null,
  pk_pts_total: null,
  pk_pts_per_game: null,
  qb: null,
  injury_status: null,
  last_news_date: null,
}

function response(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response
}

describe('PlayerDetailOverlay tabs', () => {
  beforeEach(() => {
    ;(global as typeof globalThis & { fetch: jest.Mock }).fetch = jest
      .fn()
      .mockResolvedValue(response(PLAYER))
  })

  afterEach(() => {
    jest.restoreAllMocks()
    delete (global as Partial<typeof globalThis>).fetch
  })

  it('keeps prior season totals on Overview and moves the forecast to Projections', async () => {
    render(<PlayerDetailOverlay playerId={PLAYER.player_id} onClose={() => {}} />)

    expect(await screen.findByText('Season Stats')).toBeTruthy()
    expect(screen.getByText('2025')).toBeTruthy()
    expect(screen.getByText('1715')).toBeTruthy()
    expect(screen.queryByText('2026 Projection')).toBeNull()

    fireEvent.click(screen.getByRole('tab', { name: 'Projections' }))

    expect(screen.getByText('Season Outlook')).toBeTruthy()
    expect(screen.getByText(PLAYER.season_outlook as string)).toBeTruthy()
    expect(screen.getByText('Source: ESPN')).toBeTruthy()
    expect(screen.getByText('2026 Projection')).toBeTruthy()
    expect(screen.getByText('PROJ 2026')).toBeTruthy()
    expect(screen.getByText('PPR 356.2')).toBeTruthy()
    expect(screen.queryByText('Season Stats')).toBeNull()
  })

  it('labels quarterback rates, sacks, first downs, and fumbles without calling passer rating QBR', async () => {
    const quarterback: PlayerDetailResponse = {
      ...PLAYER,
      player_id: 3918298,
      name: 'Josh Allen',
      position: 'QB',
      season_totals: {
        ...PLAYER.season_totals!,
        pass_cmp: 319,
        pass_att: 460,
        completion_pct: 69.3,
        pass_yds: 3668,
        pass_td: 25,
        interceptions: 10,
        sacks: 40,
        passing_first_downs: 177,
        qbr: 65.1,
        passer_rating: 102.2,
        adj_qbr: 65.4,
        fumbles: 7,
        fumbles_lost: 3,
      },
    }
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(response(quarterback))

    render(<PlayerDetailOverlay playerId={quarterback.player_id} onClose={() => {}} />)

    expect(await screen.findByText('CMP%')).toBeTruthy()
    expect(screen.getByText('SACK')).toBeTruthy()
    expect(screen.getByText('PASS 1D')).toBeTruthy()
    expect(screen.getByText('QBR')).toBeTruthy()
    expect(screen.getByText('RTG')).toBeTruthy()
    expect(screen.getByText('FUM')).toBeTruthy()
    expect(screen.getByText('LST')).toBeTruthy()
    expect(screen.getByText('65.1')).toBeTruthy()
    expect(screen.getByText(/Total QBR is not passer rating/)).toBeTruthy()
  })
})
