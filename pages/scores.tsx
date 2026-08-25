import { useState, useEffect, useMemo, useCallback } from 'react'
import Head from 'next/head'
import Link from 'next/link'
import { useRouter } from 'next/router'
import { SportsService, Game } from '../services/sports'
import GameCard from '../components/Scores/GameCard'
import { SkeletonList, ErrorBanner, EmptyState } from '../components/Scores/States'
import ListenLive from '../components/ListenLive'
import LiveDot from '../components/LiveDot'

function gameHref(game: Game) {
  if (game.league === 'COD') {
    return game.detailGameId ? `/game/call-of-duty/${game.detailGameId}` : '/esports/call-of-duty'
  }
  return `/game/${game.league?.toLowerCase()}/${game.gameId}`
}

// ── Broadcast Rail live section (DESIGN-live-card-rail.md) ──
// Solid surface + emerald breathing left edge. No opacity hacks, no label.
// Featured game gets display scores; rest are compact inline chips.
// `isPastDate`: the reader is browsing a date other than today — the rail
// tells them something is live right now, with a quiet way back.
function LiveNow({ games, esportsLive, isPastDate }: { games: Game[]; esportsLive: boolean; isPastDate?: boolean }) {
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
      {(rest.length > 0 || esportsLive || isPastDate) ? (
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
              <LiveDot />
              Watch live esports →
            </Link>
          ) : null}
          {isPastDate ? (
            <Link
              href="/scores"
              className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-800 bg-zinc-900/50 px-3 py-1.5 text-xs font-medium text-emerald-400/90 transition-colors hover:border-emerald-500/50 hover:text-emerald-300"
            >
              Jump to today →
            </Link>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

const LEAGUE_PRIORITY = ['NBA', 'MLB', 'NHL', 'NFL', 'LCUP', 'MLS', 'NCAAF', 'COD', 'WC', 'ATP', 'WTA', 'UFC']
const LEAGUES = ['All', 'NBA', 'MLB', 'NHL', 'NFL', 'Leagues Cup', 'MLS', 'NCAAF', 'ATP', 'WTA', 'UFC', 'Call of Duty', 'FIFA World Cup']
// API keys for the board's league fan-out — shared by the games load and the
// W3 schedule-dates navigation so a day change asks the same leagues it renders.
const LEAGUE_KEYS = ['nba', 'mlb', 'nhl', 'nfl', 'lcup', 'mls', 'ncaaf', 'atp', 'wta', 'cod', 'ufc', 'wc']
// `cod` is breakingpoint.gg, not ESPN. It used to 404 here on every page load
// and every arrow click, so the board could never step to a COD day even when
// one existed. The backend now serves cod/schedule-dates from the store like
// any other league (the ingest captures breakingpoint's whole schedule in one
// request), so it is back in the fan-out and answers honestly: no days held
// means no candidates, which is different from a broken route.
const SCHEDULE_DATE_KEYS = LEAGUE_KEYS
// The visible filter label → API key. Filter names are user-facing; keys are not.
function leagueKeyFor(filter: string): string {
  return filter === 'Call of Duty' ? 'cod'
    : filter === 'FIFA World Cup' ? 'wc'
    : filter === 'Leagues Cup' ? 'lcup'
    : filter.toLowerCase()
}
// Section headings use raw league codes; only the new soccer leagues get a friendlier label.
const LEAGUE_LABELS: Record<string, string> = {
  LCUP: 'Leagues Cup',
  MLS: 'MLS',
}

// Revalidate interval for live games (ms) — must not be statically cached
const LIVE_POLL_MS = 30_000

export default function ScoresPage() {
  const router = useRouter()
  const today = new Date().toLocaleDateString('en-CA')
  const [date, setDate] = useState<string>(today)
  const [leagueFilter, setLeagueFilter] = useState<string>('All')
  const isToday = date === today

  // The URL is the state, not a one-way seed into it. Until 2026-08-25 the query
  // was READ into state below and never written back, so changing the day or the
  // league chip left the URL at a bare `/scores`. Clicking into a game and
  // pressing back then landed on `/scores` with no query, which resets to today
  // with no filter and loses the reader's place. That is the whole bug.
  //
  // Shallow on purpose: the board loads from its own effect keyed on `date`, so a
  // route change must not re-run getServerSideProps or refetch the page.
  const syncQuery = useCallback((next: { date?: string; league?: string }) => {
    const nextDate = next.date ?? date
    const nextLeague = next.league ?? leagueFilter
    const q: Record<string, string> = {}
    // Defaults stay OUT of the URL, so a shared link carries only what was chosen
    // and `/scores` keeps meaning "today, all leagues".
    if (nextDate !== today) q.date = nextDate
    if (nextLeague !== 'All') q.league = nextLeague
    // ?live=1 is a third piece of state read from this same query (the rail's
    // "more live games" destination). It has to survive a day or league change.
    if (router.query.live === '1') q.live = '1'
    router.push({ pathname: '/scores', query: q }, undefined, { shallow: true })
  }, [date, leagueFilter, today, router])

  const selectDate = (d: string) => { setDate(d); syncQuery({ date: d }) }
  const selectLeague = (l: string) => { setLeagueFilter(l); syncQuery({ league: l }) }

  const shiftDay = (delta: number) => {
    // W3 — the arrows jump to the neighbouring date that actually has games
    // (schedule-dates contract) instead of calendar ±1. Strictness from
    // ec5872e is preserved: when the target resolves, the load effect clears
    // stale cards immediately, and partial vs full load failure stays
    // distinguishable. When schedule discovery cannot answer or finds no game
    // in that direction, we do NOT invent a calendar date — the board stays
    // on the anchor, honestly showing what the anchor has.
    const selected = leagueFilter === 'All'
      ? SCHEDULE_DATE_KEYS
      : [leagueKeyFor(leagueFilter)]
    if (!selected.length) return
    SportsService.getNeighbourGameDate(selected, date, delta as -1 | 1)
      .then((target) => {
        if (target) selectDate(target)
      })
      .catch(() => { /* discovery unavailable — stay on the anchor */ })
  }
  const goToday = () => selectDate(today)

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

  // ── live right now, independent of the selected date ────────────────────
  // The live section is a fact about the present, not about the date being
  // browsed (TASK-scoreboard-outcomes-and-homepage.md item 2): a reader on a
  // past date must still see that something is live today. When the board is
  // ON today, the live set is derived from the board's own fetch (the 30s
  // live-score poll keeps it fresh) — zero extra requests. On any other date,
  // today is fetched once per date change, then only the leagues that were
  // live are polled, the same bounded pattern as the poll below; nothing live
  // means no poll, so browsing a past date at 09:50 costs one today-read.
  const [liveGames, setLiveGames] = useState<Game[]>([])

  useEffect(() => {
    if (date === today) setLiveGames(games.filter((g) => g.status === 'LIVE'))
  }, [date, today, games])

  useEffect(() => {
    if (date === today) return
    let ignore = false
    let pollTimer: ReturnType<typeof setInterval> | null = null
    const refresh = async (leagues?: string[]) => {
      try {
        const data = leagues && leagues.length
          ? (await Promise.all(
              leagues.map((l) => SportsService.getGamesByLocalDate(l, today, { strict: false })),
            )).flat()
          : await SportsService.getAllGamesByLocalDate(today, { strict: false })
        if (ignore) return
        const live = data.filter((g) => g.status === 'LIVE')
        setLiveGames(live)
        const liveLeagues = Array.from(
          new Set(live.map((g) => g.league).filter(Boolean)),
        ) as string[]
        if (pollTimer) clearInterval(pollTimer)
        if (liveLeagues.length) pollTimer = setInterval(() => refresh(liveLeagues), LIVE_POLL_MS)
      } catch {
        /* leave as-is — a stale "something is live" beats a blank section */
      }
    }
    refresh()
    return () => { ignore = true; if (pollTimer) clearInterval(pollTimer) }
  }, [date, today])

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
      // Never let the prior selection remain the page's data while a different
      // calendar day is resolving. Loading has a skeleton; stale games do not.
      setGames([])
      try {
        if (leagueFilter === 'All') {
          // Progressive: paint each league as it resolves so the fast ones (<200ms) show
          // immediately instead of the whole board waiting on the slowest (cod ~1.3s).
          const leagues = LEAGUE_KEYS
          let cleared = false
          const clearOnce = () => { if (!cleared && !ignore) { cleared = true; setLoading(false) } }
          const settled = await Promise.allSettled(leagues.map(async (l) => {
            const g = await SportsService.getGamesByLocalDate(l, date, { strict: true })
            if (!ignore && g.length) { setGames((prev) => [...prev, ...g]); clearOnce() }
          }))
          const failures = settled.filter((result) => result.status === 'rejected').length
          if (!ignore && failures > 0) {
            setError(failures === leagues.length
              ? 'Unable to load games right now. Try another date.'
              : `${failures} league${failures === 1 ? '' : 's'} could not be loaded for this date.`)
          }
          clearOnce() // clear even if every league was empty
        } else {
          const l = leagueKeyFor(leagueFilter)
          const data = await SportsService.getGamesByLocalDate(l, date, { strict: true })
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
  // Only the leagues that actually have a game in progress get re-fetched.
  // Refreshing all of them cost 22 upstream requests per tick (11 leagues x the
  // two local dates) every 30s — ~44/minute into a publisher whose limit is a
  // request COUNT, not a rate, so one open tab exhausted the budget in about
  // two and a half minutes and blanked the board for everything. A live slate is
  // typically one or two leagues, so this is the same freshness for a fraction
  // of the spend, without making live scores any staler.
  const liveLeagues = useMemo(
    () => {
      const seen: Record<string, true> = {}
      games.forEach(g => { if (g.status === 'LIVE' && g.league) seen[g.league] = true })
      return Object.keys(seen)
    },
    [games],
  )
  // The identity of the live leagues, not the games array — otherwise every
  // score update restarts the interval and the poll never actually fires.
  const liveLeagueKey = liveLeagues.slice().sort().join(',')

  useEffect(() => {
    if (!liveLeagueKey) return
    let ignore = false
    const polled = leagueFilter === 'All'
      ? liveLeagueKey.split(',')
      : [leagueKeyFor(leagueFilter)]
    const timer = setInterval(() => {
      const refetch = async () => {
        try {
          const results = await Promise.allSettled(
            polled.map(l => SportsService.getGamesByLocalDate(leagueKeyFor(l), date, { strict: true })),
          )
          const fresh: Game[] = []
          results.forEach(r => { if (r.status === 'fulfilled' && Array.isArray(r.value)) fresh.push(...r.value) })
          if (ignore || fresh.length === 0) return
          // Only the polled leagues are replaced; every other league on the
          // board keeps the rows it already has rather than vanishing.
          const refreshed = new Set(polled.map(l => leagueKeyFor(l)))
          setGames(prev => [...prev.filter(g => !refreshed.has(leagueKeyFor(g.league || ''))), ...fresh])
        } catch { /* silent — keep stale scores rather than blank */ }
      }
      refetch()
    }, LIVE_POLL_MS)
    return () => { ignore = true; clearInterval(timer) }
  }, [liveLeagueKey, date, leagueFilter])

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
                onChange={(e) => selectLeague(e.target.value)}
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
        {/* Live right now — a fact about the present, so it sits ABOVE the
            date control and ignores the selected date (item 2). Renders
            nothing at all when nothing is live: no header, no empty state. */}
        {!liveOnly ? <LiveNow games={liveGames} esportsLive={esportsLive} isPastDate={!isToday} /> : null}
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
        {liveOnly ? (
          <Link href="/scores" className="inline-block text-sm text-zinc-500 transition-colors hover:text-emerald-400">
            ← Full scoreboard
          </Link>
        ) : null}
        {loading ? (
          <SkeletonList />
        ) : visibleGames.length === 0 ? (
          liveOnly ? (
            <div className="rounded-xl border border-zinc-800 bg-zinc-900 py-16 text-center text-sm text-zinc-500">
              Nothing is live right now.
            </div>
          ) : (
            <EmptyState leagueFilter={leagueFilter} onViewAll={() => selectLeague('All')} />
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
                    <h2 className="text-xl font-bold tracking-tight text-white">{LEAGUE_LABELS[league] || league}</h2>
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
