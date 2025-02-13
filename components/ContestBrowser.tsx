import { useEffect, useState } from 'react'
import { ContestService } from '../services/contestService'
import { NBAGameService } from '../services/nbaGames'
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
  const [games, setGames] = useState<{[key: string]: Game}>({})
  const [loading, setLoading] = useState(true)
  const [selectedContest, setSelectedContest] = useState<Contest | null>(null)

  useEffect(() => {
    const fetchContests = async () => {
      const contestsData = await ContestService.getContests()
      setContests(Object.values(contestsData))

      // Fetch game details for all contests
      const gameIds = new Set(
        Object.values(contestsData).flatMap(contest => contest.gameIds)
      )
      
      const gamesData: {[key: string]: Game} = {}
      for (const gameId of gameIds) {
        const game = await NBAGameService.getGameDetails(gameId)
        if (game) {
          gamesData[gameId] = game
        }
      }
      
      setGames(gamesData)
      setLoading(false)
    }

    fetchContests()
  }, [])

  if (loading) {
    return <div>Loading contests...</div>
  }

  if (selectedContest) {
    return (
      <div>
        <button 
          className="mb-4 text-blue-500"
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
            className="border rounded-lg p-4 hover:border-blue-500 cursor-pointer"
            onClick={() => setSelectedContest(contest)}
          >
            <div className="space-y-2">
              <div className="flex justify-between">
                <h3 className="font-semibold">Contest #{contest.contestId}</h3>
                <span className="text-green-600">{contest.entryFee} FLOW</span>
              </div>
              
              <div className="text-sm text-gray-600">
                {contest.gameIds.map(gameId => {
                  const game = games[gameId]
                  return game ? (
                    <div key={gameId}>
                      {game.homeTeam.name} vs {game.awayTeam.name}
                      <span className="text-gray-400 ml-2">
                        {new Date(game.startTime).toLocaleTimeString()}
                      </span>
                    </div>
                  ) : null
                })}
              </div>

              <div className="text-sm">
                <span className="text-gray-500">Required:</span>
                {Object.entries(contest.requirements.requiredPositions).map(([pos, count]) => (
                  <span key={pos} className="ml-2">
                    {count} {pos}
                  </span>
                ))}
              </div>

              <div className="text-sm text-gray-500">
                {contest.maxEntries - (contest as any).entries?.length || contest.maxEntries} spots remaining
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
} 