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
  depth_team: string | null
  team_changed: boolean | null
  /** Current role from the published depth chart. 1 = starter. */
  depth_rank: number | null
  /** Position attached to depth_rank in the published depth chart. */
  depth_position: string | null
  adp: number | null
  /** ESPN's published 2026 PPR draft rank. */
  espn_ppr_rank: number | null
  /** LP PPR total computed from ESPN's published 2026 projected stat line. */
  proj_ppr_points: number | null
  proj_season: number
  proj_source: 'espn' | null
  bye_week: number | null
  /** True when ESPN published an ADP value for this player. */
  adp_is_ranked: boolean
  percent_owned: number | null
  /** Current ESPN injury designation. ACTIVE and null render no warning tag. */
  injury_status: string | null
  /** The headline: regular-season games played out of the team's 17. */
  games_played: number | null
  games_missed: number | null
  team_games: number | null
  /** Weeks 1-18 he appeared in. The gaps are the story. */
  weeks_played: number[]
  /** The 17 weeks his team played, so a bye renders as a bye, not an absence. */
  team_weeks: number[]
  /** What every fantasy site shows - conditional on him being available. */
  ppr_per_game_played: number | null
  /** What the roster spot actually returned. */
  ppr_per_team_game: number | null
  xfp_per_game: number | null
  snap_pct: number | null
  target_share: number | null
  /** D/ST fantasy points: total and per-game. Null for non-DEF. */
  dst_pts_total: number | null
  dst_pts_per_game: number | null
  /** PK fantasy points: total and per-game. Null for non-PK. */
  pk_pts_total: number | null
  pk_pts_per_game: number | null
  sample: 'full' | 'thin' | 'none'
}

export interface NflDraftBoard {
  contract: string
  league: string
  current_season: number
  reference_season: number
  scoring: string
  team_games: number
  thin_sample_games: number
  sort: string
  position: string | null
  query: string | null
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

export type NflDraftSort = 'rank' | 'proj' | 'adp' | 'ppr_per_team_game' | 'ppr_per_game_played' | 'xfp_per_game' | 'games_played' | 'snap_pct' | 'target_share' | 'dst_pts_per_game' | 'pk_pts_per_game'

export interface NflDraftNotes {
  rank: Record<number, number>
  watch: Record<number, boolean>
  fade: Record<number, boolean>
}

export interface DraftNotesResponse {
  contract: string
  season: number
  notes: NflDraftNotes
  note_count: number
  updated_at: number | null
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
  carries: number | null
  carry_share: number | null
  rush_yds: number | null
  rush_td: number | null
  fpts_ppr: number | null
  // Next Gen receiving — WR/TE only, no RB or QB carries these.
  separation: number | null
  cushion: number | null
  yac_above_exp: number | null
  // Play-by-play passing — QBs, 2025 onward only.
  cpoe: number | null
  pass_epa: number | null
  pass_att: number | null
  epa_per_db: number | null
  // Special teams — the only thing that explains a low-offensive-snap player.
  st_snaps: number | null
  st_pct: number | null
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

// ── Mock draft contracts ─────────────────────────────────────────────────

export interface PoolPlayer {
  player_id: number
  name: string
  position: string
  team: string
  adp: number | null
  /** ESPN's published PPR draft rank for the drafted season. */
  espn_ppr_rank?: number | null
  /** LP PPR total computed from ESPN's published projected stat line. */
  proj_ppr_points?: number | null
  proj_season?: number | null
  proj_source?: 'espn' | null
  percent_owned: number | null
  sample: 'full' | 'thin' | 'none'
  /** Whether we hold any NFL game log for this player before the reference
   *  season. Distinguishes a rookie from a veteran who missed the year. */
  has_prior_nfl_sample?: boolean
  games_played: number | null
  games_missed: number | null
  weeks_played: number[]
  team_weeks: number[]
  /** Current ESPN injury designation. ACTIVE and null render no warning tag. */
  injury_status?: string | null
  last_news_date?: number | null

