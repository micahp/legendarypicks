import { useEffect, useState } from 'react'
import * as fcl from "@onflow/fcl"
import { NBAGameService } from '../services/nbaGames'

interface Game {
  gameId: string
  homeTeam: {
    teamId: string
    name: string
    score?: number
  }
  awayTeam: {
    teamId: string
    name: string
    score?: number
  }
  startTime: string
  status: 'SCHEDULED' | 'LIVE' | 'FINAL'
}

export default function GameBrowser() {
  const [games, setGames] = useState<Game[]>([])
  const [user, setUser] = useState<{ addr: string | null }>({ addr: null })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fcl.currentUser.subscribe(setUser)
  }, [])

  useEffect(() => {
    const fetchGames = async () => {
      try {
        console.log("Fetching today's games...")
        const todaysGames = await NBAGameService.getTodaysGames()
        console.log("Games fetched:", todaysGames)
        setGames(todaysGames)
      } catch (error) {
        console.error("Error fetching games:", error)
      } finally {
        setLoading(false)
      }
    }

    fetchGames()
  }, [])

  if (!user.addr) {
    return (
      <div className="flex flex-col items-center justify-center h-64">
        <h2 className="text-2xl font-bold mb-4">Welcome to Legendary Picks</h2>
        <p className="text-gray-600 mb-4">Connect your wallet to start playing</p>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-pulse flex space-x-4">
          <div className="rounded-full bg-slate-200 h-10 w-10"></div>
          <div className="flex-1 space-y-6 py-1">
            <div className="h-2 bg-slate-200 rounded"></div>
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-4">
                <div className="h-2 bg-slate-200 rounded col-span-2"></div>
                <div className="h-2 bg-slate-200 rounded col-span-1"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-xl shadow-sm p-6">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-bold bg-gradient-to-r from-blue-600 to-blue-400 bg-clip-text text-transparent">
          Today's Games
        </h2>
        <div className="flex gap-2">
          <select className="px-3 py-1.5 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="all">All Games</option>
            <option value="live">Live Games</option>
            <option value="upcoming">Upcoming</option>
          </select>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {games.map((game) => (
          <div 
            key={game.gameId} 
            className="relative bg-white rounded-xl border border-gray-100 p-4 shadow-sm hover:shadow-md transition-all duration-200"
          >
            {/* Status Badge */}
            <div className="absolute -top-3 right-4">
              <span className={`text-xs font-medium px-3 py-1 rounded-full ${
                game.status === 'LIVE' ? 'bg-red-100 text-red-700' :
                game.status === 'FINAL' ? 'bg-gray-100 text-gray-700' :
                'bg-emerald-100 text-emerald-700'
              }`}>
                {game.status}
              </span>
            </div>

            {/* Game Time */}
            <div className="text-sm text-gray-500 mb-4">
              {new Date(game.startTime).toLocaleTimeString([], { 
                hour: '2-digit', 
                minute: '2-digit'
              })}
            </div>

            {/* Teams */}
            <div className="space-y-4">
              {/* Home Team */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 bg-gray-100 rounded-full"></div>
                  <span className="font-semibold">{game.homeTeam.name}</span>
                </div>
                {game.homeTeam.score !== undefined && (
                  <span className="text-xl font-bold">{game.homeTeam.score}</span>
                )}
              </div>

              {/* Away Team */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 bg-gray-100 rounded-full"></div>
                  <span className="font-semibold">{game.awayTeam.name}</span>
                </div>
                {game.awayTeam.score !== undefined && (
                  <span className="text-xl font-bold">{game.awayTeam.score}</span>
                )}
              </div>
            </div>

            {/* Action Button */}
            {game.status === 'SCHEDULED' && (
              <button 
                className="w-full mt-6 bg-gradient-to-r from-blue-600 to-blue-400 text-white px-4 py-2.5 rounded-lg 
                  font-medium hover:from-blue-700 hover:to-blue-500 transition-all duration-200 
                  focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
                onClick={() => console.log('Create lineup for game:', game.gameId)}
              >
                Create Lineup
              </button>
            )}
          </div>
        ))}
      </div>

      {games.length === 0 && !loading && (
        <div className="text-center py-12">
          <div className="text-gray-400 text-lg">No games scheduled for today</div>
        </div>
      )}
    </div>
  )
} 