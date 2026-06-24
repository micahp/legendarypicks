import { useState, useEffect, useCallback, useRef } from 'react'
import Head from 'next/head'

// ── types ────────────────────────────────────────────────
interface Player {
  id: number; name: string; team: string; league: string
}
interface Prop {
  id: number; market: string; line: number; side: string; source: string
  captured_at: string; player_name: string; player_team: string; league: string
  actual_value: number | null; hit: boolean | null; settled_at: string | null
}
interface SlateGame {
  game_id: number; home: string; away: string; date: string; league: string
  prop_count: number
  players: { name: string; team: string; props: { market: string; line: number; side: string; source: string }[] }[]
}
interface PerfRow {
  market: string; side: string; total_settled: number
  hit_rate_l5: number | null; hit_rate_l10: number | null
  hit_rate_l20: number | null; hit_rate_season: number | null
  hit_rate_weighted: number; trend: string
}

type Tab = 'lines' | 'slate' | 'performance' | 'matchups' | 'model'
type League = 'All' | 'nba' | 'mlb' | 'nfl' | 'nhl'

const TABS: { key: Tab; label: string }[] = [
  { key: 'lines', label: 'Lines' },
  { key: 'slate', label: 'Slate' },
  { key: 'performance', label: 'Performance' },
  { key: 'matchups', label: 'Matchups' },
  { key: 'model', label: 'Model' },
]
const LEAGUES: League[] = ['All', 'mlb', 'nba', 'nfl', 'nhl']
const MARKETS = ['All', 'points', 'rebounds', 'assists', 'threes', 'strikeouts', 'passing_yards', 'rushing_yards', 'receiving_yards', 'hits', 'home_runs', 'goals', 'shots', 'saves']
const BOOKS = ['All', 'bovada', 'kalshi']

function Skeleton({ lines = 4 }: { lines?: number }) {
  return (
    <div className="space-y-3 animate-pulse">
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="h-4 bg-zinc-800 rounded w-full" style={{ opacity: 1 - i * 0.15 }} />
      ))}
    </div>
  )
}

function HitBadge({ hit }: { hit: boolean | null }) {
  if (hit === null) return <span className="text-zinc-600">—</span>
  return hit
    ? <span className="text-emerald-400 font-bold">✅</span>
    : <span className="text-red-400 font-bold">❌</span>
}

function LeaguePills({ league, onChange }: { league: League; onChange: (l: League) => void }) {
  return (
    <div className="flex gap-1.5">
      {LEAGUES.map(l => (
        <button key={l} onClick={() => onChange(l)}
          className={`px-3.5 py-1.5 rounded-lg text-sm font-medium transition-colors ${league === l ? 'bg-emerald-600 text-white' : 'bg-zinc-900 border border-zinc-800 text-zinc-400 hover:text-zinc-200'}`}>
          {l === 'All' ? 'All' : l.toUpperCase()}
        </button>
      ))}
    </div>
  )
}

