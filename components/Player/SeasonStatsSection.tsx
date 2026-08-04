import { seasonLabel } from '../Leagues/presentation'
import type { SeasonStats, SeasonStatBlock, MlbSeasonStats } from './types'
import { statLabel, formatStatValue } from './format'

// Renders one compact stat grid (a flat `stats` dict, or an MLB batting/pitching split).
export default function SeasonStatsSection({ league, seasonStats }: { league: string; seasonStats: SeasonStats }) {
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
        Season Stats{seasonStats.window ? ` · ${seasonLabel(league, seasonStats.window)}` : ''}{meta.games ? ` · ${meta.games} games` : ''}
      </h2>
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 divide-y divide-zinc-800">
        {blocks.map(b => (
          <div key={b.label} className="p-4">
            {blocks.length > 1 && <div className="text-xs font-semibold text-zinc-400 mb-2">{b.label}</div>}
            {/* Label over value, not label-and-value spread across the column:
                at three columns a justified pair puts the number nearer the next
                column's label than its own. */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-x-6 gap-y-4">
              {b.entries.map(([k, v]) => (
                <div key={k} className="flex flex-col gap-0.5">
                  <span className="text-[11px] uppercase tracking-wide text-zinc-500">{statLabel(k)}</span>
                  <span className="font-mono tabular-nums text-lg text-zinc-100">{formatStatValue(k, v)}</span>
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
