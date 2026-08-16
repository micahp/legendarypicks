import { useState } from 'react'
import PropChart, { PropHistory } from '../Props/PropChart'
import { GamePropPlayer, Prop } from './useGameProps'

export type { Prop }

/**
 * One chip per settled LINE instead of one per side.
 *
 * We store both sides of most lines, so a settled game rendered the same number twice —
 * "total bases over 1.5 → 0" next to "total bases under 1.5 → 0" — and by construction one
 * was always green and one always grey. That is not two results, it is one result printed
 * twice with a guaranteed 50% success rate attached. Once a line is settled the side is a
 * property of the OUTCOME (`cashed`), not a separate row worth showing.
 *
 * Unsettled props are untouched: before the game both sides are real, distinct offers.
 */
export function collapseSettledSides(props: Prop[]): Prop[] {
  const seen = new Set<string>()
  return props.filter(p => {
    if (!p.result) return true
    const line = `${p.market}|${p.line}`
    if (seen.has(line)) return false
    seen.add(line)
    return true
  })
}

/** Presentational: the page owns the single fetch (see useGameProps). */
export default function GameProps({
  league, players, settledLines, edgeLabel, loading, inTab = false,
}: {
  league: string
  players: GamePropPlayer[]
  settledLines: number
  edgeLabel: boolean
  loading: boolean
  inTab?: boolean
}) {
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [chart, setChart] = useState<PropHistory | null>(null)

  if (loading) return inTab ? (
    <div className="space-y-3 animate-pulse">
      {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-3 rounded bg-zinc-800" />)}
    </div>
  ) : null
  if (!players.length) return inTab ? (
    <p className="py-8 text-center text-sm text-zinc-500">No player props available for this game.</p>
  ) : null

  const openChart = async (pid: number, pr: Prop) => {
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
          {edgeLabel ? 'Projected Lines' : settledLines > 0 ? 'How the props landed' : 'Player Props'}
        </h2>
        {settledLines > 0 && (
          // Lines settled, NOT a hit rate. We hold both sides of most lines, so any
          // win-loss record computed here would describe our storage layout rather than
          // our judgement — and we do not publish a side to be judged on.
          <span className="font-mono text-[11px] tabular-nums text-zinc-400">
            {settledLines} {settledLines === 1 ? 'line' : 'lines'} settled
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
              {collapseSettledSides(pl.props).map((pr, i) => {
                const key = `${pl.player_id}-${pr.market}-${pr.side}`
                const open = openKey === key
                // Three states, three looks. Settled-and-hit and settled-and-missed both
                // make a claim; unsettled makes none and keeps the neutral chip it always
                // had, so "we don't know yet" never reads as "we were wrong".
                const settledClass = !pr.result
                  ? 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
                  : 'bg-zinc-800/80 text-zinc-300 ring-1 ring-zinc-700 hover:bg-zinc-800'
                return (
                  <button key={i} onClick={() => openChart(pl.player_id, pr)}
                    title={pr.result ? `Line ${pr.line}, actual ${pr.result.actual} — the ${pr.result.cashed} cashed` : undefined}
                    className={`text-[11px] px-2 py-1 rounded font-mono tabular-nums transition-colors ${open ? 'bg-emerald-600 text-white' : settledClass}`}>
                    {pr.market.replace(/_/g, ' ')} {pr.result ? pr.line : `${pr.side} ${pr.line}`}
                    {pr.result && (
                      <span className={open ? 'ml-1.5' : 'ml-1.5 text-emerald-400'}>
                        → {pr.result.actual} <span className={open ? '' : 'text-zinc-500'}>{pr.result.cashed}</span>
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
