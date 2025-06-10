import { useEffect, useState } from 'react'
import { SportsService } from '../services/sports'

interface Game {
  gameId: string
  homeTeam: { teamId: string; name: string; score?: number }
  awayTeam: { teamId: string; name: string; score?: number }
  startTime?: string
  status: string
}

const leagues = ['nba', 'nfl', 'nhl', 'mlb']

export default function GamesPage() {
  const [league, setLeague] = useState('nba')
  const [games, setGames] = useState<Game[]>([])

  useEffect(() => {
    SportsService.getGames(league).then(setGames)
  }, [league])

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-bold">Upcoming Games</h1>
      <select value={league} onChange={e => setLeague(e.target.value)} className="border p-2 rounded">
        {leagues.map(l => (
          <option key={l} value={l}>{l.toUpperCase()}</option>
        ))}
      </select>
      <ul className="space-y-2">
        {games.map(g => (
          <li key={g.gameId} className="border p-2 rounded">
            <span className="font-medium">{g.awayTeam.name}</span> at <span className="font-medium">{g.homeTeam.name}</span>
            <span className="ml-2 text-sm text-gray-500">{g.status}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
