import Head from 'next/head'
import Link from 'next/link'
import { useRouter } from 'next/router'
import { useEffect, useMemo, useState } from 'react'
import GameCard from '../../components/Scores/GameCard'
import HorizontalScrollRail from '../../components/HorizontalScrollRail'
import NewsTab from '../../components/Leagues/NewsTab'
import { useNewsData } from '../../components/Leagues/hooks/useNewsData'
import type { LeagueNews } from '../../components/News/LeagueSection'
import { SportsService } from '../../services/sports'
import type { Game } from '../../services/sports'

type HubTab = 'scores' | 'draws' | 'rankings' | 'news'
type Tour = 'all' | 'atp' | 'wta'

type DrawMatch = {
  game_id: string
  date?: string
  state?: string
  status?: string
  status_detail?: string
  round: string
  home?: { athlete_id?: string; name?: string; seed?: number | null; sets?: number[] }
  away?: { athlete_id?: string; name?: string; seed?: number | null; sets?: number[] }
}

type Draw = {
  league: 'atp' | 'wta'
  event_name: string
  draw_type?: string
  bracket_url?: string
  fetched_at: string
  matches: DrawMatch[]
}

type DrawResponse = {
  available: boolean
  tours: Draw[]
  reason?: string | null
}

type Ranking = {
  espn_athlete_id: string
  player_id: number
  player_name: string
  rank: number
  previous_rank?: number | null
  points?: number | null
}

type RankingTour = {
  tour: 'atp' | 'wta'
  captured_at: string
  rankings: Ranking[]
}

type RankingResponse = {
  available: boolean
  tours: RankingTour[]
  reason?: string | null
}

const TABS: { key: HubTab; label: string }[] = [
  { key: 'scores', label: 'Scores' },
  { key: 'draws', label: 'Draws' },
  { key: 'rankings', label: 'Rankings' },
  { key: 'news', label: 'News' },
]

const TOURS: { key: Tour; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'atp', label: 'ATP' },
  { key: 'wta', label: 'WTA' },
]

const TAB_KEYS = new Set(TABS.map(item => item.key))
const TOUR_KEYS = new Set(TOURS.map(item => item.key))

function localDate(offset = 0) {
  const date = new Date()
  date.setHours(12, 0, 0, 0)
  date.setDate(date.getDate() + offset)
  return date.toLocaleDateString('en-CA')
}

function shiftDate(value: string, offset: number) {
  const date = new Date(`${value}T12:00:00`)
  date.setDate(date.getDate() + offset)
  return date.toLocaleDateString('en-CA')
}

function selectedTours(tour: Tour): ('atp' | 'wta')[] {
  return tour === 'all' ? ['atp', 'wta'] : [tour]
}

function uniqueBy<T>(items: T[], key: (item: T) => string | number): T[] {
  const seen = new Set<string | number>()
  return items.filter(item => {
    const value = key(item)
    if (seen.has(value)) return false
    seen.add(value)
    return true
  })
}

function combineTennisNews(atp: LeagueNews | null, wta: LeagueNews | null): LeagueNews | null {
  if (!atp && !wta) return null
  const feeds = [atp, wta].filter((feed): feed is LeagueNews => Boolean(feed))
  return {
    conversations: uniqueBy(feeds.flatMap(feed => feed.conversations), item => item.conv_id)
      .sort((a, b) => new Date(b.story_time || b.generated_at).getTime() - new Date(a.story_time || a.generated_at).getTime()),
    narratives: uniqueBy(feeds.flatMap(feed => feed.narratives), item => item.id),
    granular: uniqueBy(feeds.flatMap(feed => feed.granular), item => item.id),
    other: feeds.reduce((total, feed) => total + feed.other, 0),
  }
}

