import { useState, useEffect, useRef } from 'react'
import Head from 'next/head'
import MarketSlateBoard from '../components/Props/MarketSlateBoard'

// ── types ────────────────────────────────────────────────
interface Player {
  id: number; name: string; team: string; league: string
}
interface SlateGame {
  game_id: number; home: string; away: string; date: string; start_time?: string | null; league: string
  prop_count: number
  players: { name: string; team: string; props: { market: string; line: number; side: string; source: string }[] }[]
}
interface PerfRow {
  market: string; side: string; total_settled: number
  hit_rate_l5: number | null; hit_rate_l10: number | null
  hit_rate_l20: number | null; hit_rate_season: number | null
  hit_rate_weighted: number; trend: string
}

type Tab = 'slate' | 'props' | 'performance' | 'matchups' | 'model'
type League = 'All' | 'nba' | 'mlb' | 'mls' | 'nfl' | 'nhl' | 'ufc'

const TABS: { key: Tab; label: string }[] = [
  { key: 'slate', label: 'Slate' },
  { key: 'props', label: 'Props' },
  { key: 'performance', label: 'Performance' },
  { key: 'matchups', label: 'Matchups' },
  { key: 'model', label: 'Model' },
]
export const LEAGUES: League[] = ['All', 'ufc', 'mls', 'nba', 'nfl', 'nhl', 'mlb']

function Skeleton({ lines = 4 }: { lines?: number }) {
  return (
    <div className="space-y-3 animate-pulse">
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="h-4 bg-zinc-800 rounded w-full" style={{ opacity: 1 - i * 0.15 }} />
      ))}
    </div>
  )
}

