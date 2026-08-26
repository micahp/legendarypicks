import Head from 'next/head'
import Link from 'next/link'
import { useRouter } from 'next/router'
import { useEffect, useState } from 'react'
import GameCard from '../../components/Scores/GameCard'
import NewsTab from '../../components/Leagues/NewsTab'
import StandingsTab from '../../components/Leagues/StandingsTab'
import { useNewsData } from '../../components/Leagues/hooks/useNewsData'
import type { StandingGroup } from '../../components/Leagues/types'
import { SportsService } from '../../services/sports'
import type { Game } from '../../services/sports'

type Competition = 'mls' | 'lcup'
type Section = 'scores' | 'standings' | 'bracket' | 'leaders' | 'news'

type BracketTeam = {
  id: string
  abbrev?: string
  name: string
  score?: number | null
  winner?: boolean
}

type BracketMatch = {
  game_id: string
  date?: string
  state?: string
  status?: string
  home: BracketTeam
  away: BracketTeam
}

type BracketRound = {
  key: string
  label: string
  dateLabel?: string
  matches: BracketMatch[]
}

type Leader = {
  rank?: number
  espn_athlete_id?: string
  player_id?: number
  name: string
  team?: string
  team_abbrev?: string
  matches?: number | null
  games?: number | null
  value?: number | null
  goals?: number | null
  assists?: number | null
}

type LeaderCategory = {
  key: string
  label: string
  leaders: Leader[]
}

type CompetitionSnapshot = {
  available: boolean
  season?: number
  available_seasons?: number[]
  phase?: string
  fetched_at?: string
  groups?: StandingGroup[]
  rounds?: BracketRound[]
  leader_categories?: LeaderCategory[]
  reason?: string
}

type MlsLeaderResponse = {
  season?: number
  columns?: { key: string; label: string }[]
  leaders?: Leader[]
}

const COMPETITIONS: { key: Competition; label: string }[] = [
  { key: 'mls', label: 'MLS' },
  { key: 'lcup', label: 'Leagues Cup' },
]

const SECTIONS: Record<Competition, { key: Section; label: string }[]> = {
  mls: [
    { key: 'scores', label: 'Scores' },
    { key: 'standings', label: 'Standings' },
    { key: 'leaders', label: 'Leaders' },
    { key: 'news', label: 'News' },
  ],
  lcup: [
    { key: 'bracket', label: 'Bracket' },
    { key: 'scores', label: 'Scores' },
    { key: 'leaders', label: 'Leaders' },
    { key: 'news', label: 'News' },
  ],
}

