import { useEffect, useState } from 'react'
import Head from 'next/head'
import Link from 'next/link'
import { useRouter } from 'next/router'

import BoothFeed from '../../../components/Game/BoothFeed'

type SeriesResult = {
  match_id: number
  date: string | null
  opponent: string
  opponent_logo?: string | null
  result: 'W' | 'L'
  score_for: number | null
  score_against: number | null
  event?: string | null
}

type TeamForm = {
  series: SeriesResult[]
  series_record: { wins: number; losses: number }
  recent_maps: Array<{ result: 'W' | 'L' }>
  map_record: { wins: number; losses: number }
  map_win_pct: number | null
}

type Team = {
  id: number
  name: string
  acronym?: string | null
  logo?: string | null
  score: number | null
  winner: boolean
  form: TeamForm
}

type MapRow = {
  position: number
  status: string
  finished: boolean
  winner_id?: number | null
  winner_name?: string | null
  length_seconds?: number | null
}

type HeadToHead = {
  match_id: number
  date?: string | null
  team_a_score?: number | null
  team_b_score?: number | null
  winner_id?: number | null
  winner_name?: string | null
  event?: string | null
}

type ReadCard = {
  headline: string
  evidence?: string
  source: 'pandascore' | 'booth' | 'combined'
}

type DiscountPlay = {
  selection: string
  market: string
  line: string
  rationale: string
}

type CodContext = {
  game_id: string
  status: string
  live: boolean
  finished: boolean
  scheduled_at?: string | null
  begin_at?: string | null
  best_of?: number | null
  event: {
    league?: string | null
    serie?: string | null
    tournament?: string | null
    serie_id?: number | null
  }
  teams: Team[]
  market?: { name: string; pct: number } | null
  watch?: { platform: string; url: string } | null
  maps: MapRow[]
  head_to_head: HeadToHead[]
  read: ReadCard[]
  discount_play?: DiscountPlay | null
  discount_reason?: string | null
  limitations?: string[]
}

function TeamLogo({ src, name, size = 'h-12 w-12' }: { src?: string | null; name: string; size?: string }) {
  return src
    ? <img src={src} alt={`${name} logo`} className={`${size} shrink-0 object-contain`} />
    : <span aria-hidden className={`${size} shrink-0 rounded-lg bg-zinc-800`} />
}

function SectionHeader({ eyebrow, title, meta }: { eyebrow: string; title: string; meta?: string }) {
  return (
    <div className="space-y-2">
      <div className="flex items-end justify-between gap-3">
        <div className="space-y-1.5">
          <div className="text-[10px] font-medium uppercase tracking-[0.2em] text-zinc-500">{eyebrow}</div>
          <h2 className="text-xl font-bold tracking-tight text-zinc-50">{title}</h2>
        </div>
        {meta ? <span className="shrink-0 pb-0.5 font-mono text-[10px] uppercase tracking-wider text-zinc-600">{meta}</span> : null}
      </div>
      <div className="h-px w-full bg-gradient-to-r from-zinc-700 to-transparent" />
    </div>
  )
}

function statusLabel(status: string): string {
  if (status === 'live' || status === 'running') return 'LIVE'
  if (status === 'finished' || status === 'final') return 'FINAL'
  if (status === 'scheduled' || status === 'not_started') return 'SCHEDULED'
  return status.replaceAll('_', ' ').toUpperCase()
}

