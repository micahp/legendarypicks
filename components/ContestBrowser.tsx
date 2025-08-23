import { useEffect, useState } from 'react'
import { ContestService } from '../services/contestService'
import ContestEntry from './ContestEntry'

interface Contest {
  contestId: number
  gameIds: string[]
  startTime: number
  endTime: number
  entryFee: number
  maxEntries: number
  requirements: {
    requiredPositions: { [key: string]: number }
    maxPlayersPerTeam: number
    totalPlayers: number
  }
}

interface Game {
  gameId: string
  homeTeam: {
    name: string
  }
  awayTeam: {
    name: string
  }
  startTime: string
}

export default function ContestBrowser() {
  const [contests, setContests] = useState<Contest[]>([])
  const [games] = useState<{[key: string]: Game}>({})
  const [loading, setLoading] = useState(true)
  const [selectedContest, setSelectedContest] = useState<Contest | null>(null)

  useEffect(() => {
    const fetchContests = async () => {
      const contestsData: any = await ContestService.getContests()
      setContests(Object.values(contestsData))
      setLoading(false)
    }

    fetchContests()
  }, [])

  if (loading) {
    return (
      <div className="panel p-4 text-sm">Loading contests...</div>
    )
  }

  if (selectedContest) {
    return (
      <div className="space-y-4">
        <button 
          className="text-emerald-400 hover:text-emerald-300"
          onClick={() => setSelectedContest(null)}
        >
          ← Back to Contests
        </button>
        <ContestEntry contest={selectedContest} />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Available Contests</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {contests.map((contest) => (
          <div 
            key={contest.contestId}
            className="panel p-4 hover:border-emerald-400 cursor-pointer"
            onClick={() => setSelectedContest(contest)}
          >
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <h3 className="font-semibold">Contest #{contest.contestId}</h3>
                <span className="px-2 py-1 rounded bg-zinc-800 text-emerald-400 font-semibold">{contest.entryFee} FLOW</span>
              </div>
              <div className="text-sm text-zinc-400">
                {contest.gameIds.map(gameId => (
                  <div key={gameId} className="flex items-center justify-between">
                    <div>Game {gameId}</div>
                  </div>
                ))}
              </div>
              <div className="text-sm">
                <span className="text-zinc-500">Required:</span>
                {Object.entries(contest.requirements.requiredPositions).map(([pos, count]) => (
                  <span key={pos} className="ml-2">
                    {count} {pos}
                  </span>
                ))}
              </div>
              <div className="text-sm text-zinc-400">
                {contest.maxEntries - (contest as any).entries?.length || contest.maxEntries} spots remaining
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
} 