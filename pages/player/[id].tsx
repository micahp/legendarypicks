import { useState, useEffect } from 'react'
import { useRouter } from 'next/router'
import Head from 'next/head'
import PropChart, { PropHistory } from '../../components/Props/PropChart'

interface Projection {
  n: number; projection: number; median: number; floor: number; ceiling: number
  l5_avg: number; season_avg: number; trend: string; last5: number[]
}
interface RecentGame { date: string | null; opponent: string | null; home: boolean | null; stats: Record<string, number> }
interface PropRow { market: string; side: string; line: number }
interface PlayerProfile {
  id: number; name: string; team: string; league: string; position: string | null
  season: number | null; games: number
  recent_games: RecentGame[]
  projections: Record<string, Projection>
  props: PropRow[]
}

const STAT_ORDER = ['pass_yds', 'rush_yds', 'rec_yds', 'PTS', 'REB', 'AST', 'PRA', '3PM',
  'points', 'goals', 'assists', 'shots', 'H', 'TB', 'HR', 'K', 'outs', 'hits_allowed', 'fpts_ppr']
const TREND: Record<string, string> = { up: '↑', down: '↓', flat: '→' }

export default function PlayerPage() {
  const router = useRouter()
  const { id } = router.query
  const [p, setP] = useState<PlayerProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [openProp, setOpenProp] = useState<string | null>(null)
  const [chart, setChart] = useState<PropHistory | null>(null)

  useEffect(() => {
    if (!id) return
    setLoading(true)
    fetch(`/api/player/${id}`).then(r => r.json()).then(d => { setP(d); setLoading(false) }).catch(() => setLoading(false))
  }, [id])

  const openChart = async (pr: PropRow) => {
    const key = `${pr.market}-${pr.side}`
    if (openProp === key) { setOpenProp(null); setChart(null); return }
    setOpenProp(key); setChart(null)
    try {
      const params = new URLSearchParams({ player_id: String(id), market: pr.market, line: String(pr.line), side: pr.side, league: p?.league || 'mlb' })
      const r = await fetch(`/api/props/history?${params}`)
      const d = await r.json()
      setChart(d.games?.length ? d : null)
    } catch { setChart(null) }
  }

  if (loading) return <div className="text-zinc-500 text-sm py-16 text-center">Loading…</div>
  if (!p || !p.name) return <div className="text-zinc-500 text-sm py-16 text-center">Player not found.</div>

  const projKeys = Object.keys(p.projections).sort((a, b) => {
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
                      <span className="font-mono tabular-nums text-zinc-300">{pr.side} {pr.line}</span>
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

        {/* Recent games */}
        {p.recent_games.length > 0 && (
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
