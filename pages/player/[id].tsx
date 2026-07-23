import { useState, useEffect } from 'react'
import { useRouter } from 'next/router'
import Head from 'next/head'
import PropChart, { PropHistory } from '../../components/Props/PropChart'

interface Projection {
  n: number; projection: number; median: number; floor: number; ceiling: number
  l5_avg: number; season_avg: number; trend: string; last5: number[]
}
interface RecentGame { date: string | null; opponent: string | null; home: boolean | null; stats: Record<string, number | string> }
interface PropRow { market: string; side: string; line: number }
interface SeasonStatBlock {
  window?: string
  games?: number
  team?: string
  position?: string
  source?: string
  stats?: Record<string, number | string | null>
}
interface MlbSeasonStats {
  window?: string
  batting?: Record<string, number | string | null> | null
  pitching?: Record<string, number | string | null> | null
}
type SeasonStats = SeasonStatBlock | MlbSeasonStats
interface PlayerProfile {
  id: number; name: string; team: string; league: string; position: string | null
  season: number | null; games: number
  recent_games: RecentGame[]
  projections: Record<string, Projection>
  props: PropRow[]
  season_stats: SeasonStats | null
  coverage: { game_logs: boolean; props: boolean; season_stats: boolean }
  data_status: 'ready' | 'unavailable'
}

const STAT_ORDER = ['pass_yds', 'rush_yds', 'rec_yds', 'PTS', 'REB', 'AST', 'PRA', '3PM',
  'points', 'goals', 'assists', 'shots', 'H', 'TB', 'HR', 'K', 'outs', 'hits_allowed', 'fpts_ppr']
const TREND: Record<string, string> = { up: '↑', down: '↓', flat: '→' }

const MARKET_STAT: Record<string, string[]> = {
  points: ['PTS', 'points'], rebounds: ['REB'], assists: ['AST'], threes: ['3PM'], pra: ['PRA'],
  steals: ['STL'], blocks: ['BLK'], turnovers: ['TO'],
  goals: ['goals'], shots: ['shots'], saves: ['saves'],
  hits: ['H'], home_runs: ['HR'], strikeouts: ['K'], total_bases: ['TB'],
  walks: ['BB'], doubles: ['2B'], triples: ['3B'],
  passing_yards: ['passing_yards'], rushing_yards: ['rushing_yards'],
  receiving_yards: ['receiving_yards'], receptions: ['receptions'],
  outs: ['outs'], hits_allowed: ['hits_allowed'],
}