function PlayerSearch({ query, setQuery, players, onSelect }: {
  query: string; setQuery: (q: string) => void; players: Player[]; onSelect: (p: Player) => void
}) {
  // own the dropdown open/close so selecting a player (which re-sets query and
  // re-fires the parent search) does NOT re-open the list; also closes on click-outside.
  const [open, setOpen] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])
  return (
    <div ref={boxRef} className="relative flex-1 min-w-[200px] max-w-sm">
      <input type="text" value={query}
        onChange={e => { setQuery(e.target.value); setOpen(true) }}
        onFocus={() => { if (players.length > 0) setOpen(true) }}
        placeholder="Search player…"
        className="w-full px-4 py-2.5 rounded-xl border border-zinc-800 bg-zinc-900 text-zinc-200 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500 text-sm" />
      {open && players.length > 0 && (
        <div className="absolute top-full mt-1 w-full rounded-xl border border-zinc-700 bg-zinc-900 shadow-xl z-50 overflow-hidden">
          {players.map(p => (
            <button key={p.id} onClick={() => { setOpen(false); onSelect(p) }}
              className="w-full text-left px-4 py-2.5 hover:bg-zinc-800 flex justify-between items-center text-sm">
              <span className="font-medium">{p.name}</span>
              <span className="text-xs text-zinc-500">{p.team} · {p.league.toUpperCase()}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Select({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: { v: string; label: string }[] }) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)}
      className="px-3 py-2.5 rounded-xl border border-zinc-800 bg-zinc-900 text-zinc-200 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500">
      {options.map(o => <option key={o.v} value={o.v}>{o.label}</option>)}
    </select>
  )
}

// ── Tab: Lines ───────────────────────────────────────────
function LinesTab({ league, date }: { league: League; date: string }) {
  const [query, setQuery] = useState('')
  const [players, setPlayers] = useState<Player[]>([])
  const [props, setProps] = useState<Prop[]>([])
  const [market, setMarket] = useState('All')
  const [book, setBook] = useState('All')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (query.length < 2) { setPlayers([]); return }
    const t = setTimeout(async () => {
      try { const r = await fetch(`/api/players/search?q=${encodeURIComponent(query)}`); setPlayers(await r.json()) } catch {}
    }, 250)
    return () => clearTimeout(t)
  }, [query])

  useEffect(() => {
    setLoading(true); setError(null)
    const params = new URLSearchParams({ limit: '100' })
    params.set('date', date)
    if (query) params.set('player', query)
    if (league !== 'All') params.set('league', league)
    if (market !== 'All') params.set('market', market)
    fetch(`/api/props?${params}`)
      .then(r => r.json()).then(d => { setProps(d); setLoading(false) })
      .catch(() => { setError('Failed to load props.'); setLoading(false) })
  }, [query, league, market, date])

  const filtered = book === 'All' ? props : props.filter(p => p.source === book)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 items-center">
        <PlayerSearch query={query} setQuery={setQuery} players={players} onSelect={p => { setQuery(p.name); setPlayers([]) }} />
        <Select value={market} onChange={setMarket} options={MARKETS.map(m => ({ v: m, label: m === 'All' ? 'All Markets' : m.replace(/_/g, ' ') }))} />
        <Select value={book} onChange={setBook} options={BOOKS.map(b => ({ v: b, label: b === 'All' ? 'All Books' : b }))} />
      </div>
      {error && <div className="rounded-lg border border-red-500/40 bg-red-950/40 text-red-200 px-4 py-3 text-sm">{error}</div>}
      {loading ? <Skeleton lines={6} /> : filtered.length === 0 ? (
        <div className="text-center py-16 text-zinc-500 text-sm">No props found. Try a different filter or league.</div>
      ) : (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-800 text-zinc-500 text-[11px] uppercase tracking-wider">
                <th className="text-left px-4 py-3 font-medium">Player</th>
                <th className="text-left px-4 py-3 font-medium">Market</th>
                <th className="text-right px-4 py-3 font-medium">Line</th>
                <th className="text-center px-4 py-3 font-medium">Side</th>
                <th className="text-right px-4 py-3 font-medium">Actual</th>
                <th className="text-center px-4 py-3 font-medium">Hit</th>
                <th className="text-left px-4 py-3 font-medium">Book</th>
                <th className="text-left px-4 py-3 font-medium hidden md:table-cell">Date</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(p => (
                <tr key={p.id} className="border-b border-zinc-800/50 hover:bg-zinc-800/30 transition-colors">
                  <td className="px-4 py-2.5"><span className="font-medium">{p.player_name}</span><span className="text-zinc-500 text-xs ml-1.5">{p.player_team}</span></td>
                  <td className="px-4 py-2.5 text-zinc-300">{p.market.replace(/_/g, ' ')}</td>
                  <td className="px-4 py-2.5 text-right font-mono tabular-nums">{p.line}</td>
                  <td className="px-4 py-2.5 text-center"><span className={`text-[11px] font-bold px-2 py-0.5 rounded ${p.side === 'over' ? 'bg-emerald-900/30 text-emerald-300' : 'bg-red-900/30 text-red-300'}`}>{p.side.toUpperCase()}</span></td>
                  <td className="px-4 py-2.5 text-right font-mono tabular-nums text-zinc-400">{p.actual_value ?? '—'}</td>
                  <td className="px-4 py-2.5 text-center"><HitBadge hit={p.hit} /></td>
                  <td className="px-4 py-2.5 text-zinc-500 text-xs capitalize">{p.source}</td>
                  <td className="px-4 py-2.5 text-zinc-500 text-xs hidden md:table-cell whitespace-nowrap">{p.captured_at ? new Date(p.captured_at).toLocaleDateString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Tab: Slate ────────────────────────────────────────────
function SlateTab({ league, date }: { league: League; date: string }) {
  const [slate, setSlate] = useState<SlateGame[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedGame, setExpandedGame] = useState<number | null>(null)

  useEffect(() => {
    setLoading(true)
    const params = new URLSearchParams()
    params.set('date', date)
    if (league !== 'All') params.set('league', league)
    fetch(`/api/props/slate?${params}`)
      .then(r => r.json()).then(d => { setSlate(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [league, date])

  return (
    <div className="space-y-4">
      {loading ? <Skeleton lines={4} /> : slate.length === 0 ? (
        <div className="text-center py-16 text-zinc-500 text-sm">No games on the board. Check back closer to game time.</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {slate.map(g => (
            <div key={g.game_id} className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-hidden">
              <button onClick={() => setExpandedGame(expandedGame === g.game_id ? null : g.game_id)}
                className="w-full text-left px-4 py-3 hover:bg-zinc-800/50 transition-colors flex items-center justify-between">
                <div>
                  <div className="font-semibold text-sm">{g.away} @ {g.home}</div>
                  <div className="text-xs text-zinc-500">{g.league.toUpperCase()} · {new Date(g.date).toLocaleDateString()} · {g.prop_count} props</div>
                </div>
                <span className="text-zinc-500 text-lg">{expandedGame === g.game_id ? '▾' : '▸'}</span>
              </button>
              {expandedGame === g.game_id && (
                <div className="border-t border-zinc-800 px-4 py-3 space-y-4 max-h-96 overflow-y-auto">
                  {g.players.map(p => (
                    <div key={p.name}>
                      <div className="text-xs font-bold text-zinc-400 mb-1.5 flex items-center gap-1.5">{p.name}<span className="text-zinc-600 font-normal">{p.team}</span></div>
                      <div className="flex flex-wrap gap-1.5">
                        {p.props.map((pr, i) => (
                          <span key={i} className={`inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-mono ${pr.side === 'over' ? 'bg-emerald-900/30 text-emerald-300' : 'bg-red-900/30 text-red-300'}`}>
                            {pr.market.replace(/_/g, ' ')} {pr.line} {pr.side.toUpperCase()}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Tab: Performance (player stats dashboard) ─────────────
function PerformanceTab({ league }: { league: League }) {
  const [query, setQuery] = useState('')
  const [players, setPlayers] = useState<Player[]>([])
  const [selectedPlayer, setSelectedPlayer] = useState<Player | null>(null)
  const [perf, setPerf] = useState<PerfRow[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (query.length < 2) { setPlayers([]); return }
    const t = setTimeout(async () => {
      try { const r = await fetch(`/api/players/search?q=${encodeURIComponent(query)}`); setPlayers(await r.json()) } catch {}
    }, 250)
    return () => clearTimeout(t)
  }, [query])

  const [stats, setStats] = useState<any>(null)
  const [statsLoading, setStatsLoading] = useState(false)

  useEffect(() => {
    if (!selectedPlayer) return
    setLoading(true); setStats(null)
    fetch(`/api/props/player/${selectedPlayer.id}/performance`)
      .then(r => r.json()).then(d => { setPerf(d.performance || []); setLoading(false) })
      .catch(() => setLoading(false))
    // Also fetch advanced stats
    const league = selectedPlayer.league
    if (league === 'mlb' || league === 'nfl' || league === 'nba' || league === 'nhl') {
      setStatsLoading(true)
      fetch(`/api/player/${selectedPlayer.id}/stats?league=${league}`)
        .then(r => r.json()).then(d => { setStats(d); setStatsLoading(false) })
        .catch(() => setStatsLoading(false))
    }
  }, [selectedPlayer])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 items-center">
        <PlayerSearch query={query} setQuery={setQuery} players={players} onSelect={p => { setSelectedPlayer(p); setQuery(p.name); setPlayers([]) }} />
      </div>

      {selectedPlayer && (
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold">{selectedPlayer.name}</h2>
          <span className="text-sm text-zinc-500">{selectedPlayer.team} · {selectedPlayer.league.toUpperCase()}</span>
        </div>
      )}

      {!selectedPlayer ? (
        <div className="text-center py-16 text-zinc-500 text-sm">Search for a player to see their hit rates and advanced metrics.</div>
      ) : (
        <div className="space-y-6">
          {/* Advanced metrics from Statcast (MLB only for now) */}
          {selectedPlayer.league === 'mlb' && (
            <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Statcast — Last 30 Days</span>
                {statsLoading && <span className="text-[10px] text-zinc-600 bg-zinc-800 px-1.5 py-0.5 rounded animate-pulse">loading...</span>}
              </div>
              {stats?.batting ? (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <StatBox label="AVG" value={stats.batting.avg?.toFixed(3)} />
                  <StatBox label="HR" value={stats.batting.hr} />
                  <StatBox label="K%" value={stats.batting.k_pct + '%'} />
                  <StatBox label="BB%" value={stats.batting.bb_pct + '%'} />
                  <StatBox label="Exit Velo" value={stats.batting.exit_velo + ' mph'} />
                  <StatBox label="Hard Hit%" value={stats.batting.hard_hit_pct + '%'} />
                  <StatBox label="Barrel%" value={stats.batting.barrel_pct + '%'} />
                  <StatBox label="Launch Angle" value={stats.batting.launch_angle + '°'} />
                  <StatBox label="wOBA" value={stats.batting.woba?.toFixed(3)} desc="weighted on-base" />
                  <StatBox label="xwOBA" value={stats.batting.xwoba?.toFixed(3)} desc="expected wOBA" />
                </div>
              ) : stats?.message ? (
                <p className="text-xs text-zinc-600">{stats.message}</p>
              ) : (
                <p className="text-xs text-zinc-600">Statcast data not available for this player.</p>
              )}

              {stats?.pitching && (
                <>
                  <div className="mt-4 mb-3">
                    <span className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Pitching</span>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <StatBox label="Whiff%" value={stats.pitching.whiff_pct + '%'} />
                    <StatBox label="K%" value={stats.pitching.k_pct + '%'} />
                    <StatBox label="EV Against" value={stats.pitching.exit_velo_against + ' mph'} />
                    <StatBox label="Barrel Against" value={stats.pitching.barrel_pct_against + '%'} />
                    <StatBox label="xwOBA Against" value={stats.pitching.xwoba_against?.toFixed(3)} desc="lower = better" />
                  </div>
                </>
              )}
            </div>
          )}

          {/* NFL weekly stats */}
          {selectedPlayer.league === 'nfl' && (
            <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-xs font-bold text-zinc-400 uppercase tracking-wider">NFL — Season Stats (nflverse)</span>
                {statsLoading && <span className="text-[10px] text-zinc-600 bg-zinc-800 px-1.5 py-0.5 rounded animate-pulse">loading...</span>}
              </div>
              {stats?.stats ? (
                <div>
                  <div className="flex items-center gap-2 mb-3 text-sm text-zinc-500">
                    <span>{stats.position} · {stats.team}</span>
                    <span className="text-zinc-700">|</span>
                    <span>{stats.games} games · {stats.window}</span>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    {stats.stats.passing_yards_pg != null && <StatBox label="Pass Yds/G" value={stats.stats.passing_yards_pg} />}
                    {stats.stats.passing_tds != null && <StatBox label="Pass TD" value={stats.stats.passing_tds} />}
                    {stats.stats.interceptions != null && <StatBox label="INT" value={stats.stats.interceptions} />}
                    {stats.stats.completions_pg != null && <StatBox label="Cmp/G" value={stats.stats.completions_pg} />}
                    {stats.stats.passing_epa != null && <StatBox label="EPA" value={stats.stats.passing_epa} desc="total" />}
                    {stats.stats.carries_pg != null && <StatBox label="Carries/G" value={stats.stats.carries_pg} />}
                    {stats.stats.rushing_yards_pg != null && <StatBox label="Rush Yds/G" value={stats.stats.rushing_yards_pg} />}
                    {stats.stats.receptions != null && <StatBox label="Rec" value={stats.stats.receptions} />}
                    {stats.stats.receiving_yards_pg != null && <StatBox label="Rec Yds/G" value={stats.stats.receiving_yards_pg} />}
                    {stats.stats.targets != null && <StatBox label="Targets" value={stats.stats.targets} />}
                    {stats.stats.fantasy_points_pg != null && <StatBox label="Fantasy/G" value={stats.stats.fantasy_points_pg} />}
                    {stats.stats.fantasy_points_ppr_pg != null && <StatBox label="PPR/G" value={stats.stats.fantasy_points_ppr_pg} />}
                  </div>
                </div>
              ) : stats?.message ? (
                <p className="text-xs text-zinc-600">{stats.message}</p>
              ) : (
                <p className="text-xs text-zinc-600">NFL stats not available for this player.</p>
              )}
            </div>
          )}

          {/* NBA season stats */}
          {selectedPlayer.league === 'nba' && (
            <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-xs font-bold text-zinc-400 uppercase tracking-wider">NBA — Season Averages (stats.nba.com)</span>
                {statsLoading && <span className="text-[10px] text-zinc-600 bg-zinc-800 px-1.5 py-0.5 rounded animate-pulse">loading...</span>}
              </div>
              {stats?.stats ? (
                <div>
                  <div className="flex items-center gap-2 mb-3 text-sm text-zinc-500">
                    <span>{stats.player_name_nba}</span>
                    <span className="text-zinc-700">|</span>
                    <span>{stats.games} games · {stats.window}</span>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    {stats.stats.pts != null && <StatBox label="PTS" value={stats.stats.pts} />}
                    {stats.stats.reb != null && <StatBox label="REB" value={stats.stats.reb} />}
                    {stats.stats.ast != null && <StatBox label="AST" value={stats.stats.ast} />}
                    {stats.stats.stl != null && <StatBox label="STL" value={stats.stats.stl} />}
                    {stats.stats.blk != null && <StatBox label="BLK" value={stats.stats.blk} />}
                    {stats.stats.fg_pct != null && <StatBox label="FG%" value={stats.stats.fg_pct + '%'} />}
                    {stats.stats.fg3_pct != null && <StatBox label="3PT%" value={stats.stats.fg3_pct + '%'} />}
                    {stats.stats.ft_pct != null && <StatBox label="FT%" value={stats.stats.ft_pct + '%'} />}
                    {stats.stats.min_pg != null && <StatBox label="MIN" value={stats.stats.min_pg} />}
                    {stats.stats.turnovers != null && <StatBox label="TOV" value={stats.stats.turnovers} />}
                    {stats.stats.ts_pct != null && <StatBox label="TS%" value={stats.stats.ts_pct + '%'} desc="true shooting" />}
                  </div>
                </div>
              ) : stats?.message ? (
                <p className="text-xs text-zinc-600">{stats.message}</p>
              ) : (
                <p className="text-xs text-zinc-600">NBA stats not available for this player.</p>
              )}
            </div>
          )}

          {/* NHL season stats */}
          {selectedPlayer.league === 'nhl' && (
            <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-xs font-bold text-zinc-400 uppercase tracking-wider">NHL — Season Stats (NHL.com)</span>
                {statsLoading && <span className="text-[10px] text-zinc-600 bg-zinc-800 px-1.5 py-0.5 rounded animate-pulse">loading...</span>}
              </div>
              {stats?.stats ? (
                <div>
                  <div className="flex items-center gap-2 mb-3 text-sm text-zinc-500">
                    <span>{stats.player_name_nhl} · {stats.position}</span>
                    <span className="text-zinc-700">|</span>
                    <span>{stats.team} · {stats.games} GP · {stats.window}</span>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    {stats.stats.goals != null && <StatBox label="G" value={stats.stats.goals} />}
                    {stats.stats.assists != null && <StatBox label="A" value={stats.stats.assists} />}
                    {stats.stats.points != null && <StatBox label="PTS" value={stats.stats.points} />}
                    {stats.stats.shots != null && <StatBox label="SOG" value={stats.stats.shots} />}
                    {stats.stats.shooting_pct != null && <StatBox label="SH%" value={stats.stats.shooting_pct + '%'} />}
                    {stats.stats.plus_minus != null && <StatBox label="±" value={(stats.stats.plus_minus > 0 ? '+' : '') + stats.stats.plus_minus} />}
                    {stats.stats.pim != null && <StatBox label="PIM" value={stats.stats.pim} />}
                    {stats.stats.ppg != null && <StatBox label="PPG" value={stats.stats.ppg} />}
                    {stats.stats.ppp != null && <StatBox label="PPP" value={stats.stats.ppp} />}
                    {stats.stats.shg != null && <StatBox label="SHG" value={stats.stats.shg} />}
                    {stats.stats.toi != null && <StatBox label="TOI" value={stats.stats.toi} />}
                    {stats.stats.faceoff_pct != null && <StatBox label="FO%" value={stats.stats.faceoff_pct + '%'} />}
                  </div>
                </div>
              ) : stats?.message ? (
                <p className="text-xs text-zinc-600">{stats.message}</p>
              ) : (
                <p className="text-xs text-zinc-600">NHL stats not available for this player.</p>
              )}
            </div>
          )}

          {/* Other leagues — coming soon */}
          {selectedPlayer.league !== 'mlb' && selectedPlayer.league !== 'nfl' && selectedPlayer.league !== 'nba' && selectedPlayer.league !== 'nhl' && (
            <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Advanced Metrics</span>
                <span className="text-[10px] text-zinc-600 bg-zinc-800 px-1.5 py-0.5 rounded">coming soon</span>
              </div>
              <p className="text-xs text-zinc-600">
                {selectedPlayer.league === 'nfl' && 'EPA, CPOE, target share, DVOA — pulling from nflfastR soon.'}
                {selectedPlayer.league === 'nba' && 'TS%, USG%, pace, Opp DvP — pulling from hoopR soon.'}
                {selectedPlayer.league === 'nhl' && 'Corsi, xG, PDO, O-zone% — pulling from fastRhockey soon.'}
              </p>
            </div>
          )}

          {/* Hit rate table */}
          {loading ? <Skeleton lines={4} /> : perf.length === 0 ? (
            <div className="text-center py-8 text-zinc-500 text-sm">No settled props yet. Props are settled after games finish.</div>
          ) : (
            <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-800 text-zinc-500 text-[11px] uppercase tracking-wider">
                    <th className="text-left px-4 py-3 font-medium">Market</th>
                    <th className="text-center px-3 py-3 font-medium">Side</th>
                    <th className="text-right px-3 py-3 font-medium">Settled</th>
                    <th className="text-right px-3 py-3 font-medium">L5</th>
                    <th className="text-right px-3 py-3 font-medium">L10</th>
                    <th className="text-right px-3 py-3 font-medium">L20</th>
                    <th className="text-right px-3 py-3 font-medium">Season</th>
                    <th className="text-right px-3 py-3 font-medium">Weighted</th>
                    <th className="text-center px-3 py-3 font-medium">Trend</th>
                  </tr>
                </thead>
                <tbody>
                  {perf.map((r, i) => (
                    <tr key={i} className="border-b border-zinc-800/50 hover:bg-zinc-800/30 transition-colors">
                      <td className="px-4 py-2.5 font-medium">{r.market.replace(/_/g, ' ')}</td>
                      <td className="px-3 py-2.5 text-center"><span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${r.side === 'over' ? 'bg-emerald-900/30 text-emerald-300' : 'bg-red-900/30 text-red-300'}`}>{r.side.toUpperCase()}</span></td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{r.total_settled}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{r.hit_rate_l5 !== null ? (r.hit_rate_l5 * 100).toFixed(0) + '%' : '—'}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{r.hit_rate_l10 !== null ? (r.hit_rate_l10 * 100).toFixed(0) + '%' : '—'}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{r.hit_rate_l20 !== null ? (r.hit_rate_l20 * 100).toFixed(0) + '%' : '—'}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{r.hit_rate_season !== null ? (r.hit_rate_season * 100).toFixed(0) + '%' : '—'}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums font-bold"><span className={r.hit_rate_weighted >= 0.5 ? 'text-emerald-300' : 'text-red-300'}>{(r.hit_rate_weighted * 100).toFixed(0)}%</span></td>
                      <td className="px-3 py-2.5 text-center text-lg">{r.trend}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Legend / guide */}
          <details className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 text-sm">
            <summary className="font-medium text-zinc-400 cursor-pointer">How to read this</summary>
            <div className="mt-3 space-y-2 text-zinc-500 text-xs leading-relaxed">
              <p><strong>L5 / L10 / L20</strong> — Hit rate over the last 5, 10, or 20 settled props. Shorter windows react faster to slumps or hot streaks.</p>
              <p><strong>Season</strong> — Hit rate across all settled props for this market. The big-picture baseline.</p>
              <p><strong>Weighted</strong> — An EMA (exponential moving average) that gives more weight to recent games: L5 × 0.5 + L10 × 0.25 + L20 × 0.15 + season × 0.1. This is the best single number for predicting the next game.</p>
              <p><strong>Trend</strong> — ↑ improving (L5 &gt; L20 by 10%+), → flat, ↓ declining.</p>
            </div>
          </details>
        </div>
      )}
    </div>
  )
}

// ── Tab: Matchups (placeholder) ────────────────────────────
function MatchupsTab() {
  return (
    <div className="text-center py-16 space-y-3">
      <div className="text-5xl">🏟️</div>
      <h3 className="text-lg font-bold text-zinc-300">Matchup Analysis</h3>
      <p className="text-zinc-500 text-sm max-w-md mx-auto">Player-vs-opponent history with defensive rankings and pace-adjusted splits. Coming after settlement data is live.</p>
    </div>
  )
}

// ── Tab: Model (placeholder) ───────────────────────────────
function ModelTab() {
  return (
    <div className="text-center py-16 space-y-3">
      <div className="text-5xl">🧠</div>
      <h3 className="text-lg font-bold text-zinc-300">Model Projections</h3>
      <p className="text-zinc-500 text-sm max-w-md mx-auto">LightGBM projections vs sportsbook lines with confidence scoring. Built on EMA performance + matchup context + pace-adjusted features.</p>
    </div>
  )
}

function StatBox({ label, value, desc }: { label: string; value: string | number; desc?: string }) {
  return (
    <div className="bg-zinc-800/50 rounded-lg px-3 py-2.5">
      <div className="text-[10px] text-zinc-500 uppercase tracking-wider">{label}{desc ? <span className="ml-1 normal-case tracking-normal">({desc})</span> : ''}</div>
      <div className="text-lg font-bold font-mono tabular-nums mt-0.5">{value ?? '—'}</div>
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────
export default function PropsPage() {
  const [tab, setTab] = useState<Tab>('slate')
  const [league, setLeague] = useState<League>('mlb')

  // Date navigation — mirrors scores.tsx pattern exactly
  const today = new Date().toLocaleDateString('en-CA')
  const [date, setDate] = useState<string>(today)
  const isToday = date === today
  const shiftDay = (delta: number) => {
    const d = new Date(date + 'T12:00:00')   // noon-anchored to dodge TZ rollover
    d.setDate(d.getDate() + delta)
    setDate(d.toLocaleDateString('en-CA'))
  }
  const goToday = () => setDate(today)

  // allow deep-linkable date via ?date=YYYY-MM-DD
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const q = params.get('date')
    if (q && /^\d{4}-\d{2}-\d{2}$/.test(q)) setDate(q)
  }, [])

  const showDateNav = tab === 'lines' || tab === 'slate'

  return (
    <>
      <Head>
        <title>Prop Data — Legendary Picks</title>
        <meta name="description" content="Player prop lines, hit rates, matchup analysis, and model projections" />
      </Head>

      <div className="space-y-4">
        {/* Page header row: title + league pills */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <h1 className="text-3xl font-extrabold tracking-tight">Props</h1>
          <LeaguePills league={league} onChange={setLeague} />
        </div>

        {/* Tab bar */}
        <div className="flex gap-0 overflow-x-auto border-b border-zinc-800 -mx-4 px-4 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {TABS.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px ${tab === t.key ? 'border-emerald-500 text-white' : 'border-transparent text-zinc-500 hover:text-zinc-300'}`}>
              {t.label}
            </button>
          ))}
        </div>

        {/* Date navigator — only on date-scoped tabs */}
        {showDateNav && (
          <div className="flex items-center justify-center gap-2 sm:gap-3">
            <button
              type="button"
              onClick={() => shiftDay(-1)}
              aria-label="Previous day"
              className="flex items-center justify-center w-10 h-10 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-300 text-xl leading-none hover:bg-zinc-800 active:scale-95"
            >
              ‹
            </button>
            <div className="min-w-[11rem] text-center" aria-live="polite">
              <span className="text-sm font-bold text-zinc-200">
                {new Date(date + 'T12:00:00').toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })}
              </span>
              {!isToday && (
                <button type="button" onClick={goToday} className="block mx-auto mt-0.5 text-xs font-medium text-emerald-400 hover:text-emerald-300">
                  Jump to today
                </button>
              )}
            </div>
            <button
              type="button"
              onClick={() => shiftDay(1)}
              aria-label="Next day"
              className="flex items-center justify-center w-10 h-10 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-300 text-xl leading-none hover:bg-zinc-800 active:scale-95"
            >
              ›
            </button>
          </div>
        )}

        {/* Tab content */}
        {tab === 'lines' && <LinesTab league={league} date={date} />}
        {tab === 'slate' && <SlateTab league={league} date={date} />}
        {tab === 'performance' && <PerformanceTab league={league} />}
        {tab === 'matchups' && <MatchupsTab />}
        {tab === 'model' && <ModelTab />}
      </div>
    </>
  )
}