  /* Production fields — job16 (docs/TASK-job16-pool-payload-parity.md).
     Optional because the pool payload does not carry them yet; the same ten
     fields already ship on /api/nfl/draft/player/{id}. Absent and null render
     identically ("—"), so the row is honest before and after the backend lands. */
  team_games?: number | null
  ppr_per_game_played?: number | null
  ppr_per_team_game?: number | null
  xfp_per_game?: number | null
  snap_pct?: number | null
  target_share?: number | null
  pk_pts_total?: number | null
  pk_pts_per_game?: number | null
  dst_pts_total?: number | null
  dst_pts_per_game?: number | null
  /** ESPN-style 4-stat league ranks.
   * Population field — job16+. */
  stat_ranks?: Record<string, { value: number | null; rank: number | null; label: string }> | null
}

export interface PoolResponse {
  contract: string
  /** The season being drafted. */
  season: number
  /** The season every statistic in `players` describes. */
  reference_season?: number | null
  count: number
  players: PoolPlayer[]
}

export interface MockDraftPick {
  pick_no: number
  team_no: number
  player_id: number
  player_name?: string
  player_position?: string
  player_team?: string
  auto: boolean
  created_at?: number
}

export interface MockDraft {
  id: string
  season: number
  seat: number
  teams: number
  rounds: number
  seed: number
  /* The backend writes exactly these two. This union previously read
     'active' | 'complete' | 'abandoned' -- two of those three strings are
     written by nothing, and the page's completion check compared against one
     of them, so it never matched. */
  status: 'active' | 'completed'
  created_at: number
  updated_at: number
  completed_at: number | null
  picks: MockDraftPick[]
  total_picks: number
  /** teams × rounds — what a finished draft holds. */
  picks_expected: number
  /** Pick numbers absent below the highest one saved. Empty is the normal case;
   *  non-empty means an append was dropped and never retried. */
  missing_picks: number[]
  current_round: number
  current_pick: number
}

export interface NflPlayerStatLine {
  games: number | null
  pass_att: number | null
  pass_cmp: number | null
  pass_yds: number | null
  pass_td: number | null
  interceptions: number | null
  completion_pct: number | null
  sacks: number | null
  rush_att: number | null
  rush_yds: number | null
  rush_td: number | null
  receptions: number | null
  targets: number | null
  rec_yds: number | null
  rec_td: number | null
  fumbles: number | null
  fumbles_lost: number | null
  passing_first_downs: number | null
  rushing_first_downs: number | null
  receiving_first_downs: number | null
  /** ESPN Total QBR, not passer rating. Published for prior-season QBs. */
  qbr: number | null
  passer_rating: number | null
  adj_qbr: number | null
  fg_att: number | null
  fg_made: number | null
  xp_att: number | null
  xp_made: number | null
  def_td: number | null
  def_int: number | null
  def_sack: number | null
  def_fumble_rec: number | null
  def_points_allowed: number | null
  def_yds_allowed: number | null
}

export interface NflSeasonTotals extends NflPlayerStatLine {
  season: number | null
  ppr_points: number | null
}

export interface PlayerDetailResponse {
  player_id: number
  name: string
  team: string
  position: string
  active: boolean
  adp: number | null
  percent_owned: number | null
  espn_ppr_rank?: number | null
  espn_standard_rank?: number | null
  proj_2026_pts?: number | null
  projection_2026?: NflPlayerStatLine | null
  projection_source?: 'espn' | null
  season_outlook?: string | null
  season_outlook_source?: 'espn' | null
  season_totals?: NflSeasonTotals | null
  season_totals_source?: 'espn' | null
  /** Canonical prior regular-season league ranks and their sample. */
  stat_ranks?: Record<string, { value: number | null; rank: number | null; label: string }> | null
  stat_rank_season?: number | null
  stat_rank_games?: number | null
  sample: 'full' | 'thin' | 'none'
  /** Whether we hold any NFL game log for this player before the reference
   *  season. Distinguishes a rookie from a veteran who missed the year. */
  has_prior_nfl_sample?: boolean
  games_played: number | null
  games_missed: number | null
  team_games: number | null
  weeks_played: number[]
  team_weeks: number[]
  ppr_per_game_played: number | null
  ppr_per_team_game: number | null
  snap_pct: number | null
  target_share: number | null
  xfp_per_game: number | null
  /** D/ST fantasy points: total and per-game. Null for non-DEF. */
  dst_pts_total: number | null
  dst_pts_per_game: number | null
  /** PK fantasy points: total and per-game. Null for non-PK. */
  pk_pts_total: number | null
  pk_pts_per_game: number | null
  /** QB throwing to this receiver (WR/RB/TE only). */
  qb: { player_id: number; name: string; team: string; games_played: number } | null
  /** Injury designation from ESPN (ACTIVE, QUESTIONABLE, OUT, INJURY_RESERVE). */
  injury_status: string | null
  /** Timestamp of last news update (ms since epoch). */
  last_news_date: number | null
}
