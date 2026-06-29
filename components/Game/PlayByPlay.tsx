import { useState } from 'react'
import { ScoringPlay, PbPData, PbPPlay, SoccerPbPData, SoccerEvent } from './types'

// ── Legacy play-by-play for NBA/NHL (detail endpoint data) ──
export function LegacyPlayByPlay({ allPlays, homeTeam, awayTeam }: {
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
              const icon = '◆'
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

// ── US sports PlayByPlay (MLB/NFL/NBA/NHL) from per-tab endpoint ──
export function USPlayByPlay({ data }: { data: PbPData }) {
  const [showAll, setShowAll] = useState(false)

  if (!data.available || !data.periods || data.periods.length === 0) {
    return (
      <div className="text-zinc-500 text-sm text-center py-12">
        Play-by-play begins at kickoff / first pitch / tip-off.
      </div>
    )
  }

  const allPlays: PbPPlay[] = data.periods.flatMap(p => p.plays)
  const scoringOnly = allPlays.filter(p => p.scoringPlay)
  const displayPlays = showAll ? data.periods : data.periods.map(p => ({
    ...p,
    plays: p.plays.filter(pl => pl.scoringPlay),
  })).filter(p => p.plays.length > 0)

  return (
    <div>
      {/* Toggle */}
      <div className="flex items-center justify-end gap-1 mb-4">
        <div className="flex items-center gap-0 bg-zinc-800 rounded-lg p-0.5">
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
      </div>

      {/* Timeline */}
      <div className="max-h-[500px] overflow-y-auto">
        {displayPlays.map((period, pi) => (
          <div key={pi} className="mb-4">
            <div className="text-xs font-bold text-zinc-500 mb-2 sticky top-0 bg-zinc-900/90 py-1 backdrop-blur z-10">
              {period.label || `Period ${pi + 1}`}
            </div>
            {period.plays.map((p, i) => {
              // Determine scoring highlight
              const isScoring = p.scoringPlay
              return (
                <div
                  key={i}
                  className={`flex items-start gap-2 py-1.5 border-b border-zinc-800/30 text-sm hover:bg-zinc-800/50 ${
                    isScoring ? 'border-l-2 border-amber-500/60 pl-3 -ml-[2px]' : ''
                  }`}
                >
                  <span className="text-zinc-600 font-mono w-10 shrink-0 text-xs pt-0.5">{p.clock}</span>
                  <span className={`text-zinc-${isScoring ? '200' : '300'} flex-1 leading-snug ${isScoring ? 'font-medium' : ''}`}>
                    {p.text}
                  </span>
                  <span className={`font-mono shrink-0 text-xs pt-0.5 tabular-nums ${
                    isScoring ? 'text-zinc-300 font-bold' : 'text-zinc-600'
                  }`}>
                    {p.scoreAway ?? '-'}-{p.scoreHome ?? '-'}
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

// ── Soccer event timeline (WC) ──
export function SoccerPlayByPlay({ data }: { data: SoccerPbPData }) {
  if (!data.available || !data.events || data.events.length === 0) {
    return (
      <div className="text-zinc-500 text-sm text-center py-12">
        Play-by-play begins at kickoff.
      </div>
    )
  }

  const events = data.events
  const halfIdx = events.findIndex(e => e.minute > 45)

  // Icon by type
  const eventIcon = (type: SoccerEvent['type']) => {
    switch (type) {
      case 'goal': return { symbol: '●', cls: 'text-emerald-500' }
      case 'card': return { symbol: '■', cls: 'text-yellow-500' }
      case 'sub':  return { symbol: '◆', cls: 'text-zinc-500' }
      case 'var':  return { symbol: '▸', cls: 'text-blue-400' }
      default:     return { symbol: '●', cls: 'text-zinc-500' }
    }
  }

  return (
    <div className="pl-4 border-l border-zinc-700 max-h-[500px] overflow-y-auto">
      {events.map((ev, i) => {
        // Insert half-time marker
        const showHalfTime = halfIdx > 0 && i === halfIdx
        const icon = eventIcon(ev.type)
        const isGoal = ev.type === 'goal'
        const isCard = ev.type === 'card'

        return (
          <div key={i}>
            {showHalfTime && (
              <div className="flex items-center gap-4 py-3 -ml-4 pl-4">
                <div className="border-t border-zinc-700 flex-1" />
                <span className="text-xs text-zinc-500 font-medium uppercase tracking-wider">Half Time</span>
                <div className="border-t border-zinc-700 flex-1" />
              </div>
            )}

            <div className="flex items-start gap-3 py-2">
              {/* Icon + minute */}
              <div className="w-14 shrink-0 flex flex-col items-center pt-0.5">
                <span className={`text-[14px] leading-none ${icon.cls}`}>{icon.symbol}</span>
                <span className="font-mono text-[10px] text-zinc-500 mt-0.5">{ev.minute}'</span>
              </div>

              {/* Event text */}
              <div className="flex-1 min-w-0">
                <div className={`text-sm leading-snug ${isGoal ? 'text-zinc-200 font-medium' : isCard ? 'text-zinc-200' : 'text-zinc-300'}`}>
                  {ev.text}
                </div>
                {ev.team && (
                  <div className={`text-[10px] mt-0.5 ${isGoal ? 'text-emerald-500/60' : 'text-zinc-500'}`}>
                    {ev.team}
                  </div>
                )}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Combined PlayByPlay component that detects data shape ──
export default function PlayByPlay({
  legacyPlays, homeTeam, awayTeam, data, soccerData,
}: {
  legacyPlays?: ScoringPlay[]
  homeTeam?: string
  awayTeam?: string
  data?: PbPData
  soccerData?: SoccerPbPData
}) {
  // Legacy path: NBA/NHL from detail endpoint
  if (legacyPlays && legacyPlays.length > 0 && homeTeam && awayTeam) {
    return <LegacyPlayByPlay allPlays={legacyPlays} homeTeam={homeTeam} awayTeam={awayTeam} />
  }

  // New US sports path
  if (data) {
    return <USPlayByPlay data={data} />
  }

  // Soccer path
  if (soccerData) {
    return <SoccerPlayByPlay data={soccerData} />
  }

  return (
    <div className="text-zinc-500 text-sm text-center py-12">
      Play-by-play begins at kickoff / first pitch / tip-off.
    </div>
  )
}
