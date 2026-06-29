import { SoccerBoxScoreData, SoccerStatBar } from './types'

// ── WC soccer box score: team stat comparison bars + both lineups ──
export default function SoccerBoxScore({ data }: { data: SoccerBoxScoreData }) {
  if (!data.available || (!data.teamStats && !data.lineups)) {
    return (
      <div className="text-zinc-500 text-sm text-center py-12">
        Box score available at kickoff.
      </div>
    )
  }

  const homeLineup = data.lineups?.find(l => l.side === 'home')
  const awayLineup = data.lineups?.find(l => l.side === 'away')
  const homeLabel = data.lineups?.[0]?.side === 'home' ? data.lineups[0] : data.lineups?.[1]
  const awayLabel = data.lineups?.[0]?.side === 'away' ? data.lineups[0] : data.lineups?.[1]

  return (
    <div className="grid grid-cols-[1fr_280px] gap-6 lg:grid-cols-[1fr_280px] max-lg:grid-cols-1 max-lg:gap-8">
      {/* Left panel: Team Stats bar comparison */}
      <div>
        <div className="text-[10px] tracking-widest text-zinc-500 uppercase mb-3">Team Stats</div>

        <div className="space-y-2">
          {(data.teamStats || []).map((stat, i) => (
            <StatBar key={i} stat={stat} />
          ))}
        </div>

        {/* Team abbreviations centered below */}
        <div className="flex justify-center gap-6 mt-3">
          <span className="text-[10px] text-zinc-500 tracking-wider">{awayLabel?.side || 'AWAY'}</span>
          <span className="text-[10px] text-zinc-600">·</span>
          <span className="text-[10px] text-zinc-500 tracking-wider">{homeLabel?.side || 'HOME'}</span>
        </div>
      </div>

      {/* Right panel: Lineups */}
      <div>
        <div className="text-[10px] tracking-widest text-zinc-500 uppercase mb-3">Lineups</div>

        <div className="space-y-4">
          {[awayLineup, homeLineup].map((lu, li) => {
            if (!lu) return null
            const xi = lu.players.slice(0, 11)
            const subs = lu.players.slice(11)

            return (
              <div key={li} className="bg-zinc-800/50 border border-zinc-800 rounded-lg p-3">
                <div className="text-xs font-bold text-zinc-400 uppercase tracking-wide mb-1">{lu.side}</div>
                {lu.formation ? (
                  <div className="text-sm font-bold text-zinc-300 mb-2">{lu.formation}</div>
                ) : null}

                {/* Starting XI */}
                {xi.map((p, pi) => (
                  <div key={pi} className="flex items-center gap-2 text-xs py-0.5">
                    <span className="font-mono text-zinc-500 w-6 shrink-0 text-right">{p.num}</span>
                    <span className="text-zinc-200 truncate">{p.name}</span>
                    {p.pos ? <span className="text-zinc-500">({p.pos})</span> : null}
                  </div>
                ))}

                {/* Substitutes */}
                {subs.length > 0 && (
                  <div className="border-t border-zinc-800/50 pt-2 mt-2">
                    <span className="text-[10px] text-zinc-500">
                      Subs: {subs.map(s => `${s.num} ${s.name}`).join(' · ')}
                    </span>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── Individual stat bar row ──
function StatBar({ stat }: { stat: SoccerStatBar }) {
  const homeNum = parseFloat(stat.home) || 0
  const awayNum = parseFloat(stat.away) || 0
  const maxVal = Math.max(homeNum, awayNum, 1)
  const label = stat.label || ''

  // Determine if this stat is possession (rendered as a single continuous bar)
  const isPossession = label.toLowerCase().includes('possession')

  // Special handling for 0/0 stats
  if (homeNum === 0 && awayNum === 0) {
    return (
      <div className="grid items-center" style={{ gridTemplateColumns: '120px 1fr 40px 8px 40px 1fr' }}>
        <span className="text-xs text-zinc-400 text-right pr-3">{label}</span>
        <div className="flex justify-end">
          <div className="h-4 bg-zinc-800 rounded-sm" style={{ width: '2px' }} />
        </div>
        <span className="font-mono tabular-nums text-xs text-zinc-600 text-center">—</span>
        <div className="border-l border-zinc-700 h-full" />
        <span className="font-mono tabular-nums text-xs text-zinc-600 text-center">—</span>
        <div className="flex justify-start">
          <div className="h-4 bg-zinc-800 rounded-sm" style={{ width: '2px' }} />
        </div>
      </div>
    )
  }

  if (isPossession) {
    const homePct = homeNum / (homeNum + awayNum || 1)
    return (
      <div className="grid items-center" style={{ gridTemplateColumns: '120px 1fr 40px 8px 40px 1fr' }}>
        <span className="text-xs text-zinc-400 text-right pr-3">{label}</span>
        <div className="flex justify-end pr-0.5">
          <div className="h-4 rounded-sm" style={{
            width: `${Math.max(homePct * 100, 2)}%`,
            minWidth: '4px',
            backgroundColor: homeNum > awayNum ? 'rgb(113,113,122)' : 'rgb(82,82,91)'
          }} />
        </div>
        <span className={`font-mono tabular-nums text-xs text-center ${homeNum > awayNum ? 'text-zinc-200' : 'text-zinc-400'}`}>
          {stat.home}{isPossession ? '%' : ''}
        </span>
        <div className="border-l border-zinc-700 h-4" />
        <span className={`font-mono tabular-nums text-xs text-center ${awayNum > homeNum ? 'text-zinc-200' : 'text-zinc-400'}`}>
          {stat.away}{isPossession ? '%' : ''}
        </span>
        <div className="flex justify-start pl-0.5">
          <div className="h-4 rounded-sm" style={{
            width: `${Math.max((1 - homePct) * 100, 2)}%`,
            minWidth: '4px',
            backgroundColor: awayNum > homeNum ? 'rgb(113,113,122)' : 'rgb(82,82,91)'
          }} />
        </div>
      </div>
    )
  }

  const homeWidth = Math.max((homeNum / maxVal) * 100, 2)
  const awayWidth = Math.max((awayNum / maxVal) * 100, 2)

  // Check if this is a card stat
  const isYellowCard = label.toLowerCase().includes('yellow')
  const isRedCard = label.toLowerCase().includes('red')

  return (
    <div className="grid items-center" style={{ gridTemplateColumns: '120px 1fr 40px 8px 40px 1fr' }}>
      <span className="text-xs text-zinc-400 text-right pr-3">{label}</span>
      <div className="flex justify-end pr-0.5">
        <div className="h-4 rounded-sm" style={{
          width: `${homeWidth}%`,
          minWidth: '4px',
          backgroundColor: homeNum > awayNum ? 'rgb(113,113,122)' : 'rgb(82,82,91)'
        }} />
      </div>
      <span className={`font-mono tabular-nums text-xs text-center ${homeNum > awayNum ? 'text-zinc-200' : 'text-zinc-400'}`}>
        {isYellowCard ? <span className="text-yellow-500">■ </span> : null}
        {isRedCard ? <span className="text-red-500">■ </span> : null}
        {stat.home}
      </span>
      <div className="border-l border-zinc-700 h-4" />
      <span className={`font-mono tabular-nums text-xs text-center ${awayNum > homeNum ? 'text-zinc-200' : 'text-zinc-400'}`}>
        {isYellowCard ? <span className="text-yellow-500">■ </span> : null}
        {isRedCard ? <span className="text-red-500">■ </span> : null}
        {stat.away}
      </span>
      <div className="flex justify-start pl-0.5">
        <div className="h-4 rounded-sm" style={{
          width: `${awayWidth}%`,
          minWidth: '4px',
          backgroundColor: awayNum > homeNum ? 'rgb(113,113,122)' : 'rgb(82,82,91)'
        }} />
      </div>
    </div>
  )
}
