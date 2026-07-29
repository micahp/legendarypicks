import type { PoolPlayer, PoolResponse, MockDraft, MockDraftPick } from '../../components/Leagues/types'
import { getDeviceId } from '../deviceId'
import { poolTeamGames } from './availability'

const BASE = '/api/nfl/mock-draft'

function headers(): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    'X-Device-Id': getDeviceId(),
  }
}

export async function fetchPool(season: number = 2026): Promise<PoolResponse> {
  const res = await fetch(`${BASE}/pool?season=${season}`)
  if (!res.ok) throw new Error(`pool fetch failed: ${res.status}`)
  return res.json()
}

export async function createDraft(
  season: number,
  seat: number,
  seed: number,
  teams: number = 12,
): Promise<{ id: string }> {
  const res = await fetch(BASE, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ season, seat, seed, teams }),
  })
  if (!res.ok) throw new Error(`create draft failed: ${res.status}`)
  return res.json()
}

export async function appendPicks(draftId: string, picks: Array<{ pick_no: number; team_no: number; player_id: number; auto?: boolean }>): Promise<{ inserted: number }> {
  const res = await fetch(`${BASE}/${draftId}/picks`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ picks }),
  })
  if (!res.ok) throw new Error(`append picks failed: ${res.status}`)
  return res.json()
}

export async function completeDraft(draftId: string): Promise<{
  status: string
  pick_count: number
  picks_expected: number
  missing_picks: number[]
}> {
  const res = await fetch(`${BASE}/${draftId}/complete`, {
    method: 'POST',
    headers: headers(),
  })
  if (!res.ok) throw new Error(`complete draft failed: ${res.status}`)
  return res.json()
}

export async function fetchDraft(draftId: string): Promise<MockDraft> {
  const res = await fetch(`${BASE}/${draftId}`, { headers: headers() })
  if (!res.ok) throw new Error(`fetch draft failed: ${res.status}`)
  return res.json()
}

export async function listDrafts(): Promise<{ drafts: MockDraft[] }> {
  const res = await fetch(`${BASE}s`, { headers: headers() })
  if (!res.ok) throw new Error(`list drafts failed: ${res.status}`)
  return res.json()
}

/**
 * Map a pool player to a shape DraftPlayerRow can render.
 *
 * These five scoring fields used to be written as a literal `null` under the
 * comment "not available from the pool endpoint". They were available: the pool
 * contract ships all five, and on 2026-07-28 the live payload carried a non-null
 * xfp_per_game for 206 of its 300 players. Nulling them here is what emptied the
 * expected-fantasy-points column on every mock-draft surface, and a null is
 * read by the renderer as "no sample" — a claim about the player, made on the
 * player's behalf, that was actually a claim about this mapper.
 *
 * `?? null` rather than a bare read: the fields are optional on PoolPlayer, and
 * `undefined` and `null` must not be two branches for one meaning.
 */
export function poolToDraftRow(player: PoolPlayer, rank: number) {
  return {
    rank,
    player_id: player.player_id,
    name: player.name,
    position: player.position,
    current_team: player.team,
    depth_team: null as string | null,
    team_changed: null as boolean | null,
    depth_rank: null as number | null,
    adp: player.adp,
    adp_is_ranked: true,
    percent_owned: player.percent_owned,
    games_played: player.games_played,
    games_missed: player.games_missed,
    team_games: poolTeamGames(player),
    weeks_played: player.weeks_played,
    team_weeks: player.team_weeks,
    ppr_per_game_played: player.ppr_per_game_played ?? null,
    ppr_per_team_game: player.ppr_per_team_game ?? null,
    xfp_per_game: player.xfp_per_game ?? null,
    snap_pct: player.snap_pct ?? null,
    target_share: player.target_share ?? null,
    sample: player.sample,
  }
}
