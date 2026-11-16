// Shapes of GET /api/home/featured (backend/routers/home.py). Every piece may be null:
// absence is absence, never zero, and the page hides what it cannot show.
export type Source = { as_of?: string | null; [k: string]: unknown }

export type FeaturedProp = {
  player_id: number
  player: string
  team: string
  market: string
  line: number
  side: string
  matchup: { home: string; away: string; date: string; start_time: string | null } | null
  hit_rate: { l5: number; l10: number; l20: number; season: number }
  hit_rate_n: { l5: number; l10: number; l20: number; season: number }
  games: { date: string; opponent: string; home: boolean | null; value: number; hit: boolean }[]
  source: Source
}

export type FeaturedGame = {
  game_id: string
  week: number
  home: string
  away: string
  home_name: string | null
  away_name: string | null
  kickoff_utc: string | null
  proj_home: number | null
  proj_away: number | null
  our_margin: number
  our_total: number | null
  p_home_win: number | null
  market_spread: number | null
  pick: { market: string | null; side: string | null; line: number | null; rule: number | null; status: string; label: string } | null
  final: { home: number; away: number } | null
  pick_result: string | null
  model_label: string
  source: Source
}

export type PlayoffTeam = { team: string; team_name: string; p_playoffs: number }
export type FeaturedOdds = {
  season: number
  week: number
  teams_in_run: number
  sims: number | null
  top: PlayoffTeam[]
  source: Source
}

export type Featured = {
  prop: FeaturedProp | null
  game: FeaturedGame | null
  playoff_odds: FeaturedOdds | null
  record: { season: number; win: number; loss: number; push: number; games: number } | null
  chain: {
    player: {
      player: string
      market: string
      line: number
      matchup: FeaturedProp['matchup']
      projection: number
      games: number
      source: Source
    } | null
    game: FeaturedGame | null
    market: {
      home: string
      away: string
      home_name: string | null
      away_name: string | null
      model_p_home_win: number | null
      market_p_home_win: number
      source: Source
    } | null
    season: { top: PlayoffTeam; next: PlayoffTeam[]; sims: number | null; week: number; source: Source } | null
  }
  absent: Record<string, string>
}

export type Load<T> = { status: 'loading' } | { status: 'error' } | { status: 'ready'; data: T }
