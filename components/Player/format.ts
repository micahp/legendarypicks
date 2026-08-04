import type { Projection } from './types'

// Labels and number formatting for the player surfaces. Pulled out of the page
// because precision here is a correctness concern, not a styling one: a
// one-decimal default rendered three hitters twelve points of average apart as
// `0.3` each, and the column stopped ranking anybody.

export const STAT_ORDER = ['pass_yds', 'rush_yds', 'rec_yds', 'PTS', 'REB', 'AST', 'PRA', '3PM',
  'points', 'goals', 'assists', 'shots', 'H', 'TB', 'HR', 'K', 'outs', 'hits_allowed', 'fpts_ppr']
export const TREND: Record<string, string> = { up: '↑', down: '↓', flat: '→' }
export const MARKET_STAT: Record<string, string[]> = {
  points: ['PTS', 'points'], rebounds: ['REB'], assists: ['AST'], threes: ['3PM'], pra: ['PRA'],
  steals: ['STL'], blocks: ['BLK'], turnovers: ['TO'],
  goals: ['goals'], shots: ['shots'], saves: ['saves'],
  hits: ['H'], home_runs: ['HR'], strikeouts: ['K'], total_bases: ['TB'],
  walks: ['BB'], doubles: ['2B'], triples: ['3B'],
  // NFL: canonical key first, legacy nflverse key as fallback. /api/player/{id}
  // now normalizes NFL keys, so the legacy names no longer reach this map — but
  // a player whose only logs predate the rename still resolves through them.
  passing_yards: ['pass_yds', 'passing_yards'], rushing_yards: ['rush_yds', 'rushing_yards'],
  receiving_yards: ['rec_yds', 'receiving_yards'], receptions: ['rec', 'receptions'],
  outs: ['outs'], hits_allowed: ['hits_allowed'],
}

// Compact, league-appropriate labels for the season_stats keys returned by
export const STAT_LABELS: Record<string, string> = {
  // NHL
  goals: 'Goals', assists: 'Assists', points: 'Points', shots: 'Shots',
  shooting_pct: 'Shooting %', plus_minus: '+/-', pim: 'PIM', ppg: 'PP Goals',
  ppp: 'PP Points', shg: 'SH Goals', toi: 'TOI', faceoff_pct: 'Faceoff %',
  // NBA
  pts: 'Points', reb: 'Rebounds', ast: 'Assists', stl: 'Steals', blk: 'Blocks',
  fg_pct: 'FG %', fg3_pct: '3PT %', ft_pct: 'FT %', min_pg: 'Minutes/G',
  turnovers: 'Turnovers', ts_pct: 'True Shooting %',
  // NFL
  passing_yards_pg: 'Pass Yds/G', passing_tds: 'Pass TDs', interceptions: 'INTs',
  completions_pg: 'Comp/G', passing_epa: 'Pass EPA', carries_pg: 'Carries/G',
  rushing_yards_pg: 'Rush Yds/G', receptions: 'Receptions',
  receiving_yards_pg: 'Rec Yds/G', targets: 'Targets',
  fantasy_points_pg: 'Fantasy Pts/G', fantasy_points_ppr_pg: 'Fantasy Pts/G (PPR)',
  // MLB batting
  avg: 'AVG', hr: 'HR', k_pct: 'K %', bb_pct: 'BB %', exit_velo: 'Exit Velo',
  hard_hit_pct: 'Hard-Hit %', barrel_pct: 'Barrel %', launch_angle: 'Launch Angle',
  woba: 'wOBA', xwoba: 'xwOBA',
  // MLB pitching
  whiff_pct: 'Whiff %', exit_velo_against: 'Exit Velo Against',
  barrel_pct_against: 'Barrel % Against', xwoba_against: 'xwOBA Against',
}

export function statLabel(key: string): string {
  return STAT_LABELS[key] || key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

/* Columns holding a fantasy-point total. They carry one decimal ALWAYS, even
   when the value is whole, because a PPR column reading `18` two rows under
   `23.2` is the ragged edge this exists to stop. It is the same rule
   PlayerGameLog's cell() applies, by leaving these out of its INTEGER set —
   stated here rather than imported so neither surface can quietly drift, since
   the two disagreeing is what this fixes. */
export const ONE_DECIMAL = new Set([
  'fpts', 'fpts_ppr', 'xfpts_ppr', 'fantasy_pts', 'proj_pts', 'proj_ppr_points',
])
export function statCell(key: string, value: number | null): string {
  if (value == null) return '—'
  if (ONE_DECIMAL.has(key)) return value.toFixed(1)
  // Rounding is not cosmetic here. The weekly PPR series arrives off the parquet
  // as binary floats, so week 12 is 8.120000000000001 and week 10 is
  // 19.340000000000003 — printed raw, which is what the game log was doing.
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

// Baseball rate stats are published to three decimals with no leading zero —
// `.336`, not `0.336` and emphatically not `0.3`. `statCell`'s one-decimal
// default was collapsing Andrew Vaughn's .336 average to `0.3` and his .423 wOBA
// to `0.4`, which is not a rounding preference: three hitters separated by twelve
// points of average all read `0.3`, so the column stopped ranking anybody. Fake
// precision and lost precision are the same defect from opposite directions.
const THREE_DECIMAL_RATES = new Set([
  'avg', 'obp', 'slg', 'ops', 'woba', 'xwoba', 'xwoba_against', 'babip',
])

export function formatStatValue(key: string, value: number | string | null): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  if (THREE_DECIMAL_RATES.has(key)) return value.toFixed(3).replace(/^0\./, '.')
  if (key.endsWith('_pct')) return `${value.toFixed(1)}%`
  return statCell(key, value)
}

export function projForMarket(projections: Record<string, Projection>, market: string): Projection | null {
  const candidates = MARKET_STAT[market] || [market]
  for (const c of candidates) {
    if (projections[c]) return projections[c]
    // Also try case-insensitive
    const lc = c.toLowerCase()
    for (const k of Object.keys(projections)) {
      if (k.toLowerCase() === lc) return projections[k]
    }
  }
  return null
}

