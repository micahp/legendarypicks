interface TeamInfo {
  name: string
  score?: number
}

interface GameProps {
  gameId: string
  homeTeam: TeamInfo
  awayTeam: TeamInfo
  startTime: string
  status: 'SCHEDULED' | 'LIVE' | 'FINAL'
}

export default function GameCard(g: GameProps) {
  const time = new Date(g.startTime)
  const timeLabel = time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return (
    <div className="bg-zinc-900 text-zinc-100 rounded-xl p-4 shadow border border-zinc-800">
      <div className="flex items-center justify-between text-xs text-zinc-400 mb-2">
        <div>{timeLabel}</div>
        <span className="px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-200">{g.status}</span>
      </div>
      <div className="space-y-3">
        <div className="flex justify-between items-center">
          <span className="font-semibold">{g.homeTeam.name}</span>
          {g.homeTeam.score !== undefined && <span className="text-lg font-bold">{g.homeTeam.score}</span>}
        </div>
        <div className="flex justify-between items-center">
          <span className="font-semibold">{g.awayTeam.name}</span>
          {g.awayTeam.score !== undefined && <span className="text-lg font-bold">{g.awayTeam.score}</span>}
        </div>
      </div>
    </div>
  )
}


