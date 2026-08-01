/** @jest-environment node */

import type { PoolPlayer } from '../Leagues/types'
import type { DraftPlayer } from '../../lib/mockDraft/engine'
import { DEFAULT_SORT, sortOptions, sortPool } from './sort'

const draftPlayers: DraftPlayer[] = [
  { player_id: 1, name: 'One', position: 'RB', team: 'DET', adp: 10 },
  { player_id: 2, name: 'Two', position: 'WR', team: 'MIN', adp: 2 },
  { player_id: 3, name: 'Missing', position: 'TE', team: 'NE', adp: 4 },
]

const pool = new Map<number, PoolPlayer>([
  [1, { player_id: 1, espn_ppr_rank: 1, proj_ppr_points: 300 } as PoolPlayer],
  [2, { player_id: 2, espn_ppr_rank: 2, proj_ppr_points: 340 } as PoolPlayer],
  [3, { player_id: 3, espn_ppr_rank: null, proj_ppr_points: null } as PoolPlayer],
])

const context = { playerMap: pool, byeMap: new Map<string, number | null>() }

describe('2026 draft ordering', () => {
  it('defaults to published rank and puts it first in the control', () => {
    expect(DEFAULT_SORT).toBe('rank')
    expect(sortOptions(2025).map(option => option.label)).toEqual([
      'Rank', 'Proj Pts', 'ADP', 'Availability', 'Bye', '2025 Pts/G', '2025 xFP/G',
    ])
  })

  it('sorts projection descending while keeping missing projections last', () => {
    expect(sortPool(draftPlayers, 'proj', context).map(player => player.player_id)).toEqual([2, 1, 3])
  })

  it('sorts published rank independently of ADP and keeps missing ranks last', () => {
    expect(sortPool(draftPlayers, 'rank', context).map(player => player.player_id)).toEqual([1, 2, 3])
  })
})
