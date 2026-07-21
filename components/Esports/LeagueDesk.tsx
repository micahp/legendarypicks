import { useEffect, useMemo, useState } from 'react'
import Head from 'next/head'
import Link from 'next/link'
import { LiveNow } from '../../pages/esports'

type Watch = {
  platform: string
  url: string
  channel: string | null
  online?: boolean | null
  embedUrl?: string | null
  alternates?: Watch[]
}

export type LeagueMatch = {
  matchKey: string
  startTime: number | null
  endTime: number | null
  live: boolean
  state?: string | null
  title: string
  league: string
  teamA: string
  teamB: string
  favorite: { name: string; pct: number } | null
  watch: Watch | null
  score?: { a: number | null; b: number | null } | null
  finished?: boolean | null
  finishedAt?: number | null
  winner?: 'a' | 'b' | null
  resultUnknown?: boolean | null
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

export type TitleOption = {
  slug: string
  label: string
  match_count: number
  live_count: number
  result_count: number
  next_start: number | null
}

export type LeagueSlate = {
  schema_version: string
  selected_title: { slug: string; label: string }
  titles: TitleOption[]
  matches: LeagueMatch[]
  results: LeagueMatch[]
  match_count: number
  result_count: number
  has_more_matches: boolean
  has_more_results: boolean
  building: boolean
  error: string | null
  source: string | null
}

type StreamGroup = { streamKey: string; matches: LeagueMatch[] }

const POLL_MS = 10_000

// Only Call of Duty has a real match-detail route today (/game/call-of-duty/{psId}).
// Other titles get no dead link until an equivalent route exists.
const DETAIL_ROUTE_SLUGS = new Set(['call-of-duty'])

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

// This is a multi-day slate (schedule/results routinely span several days), so
// a bare time-only label on a non-today row is misleading — include the date.
function formatStart(ms: number | null): string {
  if (!ms) return 'Time TBD'
  const d = new Date(ms)
  const isToday = d.toDateString() === new Date().toDateString()
  return isToday
    ? d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
    : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

function detailHref(slug: string, match: LeagueMatch): string | null {
  if (!DETAIL_ROUTE_SLUGS.has(slug) || match.psId == null) return null
  return `/game/${slug}/${match.psId}`
}

// Groups matches that share a confirmed broadcast (streamKey). Matches without
// one are NOT dropped — they're returned separately so partial stream coverage
// never silently loses games off the schedule.
function groupByStream(matches: LeagueMatch[]): { groups: StreamGroup[]; ungrouped: LeagueMatch[] } {
  const byStream = new Map<string, LeagueMatch[]>()
  const ungrouped: LeagueMatch[] = []
  for (const match of matches) {
    if (!match.streamKey) { ungrouped.push(match); continue }
    const group = byStream.get(match.streamKey) ?? []
    group.push(match)
    byStream.set(match.streamKey, group)
  }
  const groups = Array.from(byStream.entries())
    .map(([streamKey, streamMatches]) => ({
      streamKey,
      matches: streamMatches.sort((a, b) => (a.startTime ?? Infinity) - (b.startTime ?? Infinity)),
    }))
    .sort((a, b) => (a.matches[0]?.startTime ?? Infinity) - (b.matches[0]?.startTime ?? Infinity))
  ungrouped.sort((a, b) => (a.startTime ?? Infinity) - (b.startTime ?? Infinity))
  return { groups, ungrouped }
}

function StateChip({ match }: { match: LeagueMatch }) {
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

function StreamMatchRow({ slug, match }: { slug: string; match: LeagueMatch }) {
  const href = detailHref(slug, match)
  const teamClass = (side: 'a' | 'b') => {
    if (!match.finished || !match.winner) return 'text-zinc-200'
    return match.winner === side ? 'text-zinc-100' : 'text-zinc-500'
  }
  return (
    <div data-league-match={`${match.teamA} vs ${match.teamB}`} className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center">
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
      {href ? (
        <Link href={href} className="shrink-0 font-mono text-[10px] uppercase tracking-wider text-zinc-500 hover:text-emerald-400">
          Match read →
        </Link>
      ) : null}
    </div>
  )
}

function ResultRow({ slug, match }: { slug: string; match: LeagueMatch }) {
  const href = detailHref(slug, match)
  const unknown = Boolean(match.resultUnknown)
  const teamClass = (side: 'a' | 'b') => (!unknown && match.winner === side) ? 'text-zinc-100' : 'text-zinc-500'
  return (
    <div data-league-result={`${match.teamA} vs ${match.teamB}`} className="flex items-center gap-4 py-3">
      <div className="hidden w-24 shrink-0 font-mono text-[10px] tabular-nums text-zinc-600 sm:block">{formatStart(match.startTime)}</div>
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex items-center gap-2">
          <TeamCrest src={match.logoA} size="h-5 w-5" />
          <span className={`min-w-0 flex-1 truncate text-sm font-semibold ${teamClass('a')}`}>{match.teamA}</span>
          {!unknown && <span className={`font-mono text-sm font-bold tabular-nums ${teamClass('a')}`}>{match.score?.a ?? '–'}</span>}
        </div>
        <div className="flex items-center gap-2">
          <TeamCrest src={match.logoB} size="h-5 w-5" />
          <span className={`min-w-0 flex-1 truncate text-sm font-semibold ${teamClass('b')}`}>{match.teamB}</span>
          {!unknown && <span className={`font-mono text-sm font-bold tabular-nums ${teamClass('b')}`}>{match.score?.b ?? '–'}</span>}
        </div>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-2">
        {unknown ? (
          <span className="rounded border border-zinc-800 bg-zinc-900 px-2 py-1 font-mono text-[10px] font-medium uppercase tracking-wider text-zinc-500">Result unavailable</span>
        ) : (
          <span className="rounded border border-zinc-700 bg-zinc-800/60 px-2 py-1 font-mono text-[10px] font-medium uppercase tracking-wider text-zinc-400">Final</span>
        )}
        {href ? <Link href={href} className="font-mono text-[10px] uppercase tracking-wider text-zinc-500 hover:text-emerald-400">Match read →</Link> : null}
      </div>
    </div>
  )
}

export default function LeagueDesk({ slug, onSelectTitle }: { slug: string; onSelectTitle: (slug: string) => void }) {
  const [slate, setSlate] = useState<LeagueSlate | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [reloadTick, setReloadTick] = useState(0)
  const [host, setHost] = useState('')

  useEffect(() => { setHost(window.location.hostname) }, [])

  useEffect(() => {
    let alive = true
    setLoading(true)
    setFetchError(null)
    fetch(`/api/esports/league/${encodeURIComponent(slug)}`, { cache: 'no-store' })
      .then(async (r) => {
        if (!r.ok) {
          const body = await r.json().catch(() => null)
          throw new Error(body?.detail || `Failed to load league desk (${r.status})`)
        }
        return r.json() as Promise<LeagueSlate>
      })
      .then((data) => { if (alive) setSlate(data) })
      .catch((e) => { if (alive) setFetchError(e instanceof Error ? e.message : 'Failed to load league desk') })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [slug, reloadTick])

  // Poll while mounted, same cadence as the previous CoD-only desk.
  useEffect(() => {
    const timer = setInterval(() => setReloadTick((t) => t + 1), POLL_MS)
    return () => clearInterval(timer)
  }, [])

  const matches = slate?.matches ?? []
  const results = slate?.results ?? []
  const liveMatches = useMemo(() => matches.filter((m) => m.live), [matches])
  const { groups: streamGroups, ungrouped } = useMemo(() => groupByStream(matches), [matches])
  const isBuilding = slate === null || Boolean(slate.building && matches.length === 0 && results.length === 0)
  const unavailable = Boolean(fetchError) || Boolean(slate?.error)
  const selectedLabel = slate?.selected_title.label || slug
  // The requested slug can be an alias (e.g. /esports/cod) — use the API's
  // resolved canonical slug for pill highlighting, detail links, and Predict.
  const canonicalSlug = slate?.selected_title.slug || slug

  return (
    <div className="space-y-10">
      <Head><title>{selectedLabel} — Legendary Picks</title></Head>
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-extrabold tracking-tight text-zinc-50">{selectedLabel}</h1>
          <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-400">Esports</span>
          {liveMatches.length > 0 ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-red-500/30 bg-red-500/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-red-400">
              <span className="h-1.5 w-1.5 rounded-full bg-red-500 animate-pulse motion-reduce:animate-none" />
              Live
            </span>
          ) : null}
        </div>
        <p className="max-w-2xl text-sm text-zinc-500">The broadcast schedule, running order, and results for {selectedLabel}, in one place.</p>
      </header>

      {/* Title selector — all 8 supported esports titles */}
      <div className="flex gap-1.5 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {(slate?.titles || []).map((t) => {
          const active = t.slug === canonicalSlug
          return (
            <button
              key={t.slug}
              type="button"
              onClick={() => onSelectTitle(t.slug)}
              className={`shrink-0 rounded-full border px-3 py-1.5 text-[12px] font-medium transition-colors ${
                active
                  ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                  : 'border-zinc-800 bg-zinc-900/60 text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {t.live_count > 0 && <span className="mr-1 text-emerald-400">●</span>}
              {t.label}
              {t.match_count > 0 && <span className="ml-1 opacity-60">{t.match_count}</span>}
            </button>
          )
        })}
      </div>

      {fetchError && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          <span>{fetchError}</span>
          <button onClick={() => setReloadTick((t) => t + 1)} className="shrink-0 font-medium text-red-200 hover:text-red-100">
            Retry
          </button>
        </div>
      )}
      {!fetchError && slate?.error && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
          {slate.error}
        </div>
      )}

      <LiveNow matches={liveMatches} host={host} slate={matches} />

      <section className="space-y-5">
        <SectionHeader
          eyebrow="Broadcast schedule"
          title="Live and upcoming"
          meta={slate?.has_more_matches ? `${matches.length} of ${slate.match_count} matches` : `${slate?.match_count ?? matches.length} matches`}
        />
        {unavailable ? (
          <p className="text-sm text-zinc-500">The {selectedLabel} slate is unavailable right now — retrying.</p>
        ) : isBuilding ? (
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
            <Eyebrow>Building the board</Eyebrow>
            <p className="mt-2 text-sm text-zinc-500">Pulling the live match, schedule, and results.</p>
          </div>
        ) : matches.length === 0 ? (
          <p className="text-sm text-zinc-500">No open {selectedLabel} matches right now.</p>
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
                    <StreamMatchRow key={match.matchKey} slug={canonicalSlug} match={match} />
                  ))}
                </div>
              </div>
            ))}
            {ungrouped.length > 0 && (
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 sm:p-5">
                {streamGroups.length > 0 && (
                  <div className="border-b border-zinc-800/70 pb-3">
                    <Eyebrow>Other matches</Eyebrow>
                  </div>
                )}
                <div className="divide-y divide-zinc-800/70">
                  {ungrouped.map((match) => (
                    <StreamMatchRow key={match.matchKey} slug={canonicalSlug} match={match} />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      <section className="space-y-5">
        <SectionHeader
          eyebrow="Completed matches"
          title="Results"
          meta={slate?.has_more_results ? `${results.length} of ${slate.result_count} final` : `${slate?.result_count ?? results.length} final`}
        />
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 sm:p-5">
          {isBuilding ? (
            <p className="text-sm text-zinc-500">Loading results.</p>
          ) : results.length === 0 ? (
            <p className="text-sm text-zinc-500">No finished {selectedLabel} matches yet.</p>
          ) : (
            <div className="divide-y divide-zinc-800/70">
              {results.map((match) => (
                <ResultRow key={match.matchKey} slug={canonicalSlug} match={match} />
              ))}
            </div>
          )}
        </div>
      </section>

      {/* No derived standings here: results span many concurrent tournaments/
          leagues per title (confirmed on live CS2/LoL/CoD data), so aggregating
          them into one win-loss table would be a false standings table. Only
          add this back once the league API can scope results to one
          competition. */}

      <section className="space-y-5">
        <SectionHeader eyebrow={`${selectedLabel} picks`} title="Make your pick" />
        <div className="flex flex-col items-start justify-between gap-4 rounded-xl border border-zinc-800 bg-zinc-900/40 p-5 sm:flex-row sm:items-center">
          <div>
            <p className="text-sm font-semibold text-zinc-200">See the current {selectedLabel} matches on the picks board.</p>
            <p className="mt-1 text-xs text-zinc-500">The existing pick flow keeps your selection and ledger in one place.</p>
          </div>
          <Link href={`/predict?title=${canonicalSlug}`} className="shrink-0 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm font-semibold text-emerald-300 transition-colors hover:bg-emerald-500/15 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-emerald-400">
            Make a {selectedLabel} pick
          </Link>
        </div>
      </section>
    </div>
  )
}