function formatStart(value?: string | null): string {
  if (!value) return 'Time TBD'
  const date = new Date(value)
  return date.toLocaleString(undefined, {
    weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}

function formatDate(value?: string | null): string {
  if (!value) return ''
  return new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function formatLength(seconds?: number | null): string {
  if (seconds == null) return ''
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  return `${minutes}:${String(remainder).padStart(2, '0')}`
}

function MatchHeader({ context }: { context: CodContext }) {
  const [teamA, teamB] = context.teams
  const showScore = context.live || context.finished
  const live = context.live
  const state = statusLabel(context.status)

  return (
    <section className="overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-900/60">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-800 px-4 py-3 sm:px-6">
        <div className={`font-mono text-[10px] uppercase tracking-[0.18em] ${live ? 'text-red-400' : 'text-zinc-500'}`}>
          CASE · {context.game_id} — {context.event.serie || context.event.league || 'Call of Duty'} / {state}
        </div>
        <div className="flex items-center gap-3">
          {context.market ? (
            <span className="font-mono text-[10px] uppercase tracking-wider text-emerald-300">
              {context.market.name} {context.market.pct}% favorite
            </span>
          ) : null}
          {context.watch?.url ? (
            <a href={context.watch.url} target="_blank" rel="noreferrer" className="font-mono text-[10px] uppercase tracking-wider text-zinc-500 hover:text-emerald-400">
              Watch ↗
            </a>
          ) : null}
        </div>
      </div>

      <div className="grid items-center gap-5 px-4 py-6 sm:grid-cols-[1fr_auto_1fr] sm:px-6 sm:py-8">
        {[teamA, teamB].map((team, index) => (
          <div key={team.id} className={`flex items-center gap-3 ${index === 1 ? 'sm:flex-row-reverse sm:text-right' : ''}`}>
            <TeamLogo src={team.logo} name={team.name} />
            <div className="min-w-0">
              <div className={`truncate text-lg font-bold ${context.finished && !team.winner ? 'text-zinc-500' : 'text-zinc-100'}`}>{team.name}</div>
              <div className="mt-1 font-mono text-[10px] uppercase tracking-wider text-zinc-600">{team.acronym || 'CDL'}</div>
            </div>
            {showScore ? (
              <span className={`ml-auto font-mono text-3xl font-bold tabular-nums sm:ml-0 ${context.finished && !team.winner ? 'text-zinc-600' : 'text-zinc-50'}`}>
                {team.score ?? '–'}
              </span>
            ) : null}
          </div>
        )).reduce<React.ReactNode[]>((rows, team, index) => {
          if (index === 1) rows.push(
            <div key="versus" className="hidden text-center font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-700 sm:block">vs</div>
          )
          rows.push(team)
          return rows
        }, [])}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-zinc-800 px-4 py-3 font-mono text-[10px] uppercase tracking-wider text-zinc-600 sm:px-6">
        <span>{formatStart(context.begin_at || context.scheduled_at)}</span>
        <span>{context.event.tournament || 'CDL'}{context.best_of ? ` · Best of ${context.best_of}` : ''}</span>
      </div>
    </section>
  )
}

function MapProgress({ maps }: { maps: MapRow[] }) {
  if (!maps.length) return null
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-zinc-200">Series map progress</h3>
        <span className="font-mono text-[9px] uppercase tracking-wider text-zinc-600">PandaScore map winners</span>
      </div>
      <div className="grid gap-2 sm:grid-cols-5">
        {maps.map((map) => {
          const live = map.status === 'running'
          return (
            <div key={map.position} className={`rounded-lg border px-3 py-2 ${
              live ? 'border-red-500/30 bg-red-500/10' : map.finished ? 'border-zinc-700 bg-zinc-800/50' : 'border-zinc-800 bg-zinc-950/30'
            }`}>
              <div className={`font-mono text-[9px] uppercase tracking-wider ${live ? 'text-red-400' : 'text-zinc-600'}`}>
                Map {map.position} {live ? '· Live' : ''}
              </div>
              <div className={`mt-1 truncate text-xs font-semibold ${map.winner_name ? 'text-zinc-200' : 'text-zinc-600'}`}>
                {map.winner_name || (map.status === 'not_started' ? 'Not started' : map.status)}
              </div>
              {map.length_seconds ? <div className="mt-1 font-mono text-[9px] text-zinc-600">{formatLength(map.length_seconds)}</div> : null}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function FormChips({ results }: { results: Array<'W' | 'L'> }) {
  return (
    <div className="flex gap-1" aria-label={`Recent map form ${results.join(' ')}`}>
      {results.map((result, index) => (
        <span key={index} className={`flex h-5 w-5 items-center justify-center rounded-sm font-mono text-[9px] font-bold ${
          result === 'W' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-red-500/15 text-red-300'
        }`}>{result}</span>
      ))}
    </div>
  )
}

function TeamFormCard({ team }: { team: Team }) {
  const form = team.form
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <TeamLogo src={team.logo} name={team.name} size="h-7 w-7" />
          <div>
            <h3 className="truncate text-sm font-semibold text-zinc-100">{team.name}</h3>
            <p className="font-mono text-[9px] uppercase tracking-wider text-zinc-600">Before this match</p>
          </div>
        </div>
        <div className="shrink-0 text-right font-mono">
          <div className="text-sm font-bold tabular-nums text-zinc-200">{form.map_record.wins}-{form.map_record.losses}</div>
          <div className="text-[9px] uppercase tracking-wider text-zinc-600">last {form.recent_maps.length} maps</div>
        </div>
      </div>

      {form.recent_maps.length > 0 ? <div className="mt-3"><FormChips results={form.recent_maps.map((map) => map.result)} /></div> : null}

      <div className="mt-4 divide-y divide-zinc-800/70 border-t border-zinc-800/70">
        {form.series.length === 0 ? (
          <p className="py-3 text-xs text-zinc-600">No earlier finished series in the current PandaScore window.</p>
        ) : form.series.map((series) => (
          <div key={series.match_id} className="flex items-center gap-2 py-2.5">
            <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-sm font-mono text-[9px] font-bold ${
              series.result === 'W' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-red-500/15 text-red-300'
            }`}>{series.result}</span>
            <span className="min-w-0 flex-1 truncate text-xs text-zinc-400">vs {series.opponent}</span>
            <span className="font-mono text-xs tabular-nums text-zinc-300">{series.score_for ?? '–'}-{series.score_against ?? '–'}</span>
            <span className="hidden w-12 text-right font-mono text-[9px] text-zinc-600 sm:block">{formatDate(series.date)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function HeadToHeadList({ rows, teams }: { rows: HeadToHead[]; teams: Team[] }) {
  if (!rows.length) return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-600">
      No earlier head-to-head series in the current PandaScore window.
    </div>
  )
  return (
    <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/40">
      <div className="divide-y divide-zinc-800/70">
        {rows.map((row) => (
          <div key={row.match_id} className="flex items-center gap-3 px-4 py-3">
            <span className="w-14 shrink-0 font-mono text-[10px] text-zinc-600">{formatDate(row.date)}</span>
            <span className={`min-w-0 flex-1 truncate text-sm ${row.winner_id === teams[0].id ? 'font-semibold text-zinc-100' : 'text-zinc-500'}`}>{teams[0].name}</span>
            <span className="shrink-0 font-mono text-sm font-bold tabular-nums text-zinc-200">{row.team_a_score ?? '–'}-{row.team_b_score ?? '–'}</span>
            <span className={`min-w-0 flex-1 truncate text-right text-sm ${row.winner_id === teams[1].id ? 'font-semibold text-zinc-100' : 'text-zinc-500'}`}>{teams[1].name}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function TheRead({ cards }: { cards: ReadCard[] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/40">
      {cards.length === 0 ? (
        <p className="p-5 text-sm text-zinc-500">No grounded read is available yet.</p>
      ) : (
        <ol className="divide-y divide-zinc-800/70">
          {cards.map((card, index) => (
            <li key={`${card.headline}-${index}`} className="p-4 sm:p-5">
              <div className="flex gap-3">
                <span className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded border border-emerald-500/30 bg-emerald-500/10 font-mono text-[9px] text-emerald-300">{index + 1}</span>
                <div className="min-w-0">
                  <div className="mb-1 font-mono text-[9px] uppercase tracking-wider text-zinc-600">{card.source}</div>
                  <p className="text-sm font-semibold leading-snug text-zinc-100">{card.headline}</p>
                  {card.evidence ? <p className="mt-1 text-xs leading-relaxed text-zinc-500">{card.evidence}</p> : null}
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

export default function CodGameDetailPage() {
  const router = useRouter()
  const gameId = typeof router.query.gameId === 'string' ? router.query.gameId : undefined
  const [context, setContext] = useState<CodContext | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    if (!gameId) return
    let alive = true
    const load = async () => {
      try {
        const response = await fetch(`/api/cod/${gameId}/context`, { cache: 'no-store' })
        if (!response.ok) throw new Error(`Context request failed: ${response.status}`)
        const data = await response.json() as CodContext
        if (alive) {
          setContext(data)
          setError(false)
          setLoading(false)
        }
      } catch {
        if (alive) {
          setError(true)
          setLoading(false)
        }
      }
    }
    load()
    const timer = setInterval(load, 15_000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [gameId])

  if (loading) return (
    <div className="mx-auto max-w-4xl animate-pulse space-y-5">
      <div className="h-5 w-32 rounded bg-zinc-800" />
      <div className="h-56 rounded-2xl bg-zinc-800" />
      <div className="h-72 rounded-xl bg-zinc-800" />
    </div>
  )

  if (!context || error) return (
    <div className="mx-auto max-w-4xl space-y-5">
      <Link href="/cod" className="text-sm text-zinc-500 hover:text-zinc-200">← Back to CDL desk</Link>
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-8 text-center">
        <p className="text-sm text-zinc-400">This CoD match context is unavailable.</p>
        <p className="mt-2 text-xs text-zinc-600">The match may be outside the current PandaScore history window.</p>
      </div>
    </div>
  )

  return (
    <>
      <Head><title>{context.teams.map((team) => team.name).join(' vs ')} — Legendary Picks</title></Head>

      <div className="mx-auto max-w-4xl space-y-8">
        <div className="flex items-center justify-between gap-3">
          <Link href="/cod" className="text-sm text-zinc-500 transition-colors hover:text-zinc-200">← Back to CDL desk</Link>
          <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Call of Duty League</span>
        </div>

        <MatchHeader context={context} />

        <section className="space-y-5">
          <SectionHeader eyebrow="PandaScore codmw" title="Game context" meta="Before this match" />
          <MapProgress maps={context.maps} />
          <div className="grid gap-4 md:grid-cols-2">
            {context.teams.map((team) => <TeamFormCard key={team.id} team={team} />)}
          </div>
          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-zinc-300">Recent head-to-head</h3>
            <HeadToHeadList rows={context.head_to_head} teams={context.teams} />
          </div>
        </section>

        <section className="space-y-5">
          <SectionHeader eyebrow="Timestamp-matched broadcast reads" title="From the Booth" />
          <BoothFeed gameId={context.game_id} contextLeague="cod" showListenLive={false} />
        </section>

        <section className="space-y-5">
          <SectionHeader eyebrow="Context plus broadcast" title="The Read" />
          <TheRead cards={context.read} />
        </section>

        <section className="space-y-5">
          <SectionHeader eyebrow="Optional value only" title="Discount play" />
          {context.discount_play ? (
            <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-5">
              <div className="font-mono text-[10px] uppercase tracking-wider text-emerald-300">{context.discount_play.market} · {context.discount_play.line}</div>
              <p className="mt-2 text-lg font-bold text-zinc-50">{context.discount_play.selection}</p>
              <p className="mt-2 text-sm leading-relaxed text-zinc-300">{context.discount_play.rationale}</p>
            </div>
          ) : (
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
              <p className="text-sm font-semibold text-zinc-300">No verified discount</p>
              <p className="mt-1 text-xs leading-relaxed text-zinc-500">{context.discount_reason}</p>
            </div>
          )}
        </section>

        {context.limitations?.length ? (
          <aside className="rounded-xl border border-zinc-800/70 bg-zinc-950/30 p-4">
            <div className="font-mono text-[9px] uppercase tracking-wider text-zinc-600">Data notes</div>
            <ul className="mt-2 space-y-1 text-xs leading-relaxed text-zinc-600">
              {context.limitations.map((note) => <li key={note}>{note}</li>)}
            </ul>
          </aside>
        ) : null}
      </div>
    </>
  )
}
