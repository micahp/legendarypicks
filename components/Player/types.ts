// Shapes served by `/api/player/{id}`. Extracted from the page 2026-08-04, when
// it had reached 891 lines and the file that renders a player was also the file
// that defines what a player is.
export interface Projection {
  n: number; projection: number; median: number; floor: number; ceiling: number
  l5_avg: number; season_avg: number; trend: string; last5: number[]
}
export interface RecentGame { date: string | null; opponent: string | null; home: boolean | null; game_no?: string | number | null; stats: Record<string, number | string> }
export interface NflScheduleGame { week: number; phase: 'regular' | 'postseason' | 'preseason'; opponent: string; home: boolean }
export interface PropRow { market: string; side: string; line: number }
export interface PlayerLogContext { league: string; season: number; games: number }
export interface SeasonStatBlock {
  window?: string
  games?: number
  team?: string
  position?: string
  source?: string
  stats?: Record<string, number | string | null>
}
export interface MlbSeasonStats {
  window?: string
  batting?: Record<string, number | string | null> | null
  pitching?: Record<string, number | string | null> | null
}
export type SeasonStats = SeasonStatBlock | MlbSeasonStats
export interface PlayerProfile {
  id: number; name: string; team: string; league: string; position: string | null
  selected_league: string; position_group: string | null; log_contexts: PlayerLogContext[]
  season: number | null; regular_season_games: number; postseason_games: number; preseason_games: number
  recent_games: RecentGame[]
  postseason_recent_games: RecentGame[]
  preseason_recent_games: RecentGame[]
  nfl_schedule_games: NflScheduleGame[]
  projections: Record<string, Projection>
  props: PropRow[]
  season_stats: SeasonStats | null
  tennis_ranking?: {
    tour: 'atp' | 'wta'; rank: number; previous_rank: number | null
    points: number | null; captured_at: string; source: string | null
  } | null
  coverage: { game_logs: boolean; props: boolean; season_stats: boolean; rankings?: boolean }
  data_status: 'ready' | 'unavailable'
  injury_status?: string | null
  last_news_date?: number | null
  stat_ranks?: Record<string, { value: number | null; rank: number | null; label: string }> | null
  stat_rank_season?: number | null
  stat_rank_games?: number | null
}
