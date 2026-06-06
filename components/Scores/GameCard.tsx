interface TeamInfo {
  name: string
  score?: number
}

interface GameProps {
  gameId: string
  league?: string
  homeTeam: TeamInfo
  awayTeam: TeamInfo
  startTime: string
  status: 'SCHEDULED' | 'LIVE' | 'FINAL'
}

export default function GameCard(g: GameProps) {
  const time = new Date(g.startTime)
  const timeLabel = time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return (
    <div className="bg-zinc-900 text-zinc-100 rounded-xl p-4 shadow border border-zinc-800 hover:border-zinc-700 transition-colors">
      <div className="flex items-center justify-between text-xs text-zinc-400 mb-2">
        <div className="flex items-center gap-2">
          {g.league && (
            <span className="font-bold text-blue-500 uppercase tracking-widest text-[10px]">
              {g.league}
            </span>
          )}
          <span>{timeLabel}</span>
        </div>
        <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${
          g.status === 'LIVE' ? 'bg-red-500/10 text-red-500 border border-red-500/20' : 
          g.status === 'FINAL' ? 'bg-zinc-800 text-zinc-400' : 
          'bg-blue-500/10 text-blue-400 border border-blue-500/20'
        }`}>
          {g.status}
        </span>
      </div>
      <div className="space-y-3">
        <div className="flex justify-between items-center">
          <span className="font-semibold text-zinc-200">{g.homeTeam.name}</span>
          {g.homeTeam.score !== undefined && <span className="text-xl font-black text-white">{g.homeTeam.score}</span>}
        </div>
        <div className="flex justify-between items-center">
          <span className="font-semibold text-zinc-200">{g.awayTeam.name}</span>
          {g.awayTeam.score !== undefined && <span className="text-xl font-black text-white">{g.awayTeam.score}</span>}
        </div>
      </div>
    </div>
  )
}