// Leagues Cup publishes the 2026 knockout calendar before it publishes the
// participant-bearing ESPN event objects for later rounds.
// https://www.leaguescup.com/about/
const LCUP_2026_ROUNDS: Omit<BracketRound, 'matches'>[] = [
  { key: 'quarterfinals', label: 'Quarterfinals', dateLabel: 'Aug 25–26' },
  { key: 'semifinals', label: 'Semifinals', dateLabel: 'Sep 1–2' },
  { key: 'third-place', label: 'Third Place', dateLabel: 'Sep 6' },
  { key: 'final', label: 'Final', dateLabel: 'Sep 6' },
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

export default function SoccerLeaguePage({
  initialCompetition = 'mls',
  initialSection,
}: {
  initialCompetition?: Competition
  initialSection?: Section
} = {}) {
  const router = useRouter()
  const requestedSection = typeof router.query.tab === 'string' ? router.query.tab : undefined
  const defaultSection = initialCompetition === 'lcup' ? 'bracket' : 'scores'
  const resolvedSection = initialSection
    || SECTIONS[initialCompetition].find(item => item.key === requestedSection)?.key
    || defaultSection
  const [competition, setCompetition] = useState<Competition>(initialCompetition)
  const [section, setSection] = useState<Section>(resolvedSection)
  const [date, setDate] = useState(localDate())
  const [games, setGames] = useState<Game[]>([])
  const [scoresLoading, setScoresLoading] = useState(true)
  const [scoresError, setScoresError] = useState<string | null>(null)
  const [lcup, setLcup] = useState<CompetitionSnapshot | null>(null)
  const [lcupError, setLcupError] = useState<string | null>(null)
  const [mls, setMls] = useState<CompetitionSnapshot | null>(null)
  const [mlsError, setMlsError] = useState<string | null>(null)
  const [mlsLeaders, setMlsLeaders] = useState<MlsLeaderResponse | null>(null)
  const [mlsLeadersError, setMlsLeadersError] = useState<string | null>(null)
  const mlsNews = useNewsData('mls', competition === 'mls' && section === 'news')
  const lcupNews = useNewsData('lcup', competition === 'lcup' && section === 'news')

  useEffect(() => {
    let active = true
    setMlsError(null)
    fetch('/api/soccer/competitions/mls', { cache: 'no-store' })
      .then(async response => {
        if (!response.ok) throw new Error('MLS standings request failed')
        return response.json()
      })
      .then(payload => {
        if (!active) return
        setMls(payload)
        if (!payload.available) setMlsError(payload.reason || 'MLS standings are unavailable right now.')
      })
      .catch(() => {
        if (active) {
          setMls(null)
          setMlsError('MLS standings are unavailable right now.')
        }
      })
    return () => { active = false }
  }, [])

  useEffect(() => {
    setCompetition(initialCompetition)
    setSection(resolvedSection)
  }, [initialCompetition, resolvedSection])

  useEffect(() => {
    let active = true
    setLcupError(null)
    fetch('/api/soccer/competitions/lcup', { cache: 'no-store' })
      .then(async response => {
        if (!response.ok) throw new Error('Leagues Cup request failed')
        return response.json()
      })
      .then(payload => { if (active) setLcup(payload) })
      .catch(() => {
        if (active) {
          setLcup(null)
          setLcupError('Leagues Cup bracket and leaders are unavailable right now.')
        }
      })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (section !== 'scores') return
    let active = true
    setScoresLoading(true)
    setScoresError(null)
    SportsService.getGamesByLocalDate(competition, date, { strict: true })
      .then(result => { if (active) setGames(result) })
      .catch(() => {
        if (active) {
          setGames([])
          setScoresError(`${competition === 'mls' ? 'MLS' : 'Leagues Cup'} scores are unavailable right now.`)
        }
      })
      .finally(() => { if (active) setScoresLoading(false) })
    return () => { active = false }
  }, [competition, date, section])

  useEffect(() => {
    if (competition !== 'mls' || section !== 'leaders') return
    let active = true
    setMlsLeadersError(null)
    fetch('/api/mls/leaders?limit=10')
      .then(async response => {
        if (!response.ok) throw new Error('MLS leaders request failed')
        return response.json()
      })
      .then(payload => { if (active) setMlsLeaders(payload) })
      .catch(() => {
        if (active) {
          setMlsLeaders(null)
          setMlsLeadersError('MLS leaders are unavailable right now.')
        }
      })
    return () => { active = false }
  }, [competition, section])

  return (
    <>
      <Head><title>Soccer — Legendary Picks</title></Head>
      <div className="space-y-6">
        <header>
          <h1 className="text-3xl font-extrabold tracking-tight">Soccer</h1>
        </header>

        <nav aria-label="Soccer competitions" className="flex gap-2">
          {COMPETITIONS.map(item => (
            <Link key={item.key}
              href={`/leagues/${item.key}?tab=${item.key === 'lcup' ? 'bracket' : 'scores'}`}
              onClick={() => {
                setCompetition(item.key)
                setSection(item.key === 'lcup' ? 'bracket' : 'scores')
              }}
              aria-current={competition === item.key ? 'page' : undefined}
              className={`rounded-full border px-5 py-2 text-sm font-bold ${competition === item.key ? 'border-emerald-500 bg-emerald-500/10 text-emerald-300' : 'border-zinc-800 text-zinc-400 hover:text-zinc-200'}`}>
              {item.label}
            </Link>
          ))}
        </nav>

        <nav aria-label={`${competition === 'mls' ? 'MLS' : 'Leagues Cup'} sections`} className="flex gap-1 overflow-x-auto border-b border-zinc-800">
          {SECTIONS[competition].map(item => (
            <Link key={item.key} href={`/leagues/${competition}?tab=${item.key}`}
              onClick={() => setSection(item.key)} aria-current={section === item.key ? 'page' : undefined}
              className={`whitespace-nowrap border-b-2 px-4 py-2 text-sm font-bold ${section === item.key ? 'border-emerald-400 text-white' : 'border-transparent text-zinc-500 hover:text-zinc-300'}`}>
              {item.label}
            </Link>
          ))}
        </nav>

        {section === 'scores' && (
          <ScoresPanel date={date} setDate={setDate} games={games} loading={scoresLoading} error={scoresError} competition={competition} />
        )}
        {competition === 'mls' && section === 'standings' && (
          <StandingsTab
            error={mlsError}
            loading={!mls && !mlsError}
            isWorldCup={false}
            knockout={[]}
            groups={mls?.groups || []}
            teams={[]}
            season={mls?.season}
            availableSeasons={mls?.season ? [mls.season] : []}
            leagueName="MLS"
            league="mls"
          />
        )}
        {competition === 'lcup' && section === 'bracket' && <BracketPanel data={lcup} error={lcupError} />}
        {competition === 'lcup' && section === 'leaders' && (
          <LeadersPanel
            categories={lcup?.leader_categories || []}
            season={lcup?.season}
            error={lcupError || (!lcup?.available ? lcup?.reason || null : null)}
          />
        )}
        {competition === 'mls' && section === 'leaders' && (
          <MlsLeadersPanel data={mlsLeaders} error={mlsLeadersError} />
        )}
        {section === 'news' && competition === 'mls' && <NewsTab league="mls" {...mlsNews} />}
        {section === 'news' && competition === 'lcup' && <NewsTab league="lcup" {...lcupNews} />}
      </div>
    </>
  )
}

function ScoresPanel({ date, setDate, games, loading, error, competition }: {
  date: string
  setDate: (date: string) => void
  games: Game[]
  loading: boolean
  error: string | null
  competition: Competition
}) {
  const label = competition === 'mls' ? 'MLS' : 'Leagues Cup'
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2">
        <button aria-label="Previous day" onClick={() => setDate(shiftDate(date, -1))} className="px-3 py-1 text-zinc-400 hover:text-white">←</button>
        <button onClick={() => setDate(localDate())} className="text-sm font-bold text-zinc-200">{date}</button>
        <button aria-label="Next day" onClick={() => setDate(shiftDate(date, 1))} className="px-3 py-1 text-zinc-400 hover:text-white">→</button>
      </div>
      {error ? <Unavailable text={error} /> : loading ? <Loading /> : games.length ? (
        <div className="grid gap-3 md:grid-cols-2">{games.map(game => <GameCard key={game.gameId} {...game} />)}</div>
      ) : <Unavailable text={`No ${label} matches were published for this date.`} />}
    </section>
  )
}