export default function TennisLeaguePage() {
  const router = useRouter()
  const [tab, setTab] = useState<HubTab>('scores')
  const [tour, setTour] = useState<Tour>('all')
  const [date, setDate] = useState(localDate())
  const [games, setGames] = useState<Game[]>([])
  const [scoresLoading, setScoresLoading] = useState(true)
  const [scoresError, setScoresError] = useState<string | null>(null)
  const [draws, setDraws] = useState<DrawResponse | null>(null)
  const [drawsError, setDrawsError] = useState<string | null>(null)
  const [rankings, setRankings] = useState<RankingResponse | null>(null)
  const [rankingsError, setRankingsError] = useState<string | null>(null)
  const atpNews = useNewsData('atp', tab === 'news')
  const wtaNews = useNewsData('wta', tab === 'news')
  const tennisNews = useMemo(() => combineTennisNews(atpNews.news, wtaNews.news), [atpNews.news, wtaNews.news])

  useEffect(() => {
    const requestedTab = typeof router.query.tab === 'string' ? router.query.tab : 'scores'
    const requestedTour = typeof router.query.tour === 'string' ? router.query.tour : 'all'
    setTab((TAB_KEYS.has(requestedTab as HubTab) ? requestedTab : 'scores') as HubTab)
    setTour((TOUR_KEYS.has(requestedTour as Tour) ? requestedTour : 'all') as Tour)
  }, [router.query.tab, router.query.tour])

  useEffect(() => {
    if (tab !== 'scores') return
    let active = true
    setScoresLoading(true)
    setScoresError(null)
    Promise.all(selectedTours(tour).map(item =>
      SportsService.getGamesByLocalDate(item, date, { strict: true }),
    )).then(result => {
      if (!active) return
      setGames(result.flat().sort((a, b) => a.startTime.localeCompare(b.startTime)))
    }).catch(() => {
      if (active) {
        setGames([])
        setScoresError('Tennis scores are unavailable right now.')
      }
    }).finally(() => { if (active) setScoresLoading(false) })
    return () => { active = false }
  }, [date, tab, tour])

  useEffect(() => {
    if (tab !== 'draws') return
    let active = true
    setDrawsError(null)
    fetch(`/api/tennis/draws?tour=${tour}`, { cache: 'no-store' })
      .then(async response => {
        if (!response.ok) throw new Error('Draw request failed')
        return response.json()
      })
      .then(payload => { if (active) setDraws(payload) })
      .catch(() => {
        if (active) {
          setDraws(null)
          setDrawsError('Tennis draws are unavailable right now.')
        }
      })
    return () => { active = false }
  }, [tab, tour])

  useEffect(() => {
    if (tab !== 'rankings') return
    let active = true
    setRankingsError(null)
    fetch(`/api/tennis/rankings?tour=${tour}&limit=50`, { cache: 'no-store' })
      .then(async response => {
        if (!response.ok) throw new Error('Ranking request failed')
        return response.json()
      })
      .then(payload => { if (active) setRankings(payload) })
      .catch(() => {
        if (active) {
          setRankings(null)
          setRankingsError('Tennis rankings are unavailable right now.')
        }
      })
    return () => { active = false }
  }, [tab, tour])

  return (
    <>
      <Head><title>Tennis — Legendary Picks</title></Head>
      <div className="space-y-6">
        <header>
          <h1 className="text-3xl font-extrabold tracking-tight">Tennis</h1>
        </header>

        <nav aria-label="Tennis sections" className="flex gap-2 border-b border-zinc-800">
          {TABS.map(item => (
            <Link key={item.key} href={item.key === 'news' ? '/leagues/tennis?tab=news' : `/leagues/tennis?tab=${item.key}&tour=${tour}`}
              onClick={() => setTab(item.key)} aria-current={tab === item.key ? 'page' : undefined}
              className={`border-b-2 px-4 py-2 text-sm font-bold ${tab === item.key ? 'border-emerald-400 text-white' : 'border-transparent text-zinc-500 hover:text-zinc-300'}`}>
              {item.label}
            </Link>
          ))}
        </nav>

        {tab !== 'news' && <label className="flex w-fit items-center gap-2 text-sm text-zinc-500">
          <span>Tour</span>
          <select
            aria-label="Tour"
            value={tour}
            onChange={event => {
              const nextTour = event.target.value as Tour
              setTour(nextTour)
              router.push({ pathname: '/leagues/tennis', query: { tab, tour: nextTour } }, undefined, { shallow: true })
            }}
            className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm font-semibold text-zinc-200 outline-none focus:border-emerald-500"
          >
            {TOURS.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}
          </select>
        </label>}

        {tab === 'scores' && (
          <ScoresPanel date={date} setDate={setDate} games={games} loading={scoresLoading} error={scoresError} tour={tour} />
        )}
        {tab === 'draws' && <DrawsPanel data={draws} error={drawsError} />}
        {tab === 'rankings' && <RankingsPanel data={rankings} error={rankingsError} />}
        {tab === 'news' && (
          <NewsTab
            league="tennis"
            news={tennisNews}
            loading={atpNews.loading || wtaNews.loading}
            error={atpNews.error && wtaNews.error ? 'Tennis news is unavailable right now.' : null}
            showLeague
          />
        )}
      </div>
    </>
  )
}

