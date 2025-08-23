import { useState, useEffect } from 'react'
import { NBAGameService } from '../services/nbaGames'
import DayStrip from '../components/Scores/DayStrip'
import CalendarPopover from '../components/Scores/CalendarPopover'
import ProviderToggle from '../components/Scores/ProviderToggle'
import GameCard from '../components/Scores/GameCard'
import { SkeletonList, ErrorBanner, EmptyState } from '../components/Scores/States'

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
  const [error, setError] = useState<string | null>(null)
  const [provider, setProvider] = useState<'fastapi' | 'sportsdata' | 'nba_api'>(() =>
    (process.env.NBA_PROVIDER as any) || 'fastapi'
  )

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await NBAGameService.getGamesByDate(date, provider)
        setGames(Array.isArray(data) ? data : [])
      } catch (e: any) {
        setError('Unable to load games right now. Try another date.')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [date, provider])

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 px-4 py-8">
      <div className="max-w-6xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-extrabold tracking-tight">NBA Scoreboard</h1>
          <div className="flex items-center gap-3">
            <ProviderToggle
              provider={provider}
              onChange={setProvider}
              sportsdataAvailable={Boolean(process.env.SPORTSDATA_KEY)}
            />
            <CalendarPopover date={date} onChange={setDate} />
          </div>
        </div>
        <DayStrip date={date} onChange={setDate} />
        {error && <ErrorBanner message={error} />}
        {loading ? (
          <SkeletonList />
        ) : games.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {games.map((g) => (
              <GameCard key={g.gameId} {...g} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