function BracketPanel({ data, error }: { data: CompetitionSnapshot | null; error: string | null }) {
  if (error) return <Unavailable text={error} />
  if (!data) return <Loading />
  if (!data.available || !data.rounds?.length) return <Unavailable text={data.reason || 'No knockout round has been published yet.'} />
  const publishedRounds = new Map(data.rounds.map(round => [round.key, round]))
  const rounds = data.season === 2026
    ? LCUP_2026_ROUNDS.map(round => ({ ...round, matches: publishedRounds.get(round.key)?.matches || [] }))
    : data.rounds
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wider text-emerald-400">{data.season} Leagues Cup</p>
          <h2 className="text-2xl font-bold">Knockout bracket</h2>
        </div>
        {data.fetched_at && <p className="text-xs text-zinc-500">Snapshot {new Date(data.fetched_at).toLocaleString()}</p>}
      </div>
      <div className="flex gap-4 overflow-x-auto pb-3">
        {rounds.map(round => (
          <div key={round.key} className="w-80 shrink-0 space-y-3">
            <div>
              <h3 className="text-sm font-bold uppercase tracking-wider text-zinc-300">{round.label}</h3>
              {round.dateLabel && <p className="mt-1 text-xs font-medium text-zinc-500">{round.dateLabel}</p>}
            </div>
            {round.matches.length
              ? round.matches.map(match => <BracketMatchCard key={match.game_id} match={match} />)
              : <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-900/40 px-4 py-8 text-center text-sm text-zinc-500">Matchups TBD</div>}
          </div>
        ))}
      </div>
      <p className="text-xs text-zinc-500">Future matchups populate as teams advance.</p>
    </section>
  )
}

