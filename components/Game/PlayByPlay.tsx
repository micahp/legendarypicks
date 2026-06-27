import { useState } from 'react'
import { ScoringPlay } from './types'

// ── play-by-play tab ──
export default function PlayByPlay({ allPlays, homeTeam, awayTeam }: {
  allPlays: ScoringPlay[]; homeTeam: string; awayTeam: string
}) {
  const [showAll, setShowAll] = useState(false)
  const scoringOnly = allPlays.filter(p => {
    const t = p.play_text?.toLowerCase() || ''
    return t.includes('made') || t.includes('goal') || t.includes('free throw')
  })
  const plays = showAll ? allPlays : scoringOnly

  const byQuarter: Record<number, ScoringPlay[]> = {}
  for (const p of plays) {
    if (!byQuarter[p.period]) byQuarter[p.period] = []
    byQuarter[p.period].push(p)
  }

  return (
    <div>
      {/* Toggle */}
      <div className="flex items-center justify-end gap-2 mb-4">
        <button
          onClick={() => setShowAll(false)}
          className={`px-3 py-1 rounded text-xs font-medium transition ${
            !showAll ? 'bg-white text-black' : 'text-zinc-400 hover:text-zinc-200'
          }`}
        >
          Scoring ({scoringOnly.length})
        </button>
        <button
          onClick={() => setShowAll(true)}
          className={`px-3 py-1 rounded text-xs font-medium transition ${
            showAll ? 'bg-white text-black' : 'text-zinc-400 hover:text-zinc-200'
          }`}
        >
          All ({allPlays.length})
        </button>
      </div>

      {/* Timeline */}
      <div className="max-h-[500px] overflow-y-auto">
        {Object.entries(byQuarter).map(([q, pplays]) => (
          <div key={q} className="mb-4">
            <div className="text-xs font-bold text-zinc-500 mb-2 sticky top-0 bg-zinc-900/90 py-1 backdrop-blur z-10">
              {pplays[0]?.period_disp || `Q${q}`}
            </div>
            {pplays.map((p, i) => {
              const isHome = p.team_abbrev === homeTeam
              const icon = isHome ? '◆' : '◆'
              return (
                <div key={i} className="flex items-start gap-2 py-1.5 border-b border-zinc-800/30 text-sm">
                  <span className="text-zinc-600 font-mono w-10 shrink-0 text-xs pt-0.5">{p.clock}</span>
                  <span className={`shrink-0 pt-0.5 text-[10px] ${isHome ? 'text-blue-400' : 'text-red-400'}`}>
                    {icon}
                  </span>
                  <span className="text-zinc-300 flex-1 leading-snug">{p.play_text}</span>
                  <span className="text-zinc-600 font-mono shrink-0 text-xs pt-0.5 tabular-nums">
                    {p.away_score}-{p.home_score}
                  </span>
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}
