import { GameContext } from './types'

// ── score strip (compact ESPN-style) ──
export default function ScoreStrip({ ctx, score, state, homeName, awayName, homeRecord, awayRecord }: {
  ctx: GameContext | null; score: { away: number; home: number } | null; state?: string | null
  homeName: string; awayName: string; homeRecord: string; awayRecord: string
}) {
  const isFinal = state === 'post'
  const isLive = state === 'in'
  // Dim the loser only when the game is final; keep both bright while live/scheduled.
  const homeWon = isFinal && score ? score.home > score.away : false
  const awayWon = isFinal && score ? score.away > score.home : false
  const awayDim = isFinal && !awayWon
  const homeDim = isFinal && !homeWon
  return (
    <div className="flex items-center justify-center gap-4 md:gap-8 py-6">
      {/* Away */}
      <div className="flex flex-col items-center text-center min-w-0 flex-1 gap-0.5">
        <div className="text-xs font-bold text-zinc-400">{ctx?.away_team || 'AWAY'}</div>
        <span className={`text-4xl md:text-5xl font-black tabular-nums tracking-tight ${awayDim ? 'text-zinc-500' : 'text-white'}`}>
          {score?.away ?? '-'}
        </span>
        <div className={`text-xs ${awayDim ? 'text-zinc-600' : 'text-zinc-400'}`}>{awayRecord}</div>
        <div className={`text-sm font-semibold mt-0.5 truncate max-w-[140px] ${awayDim ? 'text-zinc-500' : 'text-zinc-200'}`}>{awayName}</div>
      </div>

      {/* Center: status */}
      <div className="flex items-center shrink-0">
        <span className={`text-xs font-bold uppercase tracking-widest ${isLive ? 'text-red-500' : 'text-zinc-500'}`}>
          {isFinal ? 'FINAL' : isLive ? 'LIVE' : 'SCHEDULED'}
        </span>
      </div>

      {/* Home */}
      <div className="flex flex-col items-center text-center min-w-0 flex-1 gap-0.5">
        <div className="text-xs font-bold text-zinc-400">{ctx?.home_team || 'HOME'}</div>
        <span className={`text-4xl md:text-5xl font-black tabular-nums tracking-tight ${homeDim ? 'text-zinc-500' : 'text-white'}`}>
          {score?.home ?? '-'}
        </span>
        <div className={`text-xs ${homeDim ? 'text-zinc-600' : 'text-zinc-400'}`}>{homeRecord}</div>
        <div className={`text-sm font-semibold mt-0.5 truncate max-w-[140px] ${homeDim ? 'text-zinc-500' : 'text-zinc-200'}`}>{homeName}</div>
      </div>
    </div>
  )
}
