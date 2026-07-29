/**
 * @jest-environment node
 *
 * The pool row must carry the numbers the payload actually holds.
 *
 * EXPECTED VALUES WRITTEN 2026-07-28, BEFORE THE CODE. `poolToDraftRow` wrote
 * five fields as `null as number | null` with the comment "fields not available
 * from the pool endpoint" -- but /api/nfl/mock-draft/pool ships all five, and on
 * 2026-07-28 the live dev payload carried a non-null `xfp_per_game` for 206 of
 * its 300 players. The nulls were not absence, they were discarded data, and
 * every mock-draft surface rendered "—" for expected fantasy points because of
 * this one boundary.
 *
 * A null here is indistinguishable from "we have no sample", which is the exact
 * confusion the honest-data-ui doctrine exists to prevent: absence has to be a
 * claim about the player, not an artefact of a mapper.
 */

import { poolToDraftRow } from '../api'
import type { PoolPlayer } from '../../../components/Leagues/types'

const FULL: PoolPlayer = {
  player_id: 4430807,
  name: 'Bijan Robinson',
  position: 'RB',
  team: 'ATL',
  adp: 2.4,
  percent_owned: 99.9,
  games_played: 17,
  games_missed: 0,
  team_games: 17,
  weeks_played: [1, 2, 3],
  team_weeks: [1, 2, 3],
  sample: 'full',
  ppr_per_game_played: 21.8,
  ppr_per_team_game: 21.8,
  xfp_per_game: 19.3,
  snap_pct: 78.4,
  target_share: 12.1,
} as PoolPlayer

describe('poolToDraftRow', () => {
  it('passes expected fantasy points through instead of nulling it', () => {
    expect(poolToDraftRow(FULL, 1).xfp_per_game).toBe(19.3)
  })

  it('passes the whole scoring block through', () => {
    const row = poolToDraftRow(FULL, 1)
    expect(row.ppr_per_game_played).toBe(21.8)
    expect(row.ppr_per_team_game).toBe(21.8)
    expect(row.snap_pct).toBe(78.4)
    expect(row.target_share).toBe(12.1)
  })

  it('keeps a genuinely absent value null rather than inventing a zero', () => {
    // A D/ST has no expected-fantasy-points series at all. Null is the honest
    // answer; 0 would be a claim about the defense.
    const dst = { ...FULL, position: 'DEF', xfp_per_game: null, target_share: null } as PoolPlayer
    const row = poolToDraftRow(dst, 1)
    expect(row.xfp_per_game).toBeNull()
    expect(row.target_share).toBeNull()
  })

  it('treats an absent key as null, not undefined, so the renderer has one branch', () => {
    const sparse = {
      player_id: 1,
      name: 'Rookie',
      position: 'WR',
      team: 'ARI',
      adp: 180.0,
      percent_owned: null,
      games_played: 0,
      games_missed: null,
      team_games: 17,
      weeks_played: [],
      team_weeks: [],
      sample: 'none',
    } as unknown as PoolPlayer
    const row = poolToDraftRow(sparse, 1)
    expect(row.xfp_per_game).toBeNull()
    expect(row.ppr_per_game_played).toBeNull()
    expect(row.snap_pct).toBeNull()
  })

  it('still carries rank, identity and ADP unchanged', () => {
    const row = poolToDraftRow(FULL, 7)
    expect(row.rank).toBe(7)
    expect(row.player_id).toBe(4430807)
    expect(row.adp).toBe(2.4)
  })
})
