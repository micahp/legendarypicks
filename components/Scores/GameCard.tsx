import { useRouter } from 'next/router'

interface TeamInfo {
  teamId: string
  name: string
  nickname?: string
  score?: number
}

interface TennisSet {
  homeScore: number
  awayScore: number
}

interface GameProps {
  gameId: string
  league?: string
  homeTeam: TeamInfo
  awayTeam: TeamInfo
  startTime: string
  status: 'SCHEDULED' | 'LIVE' | 'FINAL'
  subtitle?: string
  // Tennis: array of set scores [home, away] for each set
  sets?: TennisSet[]
  // Live game period details (only present when LIVE)
  livePeriod?: {
    // MLB: current inning (1-9+), NHL: period (1-3+), NBA: quarter (1-4+)
    // UFC: round (1-5), COD: game (1-5+)
    number: number
    type: 'inning' | 'period' | 'quarter' | 'round' | 'game'
    // Optional: time remaining in period, outs (MLB), etc.
    display?: string
  }
}

function getStatusBadge(status: GameProps['status']) {
  return status === 'LIVE'
    ? 'bg-red-500/10 text-red-500 border border-red-500/20'
    : status === 'FINAL'
    ? 'bg-zinc-800 text-zinc-400'
    : 'bg-blue-500/10 text-blue-400 border border-blue-500/20'
}

function getStatusLabel(status: GameProps['status']) {
  return status === 'LIVE' ? 'LIVE' : status === 'FINAL' ? 'FINAL' : 'SCHEDULED'
}

function getPeriodLabel(league?: string, livePeriod?: GameProps['livePeriod']) {
  if (!livePeriod) return null

  const { type, number, display } = livePeriod

  // Use display if provided, otherwise format based on type
  if (display) return display

  // League-specific defaults based on type
  switch (type) {
    case 'inning':
      return `Inning ${number}`
    case 'period':
      return `Period ${number}`
    case 'quarter':
      return `Q${number}`
    case 'round':
      return `Round ${number}`
    case 'game':
      return `Game ${number}`
    default:
      return `${type} ${number}`
  }
}

export default function GameCard(g: GameProps) {
  const router = useRouter()
  const time = new Date(g.startTime)
  const timeLabel = time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

  // UFC never shows time
  const isUFC = g.league === 'UFC'
  const isTennis = g.league === 'ATP' || g.league === 'WTA'
  const hasDetail = g.league === 'NBA' || g.league === 'NHL'
  const isTeamSport = g.league === 'NBA' || g.league === 'NHL' || g.league === 'MLB' || g.league === 'NFL'

  const teamLabel = (t: GameProps['homeTeam']) => {
    if (!isTeamSport) return t.name
    if (t.nickname) return `${t.teamId} ${t.nickname}`
    return t.teamId || t.name
  }

  // What to show in the top-right area:
  // - SCHEDULED: show time (except UFC)
  // - LIVE: show LIVE badge (no time), plus period info if available
  // - FINAL: show FINAL badge (no time)
  const showTime = g.status === 'SCHEDULED' && !isUFC
  const showStatusBadge = g.status === 'LIVE' || g.status === 'FINAL'
  const showPeriod = g.status === 'LIVE' && g.livePeriod
  // Scores only exist once a game starts — never render 0–0 before first pitch/tip/puck
  const showScore = g.status === 'LIVE' || g.status === 'FINAL'

  // Winner/loser dimming — same treatment as ScoreStrip on the detail page
  const isFinal = g.status === 'FINAL'
  const homeWon = isFinal && g.homeTeam.score !== undefined && g.awayTeam.score !== undefined
    ? g.homeTeam.score! > g.awayTeam.score!
    : false
  const awayWon = isFinal && g.homeTeam.score !== undefined && g.awayTeam.score !== undefined
    ? g.awayTeam.score! > g.homeTeam.score!
    : false

  const handleClick = () => {
    if (hasDetail) {
      router.push(`/game/${g.league?.toLowerCase()}/${g.gameId}`)
    }
  }

  return (
    <div
      onClick={handleClick}
      className={`bg-zinc-900 text-zinc-100 rounded-xl p-4 shadow border border-zinc-800 transition-colors ${hasDetail ? 'hover:border-blue-500/50 cursor-pointer' : 'hover:border-zinc-700'}`}
    >
      <div className="flex items-center justify-between text-xs text-zinc-400 mb-2">
        {/* Left side: time (for scheduled, non-UFC) or period info (for live) */}
        <span className="flex items-center gap-2">
          {showTime && <span>{timeLabel}</span>}
          {showPeriod && (
            <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              {getPeriodLabel(g.league, g.livePeriod)}
            </span>
          )}
        </span>

        {/* Right side: status badge (LIVE/FINAL), or SCHEDULED badge only for UFC? No badge for scheduled non-UFC */}
        <span
          className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${showStatusBadge ? getStatusBadge(g.status) : 'hidden'}`}
        >
          {showStatusBadge ? getStatusLabel(g.status) : ''}
        </span>
      </div>

      <div className="space-y-3">
        <div className="flex justify-between items-center">
          <span className={`font-semibold ${isFinal ? (homeWon ? 'text-zinc-200' : 'text-zinc-500') : 'text-zinc-200'}`}>{teamLabel(g.homeTeam)}</span>
          {showScore && g.homeTeam.score !== undefined && <span className={`text-xl font-black ${isFinal ? (homeWon ? 'text-white' : 'text-zinc-500') : 'text-white'}`}>{g.homeTeam.score}</span>}
        </div>
        <div className="flex justify-between items-center">
          <span className={`font-semibold ${isFinal ? (awayWon ? 'text-zinc-200' : 'text-zinc-500') : 'text-zinc-200'}`}>{teamLabel(g.awayTeam)}</span>
          {showScore && g.awayTeam.score !== undefined && <span className={`text-xl font-black ${isFinal ? (awayWon ? 'text-white' : 'text-zinc-500') : 'text-white'}`}>{g.awayTeam.score}</span>}
        </div>

        {/* Tennis set totals */}
        {isTennis && g.sets && g.sets.length > 0 && (
          <div className="pt-2 border-t border-zinc-800">
            <div className="text-xs text-zinc-500 uppercase tracking-wide mb-1">Set Scores</div>
            <div className="grid grid-cols-5 gap-1 text-xs text-zinc-300 font-mono">
              {g.sets.map((set, i) => (
                <div key={i} className="flex justify-between gap-2 px-1">
                  <span>{set.homeScore}</span>
                  <span className="text-zinc-500">-</span>
                  <span>{set.awayScore}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}