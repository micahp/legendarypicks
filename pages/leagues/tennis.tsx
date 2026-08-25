import Head from 'next/head'
import { useEffect, useMemo, useState } from 'react'
import GameCard from '../../components/Scores/GameCard'
import NewsTab from '../../components/Leagues/NewsTab'
import { useNewsData } from '../../components/Leagues/hooks/useNewsData'
import { SportsService } from '../../services/sports'
import type { Game } from '../../services/sports'

type HubTab = 'scores' | 'draws' | 'news'
type Tour = 'all' | 'atp' | 'wta'

type DrawMatch = {
  game_id: string
  date?: string
  state?: string
  status?: string
  status_detail?: string
  round: string
  home?: { name?: string; sets?: number[] }
  away?: { name?: string; sets?: number[] }
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

const TABS: { key: HubTab; label: string }[] = [
  { key: 'scores', label: 'Scores' },
  { key: 'draws', label: 'Draws' },
  { key: 'news', label: 'News' },
]

const TOURS: { key: Tour; label: string }[] = [
  { key: 'all', label: 'Both' },
  { key: 'atp', label: 'ATP' },
  { key: 'wta', label: 'WTA' },
]

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

export default function TennisLeaguePage() {
  const [tab, setTab] = useState<HubTab>('scores')
  const [tour, setTour] = useState<Tour>('all')
  const [date, setDate] = useState(localDate())
  const [games, setGames] = useState<Game[]>([])
  const [scoresLoading, setScoresLoading] = useState(true)
  const [scoresError, setScoresError] = useState<string | null>(null)
  const [draws, setDraws] = useState<DrawResponse | null>(null)
  const [drawsError, setDrawsError] = useState<string | null>(null)
  const atpNews = useNewsData('atp', tab === 'news' && tour !== 'wta')
  const wtaNews = useNewsData('wta', tab === 'news' && tour !== 'atp')

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

  return (
    <>
      <Head><title>Tennis — Legendary Picks</title></Head>
      <div className="space-y-6">
        <header>
          <p className="text-xs font-bold uppercase tracking-widest text-emerald-400">Major tournament coverage</p>
          <h1 className="mt-1 text-3xl font-extrabold tracking-tight">Tennis</h1>
          <p className="mt-2 max-w-2xl text-sm text-zinc-400">
            ATP and WTA scores, singles draws, and news for covered major tournaments.
            Tour events outside this coverage are not ingested here.
          </p>
        </header>

        <nav aria-label="Tennis sections" className="flex gap-2 border-b border-zinc-800">
          {TABS.map(item => (
            <button key={item.key} onClick={() => setTab(item.key)}
              className={`border-b-2 px-4 py-2 text-sm font-bold ${tab === item.key ? 'border-emerald-400 text-white' : 'border-transparent text-zinc-500 hover:text-zinc-300'}`}>
              {item.label}
            </button>
          ))}
        </nav>

        <div aria-label="Tour" className="flex gap-2">
          {TOURS.map(item => (
            <button key={item.key} onClick={() => setTour(item.key)} aria-pressed={tour === item.key}
              className={`rounded-full border px-4 py-1.5 text-sm font-semibold ${tour === item.key ? 'border-emerald-500 bg-emerald-500/10 text-emerald-300' : 'border-zinc-800 text-zinc-400'}`}>
              {item.label}
            </button>
          ))}
        </div>

        {tab === 'scores' && (
          <ScoresPanel date={date} setDate={setDate} games={games} loading={scoresLoading} error={scoresError} />
        )}
        {tab === 'draws' && <DrawsPanel data={draws} error={drawsError} />}
        {tab === 'news' && (
          <div className="space-y-8">
            {tour !== 'wta' && <section><h2 className="mb-3 text-lg font-bold">ATP News</h2><NewsTab league="atp" {...atpNews} /></section>}
            {tour !== 'atp' && <section><h2 className="mb-3 text-lg font-bold">WTA News</h2><NewsTab league="wta" {...wtaNews} /></section>}
          </div>
        )}
      </div>
    </>
  )
}

function ScoresPanel({ date, setDate, games, loading, error }: {
  date: string
  setDate: (date: string) => void
  games: Game[]
  loading: boolean
  error: string | null
}) {
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2">
        <button aria-label="Previous day" onClick={() => setDate(shiftDate(date, -1))} className="px-3 py-1 text-zinc-400 hover:text-white">←</button>
        <button onClick={() => setDate(localDate())} className="text-sm font-bold text-zinc-200">{date}</button>
        <button aria-label="Next day" onClick={() => setDate(shiftDate(date, 1))} className="px-3 py-1 text-zinc-400 hover:text-white">→</button>
      </div>
      {error ? <Unavailable text={error} /> : loading ? <Loading /> : games.length ? (
        <div className="grid gap-3 md:grid-cols-2">{games.map(game => <GameCard key={`${game.league}-${game.gameId}`} {...game} />)}</div>
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
          <p className="text-xs text-zinc-500">Snapshot {new Date(draw.fetched_at).toLocaleString()}</p>
        </div>
        {draw.bracket_url && <a href={draw.bracket_url} target="_blank" rel="noreferrer" className="text-sm font-semibold text-blue-400 hover:text-blue-300">Official bracket ↗</a>}
      </div>
      <div className="flex gap-4 overflow-x-auto pb-3">
        {rounds.map(([round, matches]) => (
          <div key={round} className="w-72 shrink-0 space-y-2">
            <h3 className="sticky top-0 bg-zinc-950 py-1 text-sm font-bold text-zinc-300">{round}</h3>
            {matches.map(match => <DrawMatchCard key={match.game_id} match={match} />)}
          </div>
        ))}
      </div>
    </section>
  )
}

function DrawMatchCard({ match }: { match: DrawMatch }) {
  const sets = Math.max(match.home?.sets?.length || 0, match.away?.sets?.length || 0)
  return (
    <article className="rounded-lg border border-zinc-800 bg-zinc-900 p-3 text-sm">
      <p className="mb-2 text-[10px] font-bold uppercase tracking-wide text-zinc-500">{match.status_detail || match.status || 'Scheduled'}</p>
      {([match.home, match.away] as const).map((player, side) => (
        <div key={side} className="flex justify-between gap-3 py-1">
          <span className={player?.name ? 'text-zinc-200' : 'italic text-zinc-500'}>{player?.name || 'TBD'}</span>
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
