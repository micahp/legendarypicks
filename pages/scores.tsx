import { useState, useEffect } from 'react'
import { NBAGameService } from '../services/nbaGames'

interface Game {
  gameId: string
  homeTeam: { name: string; score?: number }
  awayTeam: { name: string; score?: number }
  startTime: string
  status: 'SCHEDULED' | 'LIVE' | 'FINAL'
}

export default function ScoresPage() {
  const today = new Date().toISOString().split('T')[0]
  const [date, setDate] = useState<string>(today)
  const [games, setGames] = useState<Game[]>([])
  const [loading, setLoading] = useState<boolean>(false)

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      const data = await NBAGameService.getGamesByDate(date)
      setGames(data)
      setLoading(false)
    }
    load()
  }, [date])

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-8">
      <div className="max-w-5xl mx-auto">
        <h1 className="text-3xl font-bold mb-6">NBA Scores</h1>
        <div className="mb-6 flex items-center gap-3">
          <label className="text-sm font-medium">Select Date:</label>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="border px-2 py-1 rounded-md shadow-sm"
          />
        </div>
        {loading ? (
          <div>Loading…</div>
        ) : games.length === 0 ? (
          <div>No games for this date.</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {games.map((g) => (
              <div key={g.gameId} className="bg-white p-4 rounded-lg shadow">
                <div className="text-sm text-gray-500 mb-2">
                  {new Date(g.startTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  <span className="ml-2 px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-600">{g.status}</span>
                </div>
                <div className="space-y-2">
                  <div className="flex justify-between font-semibold">
                    <span>{g.homeTeam.name}</span>
                    {g.homeTeam.score !== undefined && <span>{g.homeTeam.score}</span>}
                  </div>
                  <div className="flex justify-between font-semibold">
                    <span>{g.awayTeam.name}</span>
                    {g.awayTeam.score !== undefined && <span>{g.awayTeam.score}</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
