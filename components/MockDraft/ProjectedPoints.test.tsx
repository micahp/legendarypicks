import { render, screen } from '@testing-library/react'

import type { PoolPlayer } from '../Leagues/types'
import { ProjectedPoints } from './columns'

const player = {
  player_id: 1,
  name: 'Projected Player',
  position: 'RB',
  team: 'DET',
  adp: 1.7,
  percent_owned: 99.9,
  sample: 'full',
  games_played: 17,
  games_missed: 0,
  weeks_played: [],
  team_weeks: [],
  proj_ppr_points: 364.7225,
} as PoolPlayer

describe('ProjectedPoints', () => {
  it('renders the published 2026 PPR total to one decimal', () => {
    render(<ProjectedPoints player={player} />)
    expect(screen.getByText('364.7')).toBeTruthy()
  })

  it('renders missing source coverage as a dash, never zero', () => {
    render(<ProjectedPoints player={{ ...player, proj_ppr_points: null }} />)
    expect(screen.getByText('—')).toBeTruthy()
    expect(screen.queryByText('0.0')).toBeNull()
  })
})
