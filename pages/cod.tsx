import { useEffect, useMemo, useState } from 'react'
import Head from 'next/head'
import Link from 'next/link'

import { LiveNow } from './esports'

type Watch = {
  platform: string
  url: string
  channel: string | null
  online?: boolean | null
  embedUrl?: string | null
  alternates?: Watch[]
}

type CodMatch = {
  startTime: number | null
  live: boolean
  title: string
  league: string
  teamA: string
  teamB: string
  favorite: { name: string; pct: number } | null
  watch: Watch | null
  score?: { a: number | null; b: number | null } | null
  finished?: boolean | null
  winner?: 'a' | 'b' | null
  pinned?: boolean
  model?: { favName: string; modelPct: number; marketPct: number | null; edge: number | null } | null
  logoA?: string | null
  logoB?: string | null
  minorLeague?: boolean
  tier?: number
  prominence?: number
  psId?: number | string | null
  streamKey?: string | null
  eventId?: number | string | null
}

type UpcomingData = {
  matches: CodMatch[]
  error?: string
  building?: boolean
}

type StreamGroup = {
  streamKey: string
  matches: CodMatch[]
}

type Standing = {
  team: string
  logo: string | null
  wins: number
  losses: number
}

const COD_TITLE = 'Call of Duty'
const POLL_MS = 10_000

function Eyebrow({ children, live = false }: { children: React.ReactNode; live?: boolean }) {
  return (
    <div className={`flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-[0.2em] ${live ? 'text-red-400' : 'text-zinc-500'}`}>
      {live ? <span className="h-1.5 w-1.5 rounded-full bg-red-500 animate-pulse motion-reduce:animate-none" /> : null}
      <span>{children}</span>
    </div>
  )
}

function SectionHeader({ eyebrow, title, meta }: { eyebrow: string; title: string; meta?: string }) {
  return (
    <div className="space-y-2">
      <div className="flex items-end justify-between gap-3">
        <div className="space-y-1.5">
          <Eyebrow>{eyebrow}</Eyebrow>
          <h2 className="text-xl font-bold tracking-tight text-zinc-50">{title}</h2>
        </div>
        {meta ? <span className="shrink-0 pb-0.5 font-mono text-[10px] uppercase tracking-wider text-zinc-600">{meta}</span> : null}
      </div>
      <div className="h-px w-full bg-gradient-to-r from-zinc-700 to-transparent" />
    </div>
  )
}

function TeamCrest({ src, size = 'h-6 w-6' }: { src: string | null | undefined; size?: string }) {
  return src
    ? <img src={src} alt="" className={`${size} shrink-0 object-contain`} />
    : <span className={`${size} shrink-0 rounded bg-zinc-800`} />
}

