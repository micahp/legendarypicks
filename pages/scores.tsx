import { useState, useEffect } from 'react'
import Head from 'next/head'
import Link from 'next/link'
import { useRouter } from 'next/router'
import { SportsService, Game } from '../services/sports'
import GameCard from '../components/Scores/GameCard'
import { SkeletonList, ErrorBanner, EmptyState } from '../components/Scores/States'
import ListenLive from '../components/ListenLive'
import LiveDiscounts from '../components/LiveDiscounts'

function gameHref(game: Game) {
  if (game.league === 'COD') {
    return game.detailGameId ? `/game/call-of-duty/${game.detailGameId}` : '/esports/call-of-duty'
  }
  return `/game/${game.league?.toLowerCase()}/${game.gameId}`
}

// ── Broadcast Rail live section (DESIGN-live-card-rail.md) ──
// Solid surface + emerald breathing left edge. No opacity hacks, no label.
// Featured game gets display scores; rest are compact inline chips.
function LiveNow({ games, esportsLive }: { games: Game[]; esportsLive: boolean }) {
  const live = games.filter((g) => g.status === 'LIVE').sort((a, b) => {
    const pa = LEAGUE_PRIORITY.indexOf(a.league || ''), pb = LEAGUE_PRIORITY.indexOf(b.league || '')
    return (pa === -1 ? 99 : pa) - (pb === -1 ? 99 : pb)
  })
  if (live.length === 0) return null
  const feat = live[0]
  const rest = live.slice(1)
  const teamDisplay = (t: Game['awayTeam']) => t.nickname || t.name.replace(/\s*\(.*?\)\s*/g, '')

  return (
    <div className="rounded-r-xl bg-zinc-900 live-edge">

      {/* featured game */}
      <Link href={gameHref(feat)}
            className="block px-5 py-4 hover:bg-zinc-800/50 transition-colors rounded-r-xl group">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-[10px] font-semibold uppercase tracking-[0.15em] text-emerald-400">{feat.league}</span>
          <span className="text-[10px] text-zinc-600">·</span>
          <span className="text-[10px] font-medium uppercase tracking-[0.1em] text-zinc-500">live</span>
          {feat.subtitle ? <><span className="text-[10px] text-zinc-600">·</span><span className="text-[10px] text-zinc-500">{feat.subtitle}</span></> : null}
        </div>

        <div className="space-y-1">
          <div className="flex items-center justify-between gap-4">
            <span className="text-lg font-semibold text-zinc-100 truncate">{teamDisplay(feat.awayTeam)}</span>
            <span className="font-mono text-4xl font-bold tabular-nums text-zinc-100 tracking-tight">{feat.awayTeam.score ?? 0}</span>
          </div>
          <div className="flex items-center justify-between gap-4">
            <span className="text-lg font-semibold text-zinc-100 truncate">{teamDisplay(feat.homeTeam)}</span>
            <span className="font-mono text-4xl font-bold tabular-nums text-zinc-100 tracking-tight">{feat.homeTeam.score ?? 0}</span>
          </div>
        </div>
      </Link>

      {feat.league === 'WC' ? <ListenLive /> : null}

      {/* One game, then two ways out. This used to inline a chip for every other
          live game, which on a summer evening is fifteen MLB scores squeezed to
          70px of team name each — a second, worse scoreboard sitting on top of
          the scoreboard. The rail picks ONE game and points at the rest. */}
      {(rest.length > 0 || esportsLive) ? (
        <div className="flex flex-wrap items-center gap-2 px-5 pb-4">
          {rest.length > 0 ? (
            <Link
              href="/scores?live=1"
              className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900/70 px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:border-emerald-500/50 hover:text-emerald-400"
            >
              {rest.length} more live game{rest.length === 1 ? '' : 's'} →
            </Link>
          ) : null}
          {esportsLive ? (
            <Link
              href="/esports"
              className="inline-flex items-center gap-1.5 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-1.5 text-xs font-medium text-red-400 transition-colors hover:border-red-500/60"
            >
              <span className="block h-1.5 w-1.5 shrink-0 rounded-full bg-red-500 animate-pulse motion-reduce:animate-none" />
              Watch live esports →
            </Link>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

const LEAGUE_PRIORITY = ['NBA', 'MLB', 'NHL', 'NFL', 'COD', 'WC', 'ATP', 'WTA', 'UFC']
const LEAGUES = ['All', 'NBA', 'MLB', 'NHL', 'NFL', 'ATP', 'WTA', 'UFC', 'Call of Duty', 'FIFA World Cup']

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

  // ?live=1 — the destination the rail's "more live games" points at. A whole
  // scoreboard showing only what is in progress, rather than a live game buried
  // among the finals and the not-yet-started.
  const liveOnly = router.query.live === '1'

  const [games, setGames] = useState<Game[]>([])
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  // Is anything live on the esports page right now? Drives whether the chip says "Live esports".
  const [esportsLive, setEsportsLive] = useState(false)
  useEffect(() => {
    let ignore = false
    const check = async () => {
      try {
        const r = await fetch('/api/esports/upcoming', { cache: 'no-store' })
        const d = await r.json()
        if (!ignore) setEsportsLive(Array.isArray(d?.matches) && d.matches.some((m: any) => m.live))
      } catch { /* leave as-is */ }
    }
    check()
    const t = setInterval(check, LIVE_POLL_MS)
    return () => { ignore = true; clearInterval(t) }
  }, [])

  useEffect(() => {
    let ignore = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        if (leagueFilter === 'All') {
          // Progressive: paint each league as it resolves so the fast ones (<200ms) show
          // immediately instead of the whole board waiting on the slowest (cod ~1.3s).
          setGames([])
          const leagues = ['nba', 'mlb', 'nhl', 'nfl', 'atp', 'wta', 'cod', 'ufc', 'wc']
          let cleared = false
          const clearOnce = () => { if (!cleared && !ignore) { cleared = true; setLoading(false) } }
          const settled = await Promise.allSettled(leagues.map(async (l) => {
            const g = await SportsService.getGamesByLocalDate(l, date)
            if (!ignore && g.length) { setGames((prev) => [...prev, ...g]); clearOnce() }
          }))
          if (!ignore && settled.every((r) => r.status === 'rejected')) {
            setError('Unable to load games right now. Try another date.')
          }
          clearOnce() // clear even if every league was empty
        } else {
          const l = leagueFilter === 'Call of Duty' ? 'cod' : leagueFilter === 'FIFA World Cup' ? 'wc' : leagueFilter.toLowerCase()
          const data = await SportsService.getGamesByLocalDate(l, date)
          if (!ignore) setGames(Array.isArray(data) ? data : [])
        }
      } catch (e: any) {
        if (!ignore) setError('Unable to load games right now. Try another date.')
      } finally {
        if (!ignore) setLoading(false)
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
            data = await SportsService.getAllGamesByLocalDate(date)
          } else {
            const l = leagueFilter === 'Call of Duty' ? 'cod' : leagueFilter === 'FIFA World Cup' ? 'wc' : leagueFilter.toLowerCase()
            data = await SportsService.getGamesByLocalDate(l, date)
          }
          if (!ignore) setGames(Array.isArray(data) ? data : [])
        } catch { /* silent — keep stale scores rather than blank */ }
      }
      refetch()
    }, LIVE_POLL_MS)
    return () => { ignore = true; clearInterval(timer) }
  }, [games, date, leagueFilter])

  const visibleGames = liveOnly ? games.filter((g) => g.status === 'LIVE') : games

  const groupedGames = visibleGames.reduce((acc, g) => {
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
            <h1 className="text-3xl font-extrabold tracking-tight">
            {liveOnly ? 'Live now' : 'Scoreboard'}
          </h1>
          <div className="flex items-center gap-3">
            <div className="relative">
              <select
                value={leagueFilter}
                onChange={(e) => setLeagueFilter(e.target.value)}
                className="appearance-none bg-zinc-900 border border-zinc-800 rounded-lg pl-3 pr-8 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {LEAGUES.map((l) => (
                  <option key={l} value={l}>
                    {l === 'All' ? 'All Leagues' : l}
                  </option>
                ))}
              </select>
              <svg
                className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-500"
                viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg"
              >
                <path d="M5 7.5L10 12.5L15 7.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
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
        {isToday ? <LiveDiscounts /> : null}
        {liveOnly ? (
          <Link href="/scores" className="inline-block text-sm text-zinc-500 transition-colors hover:text-emerald-400">
            ← Full scoreboard
          </Link>
        ) : null}
        {!liveOnly && !loading && games.length > 0
          ? <LiveNow games={games} esportsLive={esportsLive} /> : null}
        {loading ? (
          <SkeletonList />
        ) : visibleGames.length === 0 ? (
          liveOnly ? (
            <div className="rounded-xl border border-zinc-800 bg-zinc-900 py-16 text-center text-sm text-zinc-500">
              Nothing is live right now.
            </div>
          ) : (
            <EmptyState leagueFilter={leagueFilter} onViewAll={() => setLeagueFilter('All')} />
          )
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
