import { useState } from 'react'
import { SportsService } from '../services/sports'

const leagues = ['nba', 'nfl', 'nhl', 'mlb']

export default function PlayerStatsPage() {
  const [league, setLeague] = useState('nba')
  const [playerId, setPlayerId] = useState('')
  const [stats, setStats] = useState<any | null>(null)

  const fetchStats = async () => {
    if (!playerId) return
    const data = await SportsService.getPlayerStats(league, playerId)
    setStats(data)
  }

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-bold">Player Stats</h1>
      <div className="flex gap-2">
        <select value={league} onChange={e => setLeague(e.target.value)} className="border p-2 rounded">
          {leagues.map(l => (
            <option key={l} value={l}>{l.toUpperCase()}</option>
          ))}
        </select>
        <input value={playerId} onChange={e => setPlayerId(e.target.value)} placeholder="Player ID" className="border p-2 rounded" />
        <button onClick={fetchStats} className="bg-blue-600 text-white px-4 py-2 rounded">Load Stats</button>
      </div>
      {stats && (
        <pre className="bg-gray-100 p-4 rounded overflow-auto text-sm">{JSON.stringify(stats, null, 2)}</pre>
      )}
    </div>
  )
}