function formatStart(ms: number | null): string {
  if (!ms) return 'Time TBD'
  return new Date(ms).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

function groupByStream(matches: CodMatch[]): StreamGroup[] {
  const byStream = new Map<string, CodMatch[]>()
  for (const match of matches) {
    if (!match.streamKey) continue
    const group = byStream.get(match.streamKey) ?? []
    group.push(match)
    byStream.set(match.streamKey, group)
  }

  return [...byStream.entries()]
    .map(([streamKey, streamMatches]) => ({
      streamKey,
      matches: streamMatches.sort((a, b) => (a.startTime ?? Infinity) - (b.startTime ?? Infinity)),
    }))
    .sort((a, b) => (a.matches[0]?.startTime ?? Infinity) - (b.matches[0]?.startTime ?? Infinity))
}

function deriveStandings(matches: CodMatch[]): { rows: Standing[]; countedMatches: number } {
  const table = new Map<string, Standing>()
  let countedMatches = 0

  const ensureTeam = (team: string, logo: string | null | undefined) => {
    if (!table.has(team)) table.set(team, { team, logo: logo ?? null, wins: 0, losses: 0 })
    else if (!table.get(team)!.logo && logo) table.get(team)!.logo = logo
    return table.get(team)!
  }

  for (const match of matches) {
    if (!match.finished || (match.winner !== 'a' && match.winner !== 'b')) continue
    const teamA = ensureTeam(match.teamA, match.logoA)
    const teamB = ensureTeam(match.teamB, match.logoB)
    if (match.winner === 'a') {
      teamA.wins += 1
      teamB.losses += 1
    } else {
      teamB.wins += 1
      teamA.losses += 1
    }
    countedMatches += 1
  }

  const rows = [...table.values()].sort((a, b) =>
    b.wins - a.wins || a.losses - b.losses || a.team.localeCompare(b.team)
  )
  return { rows, countedMatches }
}

function StateChip({ match }: { match: CodMatch }) {
  if (match.live) {
    return (
      <span className="inline-flex items-center gap-1 rounded border border-red-500/30 bg-red-500/10 px-2 py-1 font-mono text-[10px] font-medium uppercase tracking-wider text-red-400">
        <span className="h-1 w-1 rounded-full bg-red-500 animate-pulse motion-reduce:animate-none" />
        Live
      </span>
    )
  }
  if (match.finished) {
    return <span className="inline-flex rounded border border-zinc-700 bg-zinc-800/60 px-2 py-1 font-mono text-[10px] font-medium uppercase tracking-wider text-zinc-400">Final</span>
  }
  return <span className="inline-flex rounded border border-zinc-800 bg-zinc-900 px-2 py-1 font-mono text-[10px] font-medium uppercase tracking-wider text-zinc-500">Scheduled</span>
}

function StreamMatchRow({ match }: { match: CodMatch }) {
  const detailHref = match.psId != null ? `/game/call-of-duty/${match.psId}` : null
  const teamClass = (side: 'a' | 'b') => {
    if (!match.finished || !match.winner) return 'text-zinc-200'
    return match.winner === side ? 'text-zinc-100' : 'text-zinc-500'
  }

  return (
    <div data-cod-match={`${match.teamA} vs ${match.teamB}`} className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center">
      <div className="flex w-28 shrink-0 items-center justify-between gap-2 sm:block">
        <StateChip match={match} />
        <div className="mt-0 sm:mt-1.5 font-mono text-[10px] tabular-nums text-zinc-600">{formatStart(match.startTime)}</div>
      </div>

      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex items-center gap-2">
          <TeamCrest src={match.logoA} size="h-5 w-5" />
          <span className={`min-w-0 flex-1 truncate text-sm font-semibold ${teamClass('a')}`}>{match.teamA}</span>
          {match.score ? <span className={`font-mono text-sm font-bold tabular-nums ${teamClass('a')}`}>{match.score.a ?? '–'}</span> : null}
        </div>
        <div className="flex items-center gap-2">
          <TeamCrest src={match.logoB} size="h-5 w-5" />
          <span className={`min-w-0 flex-1 truncate text-sm font-semibold ${teamClass('b')}`}>{match.teamB}</span>
          {match.score ? <span className={`font-mono text-sm font-bold tabular-nums ${teamClass('b')}`}>{match.score.b ?? '–'}</span> : null}
        </div>
      </div>

      {match.favorite ? (
        <div className="shrink-0 text-left sm:w-28 sm:text-right">
          <div className="truncate text-[11px] font-medium text-zinc-500">{match.favorite.name}</div>
          <div className="mt-1 font-mono text-xs tabular-nums text-emerald-300">{match.favorite.pct}% favorite</div>
        </div>
      ) : null}
      {detailHref ? (
        <Link href={detailHref} className="shrink-0 font-mono text-[10px] uppercase tracking-wider text-zinc-500 hover:text-emerald-400">
          Match read →
        </Link>
      ) : null}
    </div>
  )
}

function ResultRow({ match }: { match: CodMatch }) {
  const detailHref = match.psId != null ? `/game/call-of-duty/${match.psId}` : null
  const teamClass = (side: 'a' | 'b') => match.winner === side ? 'text-zinc-100' : 'text-zinc-500'
  return (
    <div data-cod-result={`${match.teamA} vs ${match.teamB}`} className="flex items-center gap-4 py-3">
      <div className="hidden w-24 shrink-0 font-mono text-[10px] tabular-nums text-zinc-600 sm:block">{formatStart(match.startTime)}</div>
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex items-center gap-2">
          <TeamCrest src={match.logoA} size="h-5 w-5" />
          <span className={`min-w-0 flex-1 truncate text-sm font-semibold ${teamClass('a')}`}>{match.teamA}</span>
          <span className={`font-mono text-sm font-bold tabular-nums ${teamClass('a')}`}>{match.score?.a ?? '–'}</span>
        </div>
        <div className="flex items-center gap-2">
          <TeamCrest src={match.logoB} size="h-5 w-5" />
          <span className={`min-w-0 flex-1 truncate text-sm font-semibold ${teamClass('b')}`}>{match.teamB}</span>
          <span className={`font-mono text-sm font-bold tabular-nums ${teamClass('b')}`}>{match.score?.b ?? '–'}</span>
        </div>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-2">
        <span className="rounded border border-zinc-700 bg-zinc-800/60 px-2 py-1 font-mono text-[10px] font-medium uppercase tracking-wider text-zinc-400">Final</span>
        {detailHref ? <Link href={detailHref} className="font-mono text-[10px] uppercase tracking-wider text-zinc-500 hover:text-emerald-400">Match read →</Link> : null}
      </div>
    </div>
  )
}

export default function CodPage() {
  const [upcoming, setUpcoming] = useState<UpcomingData | null>(null)
  const [loadError, setLoadError] = useState(false)
  const [host, setHost] = useState('')

  useEffect(() => { setHost(window.location.hostname) }, [])

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const response = await fetch('/api/esports/upcoming', { cache: 'no-store' })
        if (!response.ok) throw new Error(`Upcoming request failed: ${response.status}`)
        const data = await response.json() as UpcomingData
        if (alive) {
          setUpcoming(data)
          setLoadError(false)
        }
      } catch {
        if (alive) setLoadError(true)
      }
    }
    load()
    const timer = setInterval(load, POLL_MS)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [])

  const matches = useMemo(
    () => (upcoming?.matches ?? []).filter((match) => match.title === COD_TITLE),
    [upcoming]
  )
  const liveMatches = matches.filter((match) => match.live)
  const streamGroups = groupByStream(matches)
  const results = matches
    .filter((match) => match.finished)
    .sort((a, b) => (b.startTime ?? 0) - (a.startTime ?? 0))
  const standings = deriveStandings(results)
  const showStandings = standings.countedMatches >= 3 && standings.rows.length >= 4
  const isBuilding = upcoming === null || Boolean(upcoming.building && matches.length === 0)
  const unavailable = loadError || Boolean(upcoming?.error)

  return (
    <>
      <Head><title>Call of Duty League — Legendary Picks</title></Head>

      <div className="space-y-10">
        <header className="space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-extrabold tracking-tight text-zinc-50">Call of Duty League</h1>
            {liveMatches.length > 0 ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-red-500/30 bg-red-500/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-red-400">
                <span className="h-1.5 w-1.5 rounded-full bg-red-500 animate-pulse motion-reduce:animate-none" />
                Live
              </span>
            ) : null}
          </div>
          <p className="max-w-2xl text-sm text-zinc-500">The CDL broadcast, running order, results, and picks in one place.</p>
        </header>

        <LiveNow matches={liveMatches} host={host} slate={matches} />

        <section className="space-y-5">
          <SectionHeader eyebrow="Broadcast schedule" title="Today on the stream" meta={`${matches.length} matches`} />
          {unavailable ? (
            <p className="text-sm text-zinc-500">The CoD slate is unavailable right now — retrying.</p>
          ) : isBuilding ? (
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
              <Eyebrow>Building the board</Eyebrow>
              <p className="mt-2 text-sm text-zinc-500">Pulling the live match, schedule, and results.</p>
            </div>
          ) : streamGroups.length === 0 ? (
            <p className="text-sm text-zinc-500">No CoD broadcast running order is available right now.</p>
          ) : (
            <div className="space-y-4">
              {streamGroups.map((group) => (
                <div key={group.streamKey} data-stream-key={group.streamKey} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 sm:p-5">
                  <div className="flex items-center justify-between gap-3 border-b border-zinc-800/70 pb-3">
                    <Eyebrow>Official broadcast</Eyebrow>
                    <span className="truncate font-mono text-[10px] uppercase tracking-wider text-zinc-600">{group.streamKey}</span>
                  </div>
                  <div className="divide-y divide-zinc-800/70">
                    {group.matches.map((match) => (
                      <StreamMatchRow key={`${match.psId ?? 'match'}-${match.teamA}-${match.teamB}-${match.startTime ?? 'tbd'}`} match={match} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="space-y-5">
          <SectionHeader eyebrow="Completed matches" title="Results" meta={`${results.length} final`} />
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 sm:p-5">
            {isBuilding ? (
              <p className="text-sm text-zinc-500">Loading results.</p>
            ) : results.length === 0 ? (
              <p className="text-sm text-zinc-500">No finished CoD matches yet.</p>
            ) : (
              <div className="divide-y divide-zinc-800/70">
                {results.map((match) => (
                  <ResultRow key={`${match.psId ?? 'result'}-${match.teamA}-${match.teamB}-${match.startTime ?? 'tbd'}`} match={match} />
                ))}
              </div>
            )}
          </div>
        </section>

        {showStandings ? (
          <section className="space-y-5">
            <SectionHeader eyebrow="Derived from completed matches" title="Championship — results so far" />
            <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/40">
              <div className="grid grid-cols-[minmax(0,1fr)_3rem_3rem] border-b border-zinc-800 px-4 py-2 font-mono text-[10px] uppercase tracking-wider text-zinc-600 sm:px-5">
                <span>Team</span>
                <span className="text-right">W</span>
                <span className="text-right">L</span>
              </div>
              <div className="divide-y divide-zinc-800/70">
                {standings.rows.map((row) => (
                  <div key={row.team} className="grid grid-cols-[minmax(0,1fr)_3rem_3rem] items-center px-4 py-3 sm:px-5">
                    <div className="flex min-w-0 items-center gap-2">
                      <TeamCrest src={row.logo} size="h-5 w-5" />
                      <span className="truncate text-sm font-semibold text-zinc-200">{row.team}</span>
                    </div>
                    <span className="text-right font-mono text-sm font-bold tabular-nums text-zinc-100">{row.wins}</span>
                    <span className="text-right font-mono text-sm tabular-nums text-zinc-500">{row.losses}</span>
                  </div>
                ))}
              </div>
            </div>
          </section>
        ) : null}

        <section className="space-y-5">
          <SectionHeader eyebrow="Call of Duty picks" title="Make your pick" />
          <div className="flex flex-col items-start justify-between gap-4 rounded-xl border border-zinc-800 bg-zinc-900/40 p-5 sm:flex-row sm:items-center">
            <div>
              <p className="text-sm font-semibold text-zinc-200">See the current CoD prices on the picks board.</p>
              <p className="mt-1 text-xs text-zinc-500">The existing pick flow keeps your selection and ledger in one place.</p>
            </div>
            <Link href="/predict?title=cod" className="shrink-0 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm font-semibold text-emerald-300 transition-colors hover:bg-emerald-500/15 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-emerald-400">
              Make a CoD pick
            </Link>
          </div>
        </section>
      </div>
    </>
  )
}
