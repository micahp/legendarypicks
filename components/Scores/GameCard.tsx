import { useRouter } from 'next/router'

interface TeamInfo {
  teamId: string
  name: string
  nickname?: string
  score?: number
  winner?: boolean
  // EWC bracket dependency label for an undecided slot ("Winner of X–Y").
  label?: string
  pending?: boolean
  unavailable?: boolean
}

interface TennisSet {
  homeScore: number
  awayScore: number
}

interface GameProps {
  gameId: string
  detailGameId?: string
  league?: string
  homeTeam: TeamInfo
  awayTeam: TeamInfo
  startTime: string
  status: 'SCHEDULED' | 'LIVE' | 'FINAL'
  statusDetail?: string   // ESPN "Final/10" etc.
  subtitle?: string
  showScheduledTime?: boolean
  // Tennis: array of set scores [home, away] for each set
  sets?: TennisSet[]
  // Live game period details (only present when LIVE)
  livePeriod?: {
    // MLB: current inning (1-9+), NHL: period (1-3+), NBA: quarter (1-4+)
    // UFC: round (1-5), COD: game (1-5+)
    number: number
    type: 'inning' | 'period' | 'quarter' | 'round' | 'game' | 'half' | 'set'
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

function getStatusLabel(status: GameProps['status'], statusDetail?: string) {
  if (status === 'LIVE') return 'LIVE'
  // Extra innings / OT: ESPN gives "Final/10", "Final/OT" — show it instead of plain FINAL.
  if (status === 'FINAL') return statusDetail && statusDetail.includes('/') ? statusDetail : 'FINAL'
  return 'SCHEDULED'
}

function getPeriodLabel(league?: string, livePeriod?: GameProps['livePeriod']) {
  if (!livePeriod) return null

  const { type, number, display } = livePeriod

  // Use display if provided (MLB status_detail: "Top 1st", "End 5th", etc.)
  if (display) return display

  // Format based on type
  switch (type) {
    case 'inning':
      return `${number}`
    case 'period':
      return `P${number}`
    case 'quarter':
      return `Q${number}`
    case 'round':
      return `R${number}`
    case 'set':
      return `Set ${number}`
    case 'half':
      return number === 1 ? '1st Half' : number === 2 ? '2nd Half' : `Half ${number}`
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

  // UFC suppresses time on shared score surfaces; a schedule can opt in.
  const isUFC = g.league === 'UFC'
  const isTennis = g.league === 'ATP' || g.league === 'WTA'
  // Leagues with a real detail page (box score / play-by-play / game info tabs). NFL + WC were
  // added with the per-tab endpoints, so their cards must be clickable too — else the pages we built
  // are unreachable. CoD is clickable only when its score-source fixture has a verified PandaScore id.
  const hasDetail = ['NBA', 'NHL', 'MLB', 'NFL', 'WC'].includes(g.league || '')
    || (g.league === 'COD' && !!g.detailGameId)
  const isTeamSport = g.league === 'NBA' || g.league === 'NHL' || g.league === 'MLB' || g.league === 'NFL'
  const isSoccer = g.league === 'WC'

  const teamLabel = (t: GameProps['homeTeam']) => {
    // An unresolved EWC participant renders its dependency label, never a bare TBD.
    if (t.label) return t.label
    if (!isTeamSport) return t.name
    if (t.nickname) return `${t.teamId} ${t.nickname}`
    return t.teamId || t.name
  }
  // Unresolved participants get quiet, italic dependency text; no invented score/logo.
  const sideClass = (t: GameProps['homeTeam']) => {
    if (t.pending || t.unavailable) return 'italic text-zinc-500'
    return null
  }

  // What to show in the top-right area:
  // - SCHEDULED: show time (except UFC)
  // - LIVE: show LIVE badge (no time), plus period info if available
  // - FINAL: show FINAL badge (no time)
  const showTime = g.status === 'SCHEDULED' && (!isUFC || g.showScheduledTime)
  const showStatusBadge = g.status === 'LIVE' || g.status === 'FINAL'
  // Scores only exist once a game starts — never render 0–0 before first pitch/tip/puck
  const showScore = g.status === 'LIVE' || g.status === 'FINAL'

  // Winner/loser dimming — same treatment as ScoreStrip on the detail page
  const isFinal = g.status === 'FINAL'
  // Team sports: compare scores. UFC: use winner boolean. Soccer: winner flag + draw handling.
  const isSoccerFinal = isFinal && g.league === 'WC'
  const isUFCFinal = isFinal && g.league === 'UFC'
  const homeWon = isFinal
    ? (isSoccerFinal ? !!(g as any).homeTeam?.winner === true
       : isUFCFinal ? g.homeTeam.winner === true
       : (g.homeTeam.score !== undefined && g.awayTeam.score !== undefined && g.homeTeam.score! > g.awayTeam.score!))
    : false
  const awayWon = isFinal
    ? (isSoccerFinal ? !!(g as any).awayTeam?.winner === true
       : isUFCFinal ? g.awayTeam.winner === true
       : (g.homeTeam.score !== undefined && g.awayTeam.score !== undefined && g.awayTeam.score! > g.homeTeam.score!))
    : false
  // Draw: neither side dimmed
  const isDraw = isSoccerFinal && !homeWon && !awayWon

  const handleClick = () => {
    if (hasDetail) {
      const href = g.league === 'COD'
        ? `/game/call-of-duty/${g.detailGameId}`
        : `/game/${g.league?.toLowerCase()}/${g.gameId}`
      router.push(href)
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
        </span>

        {/* Right side: status badge (LIVE/FINAL), or SCHEDULED badge only for UFC? No badge for scheduled non-UFC */}
        <span
          className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${showStatusBadge ? getStatusBadge(g.status) : 'hidden'}`}
        >
          {g.status === 'LIVE' && getPeriodLabel(g.league, g.livePeriod) ? getPeriodLabel(g.league, g.livePeriod) : (showStatusBadge ? getStatusLabel(g.status, g.statusDetail) : '')}
        </span>
      </div>

      {isTennis && g.sets && g.sets.length > 0 ? (
        /* Tennis scoreboard: each player's games-per-set as aligned columns.
           Winner of each set is emphasized; match winner's name stays bright. */
        <div className="space-y-2">
          {([['home', g.homeTeam] as const, ['away', g.awayTeam] as const]).map(([side, team]) => {
            const homeSets = g.sets!.filter(s => s.homeScore > s.awayScore).length
            const awaySets = g.sets!.filter(s => s.awayScore > s.homeScore).length
            const won = isFinal && (side === 'home' ? homeSets > awaySets : awaySets > homeSets)
            return (
            <div key={side} className="flex items-center justify-between gap-3">
              <span className={`font-semibold truncate ${isFinal ? (won ? 'text-white' : 'text-zinc-500') : 'text-zinc-200'}`}>{team.name}</span>
              <div className="flex gap-1 shrink-0 tabular-nums">
                {g.sets!.map((set, i) => {
                  const mine = side === 'home' ? set.homeScore : set.awayScore
                  const theirs = side === 'home' ? set.awayScore : set.homeScore
                  const wonSet = mine > theirs
                  return (
                    <span key={i} className={`w-6 text-center text-lg ${wonSet ? 'text-white font-bold' : 'text-zinc-500'}`}>{mine}</span>
                  )
                })}
              </div>
            </div>
            )
          })}
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex justify-between items-center">
            <span className={`font-semibold ${sideClass(g.homeTeam) ?? (isFinal ? (isDraw ? 'text-zinc-200' : homeWon ? 'text-zinc-200' : 'text-zinc-500') : 'text-zinc-200')}`}>{teamLabel(g.homeTeam)}</span>
            {showScore && g.homeTeam.score !== undefined && (
              <span className="flex items-center gap-1.5">
                <span className={`text-xl font-black ${isFinal ? (isDraw ? 'text-white' : homeWon ? 'text-white' : 'text-zinc-500') : 'text-white'}`}>{g.homeTeam.score}</span>
              </span>
            )}
          </div>
          <div className="flex justify-between items-center">
            <span className={`font-semibold ${sideClass(g.awayTeam) ?? (isFinal ? (isDraw ? 'text-zinc-200' : awayWon ? 'text-zinc-200' : 'text-zinc-500') : 'text-zinc-200')}`}>{teamLabel(g.awayTeam)}</span>
            {showScore && g.awayTeam.score !== undefined && (
              <span className="flex items-center gap-1.5">
                <span className={`text-xl font-black ${isFinal ? (isDraw ? 'text-white' : awayWon ? 'text-white' : 'text-zinc-500') : 'text-white'}`}>{g.awayTeam.score}</span>
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
