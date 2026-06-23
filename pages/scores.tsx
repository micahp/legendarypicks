import { useState, useEffect } from 'react'
import Head from 'next/head'
import { useRouter } from 'next/router'
import { SportsService, Game } from '../services/sports'
import GameCard from '../components/Scores/GameCard'
import { SkeletonList, ErrorBanner, EmptyState } from '../components/Scores/States'

const LEAGUE_PRIORITY = ['NBA', 'MLB', 'NHL', 'NFL', 'COD', 'ATP', 'WTA', 'UFC']
const LEAGUES = ['All', 'NBA', 'MLB', 'NHL', 'NFL', 'ATP', 'WTA', 'UFC', 'Call of Duty']

// Revalidate interval for live games (ms) — must not be statically cached
const LIVE_POLL_MS = 30_000

export default function ScoresPage() {
  const router = useRouter()
  const today = new Date().toLocaleDateString('en-CA')
  const [date, setDate] = useState<string>(today)
  const [leagueFilter, setLeagueFilter] = useState<string>('All')
  const isToday = date === today
  const shiftDay = (delta: number) => {
    const d = new Date(date + 'T12:00:00')   // noon-anchored to dodge TZ rollover
    d.setDate(d.getDate() + delta)
    setDate(d.toLocaleDateString('en-CA'))
  }
  const goToday = () => setDate(today)

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
    let ignore = false
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
        if (!ignore) {
          setGames(Array.isArray(data) ? data : [])
          setLoading(false)
        }
      } catch (e: any) {
        if (!ignore) setError('Unable to load games right now. Try another date.')
      }
    }
    load()
    return () => { ignore = true }
  }, [date, leagueFilter])

  // ── live-score polling ──────────────────────────────────────────
  // Live scores must not be frozen; re-fetch every LIVE_POLL_MS when
  // any game is in-progress.  When status flips to post the backend
  // will reconcile from boxscore on the next tick.
  useEffect(() => {
    const liveCount = games.filter(g => g.status === 'LIVE').length
    if (liveCount === 0) return
    let ignore = false
    const timer = setInterval(() => {
      const refetch = async () => {
        try {
          let data: Game[]
          if (leagueFilter === 'All') {
            data = await SportsService.getAllGamesByDate(date)
          } else {
            const l = leagueFilter === 'Call of Duty' ? 'cod' : leagueFilter.toLowerCase()
            data = await SportsService.getGamesByDate(l, date)
          }
          if (!ignore) setGames(Array.isArray(data) ? data : [])
        } catch { /* silent — keep stale scores rather than blank */ }
      }
      refetch()
    }, LIVE_POLL_MS)
    return () => { ignore = true; clearInterval(timer) }
  }, [games, date, leagueFilter])

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
    <>
      <Head>
        <meta httpEquiv="Cache-Control" content="no-store, max-age=0" />
        <title>Scoreboard — Legendary Picks</title>
      </Head>
      <div className="space-y-6">
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
          </div>
        </div>
        {/* Day navigator: ‹ date › — works on mobile (just two buttons + a label) */}
        <div className="flex items-center justify-center gap-2 sm:gap-3">
          <button
            type="button"
            onClick={() => shiftDay(-1)}
            aria-label="Previous day"
            className="flex items-center justify-center w-10 h-10 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-300 text-xl leading-none hover:bg-zinc-800 active:scale-95"
          >
            ‹
          </button>
          <div className="min-w-[11rem] text-center" aria-live="polite">
            <span className="text-sm font-bold text-zinc-200">
              {new Date(date + 'T12:00:00').toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })}
            </span>
            {!isToday && (
              <button type="button" onClick={goToday} className="block mx-auto mt-0.5 text-xs font-medium text-emerald-400 hover:text-emerald-300">
                Jump to today
              </button>
            )}
          </div>
          <button
            type="button"
            onClick={() => shiftDay(1)}
            aria-label="Next day"
            className="flex items-center justify-center w-10 h-10 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-300 text-xl leading-none hover:bg-zinc-800 active:scale-95"
          >
            ›
          </button>
        </div>
        {error && <ErrorBanner message={error} />}
        {loading ? (
          <SkeletonList />
        ) : games.length === 0 ? (
          <EmptyState leagueFilter={leagueFilter} onViewAll={() => setLeagueFilter('All')} />
        ) : (
          <div className="space-y-12">
            {sortedLeagues.map((league) => {
              const leagueGames = groupedGames[league]
              const subGroups: Record<string, Game[]> = {}
              for (const g of leagueGames) {
                const key = g.subtitle || ''
                if (!subGroups[key]) subGroups[key] = []
                subGroups[key].push(g)
              }
              const subKeys = Object.keys(subGroups)
              return (
                <div key={league} className="space-y-4">
                  <div className="flex items-center gap-4">
                    <h2 className="text-xl font-bold tracking-tight text-white">{league}</h2>
                    <div className="h-px flex-1 bg-zinc-800" />
                  </div>
                  {subKeys.map((sub) => {
                    const sg = subGroups[sub]
                    // Compute shared time if all games in this group have the same start time
                    const times = [...new Set(sg.map((g: Game) => {
                      const d = new Date(g.startTime)
                      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                    }))]
                    const timeLabel = times.length === 1 ? ' · ' + times[0] : ''
                    return (
                    <div key={sub || league} className="space-y-3">
                      {sub && (
                        <h3 className="text-sm font-semibold text-zinc-400 uppercase tracking-wide">
                          {sub}{timeLabel}
                        </h3>
                      )}
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {sortGames(sg).map((g) => (
                          <GameCard key={g.gameId} {...g} />
                        ))}
                      </div>
                    </div>
                  )})}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </>
  )
}

