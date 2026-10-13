import { GameContext } from './types'
import { formatLiveStatus, isSoccerLeague, livePeriodTypeForLeague } from '../../lib/liveGameStatus'

// ── score strip (compact ESPN-style) ──
export default function ScoreStrip({ ctx, score, state, league, period, clock, statusDetail, startTime, isPreseason, homeName, awayName, homeRecord, awayRecord }: {
  ctx: GameContext | null; score: { away: number; home: number } | null; state?: string | null
  league?: string | null; period?: number | null; clock?: string | null
  statusDetail?: string | null; startTime?: string | null
  isPreseason?: boolean
  homeName: string; awayName: string; homeRecord: string; awayRecord: string
}) {
  // ESPN closes a postponed / cancelled / abandoned match as state=post with a 0-0 score.
  // It was never played, so it has no score, no winner and no loser to dim.
  const normalizedState = (state || '').toLowerCase()
  const terminalState = normalizedState === 'post' || normalizedState === 'final' || normalizedState === 'completed'
  const notPlayed = terminalState && !!statusDetail
    && /postpon|cancel|abandon/i.test(statusDetail)
  const isFinal = terminalState && !notPlayed
  const isLive = normalizedState === 'in' || normalizedState === 'live'
  const scheduledTime = startTime && Number.isFinite(new Date(startTime).getTime())
    ? new Date(startTime).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    : null
  const scheduledDetail = scheduledTime || (statusDetail && !/^(scheduled|pre|upcoming)$/i.test(statusDetail)
    ? statusDetail
    : null)
  const statusLabel = notPlayed
    ? (statusDetail as string).toUpperCase()
    : isFinal
    ? (statusDetail && /susp/i.test(statusDetail)
      ? 'SUSPENDED'
      : isSoccerLeague(league) && !/pens|aet|shootout/i.test(statusDetail || '')
      ? 'FULL TIME'
      : statusDetail || 'FINAL')
    : isLive
    ? formatLiveStatus({
        type: livePeriodTypeForLeague(league || undefined),
        number: period,
        display: league?.toLowerCase() === 'mlb' ? statusDetail : undefined,
        clock,
      }, statusDetail, league)
    : scheduledDetail || ''
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
          {notPlayed ? '-' : (score?.away ?? '-')}
        </span>
        <div className={`text-xs ${awayDim ? 'text-zinc-600' : 'text-zinc-400'}`}>{awayRecord}</div>
        <div className={`text-sm font-semibold mt-0.5 truncate max-w-[140px] ${awayDim ? 'text-zinc-500' : 'text-zinc-200'}`}>{awayName}</div>
      </div>

      {/* Center: status, with the publisher's preseason phase above it */}
      <div className="flex flex-col items-center gap-1 shrink-0">
        {/* Quiet: same muted text as the record lines, no colour, no weight, no border. */}
        {isPreseason && <span className="text-xs text-zinc-500">Preseason</span>}
        <span className={`text-xs font-bold uppercase tracking-widest ${isLive ? 'text-red-500' : 'text-zinc-500'}`}>
          {statusLabel}
        </span>
      </div>

      {/* Home */}
      <div className="flex flex-col items-center text-center min-w-0 flex-1 gap-0.5">
        <div className="text-xs font-bold text-zinc-400">{ctx?.home_team || 'HOME'}</div>
        <span className={`text-4xl md:text-5xl font-black tabular-nums tracking-tight ${homeDim ? 'text-zinc-500' : 'text-white'}`}>
          {notPlayed ? '-' : (score?.home ?? '-')}
        </span>
        <div className={`text-xs ${homeDim ? 'text-zinc-600' : 'text-zinc-400'}`}>{homeRecord}</div>
        <div className={`text-sm font-semibold mt-0.5 truncate max-w-[140px] ${homeDim ? 'text-zinc-500' : 'text-zinc-200'}`}>{homeName}</div>
      </div>
    </div>
  )
}
