import { useState, useEffect } from 'react'
import { useRouter } from 'next/router'
import { SportsService, Game } from '../services/sports'
import DayStrip from '../components/Scores/DayStrip'
import CalendarPopover from '../components/Scores/CalendarPopover'
import GameCard from '../components/Scores/GameCard'
import { SkeletonList, ErrorBanner, EmptyState } from '../components/Scores/States'

const LEAGUE_PRIORITY = ['NBA', 'MLB', 'NHL', 'NFL', 'COD', 'ATP', 'WTA', 'UFC']
const LEAGUES = ['All', 'NBA', 'MLB', 'NHL', 'NFL', 'ATP', 'WTA', 'UFC', 'Call of Duty']

export default function ScoresPage() {
  const router = useRouter()
  const today = new Date().toLocaleDateString('en-CA')
  const [date, setDate] = useState<string>(today)
  const [leagueFilter, setLeagueFilter] = useState<string>('All')

  // allow a shareable/deep-linkable day via ?date=YYYY-MM-DD
  useEffect(() => {
    const q = router.query.date
    if (typeof q === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(q)) setDate(q)
    const l = router.query.league
    if (typeof l === 'string' && LEAGUES.includes(l)) setLeagueFilter(l)
  }, [router.query.date, router.query.league])

  const [games, setGames] = useState<Game[]>([])
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        let data: Game[]
        if (leagueFilter === 'All') {
          data = await SportsService.getAllGamesByDate(date)
        } else {
          const l = leagueFilter === 'Call of Duty' ? 'cod' : leagueFilter.toLowerCase()
          data = await SportsService.getGamesByDate(l, date)
        }
        setGames(Array.isArray(data) ? data : [])
      } catch (e: any) {
        setError('Unable to load games right now. Try another date.')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [date, leagueFilter])

  const groupedGames = games.reduce((acc, g) => {
    const l = g.league || 'OTHER'
    if (!acc[l]) acc[l] = []
    acc[l].push(g)
    return acc
  }, {} as Record<string, Game[]>)

  const sortedLeagues = Object.keys(groupedGames).sort((a, b) => {
    const pa = LEAGUE_PRIORITY.indexOf(a)
    const pb = LEAGUE_PRIORITY.indexOf(b)
    if (pa === -1) return 1
    if (pb === -1) return -1
    return pa - pb
  })

  const sortGames = (gs: Game[]) => {
    return [...gs].sort((a, b) => {
      const statusOrder = { LIVE: 0, SCHEDULED: 1, FINAL: 2 }
      if (statusOrder[a.status] !== statusOrder[b.status]) {
        return statusOrder[a.status] - statusOrder[b.status]
      }
      return new Date(a.startTime).getTime() - new Date(b.startTime).getTime()
    })
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 px-4 py-8">
      <div className="max-w-6xl mx-auto space-y-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <h1 className="text-3xl font-extrabold tracking-tight">Scoreboard</h1>
          <div className="flex items-center gap-3">
            <select
              value={leagueFilter}
              onChange={(e) => setLeagueFilter(e.target.value)}
              className="bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {LEAGUES.map((l) => (
                <option key={l} value={l}>
                  {l === 'All' ? 'All Leagues' : l}
                </option>
              ))}
            </select>
            <CalendarPopover
              date={date}
              onChange={setDate}
              anchorContent={
                <span className="flex items-center gap-2 bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2">
                  <span className="text-sm text-zinc-300">
                    {new Date(date).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}
                  </span>
                  <span aria-hidden>📅</span>
                </span>
              }
            />
          </div>
        </div>
        <DayStrip date={date} onChange={setDate} />
        <div className="text-sm font-bold text-zinc-400" aria-live="polite">
          {(() => {
            const d = new Date(date)
            return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
          })()}
        </div>
        {error && <ErrorBanner message={error} />}
        {loading ? (
          <SkeletonList />
        ) : games.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="space-y-12">
            {sortedLeagues.map((league) => (
              <div key={league} className="space-y-4">
                <div className="flex items-center gap-4">
                  <h2 className="text-xl font-bold tracking-tight text-white">{league}</h2>
                  <div className="h-px flex-1 bg-zinc-800" />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {sortGames(groupedGames[league]).map((g) => (
                    <GameCard key={g.gameId} {...g} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

