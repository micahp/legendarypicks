export interface TeamStats {
  abbrev: string
  name: string
  wins: number
  losses: number
  win_pct: number
  differential: number
  streak: string
  last10: string
  games_played: number
}

export interface StandingRow {
  rank: number
  abbrev: string
  name: string
  played: number
  wins: number
  draws: number
  losses: number
  gf: number
  ga: number
  gd: number
  points: number
}

export interface StandingGroup {
  group: string
  rows: StandingRow[]
}

export interface Leader {
  player_id: number
  name: string
  team: string
  games: number
  [stat: string]: number | string | null
}

export type MetricFormat = 'integer' | 'decimal_1' | 'decimal_3' | 'percent_1' | 'time'

export interface StatMetric {
  key: string
  label: string
  format: MetricFormat
}

export interface StatCategory {
  key: string
  label: string
  stats: StatMetric[]
}

export interface ChangeComparison {
  recent_label: string
  baseline_label: string
  recent_games: number
  min_baseline_games: number
  status: 'display_only'
  eligible_leaders: number
  qualified_leaders: number
}

export interface StatChange {
  player_id: number
  name: string
  team: string
  metric: StatMetric
  recent_value: number | string | null
  baseline_value: number | string | null
  delta: number
  direction: 'rising' | 'falling' | 'flat'
  recent_games: number
  baseline_games: number
}

export interface LeadersData {
  league: string
  season: number | string | null
  available_seasons: (number | string)[]
  stat: string | null
  stat_type: string | null
  category: string | null
  categories: StatCategory[]
  columns: StatMetric[]
  leaders: Leader[]
  change_metric: StatMetric | null
  comparison: ChangeComparison | null
  changes: StatChange[]
}

export interface TeamColumn {
  key: string
  label: string
  format: string
}

export interface TeamStatCategory {
  key: string
  label: string
  columns: TeamColumn[]
}

export interface TeamAggregate {
  team: string
  games: number
  wins: number
  losses: number
  [key: string]: number | string
}

export interface TeamAggregateCoverage {
  status: 'measured' | 'incomplete' | 'unavailable'
  scope: 'captured_completed_games'
  team_count: number
  expected_teams: number
  games: number
  paired_games: number
  invalid_games: number
  first_game_date: string | null
  last_game_date: string | null
  external_schedule_reconciled: boolean
}

export interface TeamAggregatesData {
  league: string
  season: number | null
  supported: boolean
  reason: string | null
  coverage: TeamAggregateCoverage
  categories: TeamStatCategory[]
  columns: TeamColumn[]
  teams: TeamAggregate[]
}

export interface UFCRanked {
  rank: number
  fighter: string
  champion?: boolean
}

export interface UFCDivision {
  division: string
  champion: string
  ranked: UFCRanked[]
}

export interface UFCRankings {
  pound_for_pound: { men: UFCRanked[]; women: UFCRanked[] }
  divisions: UFCDivision[]
}

export interface KnockoutTeam {
  abbrev: string
  name: string
}

export interface KnockoutMatch {
  home: KnockoutTeam
  away: KnockoutTeam
  homeScore: number | null
  awayScore: number | null
  winner: string | null
  status: string
  state: string
}

export interface KnockoutRound {
  round: string
  matches: KnockoutMatch[]
}

export type SubView = 'players' | 'teams'
export type HubTab = 'camp' | 'standings' | 'stats' | 'schedule' | 'rankings' | 'predict'

// ── NFL camp-mode contracts ──────────────────────────────────────────────

export interface NflNextEvent {
  id: string
  label: string
  date: string
  days_until: number
}

export interface NflMilestone {
  id: string
  label: string
  date: string
  kind: string
  status: 'past' | 'today' | 'upcoming'
  days_until: number | null
}

export interface NflSeasonContext {
  contract: string
  league: string
  as_of: string
  calendar_status: string
  calendar_valid_through: string
  phase: string
  phase_label: string
  current_season: number
  reference_season: number
  next_event: NflNextEvent | null
  milestones: NflMilestone[]
  coverage: Record<string, any>
  sources: { name: string; url: string; verified_at: string }[]
}

export interface NflTransaction {
  date: string
  team: string | null
  teamName: string | null
  description: string
  players?: string[]
}

export interface NflDraftPlayer {
  rank: number
  player_id: number
  name: string
  position: string
  current_team: string
  reference_team: string
  team_changed: boolean | null
  games: number
  fantasy_ppr_g: number
  fantasy_pts_g: number
  pass_yds_g: number | null
  rush_yds_g: number | null
  rec_yds_g: number | null
  targets: number | null
  receptions: number | null
  carries_g: number | null
  adp: number | null
  percent_owned: number | null
  season_proj_pts: number | null
  games_assumed: number | null
}

export interface NflDraftBoard {
  contract: string
  league: string
  current_season: number
  reference_season: number
  scoring: string
  sort: string
  position: string | null
  limit: number
  offset: number
  eligible_players: number
  returned_players: number
  roster: {
    last_verified_at: string | null
    freshness: { status: string; age_days: number | null; max_age_days: number }
  }
  players: NflDraftPlayer[]
}

export type NflDraftSort = 'fantasy_ppr_g' | 'fantasy_pts_g' | 'pass_yds_g' | 'rush_yds_g' | 'rec_yds_g' | 'targets' | 'adp' | 'season_proj_pts'

export interface NflDraftNotes {
  rank: Record<number, number>
  watch: Record<number, boolean>
  fade: Record<number, boolean>
}

// ── NFL usage trend ────────────────────────────────────────────────────

export interface NflUsageGame {
  week: number | null
  opponent: string | null
  snaps: number | null
  snap_share: number | null
  targets: number | null
  target_share: number | null
  air_yds_share: number | null
  adot: number | null
  wopr: number | null
  rec: number | null
  rec_yds: number | null
  rec_td: number | null
  fpts_ppr: number | null
}

export interface NflUsageTrend {
  snap_share: 'up' | 'down' | 'flat' | null
  target_share: 'up' | 'down' | 'flat' | null
  wopr: 'up' | 'down' | 'flat' | null
}

export interface NflUsageAverages {
  snap_share: number | null
  target_share: number | null
  wopr: number | null
}

export interface NflUsageResponse {
  player_id: number
  name: string
  team: string
  position: string
  season: number | null
  games: NflUsageGame[]
  averages: NflUsageAverages
  trend: NflUsageTrend
}
