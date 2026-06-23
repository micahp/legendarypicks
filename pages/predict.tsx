import { useEffect, useState, useMemo } from 'react'
import Head from 'next/head'
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
  const [loading, setLoading] = useState(true)
  const [predsLoading, setPredsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Build a gameId -> "{away} at {home}" lookup from loaded games
  const gameNames = useMemo(() => {
    const map = new Map<string, string>()
    for (const g of games) {
      map.set(g.gameId, `${g.awayTeam.name} at ${g.homeTeam.name}`)
    }
    return map
  }, [games])

  useEffect(() => {
    const fetchGames = async () => {
      setLoading(true)
      setError(null)
      try {
        const g = await SportsService.getGames(league)
        setGames(g)
        if (g.length > 0) {
          setSelectedGame(g[0].gameId)
          setPredictedWinner(g[0].homeTeam.teamId)
        }
      } catch {
        setError('Could not load games. Try again.')
      } finally {
        setLoading(false)
      }
    }
    fetchGames()
  }, [league])

  useEffect(() => {
    const fetchPreds = async () => {
      setPredsLoading(true)
      try {
        const p = await SportsService.getPredictions(league)
        setPredictions(p)
      } catch { /* silent */ }
      finally { setPredsLoading(false) }
    }
    fetchPreds()
  }, [league])

  const submit = async () => {
    setSubmitting(true)
    try {
      await SportsService.submitPrediction(league, selectedGame, predictedWinner)
      const p = await SportsService.getPredictions(league)
      setPredictions(p)
    } catch {
      setError('Failed to submit prediction.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <Head>
        <title>Predictions — Legendary Picks</title>
        <meta name="description" content="Make sports predictions and track your accuracy" />
      </Head>
      <div className="space-y-6">
        <h1 className="text-3xl font-extrabold tracking-tight">Predictions</h1>

        {error && (
          <div className="rounded-lg border border-red-500/40 bg-red-950/40 text-red-200 px-4 py-3">
            {error}
          </div>
        )}

        <div className="space-y-4">
          {loading ? (
            <div className="flex gap-2">
              {[1,2,3,4].map(i => (
                <div key={i} className="h-10 w-24 bg-zinc-800 rounded-lg animate-pulse" />
              ))}
            </div>
          ) : games.length === 0 ? (
            <p className="text-zinc-500">No games available for {league.toUpperCase()}.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              <select
                value={league}
                onChange={e => setLeague(e.target.value)}
                className="px-3 py-2 rounded-lg border border-zinc-800 bg-zinc-900 text-zinc-200"
              >
                {leagues.map(l => <option key={l} value={l}>{l.toUpperCase()}</option>)}
              </select>
              <select
                value={selectedGame}
                onChange={e => setSelectedGame(e.target.value)}
                className="px-3 py-2 rounded-lg border border-zinc-800 bg-zinc-900 text-zinc-200"
              >
                {games.map(g => (
                  <option key={g.gameId} value={g.gameId}>
                    {g.awayTeam.name} at {g.homeTeam.name}
                  </option>
                ))}
              </select>
              <select
                value={predictedWinner}
                onChange={e => setPredictedWinner(e.target.value)}
                className="px-3 py-2 rounded-lg border border-zinc-800 bg-zinc-900 text-zinc-200"
              >
                {selectedGame && (
                  games.filter(g => g.gameId === selectedGame).map(g => (
                    [g.homeTeam, g.awayTeam].map(t => (
                      <option key={t.teamId} value={t.teamId}>{t.name}</option>
                    ))
                  ))
                )}
              </select>
              <button
                onClick={submit}
                disabled={submitting || !selectedGame}
                className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold transition-colors"
              >
                {submitting ? 'Submitting…' : 'Submit'}
              </button>
            </div>
          )}
        </div>

        <div className="mt-6">
          <h2 className="text-xl font-bold mb-2">Your Predictions</h2>
          {predsLoading ? (
            <div className="space-y-2">
              {[1,2,3].map(i => (
                <div key={i} className="h-8 bg-zinc-800 rounded animate-pulse" />
              ))}
            </div>
          ) : predictions.length === 0 ? (
            <p className="text-zinc-500">No predictions yet. Pick a game above.</p>
          ) : (
            <table className="min-w-full text-sm">
              <thead className="text-zinc-400">
                <tr>
                  <th className="text-left font-medium">League</th>
                  <th className="text-left font-medium">Game</th>
                  <th className="text-left font-medium">Prediction</th>
                  <th className="text-left font-medium">Correct?</th>
                </tr>
              </thead>
              <tbody>
                {predictions.map(p => (
                  <tr key={p.id} className="border-t border-zinc-800">
                    <td className="pr-2 py-2">{p.league.toUpperCase()}</td>
                    <td className="pr-2 py-2">{gameNames.get(p.gameId) ?? p.gameId}</td>
                    <td className="pr-2 py-2">{p.predictedWinner}</td>
                    <td className="pr-2 py-2">{p.correct === null ? 'Pending' : p.correct ? '✅' : '❌'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  )
}