function LeaguePills({ league, onChange }: { league: League; onChange: (l: League) => void }) {
  return (
    <div className="flex max-w-full flex-wrap gap-1.5">
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

// ── Tab: Slate (games) ───────────────────────────────────
function SlateTab({ league }: { league: League }) {
  const [slate, setSlate] = useState<SlateGame[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedGame, setExpandedGame] = useState<number | null>(null)
  // A game's props load only when it's opened — the summary list carries no props, so the tab paints
  // instantly instead of pulling every game's book (the fully-nested slate is ~1.4MB / 15k props).
  const [gameProps, setGameProps] = useState<Record<number, { loading: boolean; players: SlateGame['players'] }>>({})

  const openGame = (gid: number) => {
    const opening = expandedGame !== gid
    setExpandedGame(opening ? gid : null)
    if (!opening || gid in gameProps) return
    setGameProps(prev => ({ ...prev, [gid]: { loading: true, players: [] } }))
    fetch(`/api/props/slate?game_id=${gid}`)
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((games: SlateGame[]) => {
        const players = Array.isArray(games) && games[0] ? games[0].players : []
        setGameProps(cur => ({ ...cur, [gid]: { loading: false, players } }))
      })
      .catch(() => setGameProps(cur => ({ ...cur, [gid]: { loading: false, players: [] } })))
  }

  useEffect(() => {
    const controller = new AbortController()
    const params = new URLSearchParams()
    params.set('summary', '1')
    if (league !== 'All') params.set('league', league)

    setLoading(true)
    setError(null)
    setExpandedGame(null)
    setGameProps({})
    fetch(`/api/props/slate?${params}`, { signal: controller.signal })
      .then(response => {
        if (!response.ok) throw new Error(`Slate request failed (${response.status})`)
        return response.json()
      })
      .then(data => {
        if (!Array.isArray(data)) throw new Error('Slate response was not a list')
        setSlate(data)
        setLoading(false)
      })
      .catch(err => {
        if (err.name === 'AbortError') return
        setSlate([])
        setError('The game slate could not be loaded. Try again in a moment.')
        setLoading(false)
      })

    return () => controller.abort()
  }, [league])

  // Group by the same browser-local day shown next to each game time. The API's
  // `date` is a UTC calendar date, so it would put an evening local game under
  // the following day.
  const groupDateForGame = (game: SlateGame) => {
    if (!game.start_time) return game.date
    const startTime = new Date(game.start_time)
    if (Number.isNaN(startTime.getTime())) return game.date
    const parts = new Intl.DateTimeFormat('en-CA', {
      year: 'numeric', month: '2-digit', day: '2-digit',
    }).formatToParts(startTime)
    const year = parts.find(part => part.type === 'year')?.value
    const month = parts.find(part => part.type === 'month')?.value
    const day = parts.find(part => part.type === 'day')?.value
    return year && month && day ? `${year}-${month}-${day}` : game.date
  }

  // Day above league, with each label rendered once rather than repeated on
  // every game card.
  const leagueRank = (leagueKey: string) => {
    const rank = LEAGUES.indexOf(leagueKey as League)
    return rank === -1 ? LEAGUES.length : rank
  }
  const dateGroups = new Map<string, Map<string, SlateGame[]>>()
  for (const game of slate) {
    const gameDate = groupDateForGame(game)
    const leagueKey = String(game.league || '').toLowerCase()
    const byLeague = dateGroups.get(gameDate) || new Map<string, SlateGame[]>()
    byLeague.set(leagueKey, [...(byLeague.get(leagueKey) || []), game])
    dateGroups.set(gameDate, byLeague)
  }
  const groups = Array.from(dateGroups, ([gameDate, byLeague]) => ({
    gameDate,
    leagueGroups: Array.from(byLeague, ([leagueKey, games]) => ({ leagueKey, games }))
      .sort((a, b) => leagueRank(a.leagueKey) - leagueRank(b.leagueKey) || a.leagueKey.localeCompare(b.leagueKey)),
  })).sort((a, b) => a.gameDate.localeCompare(b.gameDate))

  const formatDate = (gameDate: string) =>
    new Date(gameDate + 'T12:00:00').toLocaleDateString(undefined, {
      weekday: 'short', month: 'short', day: 'numeric',
    })

  return (
    <div className="space-y-5" aria-label="Upcoming game slate">
      {error && (
        <div className="rounded-lg border border-red-500/40 bg-red-950/40 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}
      {loading ? <Skeleton lines={5} /> : groups.length === 0 ? (
        <div className="py-16 text-center text-sm text-zinc-500">
          No upcoming games with props. Check back closer to game time.
        </div>
      ) : (
        groups.map(({ gameDate, leagueGroups }) => (
          <section key={gameDate} data-slate-date={gameDate} className="space-y-3">
            <div className="flex min-w-0 items-center gap-2">
              <h2 className="shrink-0 text-sm font-bold uppercase tracking-wide text-zinc-300">
                {formatDate(gameDate)}
              </h2>
            </div>

            {leagueGroups.map(({ leagueKey, games }) => {
              const propCount = games.reduce((total, game) => total + game.prop_count, 0)
              return (
                <section key={leagueKey} data-slate-league={leagueKey} className="space-y-4">
                  <div className="flex min-w-0 items-center gap-2">
                    <h3 className="text-base font-extrabold uppercase tracking-wide text-zinc-100">
                      {leagueKey.toUpperCase()}
                    </h3>
                    <span className="truncate text-xs tabular-nums text-zinc-600">
                      {games.length} game{games.length === 1 ? '' : 's'} · {propCount} props
                    </span>
                  </div>
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    {games.map(game => {
                      const expanded = expandedGame === game.game_id
                      return (
                        <article key={game.game_id} data-slate-game className="min-w-0 overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900">
                          <button
                            type="button"
                            onClick={() => openGame(game.game_id)}
                            aria-expanded={expanded}
                            className="flex w-full min-w-0 items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-zinc-800/50"
                          >
                            <span className="min-w-0">
                              <span className="block break-words text-sm font-semibold">{game.away} @ {game.home}</span>
                              <span className="mt-0.5 block text-xs tabular-nums text-zinc-500">
                                {game.start_time
                                  ? `${new Date(game.start_time).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })} · `
                                  : ''}
                                {game.prop_count} props
                              </span>
                            </span>
                            <span aria-hidden="true" className="shrink-0 text-lg text-zinc-500">{expanded ? '▾' : '▸'}</span>
                          </button>

                          {expanded && (() => {
                            const gp = gameProps[game.game_id]
                            if (!gp || gp.loading) {
                              return <div data-slate-props className="border-t border-zinc-800 px-4 py-3"><Skeleton lines={3} /></div>
                            }
                            if (!gp.players.length) {
                              return <div data-slate-props className="border-t border-zinc-800 px-4 py-3 text-xs text-zinc-500">No props for this game yet.</div>
                            }
                            return (
                              <div data-slate-props className="max-h-96 space-y-4 overflow-y-auto border-t border-zinc-800 px-4 py-3">
                                {gp.players.map(player => (
                                  <div key={`${player.team}-${player.name}`}>
                                    <div className="mb-1.5 flex flex-wrap items-baseline gap-x-1.5 text-xs">
                                      <span className="font-bold text-zinc-300">{player.name}</span>
                                      <span className="text-zinc-600">{player.team}</span>
                                    </div>
                                    <div className="flex flex-wrap gap-1.5">
                                      {Array.from(new Map(player.props.map(prop => [
                                        `${prop.market}-${prop.side}-${prop.line}-${prop.source}`, prop,
                                      ] as const)).values()).map((prop, index) => (
                                        <span
                                          key={`${prop.market}-${prop.side}-${prop.line}-${index}`}
                                          className={`inline-flex max-w-full items-center gap-1 break-all rounded px-2 py-1 text-[11px] font-mono tabular-nums ${prop.side === 'over' || prop.side === 'yes' ? 'bg-emerald-900/30 text-emerald-300' : 'bg-red-900/30 text-red-300'}`}
                                        >
                                          {prop.market.replace(/_/g, ' ')} {prop.line} {prop.side.toUpperCase()}
                                        </span>
                                      ))}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            )
                          })()}
                        </article>
                      )
                    })}
                  </div>
                </section>
              )
            })}
          </section>
        ))
      )}
    </div>
  )
}

// ── Tab: Performance (player stats dashboard) ─────────────
function PerformanceTab({ league, query, setQuery, selectedPlayer, setSelectedPlayer }: {
  league: League; query: string; setQuery: (q: string) => void
  selectedPlayer: Player | null; setSelectedPlayer: (p: Player | null) => void
}) {
  const [players, setPlayers] = useState<Player[]>([])
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
                    {stats.stats.completions_pg != null && <StatBox label="Comp/G" value={stats.stats.completions_pg} />}
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
interface Matchup { opponent: string; games: number; avg: Record<string, number> }

function MatchupsTab({ query, setQuery, player, setPlayer }: {
  query: string; setQuery: (q: string) => void
  player: Player | null; setPlayer: (p: Player | null) => void
}) {
  const [players, setPlayers] = useState<Player[]>([])
  const [data, setData] = useState<{ season: number; matchups: Matchup[] } | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (query.length < 2) { setPlayers([]); return }
    const t = setTimeout(async () => {
      try { const r = await fetch(`/api/players/search?q=${encodeURIComponent(query)}`); setPlayers(await r.json()) } catch {}
    }, 250)
    return () => clearTimeout(t)
  }, [query])

  useEffect(() => {
    if (!player) return
    setLoading(true); setData(null)
    fetch(`/api/player/${player.id}/matchups`)
      .then(r => r.json()).then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [player])

  const order = ['PTS', 'REB', 'AST', 'PRA', '3PM', 'pass_yds', 'rush_yds', 'rec_yds', 'fpts_ppr',
    'points', 'goals', 'assists', 'shots', 'H', 'TB', 'HR', 'K', 'outs', 'hits_allowed',
    // UFC's game logs store ESPN's full 43-field raw stat blob, not a curated list —
    // without these prioritized first, the alphabetically-first fields (advanceToBack,
    // advanceToHalfGuard, ...) would win the slice(0, 6) below instead of anything meaningful.
    'sigStrikesLanded', 'sigStrikesAttempted', 'totalStrikesLanded', 'totalStrikesAttempted',
    'takedownsLanded', 'takedownsAttempted', 'knockDowns', 'submissions']
  const statKeys = data?.matchups?.length
    ? Object.keys(data.matchups[0].avg).sort((a, b) => {
        const ia = order.indexOf(a), ib = order.indexOf(b)
        return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib) || a.localeCompare(b)
      }).slice(0, 6)
    : []

  return (
    <div className="space-y-4">
      <PlayerSearch query={query} setQuery={setQuery} players={players} onSelect={p => { setPlayer(p); setQuery(p.name); setPlayers([]) }} />
      {!player ? (
        <div className="text-center py-16 space-y-2"><div className="text-4xl">🏟️</div>
          <p className="text-zinc-500 text-sm max-w-md mx-auto">Search a player to see how they perform split by opponent this season.</p></div>
      ) : loading ? <Skeleton lines={6} /> : !data?.matchups?.length ? (
        <div className="text-center py-12 text-zinc-500 text-sm">No opponent splits yet — needs game logs with opponents.</div>
      ) : (
        <div className="space-y-3">
          {/* Player header with league badge */}
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-bold">{player.name}</h2>
            <span className="text-xs font-medium px-2 py-0.5 rounded bg-zinc-800 text-zinc-400">{player.team}</span>
            <span className="text-xs font-medium px-2 py-0.5 rounded bg-emerald-900/50 text-emerald-400 border border-emerald-800/50">{player.league.toUpperCase()}</span>
            <span className="text-xs text-zinc-500 ml-auto">{data.matchups.length} opponents · {data.season}</span>
          </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-zinc-800 text-zinc-500 text-[11px] uppercase tracking-wider">
              <th className="text-left px-4 py-3 font-medium">Opp</th>
              <th className="text-right px-3 py-3 font-medium">GP</th>
              {statKeys.map(k => <th key={k} className="text-right px-3 py-3 font-medium">{k.replace(/_/g, ' ')}</th>)}
            </tr></thead>
            <tbody>
              {data.matchups.map((m, i) => (
                <tr key={i} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                  <td className="px-4 py-2.5 font-medium">{m.opponent}</td>
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums text-zinc-400">{m.games}</td>
                  {statKeys.map(k => <td key={k} className="px-3 py-2.5 text-right font-mono tabular-nums">{m.avg[k] ?? '—'}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        </div>
      )}
    </div>
  )
}

// ── Tab: Model (projections from per-game logs) ────────────
interface Projection {
  n: number; projection: number; median: number; floor: number; ceiling: number
  l5_avg: number; season_avg: number; trend: string; last5: number[]
  prob_over?: { line: number; n: number; over: number; p_over: number; push: number }
}
// headline markets first, then the rest alphabetically
const STAT_ORDER = ['pass_yds', 'rush_yds', 'rec_yds', 'pass_td', 'rush_td', 'rec_td', 'rec', 'targets',
  'PTS', 'REB', 'AST', 'PRA', '3PM', 'STL', 'BLK',
  'points', 'goals', 'assists', 'shots',
  'H', 'TB', 'HR', 'K', 'BB',
  'fpts_ppr', 'fpts']
const TREND_ICON: Record<string, string> = { up: '↑', down: '↓', flat: '→' }

function ModelTab({ league, query, setQuery, player, setPlayer }: {
  league: League; query: string; setQuery: (q: string) => void
  player: Player | null; setPlayer: (p: Player | null) => void
}) {
  const [players, setPlayers] = useState<Player[]>([])
  const [data, setData] = useState<{ season: number; games: number; projections: Record<string, Projection> } | null>(null)
  const [loading, setLoading] = useState(false)
  const [statKey, setStatKey] = useState<string>('')
  const [line, setLine] = useState<string>('')
  const [probe, setProbe] = useState<Projection['prob_over'] | null>(null)

  useEffect(() => {
    if (query.length < 2) { setPlayers([]); return }
    const t = setTimeout(async () => {
      try { const r = await fetch(`/api/players/search?q=${encodeURIComponent(query)}`); setPlayers(await r.json()) } catch {}
    }, 250)
    return () => clearTimeout(t)
  }, [query])

  useEffect(() => {
    if (!player) return
    setLoading(true); setData(null); setProbe(null); setStatKey(''); setLine('')
    fetch(`/api/projections/player/${player.id}`)
      .then(r => r.json()).then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [player])

  // UFC game logs store ESPN's full raw stat blob (43 fields — positional/target
  // breakdowns like advanceToBack, posBreakdownClinch, slamRate — not a curated
  // prop-market list like other leagues). Restrict to the headline stats someone
  // would actually want to check a line against, not the full raw dump.
  const _UFC_MODEL_STATS = new Set([
    'knockDowns', 'totalStrikesLanded', 'totalStrikesAttempted',
    'sigStrikesLanded', 'sigStrikesAttempted',
    'takedownsLanded', 'takedownsAttempted', 'submissions', 'timeInControl',
  ])
  const keys = data ? Object.keys(data.projections)
    .filter(k => player?.league !== 'ufc' || _UFC_MODEL_STATS.has(k))
    .sort((a, b) => {
      const ia = STAT_ORDER.indexOf(a), ib = STAT_ORDER.indexOf(b)
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib) || a.localeCompare(b)
    }) : []

  const checkLine = () => {
    if (!player || !statKey || line === '') return
    fetch(`/api/projections/player/${player.id}?market=${statKey}&line=${line}`)
      .then(r => r.json()).then(d => setProbe(d.projections?.[statKey]?.prob_over || null))
      .catch(() => setProbe(null))
  }

  return (
    <div className="space-y-4">
      <PlayerSearch query={query} setQuery={setQuery} players={players} onSelect={p => { setPlayer(p); setQuery(p.name); setPlayers([]) }} />

      {!player ? (
        <div className="text-center py-16 space-y-2">
          <div className="text-4xl">🧠</div>
          <p className="text-zinc-500 text-sm max-w-md mx-auto">Search a player for projections built from their per-game logs — recency-weighted expected value with floor / median / ceiling, plus hit rate vs any line.</p>
        </div>
      ) : loading ? <Skeleton lines={6} /> : !data || keys.length === 0 ? (
        <div className="text-center py-12 text-zinc-500 text-sm">No game logs for {player.name} yet — projections need per-game history.</div>
      ) : (
        <div className="space-y-5">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-bold">{player.name}</h2>
            <span className="text-sm text-zinc-500">{player.team} · {player.league.toUpperCase()} · {data.season} · {data.games} games</span>
          </div>

          {/* Line checker */}
          <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-3 flex flex-wrap items-end gap-2">
            <div className="text-xs text-zinc-500 w-full mb-0.5">Check a line — hit rate from this player&apos;s own game distribution</div>
            <Select value={statKey || keys[0]} onChange={setStatKey} options={keys.map(k => ({ v: k, label: k.replace(/_/g, ' ') }))} />
            <input type="number" step="0.5" value={line} onChange={e => setLine(e.target.value)} placeholder="line"
              className="w-24 px-3 py-2.5 rounded-xl border border-zinc-800 bg-zinc-900 text-zinc-200 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500" />
            <button onClick={checkLine} className="px-4 py-2.5 rounded-xl bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-500">Check</button>
            {probe && (
              <span className="text-sm ml-1">
                <span className="font-bold text-emerald-300">{(probe.p_over * 100).toFixed(0)}% over</span>
                <span className="text-zinc-500"> ({probe.over}/{probe.n} games)</span>
              </span>
            )}
          </div>

          {/* Projections table */}
          <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-800 text-zinc-500 text-[11px] uppercase tracking-wider">
                  <th className="text-left px-4 py-3 font-medium">Stat</th>
                  <th className="text-right px-3 py-3 font-medium">Proj</th>
                  <th className="text-right px-3 py-3 font-medium">Median</th>
                  <th className="text-right px-3 py-3 font-medium">Floor–Ceiling</th>
                  <th className="text-right px-3 py-3 font-medium">L5</th>
                  <th className="text-right px-3 py-3 font-medium">Season</th>
                  <th className="text-center px-3 py-3 font-medium">Trend</th>
                </tr>
              </thead>
              <tbody>
                {keys.map(k => {
                  const p = data.projections[k]
                  return (
                    <tr key={k} className="border-b border-zinc-800/50 hover:bg-zinc-800/30 transition-colors">
                      <td className="px-4 py-2.5 font-medium">{k.replace(/_/g, ' ')}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums font-bold text-emerald-300">{p.projection}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-zinc-400">{p.median}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-zinc-500">{p.floor}–{p.ceiling}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{p.l5_avg}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-zinc-400">{p.season_avg}</td>
                      <td className="px-3 py-2.5 text-center text-lg">{TREND_ICON[p.trend] || '→'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-zinc-600">Proj = recency-weighted expected value (L5·0.5 + L10·0.3 + season·0.2). Median is the typical game; means skew toward ceiling outings. Marcel-grade baseline — regression to mean, opportunity share, and matchup adjustment are upcoming layers.</p>
        </div>
      )}
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
  const [league, setLeague] = useState<League>('All')

  // Shared across Performance/Matchups/Model so switching tabs keeps the same
  // player instead of making you re-search each time.
  const [sharedQuery, setSharedQuery] = useState('')
  const [sharedPlayer, setSharedPlayer] = useState<Player | null>(null)

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

  // Land each league on today when it has props, otherwise its nearest upcoming slate. Re-run when
  // the league pill changes so a future WC/UFC slate is not hidden behind another league's date.
  // Explicit ?date= deep links always win.
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get('date')) return
    const params = new URLSearchParams()
    // Date discovery only needs game summaries. Pulling every nested prop here
    // duplicated the full slate payload before either tab rendered it.
    params.set('summary', '1')
    if (league !== 'All') params.set('league', league)
    fetch(`/api/props/slate?${params}`)
      .then(r => r.json())
      .then((games: SlateGame[]) => {
        const dates = Array.from(new Set(games.map(g => g.date))).sort()
        if (dates.length) setDate(dates.includes(today) ? today : dates[0])
      })
      .catch(() => {})
  }, [league, today])

  const showDateNav = tab === 'props'

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
        <div className="flex gap-0 flex-wrap border-b border-zinc-800 -mx-4 px-4">
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
        {tab === 'slate' && <SlateTab league={league} />}
        {tab === 'props' && <MarketSlateBoard league={league} date={date} />}
        {tab === 'performance' && <PerformanceTab league={league} query={sharedQuery} setQuery={setSharedQuery} selectedPlayer={sharedPlayer} setSelectedPlayer={setSharedPlayer} />}
        {tab === 'matchups' && <MatchupsTab query={sharedQuery} setQuery={setSharedQuery} player={sharedPlayer} setPlayer={setSharedPlayer} />}
        {tab === 'model' && <ModelTab league={league} query={sharedQuery} setQuery={setSharedQuery} player={sharedPlayer} setPlayer={setSharedPlayer} />}
      </div>
    </>
  )
}
