import { useState, useEffect, useCallback } from 'react'
import Head from 'next/head'

interface Player {
  id: number
  name: string
  team: string
  league: string
}

interface Prop {
  id: number
  market: string
  line: number
  side: string
  source: string
  captured_at: string
  player_name: string
  player_team: string
  league: string
  actual_value: number | null
  hit: boolean | null
  settled_at: string | null
}

interface StatRow {
  market: string
  side: string
  total: number
  hits: number
  hit_rate: number
  avg_line: number | null
  avg_actual: number | null
}

const LEAGUES = ['All', 'nba', 'nfl', 'mlb', 'nhl']
const MARKETS = ['All', 'points', 'rebounds', 'assists', 'threes', 'passing_yards', 'rushing_yards', 'receiving_yards', 'strikeouts', 'hits', 'home_runs']

function SkeletonRow() {
  return (
    <div className="grid grid-cols-7 gap-3 px-4 py-3 animate-pulse">
      {Array.from({ length: 7 }).map((_, i) => (
        <div key={i} className="h-4 bg-zinc-800 rounded" />
      ))}
    </div>
  )
}

export default function PropsPage() {
  const [query, setQuery] = useState('')
  const [players, setPlayers] = useState<Player[]>([])
  const [selectedPlayer, setSelectedPlayer] = useState<Player | null>(null)
  const [props, setProps] = useState<Prop[]>([])
  const [stats, setStats] = useState<StatRow[]>([])
  const [league, setLeague] = useState('All')
  const [market, setMarket] = useState('All')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<'props' | 'stats'>('props')

  // Search players
  useEffect(() => {
    if (query.length < 2) { setPlayers([]); return }
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/players/search?q=${encodeURIComponent(query)}`)
        const data = await res.json()
        setPlayers(data)
      } catch { /* silent */ }
    }, 250)
    return () => clearTimeout(timer)
  }, [query])

  // Load props for selected player
  const loadProps = useCallback(async () => {
    if (!selectedPlayer) return
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      params.set('player', selectedPlayer.name)
      if (league !== 'All') params.set('league', league)
      if (market !== 'All') params.set('market', market)
      params.set('limit', '100')
      const res = await fetch(`/api/props?${params}`)
      const data = await res.json()
      setProps(data)
    } catch {
      setError('Failed to load props.')
    } finally {
      setLoading(false)
    }
  }, [selectedPlayer, league, market])

  useEffect(() => { loadProps() }, [loadProps])

  // Load aggregate stats
  useEffect(() => {
    const loadStats = async () => {
      try {
        const params = new URLSearchParams()
        if (league !== 'All') params.set('league', league)
        if (market !== 'All') params.set('market', market)
        params.set('window', '30')
        const res = await fetch(`/api/props/stats?${params}`)
        const data = await res.json()
        setStats(data)
      } catch { /* silent */ }
    }
    loadStats()
  }, [league, market])

  const hitRate = (() => {
    const settled = props.filter(p => p.hit !== null)
    if (settled.length === 0) return null
    return Math.round((settled.filter(p => p.hit).length / settled.length) * 100)
  })()

  return (
    <>
      <Head>
        <title>Prop Data — Legendary Picks</title>
        <meta name="description" content="Player prop outcomes, hit rates, and trends across leagues" />
      </Head>
      <div className="space-y-6">
        <h1 className="text-3xl font-extrabold tracking-tight">Prop Data</h1>

        {/* Search */}
        <div className="relative">
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search a player…"
            className="w-full max-w-md px-4 py-3 rounded-xl border border-zinc-800 bg-zinc-900 text-zinc-200 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500"
          />
          {players.length > 0 && (
            <div className="absolute top-full mt-1 w-full max-w-md rounded-xl border border-zinc-700 bg-zinc-900 shadow-xl z-50 overflow-hidden">
              {players.map(p => (
                <button
                  key={p.id}
                  onClick={() => { setSelectedPlayer(p); setQuery(p.name); setPlayers([]) }}
                  className="w-full text-left px-4 py-3 hover:bg-zinc-800 transition-colors flex justify-between items-center"
                >
                  <span className="font-medium">{p.name}</span>
                  <span className="text-xs text-zinc-500">{p.team} · {p.league.toUpperCase()}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Filters */}
        <div className="flex flex-wrap gap-2">
          <select
            value={league}
            onChange={e => setLeague(e.target.value)}
            className="px-3 py-2 rounded-lg border border-zinc-800 bg-zinc-900 text-zinc-200 text-sm"
          >
            {LEAGUES.map(l => <option key={l} value={l}>{l === 'All' ? 'All Leagues' : l.toUpperCase()}</option>)}
          </select>
          <select
            value={market}
            onChange={e => setMarket(e.target.value)}
            className="px-3 py-2 rounded-lg border border-zinc-800 bg-zinc-900 text-zinc-200 text-sm"
          >
            {MARKETS.map(m => <option key={m} value={m}>{m === 'All' ? 'All Markets' : m.replace(/_/g, ' ')}</option>)}
          </select>
          <div className="flex rounded-lg border border-zinc-800 overflow-hidden">
            <button
              onClick={() => setTab('props')}
              className={`px-4 py-2 text-sm font-medium transition-colors ${tab === 'props' ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:text-zinc-200'}`}
            >
              Props
            </button>
            <button
              onClick={() => setTab('stats')}
              className={`px-4 py-2 text-sm font-medium transition-colors ${tab === 'stats' ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:text-zinc-200'}`}
            >
              Stats
            </button>
          </div>
        </div>

        {error && (
          <div className="rounded-lg border border-red-500/40 bg-red-950/40 text-red-200 px-4 py-3">{error}</div>
        )}

        {/* Props tab */}
        {tab === 'props' && (
          <>
            {selectedPlayer && (
              <div className="flex items-center gap-3">
                <h2 className="text-xl font-bold">{selectedPlayer.name}</h2>
                <span className="text-xs text-zinc-500">{selectedPlayer.team} · {selectedPlayer.league.toUpperCase()}</span>
                {hitRate !== null && (
                  <span className={`text-sm font-mono px-2 py-0.5 rounded ${hitRate >= 50 ? 'bg-emerald-900/40 text-emerald-300' : 'bg-red-900/40 text-red-300'}`}>
                    {hitRate}% hit rate ({props.filter(p => p.hit !== null).length} settled)
                  </span>
                )}
              </div>
            )}

            {loading ? (
              <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-hidden">
                <SkeletonRow />
                <SkeletonRow />
                <SkeletonRow />
                <SkeletonRow />
              </div>
            ) : !selectedPlayer ? (
              <div className="text-center py-16 text-zinc-500">
                Search for a player above to see their prop history.
              </div>
            ) : props.length === 0 ? (
              <div className="text-center py-16 text-zinc-500">
                No props found for {selectedPlayer.name}.
              </div>
            ) : (
              <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-zinc-800 text-zinc-500 text-xs uppercase tracking-wider">
                      <th className="text-left px-4 py-3 font-medium">Date</th>
                      <th className="text-left px-4 py-3 font-medium">Market</th>
                      <th className="text-right px-4 py-3 font-medium">Line</th>
                      <th className="text-center px-4 py-3 font-medium">Side</th>
                      <th className="text-right px-4 py-3 font-medium">Actual</th>
                      <th className="text-center px-4 py-3 font-medium">Hit?</th>
                      <th className="text-left px-4 py-3 font-medium">Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {props.map(p => (
                      <tr key={p.id} className="border-b border-zinc-800/50 hover:bg-zinc-800/30 transition-colors">
                        <td className="px-4 py-3 text-zinc-400 whitespace-nowrap">
                          {new Date(p.captured_at).toLocaleDateString()}
                        </td>
                        <td className="px-4 py-3 font-medium">{p.market.replace(/_/g, ' ')}</td>
                        <td className="px-4 py-3 text-right font-mono">{p.line}</td>
                        <td className="px-4 py-3 text-center">
                          <span className={`text-xs font-semibold px-2 py-0.5 rounded ${p.side === 'over' ? 'bg-emerald-900/30 text-emerald-300' : 'bg-red-900/30 text-red-300'}`}>
                            {p.side.toUpperCase()}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right font-mono">{p.actual_value ?? '—'}</td>
                        <td className="px-4 py-3 text-center">
                          {p.hit === null ? (
                            <span className="text-zinc-600">—</span>
                          ) : p.hit ? (
                            <span className="text-emerald-400">✅</span>
                          ) : (
                            <span className="text-red-400">❌</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-zinc-500 text-xs">{p.source}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        {/* Stats tab */}
        {tab === 'stats' && (
          <>
            <h2 className="text-xl font-bold">Aggregate Hit Rates</h2>
            {stats.length === 0 ? (
              <div className="text-center py-16 text-zinc-500">No settled props in the last 30 days.</div>
            ) : (
              <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-zinc-800 text-zinc-500 text-xs uppercase tracking-wider">
                      <th className="text-left px-4 py-3 font-medium">Market</th>
                      <th className="text-center px-4 py-3 font-medium">Side</th>
                      <th className="text-right px-4 py-3 font-medium">Total</th>
                      <th className="text-right px-4 py-3 font-medium">Hits</th>
                      <th className="text-right px-4 py-3 font-medium">Hit Rate</th>
                      <th className="text-right px-4 py-3 font-medium">Avg Line</th>
                      <th className="text-right px-4 py-3 font-medium">Avg Actual</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.map((s, i) => (
                      <tr key={i} className="border-b border-zinc-800/50">
                        <td className="px-4 py-3 font-medium">{s.market.replace(/_/g, ' ')}</td>
                        <td className="px-4 py-3 text-center">
                          <span className={`text-xs font-semibold px-2 py-0.5 rounded ${s.side === 'over' ? 'bg-emerald-900/30 text-emerald-300' : 'bg-red-900/30 text-red-300'}`}>
                            {s.side.toUpperCase()}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right font-mono">{s.total}</td>
                        <td className="px-4 py-3 text-right font-mono">{s.hits}</td>
                        <td className="px-4 py-3 text-right font-mono">{(s.hit_rate * 100).toFixed(1)}%</td>
                        <td className="px-4 py-3 text-right font-mono">{s.avg_line ?? '—'}</td>
                        <td className="px-4 py-3 text-right font-mono">{s.avg_actual ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </>
  )
}
