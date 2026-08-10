import { useState, useEffect } from 'react'
import PropChart, { PropHistory } from '../Props/PropChart'

// `result` is null until the prop settles. An unsettled prop is NOT a miss, and the two
// have to stay distinguishable all the way to the pixel — a page that renders them the
// same is claiming a loss we never took.
interface PropResult { actual: number | null; hit: boolean; settled_at: string }
interface GamePropPlayer { player_id: number; name: string; team: string; props: { market: string; side: string; line: number; result?: PropResult | null }[] }

export default function GameProps({ league, gameId, inTab = false }: { league: string; gameId: string; inTab?: boolean }) {
  const [players, setPlayers] = useState<GamePropPlayer[]>([])
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [chart, setChart] = useState<PropHistory | null>(null)
  const [edgeLabel, setEdgeLabel] = useState(false)
  const [settled, setSettled] = useState(0)
  const [hits, setHits] = useState(0)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setPlayers([])
    setEdgeLabel(false)
    setSettled(0)
    setHits(0)
    fetch(`/api/game/${league}/${gameId}/props`)
      .then(r => r.json()).then(d => {
        if (d.players?.length) {
          if (alive) {
            setPlayers(d.players)
            setSettled(d.settled_count || 0)
            setHits(d.hit_count || 0)
          }
          return
        }
        // NBA fallback: no Bovada props — show projected stat lines
        if (league === 'nba') {
          return fetch(`/api/game/${league}/${gameId}/edge`)
            .then(r => r.json()).then(e => {
              if (alive) { setPlayers(e.players || []); setEdgeLabel(true) }
            }).catch(() => {})
        }
      }).catch(() => {})
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [league, gameId])

  if (loading) return inTab ? (
    <div className="space-y-3 animate-pulse">
      {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-3 rounded bg-zinc-800" />)}
    </div>
  ) : null
  if (!players.length) return inTab ? (
    <p className="py-8 text-center text-sm text-zinc-500">No player props available for this game.</p>
  ) : null

  const openChart = async (pid: number, pr: GamePropPlayer['props'][0]) => {
    const key = `${pid}-${pr.market}-${pr.side}`
    if (openKey === key) { setOpenKey(null); setChart(null); return }
    setOpenKey(key); setChart(null)
    try {
      const params = new URLSearchParams({ player_id: String(pid), market: pr.market, line: String(pr.line), side: pr.side, league })
      const r = await fetch(`/api/props/history?${params}`)
      const d = await r.json()
      setChart(d.games?.length ? d : null)
    } catch { setChart(null) }
  }

  return (
    <section className={inTab ? '' : 'bg-zinc-900 border border-zinc-800 rounded-xl p-4'}>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-bold text-zinc-400 uppercase tracking-wider">
          {edgeLabel ? 'Projected Lines' : settled > 0 ? 'How the props landed' : 'Player Props'}
        </h2>
        {settled > 0 && (
          <span className="font-mono text-[11px] tabular-nums text-zinc-400">
            <span className="text-emerald-400">{hits}</span> of {settled} hit
          </span>
        )}
      </div>
      <div className="space-y-3">
        {players.map(pl => (
          <div key={pl.player_id} className="border-b border-zinc-800/50 pb-2.5 last:border-0">
            <div className="flex items-baseline gap-1.5">
              <a href={`/player/${pl.player_id}`} className="text-sm font-semibold hover:text-emerald-400">{pl.name}</a>
              <span className="text-xs text-zinc-500">{pl.team}</span>
            </div>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {pl.props.map((pr, i) => {
                const key = `${pl.player_id}-${pr.market}-${pr.side}`
                const open = openKey === key
                // Three states, three looks. Settled-and-hit and settled-and-missed both
                // make a claim; unsettled makes none and keeps the neutral chip it always
                // had, so "we don't know yet" never reads as "we were wrong".
                const settledClass = !pr.result ? 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
                  : pr.result.hit ? 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/40 hover:bg-emerald-500/25'
                    : 'bg-zinc-800/60 text-zinc-500 ring-1 ring-zinc-700 hover:bg-zinc-800'
                return (
                  <button key={i} onClick={() => openChart(pl.player_id, pr)}
                    title={pr.result ? `Actual ${pr.result.actual} — ${pr.result.hit ? 'hit' : 'missed'}` : undefined}
                    className={`text-[11px] px-2 py-1 rounded font-mono tabular-nums transition-colors ${open ? 'bg-emerald-600 text-white' : settledClass}`}>
                    {pr.market.replace(/_/g, ' ')} {pr.side} {pr.line}
                    {pr.result && (
                      <span className={open ? 'ml-1.5' : `ml-1.5 ${pr.result.hit ? 'text-emerald-400' : 'text-zinc-500'}`}>
                        → {pr.result.actual}
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
            {openKey?.startsWith(`${pl.player_id}-`) && chart && <div className="mt-2"><PropChart data={chart} /></div>}
          </div>
        ))}
      </div>
    </section>
  )
}
