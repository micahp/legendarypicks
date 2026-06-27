import { useState, useEffect } from 'react'
import PropChart, { PropHistory } from '../Props/PropChart'

interface GamePropPlayer { player_id: number; name: string; team: string; props: { market: string; side: string; line: number }[] }

export default function GameProps({ league, gameId }: { league: string; gameId: string }) {
  const [players, setPlayers] = useState<GamePropPlayer[]>([])
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [chart, setChart] = useState<PropHistory | null>(null)
  const [edgeLabel, setEdgeLabel] = useState(false)

  useEffect(() => {
    fetch(`/api/game/${league}/${gameId}/props`)
      .then(r => r.json()).then(d => {
        if (d.players?.length) { setPlayers(d.players); return }
        // NBA fallback: no Bovada props — show projected stat lines
        if (league === 'nba') {
          fetch(`/api/game/${league}/${gameId}/edge`)
            .then(r => r.json()).then(e => { setPlayers(e.players || []); setEdgeLabel(true) }).catch(() => {})
        }
      }).catch(() => {})
  }, [league, gameId])

  if (!players.length) return null

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
    <section className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
      <h2 className="text-sm font-bold text-zinc-400 uppercase tracking-wider mb-3">{edgeLabel ? 'Projected Lines' : 'Player Props'}</h2>
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
                return (
                  <button key={i} onClick={() => openChart(pl.player_id, pr)}
                    className={`text-[11px] px-2 py-1 rounded font-mono tabular-nums transition-colors ${openKey === key ? 'bg-emerald-600 text-white' : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'}`}>
                    {pr.market.replace(/_/g, ' ')} {pr.side} {pr.line}
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
