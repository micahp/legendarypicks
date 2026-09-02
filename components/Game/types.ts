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
  period?: number | null
  clock?: string | null
  status_detail?: string | null
}

export type Tab = 'boxscore' | 'playbyplay' | 'props' | 'info' | 'booth'

// ── New per-tab API response types ──

// BoxScore: US team sports (MLB, NFL, NBA, NHL)
export interface BoxStatEntry { label: string; value: string }
export interface BoxTeamTotals { name: string; abbrev: string; stats: BoxStatEntry[] }
export interface BoxPlayerRow { name: string; position: string; stats: string[] }
export interface BoxPlayerGroup { team: string; group: string; columns: string[]; rows: BoxPlayerRow[] }
export interface BoxScoreData {
  available: boolean
  teams?: BoxTeamTotals[]
  players?: BoxPlayerGroup[]
}

// BoxScore: Soccer (WC)
export interface SoccerStatBar { label: string; home: string; away: string }
export interface SoccerLineupPlayer { num: number; name: string; pos: string }
export interface SoccerLineup { side: string; formation: string; players: SoccerLineupPlayer[] }
export interface SoccerBoxScoreData {
  available: boolean
  teamStats?: SoccerStatBar[]
  lineups?: SoccerLineup[]
}

// PlayByPlay: US team sports
export interface PbPPlay {
  clock: string
  text: string
  scoreAway: number
  scoreHome: number
  scoringPlay: boolean
}
export interface PbPPeriod { label: string; plays: PbPPlay[] }
export interface PbPData {
  available: boolean
  periods?: PbPPeriod[]
}

// PlayByPlay: Soccer
export interface SoccerEvent {
  minute: number
  type: 'goal' | 'card' | 'sub' | 'var'
  text: string
  team: string
}
export interface SoccerPbPData {
  available: boolean
  events?: SoccerEvent[]
}

// GameInfo
export interface GameOdds { spread: string; overUnder: string; favorite: string }
export interface GameWeather { temperature: number | null; condition: string; wind: string }
export interface GameInfoData {
  available: boolean
  venue?: string
  city?: string
  attendance?: number
  capacity?: number
  officials?: string[]
  odds?: GameOdds
  broadcasts?: string[]
  weather?: GameWeather
}

// ── helpers ──
export function isNBA(lg: string) { return lg === 'nba' }
export function isNHL(lg: string) { return lg === 'nhl' }
export function isMLB(lg: string) { return lg === 'mlb' }
export function isNFL(lg: string) { return lg === 'nfl' }
export function isWC(lg: string) { return lg === 'wc' }
export function isSoccer(lg: string) { return isWC(lg) || lg === 'lcup' || lg === 'mls' || lg === 'ligamx' }
export function isUSTeamSport(lg: string) { return isNBA(lg) || isNHL(lg) || isMLB(lg) || isNFL(lg) }
export function hasGameTabs(lg: string) { return isNBA(lg) || isNHL(lg) || isMLB(lg) || isNFL(lg) || isSoccer(lg) }
export function usesDetailEndpoint(lg: string) { return isNBA(lg) || isNHL(lg) }
export function usesPerTabEndpoints(lg: string) { return isMLB(lg) || isNFL(lg) || isSoccer(lg) }

export function fmt(v: any, dec?: boolean): string {
  if (v === null || v === undefined) return '-'
  if (typeof v === 'number') return dec ? v.toFixed(v % 1 ? 1 : 0) : String(v)
  return String(v)
}
