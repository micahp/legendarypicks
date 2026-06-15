import { useState, useEffect, useCallback } from 'react'
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
const TABS: { key: Tab; label: string }[] = [
  { key: 'lines', label: 'Lines' },
  { key: 'slate', label: 'Slate' },
  { key: 'performance', label: 'Performance' },
  { key: 'matchups', label: 'Matchups' },
  { key: 'model', label: 'Model' },
]
const LEAGUES = ['All', 'nba', 'mlb', 'nfl', 'nhl']
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

// ── Tab: Lines ───────────────────────────────────────────
function LinesTab() {
  const [query, setQuery] = useState('')
  const [players, setPlayers] = useState<Player[]>([])
  const [props, setProps] = useState<Prop[]>([])
  const [league, setLeague] = useState('All')
  const [market, setMarket] = useState('All')
  const [book, setBook] = useState('All')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (query.length < 2) { setPlayers([]); return }
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`/api/players/search?q=${encodeURIComponent(query)}`)
        setPlayers(await r.json())
      } catch { /* */ }
    }, 250)
    return () => clearTimeout(t)
  }, [query])

  useEffect(() => {
    setLoading(true); setError(null)
    const params = new URLSearchParams({ limit: '100' })
    if (query) params.set('player', query)
    if (league !== 'All') params.set('league', league)
    if (market !== 'All') params.set('market', market)
    fetch(`/api/props?${params}`)
      .then(r => r.json())
      .then(d => { setProps(d); setLoading(false) })
      .catch(() => { setError('Failed to load props.'); setLoading(false) })
  }, [query, league, market])

  const filtered = book === 'All' ? props : props.filter(p => p.source === book)

  return (
    <div className="space-y-4">
      {/* Search + filters */}
      <div className="flex flex-wrap gap-2 items-center">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <input type="text" value={query} onChange={e => setQuery(e.target.value)}
            placeholder="Search player…"
            className="w-full px-4 py-2.5 rounded-xl border border-zinc-800 bg-zinc-900 text-zinc-200 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500 text-sm" />
          {players.length > 0 && (
            <div className="absolute top-full mt-1 w-full rounded-xl border border-zinc-700 bg-zinc-900 shadow-xl z-50 overflow-hidden">
              {players.map(p => (
                <button key={p.id} onClick={() => { setQuery(p.name); setPlayers([]) }}
                  className="w-full text-left px-4 py-2.5 hover:bg-zinc-800 flex justify-between items-center text-sm">
                  <span className="font-medium">{p.name}</span>
                  <span className="text-xs text-zinc-500">{p.team} · {p.league.toUpperCase()}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <Select value={league} onChange={setLeague} options={LEAGUES.map(l => ({ v: l, label: l === 'All' ? 'All Leagues' : l.toUpperCase() }))} />
        <Select value={market} onChange={setMarket} options={MARKETS.map(m => ({ v: m, label: m === 'All' ? 'All Markets' : m.replace(/_/g, ' ') }))} />
        <Select value={book} onChange={setBook} options={BOOKS.map(b => ({ v: b, label: b === 'All' ? 'All Books' : b }))} />
      </div>

      {error && <div className="rounded-lg border border-red-500/40 bg-red-950/40 text-red-200 px-4 py-3 text-sm">{error}</div>}

      {/* Table */}
      {loading ? <Skeleton lines={6} /> : filtered.length === 0 ? (
        <div className="text-center py-16 text-zinc-500 text-sm">No props found. Try a different filter or league.</div>
      ) : (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-x-auto">
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
                  <td className="px-4 py-2.5">
                    <span className="font-medium">{p.player_name}</span>
                    <span className="text-zinc-500 text-xs ml-1.5">{p.player_team}</span>
                  </td>
                  <td className="px-4 py-2.5 text-zinc-300">{p.market.replace(/_/g, ' ')}</td>
                  <td className="px-4 py-2.5 text-right font-mono tabular-nums">{p.line}</td>
                  <td className="px-4 py-2.5 text-center">
                    <span className={`text-[11px] font-bold px-2 py-0.5 rounded ${p.side === 'over' ? 'bg-emerald-900/30 text-emerald-300' : 'bg-red-900/30 text-red-300'}`}>
                      {p.side.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono tabular-nums text-zinc-400">{p.actual_value ?? '—'}</td>
                  <td className="px-4 py-2.5 text-center"><HitBadge hit={p.hit} /></td>
                  <td className="px-4 py-2.5 text-zinc-500 text-xs capitalize">{p.source}</td>
                  <td className="px-4 py-2.5 text-zinc-500 text-xs hidden md:table-cell whitespace-nowrap">
                    {p.captured_at ? new Date(p.captured_at).toLocaleDateString() : '—'}
                  </td>
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
function SlateTab() {
  const [league, setLeague] = useState('mlb')
  const [slate, setSlate] = useState<SlateGame[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedGame, setExpandedGame] = useState<number | null>(null)

  useEffect(() => {
    setLoading(true)
    const params = new URLSearchParams()
    if (league !== 'All') params.set('league', league)
    fetch(`/api/props/slate?${params}`)
      .then(r => r.json())
      .then(d => { setSlate(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [league])

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        {['mlb', 'nba', 'nfl', 'nhl'].map(l => (
          <button key={l} onClick={() => setLeague(l)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${league === l ? 'bg-emerald-600 text-white' : 'bg-zinc-900 border border-zinc-800 text-zinc-400 hover:text-zinc-200'}`}>
            {l.toUpperCase()}
          </button>
        ))}
      </div>

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
                      <div className="text-xs font-bold text-zinc-400 mb-1.5 flex items-center gap-1.5">
                        {p.name}
                        <span className="text-zinc-600 font-normal">{p.team}</span>
                      </div>
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

// ── Tab: Performance ───────────────────────────────────────
function PerformanceTab() {
  const [query, setQuery] = useState('')
  const [players, setPlayers] = useState<Player[]>([])
  const [selectedPlayer, setSelectedPlayer] = useState<Player | null>(null)
  const [perf, setPerf] = useState<PerfRow[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (query.length < 2) { setPlayers([]); return }
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`/api/players/search?q=${encodeURIComponent(query)}`)
        setPlayers(await r.json())
      } catch { /* */ }
    }, 250)
    return () => clearTimeout(t)
  }, [query])

  useEffect(() => {
    if (!selectedPlayer) return
    setLoading(true)
    fetch(`/api/props/player/${selectedPlayer.id}/performance`)
      .then(r => r.json())
      .then(d => { setPerf(d.performance || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [selectedPlayer])

  return (
    <div className="space-y-4">
      <div className="relative max-w-sm">
        <input type="text" value={query} onChange={e => setQuery(e.target.value)}
          placeholder="Search player…"
          className="w-full px-4 py-2.5 rounded-xl border border-zinc-800 bg-zinc-900 text-zinc-200 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500 text-sm" />
        {players.length > 0 && (
          <div className="absolute top-full mt-1 w-full rounded-xl border border-zinc-700 bg-zinc-900 shadow-xl z-50 overflow-hidden">
            {players.map(p => (
              <button key={p.id} onClick={() => { setSelectedPlayer(p); setQuery(p.name); setPlayers([]) }}
                className="w-full text-left px-4 py-2.5 hover:bg-zinc-800 flex justify-between items-center text-sm">
                <span className="font-medium">{p.name}</span>
                <span className="text-xs text-zinc-500">{p.team}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {selectedPlayer && (
        <h2 className="text-lg font-bold">{selectedPlayer.name} <span className="text-sm font-normal text-zinc-500">{selectedPlayer.team} · {selectedPlayer.league.toUpperCase()}</span></h2>
      )}

      {loading ? <Skeleton lines={5} /> : !selectedPlayer ? (
        <div className="text-center py-16 text-zinc-500 text-sm">Search for a player to see their hit-rate history with EMA weighting.</div>
      ) : perf.length === 0 ? (
        <div className="text-center py-16 text-zinc-500 text-sm">No settled props yet for {selectedPlayer.name}. Props are settled after games finish.</div>
      ) : (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-x-auto">
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
                  <td className="px-3 py-2.5 text-center">
                    <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${r.side === 'over' ? 'bg-emerald-900/30 text-emerald-300' : 'bg-red-900/30 text-red-300'}`}>
                      {r.side.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums">{r.total_settled}</td>
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums">{r.hit_rate_l5 !== null ? (r.hit_rate_l5 * 100).toFixed(0) + '%' : '—'}</td>
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums">{r.hit_rate_l10 !== null ? (r.hit_rate_l10 * 100).toFixed(0) + '%' : '—'}</td>
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums">{r.hit_rate_l20 !== null ? (r.hit_rate_l20 * 100).toFixed(0) + '%' : '—'}</td>
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums">{r.hit_rate_season !== null ? (r.hit_rate_season * 100).toFixed(0) + '%' : '—'}</td>
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums font-bold">
                    <span className={r.hit_rate_weighted >= 0.5 ? 'text-emerald-300' : 'text-red-300'}>
                      {(r.hit_rate_weighted * 100).toFixed(0)}%
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-center text-lg">{r.trend}</td>
                </tr>
              ))}
            </tbody>
          </table>
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
      <p className="text-zinc-500 text-sm max-w-md mx-auto">
        Player-vs-opponent history with defensive rankings and pace-adjusted splits. Coming after settlement data is live.
      </p>
    </div>
  )
}

// ── Tab: Model (placeholder) ───────────────────────────────
function ModelTab() {
  return (
    <div className="text-center py-16 space-y-3">
      <div className="text-5xl">🧠</div>
      <h3 className="text-lg font-bold text-zinc-300">Model Projections</h3>
      <p className="text-zinc-500 text-sm max-w-md mx-auto">
        LightGBM projections vs sportsbook lines with confidence scoring. Built on EMA performance + matchup context + pace-adjusted features.
      </p>
    </div>
  )
}

// ── Helpers ────────────────────────────────────────────────
function Select({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: { v: string; label: string }[] }) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)}
      className="px-3 py-2.5 rounded-xl border border-zinc-800 bg-zinc-900 text-zinc-200 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500">
      {options.map(o => <option key={o.v} value={o.v}>{o.label}</option>)}
    </select>
  )
}

// ── Page ───────────────────────────────────────────────────
export default function PropsPage() {
  const [tab, setTab] = useState<Tab>('lines')

  return (
    <>
      <Head>
        <title>Prop Data — Legendary Picks</title>
        <meta name="description" content="Player prop lines, hit rates, matchup analysis, and model projections" />
      </Head>

      <div className="space-y-6">
        <h1 className="text-3xl font-extrabold tracking-tight">Props</h1>

        {/* Tab bar */}
        <div className="flex gap-0 overflow-x-auto border-b border-zinc-800 -mx-4 px-4">
          {TABS.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px ${tab === t.key ? 'border-emerald-500 text-white' : 'border-transparent text-zinc-500 hover:text-zinc-300'}`}>
              {t.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {tab === 'lines' && <LinesTab />}
        {tab === 'slate' && <SlateTab />}
        {tab === 'performance' && <PerformanceTab />}
        {tab === 'matchups' && <MatchupsTab />}
        {tab === 'model' && <ModelTab />}
      </div>
    </>
  )
}