// Compact, league-appropriate labels for the season_stats keys returned by
// /api/player/{id} (NHL/NBA/NFL flat `stats`, MLB split `batting`/`pitching`).
const STAT_LABELS: Record<string, string> = {
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

function statLabel(key: string): string {
  return STAT_LABELS[key] || key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function formatStatValue(key: string, value: number | string | null): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  if (key.endsWith('_pct')) return `${value.toFixed(1)}%`
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

// Renders one compact stat grid (a flat `stats` dict, or an MLB batting/pitching split).
function SeasonStatsSection({ league, seasonStats }: { league: string; seasonStats: SeasonStats }) {
  const isMlbSplit = 'batting' in seasonStats || 'pitching' in seasonStats
  const blocks: { label: string; entries: [string, number | string | null][] }[] = []

  if (isMlbSplit) {
    const mlb = seasonStats as MlbSeasonStats
    if (mlb.batting) blocks.push({ label: 'Batting', entries: Object.entries(mlb.batting) })
    if (mlb.pitching) blocks.push({ label: 'Pitching', entries: Object.entries(mlb.pitching) })
  } else {
    const block = seasonStats as SeasonStatBlock
    if (block.stats) blocks.push({ label: 'Season', entries: Object.entries(block.stats) })
  }

  const meta = seasonStats as SeasonStatBlock

  if (blocks.length === 0) return null

  return (
    <section>
      <h2 className="text-sm font-bold text-zinc-400 uppercase tracking-wider mb-2">
        Season Stats{seasonStats.window ? ` · ${seasonStats.window}` : ''}{meta.games ? ` · ${meta.games} games` : ''}
      </h2>
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 divide-y divide-zinc-800">
        {blocks.map(b => (
          <div key={b.label} className="p-4">
            {blocks.length > 1 && <div className="text-xs font-semibold text-zinc-400 mb-2">{b.label}</div>}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2">
              {b.entries.map(([k, v]) => (
                <div key={k} className="flex items-baseline justify-between gap-2">
                  <span className="text-xs text-zinc-500">{statLabel(k)}</span>
                  <span className="font-mono tabular-nums text-sm text-zinc-200">{formatStatValue(k, v)}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      {meta.source && (
        <p className="mt-1 text-[10px] text-zinc-600">Source: {meta.source} ({league.toUpperCase()})</p>
      )}
    </section>
  )
}

function projForMarket(projections: Record<string, Projection>, market: string): Projection | null {
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

type FetchState = 'loading' | 'ready' | 'not_found' | 'error'

export default function PlayerPage() {
  const router = useRouter()
  const { id } = router.query
  const [p, setP] = useState<PlayerProfile | null>(null)
  const [state, setState] = useState<FetchState>('loading')
  const [retryTick, setRetryTick] = useState(0)
  const [openProp, setOpenProp] = useState<string | null>(null)
  const [chart, setChart] = useState<PropHistory | null>(null)

  useEffect(() => {
    if (!id) return
    let alive = true
    setState('loading')
    setP(null)
    fetch(`/api/player/${id}`)
      .then(r => {
        if (r.status === 404) { if (alive) setState('not_found'); return null }
        if (!r.ok) { if (alive) setState('error'); return null }
        return r.json()
      })
      .then(d => {
        if (!alive || !d) return
        setP(d)
        setState('ready')
      })
      .catch(() => { if (alive) setState('error') })
    return () => { alive = false }
  }, [id, retryTick])

  const openChart = async (pr: PropRow) => {
    const key = `${pr.market}-${pr.side}`
    if (openProp === key) { setOpenProp(null); setChart(null); return }
    setOpenProp(key); setChart(null)
    try {
      const params = new URLSearchParams({ player_id: String(id), market: pr.market, line: String(pr.line), side: pr.side, league: p?.league || 'mlb' })
      const r = await fetch(`/api/props/history?${params}`)
      if (!r.ok) { setChart(null); return }
      const d = await r.json()
      setChart(d.games?.length ? d : null)
    } catch { setChart(null) }
  }

  if (state === 'loading') return <div className="text-zinc-500 text-sm py-16 text-center">Loading…</div>
  if (state === 'not_found') return <div className="text-zinc-500 text-sm py-16 text-center">Player not found.</div>
  if (state === 'error' || !p) return (
    <div className="text-sm py-16 text-center space-y-2">
      <p className="text-red-400">Couldn’t load this player.</p>
      <button onClick={() => setRetryTick(t => t + 1)} className="text-emerald-400/80 hover:text-emerald-300 text-xs font-medium">
        Retry
      </button>
    </div>
  )

  // UFC's game logs store ESPN's full raw stat blob (43 fields — advances,
  // reversals, slamRate, etc.), not a curated prop-market list like other
  // leagues — this generic table has no way to know which of those are
  // meaningful, so it would dump all 43. Recent Fights (below) already shows
  // the headline UFC stats; skip this section for UFC entirely rather than
  // rendering noise.
  const projKeys = p.league === 'ufc' ? [] : Object.keys(p.projections).sort((a, b) => {
    const ia = STAT_ORDER.indexOf(a), ib = STAT_ORDER.indexOf(b)
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib) || a.localeCompare(b)
  })

  return (
    <>
      <Head><title>{p.name} — Legendary Picks</title></Head>
      <div className="space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight">{p.name}</h1>
          <div className="text-sm text-zinc-500 mt-1">
            {[p.team, p.position, p.league?.toUpperCase(), p.season ? `${p.season} · ${p.games} games` : null].filter(Boolean).join(' · ')}
          </div>
        </div>

        {/* Honest empty state: no logs, no props, no season stats on file. */}
        {p.data_status === 'unavailable' && (
          <p className="text-sm text-zinc-500 py-6 text-center border border-zinc-800 rounded-xl bg-zinc-900">
            No stats, game logs, or props on file for this player yet.
          </p>
        )}

        {/* Season stats: the only meaningful content for stats-only profiles
            (no game-log/props coverage — e.g. NHL/NBA/NFL players synced from
            season totals rather than per-game rows). */}
        {p.season_stats && <SeasonStatsSection league={p.league} seasonStats={p.season_stats} />}

        {/* Current props (each expands to a chart) */}
        {p.props.length > 0 && (
          <section>
            <h2 className="text-sm font-bold text-zinc-400 uppercase tracking-wider mb-2">Current Props</h2>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900 divide-y divide-zinc-800">
              {p.props.map((pr, i) => {
                const key = `${pr.market}-${pr.side}`
                return (
                  <div key={i}>
                    <button onClick={() => openChart(pr)} className="w-full flex items-center justify-between px-4 py-3 hover:bg-zinc-800/40 text-sm">
                      <span className="font-medium">{pr.market.replace(/_/g, ' ')}</span>
                      <span className="font-mono tabular-nums text-zinc-300">
                        {pr.side} {pr.line}
                        {(() => { const pj = projForMarket(p.projections, pr.market); return pj ? <span className="ml-2 text-xs text-emerald-400">Proj {pj.projection}</span> : null })()}
                      </span>
                    </button>
                    {openProp === key && (
                      <div className="px-4 pb-4">{chart ? <PropChart data={chart} /> : <div className="text-xs text-zinc-600 py-3">Chart not available for this market.</div>}</div>
                    )}
                  </div>
                )
              })}
            </div>
          </section>
        )}

        {/* Projections */}
        {projKeys.length > 0 && (
          <section>
            <h2 className="text-sm font-bold text-zinc-400 uppercase tracking-wider mb-2">Projections</h2>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
              <table className="w-full text-sm">
                <thead><tr className="border-b border-zinc-800 text-zinc-500 text-[11px] uppercase tracking-wider">
                  <th className="text-left px-4 py-3 font-medium">Stat</th>
                  <th className="text-right px-3 py-3 font-medium">Proj</th>
                  <th className="text-right px-3 py-3 font-medium">Median</th>
                  <th className="text-right px-3 py-3 font-medium">Floor–Ceil</th>
                  <th className="text-right px-3 py-3 font-medium">L5</th>
                  <th className="text-center px-3 py-3 font-medium">Trend</th>
                </tr></thead>
                <tbody>
                  {projKeys.map(k => { const pj = p.projections[k]; return (
                    <tr key={k} className="border-b border-zinc-800/50">
                      <td className="px-4 py-2.5 font-medium">{k.replace(/_/g, ' ')}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums font-bold text-emerald-300">{pj.projection}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-zinc-400">{pj.median}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-zinc-500">{pj.floor}–{pj.ceiling}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{pj.l5_avg}</td>
                      <td className="px-3 py-2.5 text-center text-lg">{TREND[pj.trend] || '→'}</td>
                    </tr>
                  )})}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Recent fights — UFC specific */}
        {p.league === 'ufc' && p.recent_games.length > 0 && (
          <section>
            <h2 className="text-sm font-bold text-zinc-400 uppercase tracking-wider mb-2">Recent Fights</h2>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-800 text-zinc-500 text-[11px] uppercase tracking-wider">
                    <th className="text-left py-3 pl-4 pr-2">Opponent</th>
                    <th className="text-left py-3 px-2">Date</th>
                    <th className="text-center py-3 px-2 w-12">Result</th>
                    <th className="text-right py-3 px-2">Sig Str</th>
                    <th className="text-right py-3 pr-4">Takedowns</th>
                  </tr>
                </thead>
                <tbody>
                  {p.recent_games.map((g, i) => {
                    const s = g.stats as Record<string, number | string>
                    const result = (s.result as string) || ''
                    const sigLanded = s.sigStrikesLanded ?? '—'
                    const sigAttempted = s.sigStrikesAttempted ?? '—'
                    const tdkLanded = s.takedownsLanded ?? '—'
                    const tdkAttempted = s.takedownsAttempted ?? '—'
                    const resultColor =
                      result === 'W' ? 'text-emerald-400' :
                      result === 'L' ? 'text-red-400' :
                      result === 'D' ? 'text-amber-400' : 'text-zinc-500'
                    return (
                      <tr key={i} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                        <td className="py-2.5 pl-4 pr-2 text-zinc-200">{g.opponent || '—'}</td>
                        <td className="py-2.5 px-2 text-zinc-500 text-xs">{g.date || '—'}</td>
                        <td className={`py-2.5 px-2 text-center font-bold ${resultColor}`}>
                          {result || '—'}
                        </td>
                        <td className="py-2.5 px-2 text-right font-mono tabular-nums text-xs text-zinc-300">
                          {typeof sigLanded === 'number' && typeof sigAttempted === 'number'
                            ? `${sigLanded}/${sigAttempted}` : '—'}
                        </td>
                        <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-xs text-zinc-300">
                          {typeof tdkLanded === 'number' && typeof tdkAttempted === 'number'
                            ? `${tdkLanded}/${tdkAttempted}` : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Recent games — generic (non-UFC) */}
        {p.league !== 'ufc' && p.recent_games.length > 0 && (
          <section>
            <h2 className="text-sm font-bold text-zinc-400 uppercase tracking-wider mb-2">Recent Games</h2>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900 divide-y divide-zinc-800 text-sm">
              {p.recent_games.map((g, i) => (
                <div key={i} className="flex items-center justify-between px-4 py-2.5">
                  <span className="text-zinc-400 text-xs w-32">{g.date} {g.opponent ? `${g.home ? 'vs' : '@'} ${g.opponent}` : ''}</span>
                  <span className="font-mono tabular-nums text-zinc-300 text-xs truncate">
                    {Object.entries(g.stats).filter(([, v]) => typeof v === 'number').slice(0, 6).map(([k, v]) => `${k} ${v}`).join('  ')}
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </>
  )
}