function ScoresPanel({ date, setDate, games, loading, error, tour }: {
  date: string
  setDate: (date: string) => void
  games: Game[]
  loading: boolean
  error: string | null
  tour: Tour
}) {
  const isToday = date === localDate()
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-center gap-2 sm:gap-3">
        <button
          type="button"
          aria-label="Previous day"
          onClick={() => setDate(shiftDate(date, -1))}
          className="flex h-10 w-10 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-xl leading-none text-zinc-300 hover:bg-zinc-800 active:scale-95"
        >
          ‹
        </button>
        <div className="min-w-[11rem] text-center" aria-live="polite">
          <span className="text-sm font-bold text-zinc-200">
            {new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })}
          </span>
          {!isToday && (
            <button
              type="button"
              onClick={() => setDate(localDate())}
              className="mx-auto mt-0.5 block text-xs font-medium text-emerald-400 hover:text-emerald-300"
            >
              Jump to today
            </button>
          )}
        </div>
        <button
          type="button"
          aria-label="Next day"
          onClick={() => setDate(shiftDate(date, 1))}
          className="flex h-10 w-10 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-xl leading-none text-zinc-300 hover:bg-zinc-800 active:scale-95"
        >
          ›
        </button>
      </div>
      {error ? <Unavailable text={error} /> : loading ? <Loading /> : games.length ? (
        <div className="space-y-8">
          {selectedTours(tour).map(item => {
            const tourGames = games.filter(game => String(game.league || '').toLowerCase() === item)
            if (!tourGames.length) return null
            return (
              <section key={item} aria-labelledby={`${item}-scores-heading`} className="space-y-3">
                <h2 id={`${item}-scores-heading`} className="text-lg font-bold text-zinc-100">
                  {item.toUpperCase()}
                </h2>
                <div className="grid gap-3 md:grid-cols-2">
                  {tourGames.map(game => <GameCard key={`${game.league}-${game.gameId}`} {...game} />)}
                </div>
              </section>
            )
          })}
        </div>
      ) : <Unavailable text="No covered ATP or WTA matches were published for this date." />}
    </section>
  )
}

function DrawsPanel({ data, error }: { data: DrawResponse | null; error: string | null }) {
  if (error) return <Unavailable text={error} />
  if (!data) return <Loading />
  if (!data.available || !data.tours.length) return <Unavailable text={data.reason || 'No verified major draw has been published yet.'} />
  return <div className="space-y-8">{data.tours.map(draw => <DrawTournament key={`${draw.league}-${draw.event_name}`} draw={draw} />)}</div>
}

function DrawTournament({ draw }: { draw: Draw }) {
  const rounds = useMemo(() => {
    const grouped = new Map<string, DrawMatch[]>()
    for (const match of draw.matches || []) grouped.set(match.round, [...(grouped.get(match.round) || []), match])
    return Array.from(grouped.entries())
  }, [draw.matches])
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wider text-emerald-400">{draw.league.toUpperCase()} · {draw.draw_type || 'Singles'}</p>
          <h2 className="text-2xl font-bold">{draw.event_name}</h2>
        </div>
        {draw.bracket_url && <a href={draw.bracket_url} target="_blank" rel="noreferrer" className="text-sm font-semibold text-blue-400 hover:text-blue-300">Official bracket ↗</a>}
      </div>
      <HorizontalScrollRail
        label={`${draw.event_name} draw rounds`}
        previousLabel="Previous draw rounds"
        nextLabel="Next draw rounds"
        railClassName="flex gap-4 pb-3"
        stickyControls
      >
        {rounds.map(([round, matches]) => (
          <div key={round} className="w-72 shrink-0 space-y-2">
            <h3 className="sticky top-0 bg-zinc-950 py-1 text-sm font-bold text-zinc-300">{round}</h3>
            {matches.map(match => <DrawMatchCard key={match.game_id} match={match} />)}
          </div>
        ))}
      </HorizontalScrollRail>
    </section>
  )
}

