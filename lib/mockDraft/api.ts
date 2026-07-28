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

export async function createDraft(season: number, seat: number, seed: number): Promise<{ id: string }> {
  const res = await fetch(BASE, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ season, seat, seed }),
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
 * Fields not available from the pool endpoint default to null / sensible values.
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
    ppr_per_game_played: null as number | null,
    ppr_per_team_game: null as number | null,
    xfp_per_game: null as number | null,
    snap_pct: null as number | null,
    target_share: null as number | null,
    sample: player.sample,
  }
}