function BracketMatchCard({ match }: { match: BracketMatch }) {
  const final = match.state === 'post'
  const kickoff = match.date ? new Date(match.date).toLocaleString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  }) : null
  return (
    <Link href={`/game/lcup/${match.game_id}`} className="block rounded-xl border border-zinc-800 bg-zinc-900 p-4 hover:border-emerald-500/30">
      <p className="mb-2 text-[10px] font-bold uppercase tracking-wide text-zinc-500">
        {kickoff || match.status || 'Time TBD'}
      </p>
      {[match.away, match.home].map(team => (
        <div key={team.id || team.name} className="flex items-center justify-between gap-3 py-1.5">
          <span className={final && !team.winner ? 'text-zinc-500' : 'font-semibold text-zinc-200'}>{team.name}</span>
          <span className="font-mono text-lg font-bold tabular-nums text-zinc-100">{final ? team.score ?? '–' : '–'}</span>
        </div>
      ))}
    </Link>
  )
}

function LeadersPanel({ categories, season, error }: { categories: LeaderCategory[]; season?: number; error: string | null }) {
  if (error) return <Unavailable text={error} />
  if (!categories.length) return <Unavailable text="No Leagues Cup player leaders have been published yet." />
  return (
    <div className="space-y-5">
      <div>
        <p className="text-xs font-bold uppercase tracking-wider text-emerald-400">Published tournament totals</p>
        <h2 className="text-2xl font-bold">{season} Leagues Cup leaders</h2>
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        {categories.map(category => (
          <LeaderTable key={category.key} label={category.label} valueLabel={category.label} leaders={category.leaders.slice(0, 10)} valueKey="value" />
        ))}
      </div>
    </div>
  )
}

function MlsLeadersPanel({ data, error }: { data: MlsLeaderResponse | null; error: string | null }) {
  if (error) return <Unavailable text={error} />
  if (!data) return <Loading />
  const rows = data.leaders || []
  if (!rows.length) return <Unavailable text="No MLS player leaders have been published yet." />
  return (
    <div className="space-y-5">
      <div>
        <p className="text-xs font-bold uppercase tracking-wider text-emerald-400">Published season totals</p>
        <h2 className="text-2xl font-bold">{data.season} MLS leaders</h2>
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        {(data.columns || []).map(column => (
          <LeaderTable key={column.key} label={column.label} valueLabel={column.label} leaders={rows} valueKey={column.key} />
        ))}
      </div>
    </div>
  )
}

function LeaderTable({ label, valueLabel, leaders, valueKey }: {
  label: string
  valueLabel: string
  leaders: Leader[]
  valueKey: string
}) {
  const sorted = [...leaders].sort((a, b) => Number((b as any)[valueKey] ?? -1) - Number((a as any)[valueKey] ?? -1)).slice(0, 10)
  return (
    <section className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900">
      <h3 className="border-b border-zinc-800 px-4 py-3 text-lg font-bold">{label}</h3>
      <div className="divide-y divide-zinc-800/80">
        {sorted.map((row, index) => (
          <div key={row.espn_athlete_id || row.player_id || row.name} className="grid grid-cols-[2rem_1fr_auto_auto] items-center gap-3 px-4 py-3 text-sm">
            <span className="tabular-nums text-zinc-500">{index + 1}</span>
            <div className="min-w-0">
              <p className="truncate font-semibold text-zinc-200">{row.name}</p>
              <p className="truncate text-xs text-zinc-500">{row.team || row.team_abbrev || 'Team unavailable'}</p>
            </div>
            <span className="text-xs tabular-nums text-zinc-500">{row.matches ?? row.games ?? '–'} matches</span>
            <span aria-label={valueLabel} className="text-lg font-bold tabular-nums text-white">{(row as any)[valueKey] ?? '–'}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

function Unavailable({ text }: { text: string }) {
  return <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 px-5 py-10 text-center text-sm text-zinc-400">{text}</div>
}

function Loading() {
  return <div aria-label="Loading soccer" className="h-28 animate-pulse rounded-xl bg-zinc-800" />
}