function RankingsPanel({ data, error }: { data: RankingResponse | null; error: string | null }) {
  if (error) return <Unavailable text={error} />
  if (!data) return <Loading />
  if (!data.available || !data.tours.length) {
    return <Unavailable text={data.reason || 'No verified ATP or WTA ranking snapshot has been published yet.'} />
  }
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {data.tours.map(snapshot => (
        <section key={snapshot.tour} className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900">
          <div className="flex items-end justify-between border-b border-zinc-800 px-4 py-3">
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-emerald-400">World rankings</p>
              <h2 className="text-xl font-bold">{snapshot.tour.toUpperCase()} Top 50</h2>
            </div>
            <p className="text-xs text-zinc-500">Captured {new Date(snapshot.captured_at).toLocaleDateString()}</p>
          </div>
          <div className="divide-y divide-zinc-800/80">
            {snapshot.rankings.map(row => {
              const movement = row.previous_rank == null ? null : row.previous_rank - row.rank
              return (
                <div key={row.espn_athlete_id} className="grid grid-cols-[2.5rem_1fr_auto_auto] items-center gap-3 px-4 py-2.5 text-sm">
                  <span className="font-bold tabular-nums text-zinc-400">{row.rank}</span>
                  <Link href={`/player/${row.player_id}?league=${snapshot.tour}`} className="min-w-0 truncate font-semibold text-zinc-200 hover:text-emerald-400">
                    {row.player_name}
                  </Link>
                  <span className="tabular-nums text-zinc-400">{row.points == null ? '–' : row.points.toLocaleString()} pts</span>
                  <span aria-label="Rank movement" className={`w-8 text-right text-xs tabular-nums ${movement == null || movement === 0 ? 'text-zinc-600' : movement > 0 ? 'text-emerald-400' : 'text-amber-400'}`}>
                    {movement == null || movement === 0 ? '—' : movement > 0 ? `↑${movement}` : `↓${Math.abs(movement)}`}
                  </span>
                </div>
              )
            })}
          </div>
          <p className="border-t border-zinc-800 px-4 py-3 text-xs text-zinc-500">
            ESPN publishes the current top 150. This view shows 50; tournament seeds are separate.
          </p>
        </section>
      ))}
    </div>
  )
}

function DrawMatchCard({ match }: { match: DrawMatch }) {
  const sets = Math.max(match.home?.sets?.length || 0, match.away?.sets?.length || 0)
  return (
    <article className="rounded-lg border border-zinc-800 bg-zinc-900 p-3 text-sm">
      <p className="mb-2 text-[10px] font-bold uppercase tracking-wide text-zinc-500">{match.status_detail || match.status || 'Scheduled'}</p>
      {([match.home, match.away] as const).map((player, side) => (
        <div key={side} className="flex justify-between gap-3 py-1">
          <span className={player?.name ? 'text-zinc-200' : 'italic text-zinc-500'}>
            {player?.name ? `${player.seed ? `(${player.seed}) ` : ''}${player.name}` : 'TBD'}
          </span>
          {sets > 0 && <span className="tabular-nums text-zinc-400">{Array.from({ length: sets }, (_, index) => player?.sets?.[index] ?? '–').join('  ')}</span>}
        </div>
      ))}
    </article>
  )
}

function Unavailable({ text }: { text: string }) {
  return <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 px-5 py-10 text-center text-sm text-zinc-400">{text}</div>
}

function Loading() {
  return <div aria-label="Loading tennis" className="h-28 animate-pulse rounded-xl bg-zinc-900" />
}
