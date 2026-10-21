import type { Featured, FeaturedGame, FeaturedOdds, FeaturedProp } from './types'

export const prop: FeaturedProp = {
  player_id: 1, player: 'Test Receiver', team: 'AAA', market: 'receiving_yards', line: 89.5, side: 'over',
  matchup: { home: 'DEN', away: 'SEA', date: '2026-10-18', start_time: '2026-10-18T17:00:00Z' },
  hit_rate: { l5: 0.8, l10: 0.5, l20: 0.7, season: 0.52 },
  hit_rate_n: { l5: 5, l10: 10, l20: 20, season: 42 },
  games: Array.from({ length: 20 }, (_, i) => ({
    date: `2025-10-${String((i % 28) + 1).padStart(2, '0')}`, opponent: 'OPP', home: i % 2 === 0, value: 50 + i * 5, hit: i % 3 !== 0,
  })),
  source: { as_of: '2026-10-13T05:00:00+00:00' },
}

export const game: FeaturedGame = {
  game_id: 'g', week: 5, home: 'ATL', away: 'BAL', home_name: 'Atlanta Falcons', away_name: 'Baltimore Ravens',
  kickoff_utc: '2026-10-12T00:20:00Z', proj_home: 24.1, proj_away: 24.6, our_margin: -0.5, our_total: 48.7,
  p_home_win: 0.48, market_spread: 3, pick: { market: 'spread', side: 'away', line: 3, rule: 3, status: 'pick', label: 'BAL +3' }, final: { home: 23, away: 30 },
  pick_result: 'win', model_label: 'v1 points', source: { as_of: '2026-10-11T16:00:00+00:00', line: 'lock row' },
}

export const odds: FeaturedOdds = {
  season: 2026, week: 5, teams_in_run: 32, sims: 20000, source: { as_of: '2026-10-13T06:00:00+00:00' },
  top: [
    { team: 'SF', team_name: 'San Francisco 49ers', p_playoffs: 0.995 },
    { team: 'JAX', team_name: 'Jacksonville Jaguars', p_playoffs: 0.99 },
    { team: 'MIN', team_name: 'Minnesota Vikings', p_playoffs: 0.973 },
    { team: 'KC', team_name: 'Kansas City Chiefs', p_playoffs: 0.94 },
    { team: 'NE', team_name: 'New England Patriots', p_playoffs: 0.903 },
  ],
}

export const featured: Featured = {
  prop, game, playoff_odds: odds,
  record: { season: 2026, win: 5, loss: 6, push: 1, games: 12 },
  chain: {
    player: { player: 'Test Receiver', market: 'receiving_yards', line: 89.5, matchup: prop.matchup, projection: 95.2, games: 42, source: { as_of: null } },
    game,
    market: { home: 'ATL', away: 'BAL', home_name: 'Atlanta Falcons', away_name: 'Baltimore Ravens', model_p_home_win: 0.48, market_p_home_win: 0.61, source: { as_of: null } },
    season: { top: odds.top[0], next: odds.top.slice(1, 4), sims: 20000, week: 5, source: { as_of: null } },
  },
  absent: {},
}
