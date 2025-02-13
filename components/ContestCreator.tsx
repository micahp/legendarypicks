import { useEffect, useState } from 'react'
import { NBAGameService } from '../services/nbaGames'
import { ContestService } from '../services/contestService'

interface Game {
  gameId: string
  homeTeam: {
    teamId: string
    name: string
  }
  awayTeam: {
    teamId: string
    name: string
  }
  startTime: string
}

interface Player {
  playerId: string
  name: string
  team: string
  position: string
  jerseyNumber: string
}

interface TeamRosters {
  [teamId: string]: Player[]
}

export default function ContestCreator() {
  const [games, setGames] = useState<Game[]>([])
  const [selectedGames, setSelectedGames] = useState<string[]>([])
  const [rosters, setRosters] = useState<TeamRosters>({})
  const [loading, setLoading] = useState(true)
  const [entryFee, setEntryFee] = useState<number>(0)
  const [maxEntries, setMaxEntries] = useState<number>(100)
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    const fetchGames = async () => {
      const todaysGames = await NBAGameService.getTodaysGames()
      setGames(todaysGames)
      setLoading(false)
    }

    fetchGames()
  }, [])

  useEffect(() => {
    const fetchRosters = async () => {
      const selectedTeamIds = games
        .filter(game => selectedGames.includes(game.gameId))
        .flatMap(game => [game.homeTeam.teamId, game.awayTeam.teamId])

      const newRosters: TeamRosters = {}
      
      for (const teamId of selectedTeamIds) {
        if (!rosters[teamId]) {
          const teamRoster = await NBAGameService.getTeamRoster(teamId)
          newRosters[teamId] = teamRoster
        }
      }

      setRosters(prev => ({ ...prev, ...newRosters }))
    }

    if (selectedGames.length > 0) {
      fetchRosters()
    }
  }, [selectedGames, games])

  const handleCreateContest = async () => {
    try {
      setCreating(true)
      const selectedGameData = games.filter(game => selectedGames.includes(game.gameId))
      const startTime = Math.min(...selectedGameData.map(game => new Date(game.startTime).getTime()))
      const endTime = startTime + (24 * 60 * 60 * 1000) // 24 hours after start

      await ContestService.createContest(
        selectedGames,
        startTime / 1000, // Convert to seconds for Flow
        endTime / 1000,
        entryFee,
        maxEntries
      )

      // Reset form
      setSelectedGames([])
      setEntryFee(0)
      setMaxEntries(100)
    } catch (error) {
      console.error("Error creating contest:", error)
    } finally {
      setCreating(false)
    }
  }

  if (loading) {
    return <div>Loading today's games...</div>
  }

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Create Contest</h2>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {games.map((game) => (
          <div 
            key={game.gameId}
            className={`p-4 border rounded-lg cursor-pointer ${
              selectedGames.includes(game.gameId) ? 'border-green-500 bg-green-50' : ''
            }`}
            onClick={() => {
              if (selectedGames.includes(game.gameId)) {
                setSelectedGames(selectedGames.filter(id => id !== game.gameId))
              } else {
                setSelectedGames([...selectedGames, game.gameId])
              }
            }}
          >
            <div className="flex justify-between items-center">
              <div>
                <p className="font-semibold">{game.homeTeam.name}</p>
                <p>vs</p>
                <p className="font-semibold">{game.awayTeam.name}</p>
              </div>
              <div className="text-sm text-gray-500">
                {new Date(game.startTime).toLocaleTimeString()}
              </div>
            </div>

            {selectedGames.includes(game.gameId) && (
              <div className="mt-4 space-y-2">
                <h4 className="font-semibold">Available Players:</h4>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <h5 className="font-medium">{game.homeTeam.name}</h5>
                    {rosters[game.homeTeam.teamId]?.map(player => (
                      <div key={player.playerId} className="text-gray-600">
                        {player.name} - {player.position}
                      </div>
                    ))}
                  </div>
                  <div>
                    <h5 className="font-medium">{game.awayTeam.name}</h5>
                    {rosters[game.awayTeam.teamId]?.map(player => (
                      <div key={player.playerId} className="text-gray-600">
                        {player.name} - {player.position}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      {selectedGames.length > 0 && (
        <div className="space-y-4 p-4 border rounded-lg">
          <h3 className="text-xl font-semibold">Contest Settings</h3>
          
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Entry Fee (FLOW)
              </label>
              <input
                type="number"
                min="0"
                step="0.1"
                value={entryFee}
                onChange={(e) => setEntryFee(parseFloat(e.target.value))}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm"
              />
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Max Entries
              </label>
              <input
                type="number"
                min="1"
                value={maxEntries}
                onChange={(e) => setMaxEntries(parseInt(e.target.value))}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm"
              />
            </div>
          </div>

          <button
            className="w-full bg-green-500 text-white px-4 py-2 rounded-lg disabled:opacity-50"
            onClick={handleCreateContest}
            disabled={creating}
          >
            {creating ? 'Creating...' : `Create Contest with ${selectedGames.length} Games`}
          </button>
        </div>
      )}
    </div>
  )
} 