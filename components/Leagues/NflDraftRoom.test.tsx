import { fireEvent, render, screen } from '@testing-library/react'

import { DraftPlayerRow } from './NflDraftRoom'
import type { NflDraftPlayer } from './types'


const PLAYER: NflDraftPlayer = {
  rank: 1,
  player_id: 469,
  name: 'Josh Allen',
  position: 'QB',
  current_team: 'BUF',
  depth_team: 'BUF',
  team_changed: false,
  depth_rank: 1,
  depth_position: 'QB',
  adp: 22.8,
  espn_ppr_rank: 36,
  proj_ppr_points: 363.6,
  proj_season: 2026,
  proj_source: 'espn',
  bye_week: 7,
  adp_is_ranked: true,
  percent_owned: 99.8,
  injury_status: 'ACTIVE',
  games_played: 17,
  games_missed: 0,
  team_games: 17,
  weeks_played: [1, 2],
  team_weeks: [1, 2],
  ppr_per_game_played: 21.4,
  ppr_per_team_game: 21.4,
  xfp_per_game: 20.4,
  snap_pct: 92,
  target_share: null,
  dst_pts_total: null,
  dst_pts_per_game: null,
  pk_pts_total: null,
  pk_pts_per_game: null,
  sample: 'full',
}

describe('DraftPlayerRow', () => {
  it('opens the overlay from the player name instead of linking to player detail', () => {
    const onClick = jest.fn()
    render(
      <table>
        <tbody>
          <DraftPlayerRow
            player={PLAYER}
            noteRank={undefined}
            watched={false}
            faded={false}
            onSetRank={() => {}}
            onToggleWatch={() => {}}
            onToggleFade={() => {}}
            onClick={onClick}
          />
        </tbody>
      </table>,
    )

    expect(screen.queryByRole('link', { name: 'Josh Allen' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Josh Allen' }))
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
