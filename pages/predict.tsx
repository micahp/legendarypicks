import { useEffect, useState } from 'react'
import { SportsService } from '../services/sports'

interface Game {
  gameId: string
  homeTeam: { teamId: string; name: string; score?: number }
  awayTeam: { teamId: string; name: string; score?: number }
  status: string
}

interface Prediction {
  id: number
  league: string
  gameId: string
  predictedWinner: string
  correct: boolean | null
}

const leagues = ['nba', 'nfl', 'nhl', 'mlb']

export default function PredictionsPage() {
  const [league, setLeague] = useState('nba')
  const [games, setGames] = useState<Game[]>([])
  const [selectedGame, setSelectedGame] = useState('')
  const [predictedWinner, setPredictedWinner] = useState('')
  const [predictions, setPredictions] = useState<Prediction[]>([])

  useEffect(() => {
    const fetchGames = async () => {
      const g = await SportsService.getGames(league)
      setGames(g)
      if (g.length > 0) {
        setSelectedGame(g[0].gameId)
        setPredictedWinner(g[0].homeTeam.teamId)
      }
    }
    fetchGames()
  }, [league])

  useEffect(() => {
    const fetchPreds = async () => {
      const p = await SportsService.getPredictions()
      setPredictions(p)
    }
    fetchPreds()
  }, [])

  const submit = async () => {
    await SportsService.submitPrediction(league, selectedGame, predictedWinner)
    const p = await SportsService.getPredictions()
    setPredictions(p)
  }

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">Predictions</h1>
      <div className="space-y-4">
        <div className="flex gap-2">
          <select value={league} onChange={e => setLeague(e.target.value)} className="border p-2 rounded">
            {leagues.map(l => <option key={l} value={l}>{l.toUpperCase()}</option>)}
          </select>
          <select value={selectedGame} onChange={e => setSelectedGame(e.target.value)} className="border p-2 rounded">
            {games.map(g => (
              <option key={g.gameId} value={g.gameId}>
                {g.awayTeam.name} at {g.homeTeam.name}
              </option>
            ))}
          </select>
          <select value={predictedWinner} onChange={e => setPredictedWinner(e.target.value)} className="border p-2 rounded">
            {selectedGame && (
              games.filter(g => g.gameId === selectedGame).map(g => (
                [g.homeTeam, g.awayTeam].map(t => (
                  <option key={t.teamId} value={t.teamId}>{t.name}</option>
                ))
              ))
            )}
          </select>
          <button onClick={submit} className="bg-blue-600 text-white px-4 py-2 rounded">Submit</button>
        </div>
      </div>

      <div className="mt-6">
        <h2 className="text-xl font-semibold mb-2">Your Predictions</h2>
        <table className="min-w-full text-sm">
          <thead>
            <tr>
              <th className="text-left">League</th>
              <th className="text-left">Game</th>
              <th className="text-left">Prediction</th>
              <th className="text-left">Correct?</th>
            </tr>
          </thead>
          <tbody>
            {predictions.map(p => (
              <tr key={p.id} className="border-t">
                <td className="pr-2 py-1">{p.league.toUpperCase()}</td>
                <td className="pr-2 py-1">{p.gameId}</td>
                <td className="pr-2 py-1">{p.predictedWinner}</td>
                <td className="pr-2 py-1">{p.correct === null ? 'Pending' : p.correct ? 'Yes' : 'No'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
