// Shared types + helpers for the game detail page (components/Game/*).

export interface TeamStat {
  team_abbrev: string; home_away: string
  fgm_fga?: string; fg_pct?: number; tpm_tpa?: string; tp_pct?: number
  ftm_fta?: string; ft_pct?: number
  rebounds?: number; off_rebounds?: number; def_rebounds?: number
  assists?: number; steals?: number; blocks?: number
  turnovers?: number; fouls?: number
  fast_break_pts?: number; pts_in_paint?: number; largest_lead?: number
  shots?: number; blocked_shots?: number; hits?: number
  takeaways?: number; giveaways?: number; faceoffs_won?: number; faceoff_pct?: number
  powerplay_goals?: number; powerplay_opps?: number
  penalties?: number; penalty_min?: number
}
export interface ScoringPlay {
  period: number; period_disp: string; clock: string
  away_score: number; home_score: number
  team_abbrev: string; play_text: string; play_type: string
}
export interface GameContext {
  venue_name: string; venue_city: string; attendance: number
  officials: string[]; home_team: string; away_team: string
}
export interface StrengthRow {
  abbrev: string; name: string; wins: number; losses: number
  win_pct: number; differential: string; streak: string
}
export interface GameDetail {
  game_id: string; league: string
  team_stats: TeamStat[]
  scoring_plays: ScoringPlay[]
  context: GameContext | null
  strength: Record<string, StrengthRow>
  final_score: { home: number; away: number } | null
  live_score?: { home: number; away: number } | null
  state?: string | null
}

export type Tab = 'boxscore' | 'playbyplay' | 'info'

// ── helpers ──
export function isNBA(lg: string) { return lg === 'nba' }
export function isNHL(lg: string) { return lg === 'nhl' }
export function fmt(v: any, dec?: boolean): string {
  if (v === null || v === undefined) return '-'
  if (typeof v === 'number') return dec ? v.toFixed(v % 1 ? 1 : 0) : String(v)
  return String(v)
}
