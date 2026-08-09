import Head from 'next/head'
import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import { EwcModule } from '../../components/Esports/EwcModule'
import type { EwcProjection, Standings } from '../../components/Esports/EwcModule'
import { Eyebrow, SectionHeader } from '../../components/Esports/primitives'
import LiveDot from '../../components/LiveDot'
import { LiveNow, UpcomingSlate } from '../esports'
import type { UpMatch } from '../esports'

type TitleOption = {
  slug: string
  label: string
  match_count: number
  live_count: number
  result_count: number
  next_start: number | null
}

type UpcomingData = { matches: UpMatch[]; source?: string; error?: string; building?: boolean }

type HubTab = 'ewc' | 'live' | 'results' | 'games' | 'picks'

const POLL_MS = 10_000

const TABS: { key: HubTab; label: string }[] = [
  { key: 'ewc', label: 'EWC' },
  { key: 'live', label: 'Live & Upcoming' },
  { key: 'results', label: 'Results' },
  { key: 'games', label: 'Games' },
  { key: 'picks', label: 'Picks' },
]

/* The Esports league destination under the Leagues system. EWC 2026 tournament center first
 * (event focus, today/results, Club Championship rail), then the broader all-esports board
 * rendered inline from the shared /api/esports/upcoming contract — live broadcasts, the
 * day-grouped schedule, and results — plus per-title context and filtering. The live board
 * page /esports stays the dedicated live/picks surface; nothing here duplicates collectors. */
export default function EsportsLeaguePage() {
  const [activeTab, setActiveTab] = useState<HubTab>('ewc')
  const [titleFilter, setTitleFilter] = useState<string | null>(null)

  const [projection, setProjection] = useState<EwcProjection | null>(null)
  const [projectionError, setProjectionError] = useState(false)
  const [standings, setStandings] = useState<Standings | null>(null)
  const [standingsLoading, setStandingsLoading] = useState(true)
  // The page requests only the rows it renders: ten on desktop, five on mobile; the expand
  // action performs the bounded follow-up request to ten.
  const [standingsLimit, setStandingsLimit] = useState(5)
  const [titles, setTitles] = useState<TitleOption[] | null>(null)
  const [titlesError, setTitlesError] = useState(false)
  const [upcoming, setUpcoming] = useState<UpcomingData | null>(null)
  const [upcomingError, setUpcomingError] = useState(false)
  const [host, setHost] = useState('')
  const [reloadTick, setReloadTick] = useState(0)

  useEffect(() => {
    setHost(window.location.hostname)
    const mq = window.matchMedia('(min-width: 1024px)')
    const apply = () => setStandingsLimit(mq.matches ? 10 : 5)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])

  // EWC projection — poll while mounted; the module expires on its own via `active`.
  useEffect(() => {
    let alive = true
    const load = () => {
      fetch('/api/esports/events/ewc-2026', { cache: 'no-store' })
        .then((r) => r.json())
        .then((d: EwcProjection) => { if (alive) { setProjection(d); setProjectionError(false) } })
        .catch(() => { if (alive) setProjectionError(true) })
    }
    load()
    const timer = setInterval(load, POLL_MS)
    return () => { alive = false; clearInterval(timer) }
  }, [reloadTick])

  // Club Championship — the published snapshot reader with honest status.
  useEffect(() => {
    let alive = true
    setStandingsLoading(true)
    fetch(`/api/esports/events/ewc-2026/club-standings?limit=${standingsLimit}`, { cache: 'no-store' })
      .then((r) => r.json())
      .then((d: Standings) => { if (alive) setStandings(d) })
      .catch(() => { /* keep last known; the rail renders unavailable only on a real response */ })
      .finally(() => { if (alive) setStandingsLoading(false) })
    return () => { alive = false }
  }, [standingsLimit])

  // Title directory — one source of truth: the backend registry + the shared slate.
  useEffect(() => {
    let alive = true
    const load = () => {
      fetch('/api/esports/titles', { cache: 'no-store' })
        .then((r) => r.json())
        .then((d: { titles: TitleOption[] }) => { if (alive) { setTitles(d.titles ?? null); setTitlesError(false) } })
        .catch(() => { if (alive) setTitlesError(true) })
    }
    load()
    const timer = setInterval(load, POLL_MS * 3)
    return () => { alive = false; clearInterval(timer) }
  }, [])

  // The full all-esports board — same contract and cache the live board page uses.
  useEffect(() => {
    let alive = true
    const load = () => {
      fetch('/api/esports/upcoming', { cache: 'no-store' })
        .then((r) => r.json())
        .then((d: UpcomingData) => { if (alive) { setUpcoming(d); setUpcomingError(false) } })
        .catch(() => { if (alive) setUpcomingError(true) })
    }
    load()
    const timer = setInterval(load, POLL_MS)
    return () => { alive = false; clearInterval(timer) }
  }, [reloadTick])

  const ewcHasMatches = Boolean(
    projection &&
    (projection.matches.live.length > 0 ||
      projection.matches.upcoming.length > 0 ||
      projection.matches.completed.length > 0),
  )
  const liveCount = projection?.matches.live.length ?? 0

  const allMatches = upcoming?.matches ?? []
  const filteredLabel = titleFilter
    ? (titles?.find((t) => t.slug === titleFilter)?.label ?? null)
    : null
  const boardMatches = useMemo(
    () => (filteredLabel ? allMatches.filter((m) => m.title === filteredLabel) : allMatches),
    [allMatches, filteredLabel],
  )
  const boardLive = boardMatches.filter((m) => m.live)

  return (
    <>
      <Head><title>Esports — Legendary Picks</title></Head>

      <div className="space-y-8">
        {/* League-style header */}
        <header className="space-y-2">
          <Link href="/leagues" className="text-xs font-semibold text-zinc-500 transition-colors hover:text-zinc-300">Leagues</Link>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-3xl font-extrabold tracking-tight text-zinc-50">Esports</h1>
              {boardLive.length > 0 || liveCount > 0 ? (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-red-500/30 bg-red-500/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-red-400">
                  <LiveDot /> {boardLive.length + liveCount} live
                </span>
              ) : null}
            </div>
            <Link href="/esports" className="shrink-0 rounded-lg bg-zinc-800 px-4 py-2 text-sm font-semibold text-zinc-200 transition-colors hover:bg-zinc-700">
              Live esports →
            </Link>
          </div>
          <p className="max-w-2xl text-sm text-zinc-500">Tournament center, the full esports board, per-title desks, and picks — in one place.</p>
        </header>

        {/* In-page navigation — unmistakable, scrolls on mobile */}
        <nav aria-label="Esports league sections"
             className="-mx-4 flex gap-0 overflow-x-auto overflow-y-hidden border-b border-zinc-800 px-4 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              aria-current={activeTab === tab.key ? 'page' : undefined}
              className={`whitespace-nowrap border-b-2 px-4 py-3 text-sm font-medium transition-colors -mb-px ${
                activeTab === tab.key
                  ? 'border-emerald-500 text-white'
                  : 'border-transparent text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        {/* Active title filter — applies to the board sections below */}
        {filteredLabel ? (
          <div className="flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm">
            <span className="text-emerald-300">Showing only {filteredLabel}</span>
            <button type="button" onClick={() => setTitleFilter(null)}
                    className="ml-auto rounded-full border border-emerald-500/40 px-2 py-0.5 text-[11px] font-semibold text-emerald-300 transition-colors hover:bg-emerald-500/15">
              Clear filter ×
            </button>
          </div>
        ) : null}

        {activeTab === 'ewc' && (
          <>
            {projectionError ? (
              <div className="flex items-center justify-between gap-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                <span>Couldn&apos;t load the EWC tournament center.</span>
                <button type="button" onClick={() => setReloadTick((t) => t + 1)}
                        className="shrink-0 font-medium text-red-200 transition-colors hover:text-red-100">
                  Retry
                </button>
              </div>
            ) : !projection ? (
              <div className="space-y-3 animate-pulse">
                <div className="h-6 w-56 rounded bg-zinc-800" />
                <div className="h-32 rounded-xl bg-zinc-900/50" />
              </div>
            ) : !ewcHasMatches ? (
              <div className="rounded-xl bg-zinc-900/50 px-4 py-5 sm:px-6 sm:py-6">
                <Eyebrow>Esports World Cup 2026</Eyebrow>
                <p className="mt-3 text-sm text-zinc-500">
                  No active EWC 2026 matches right now. The tournament center returns automatically when the next event goes live.
                </p>
              </div>
            ) : (
              <EwcModule projection={projection} host={host} standings={standings}
                         standingsLimit={standingsLimit} onExpandStandings={() => setStandingsLimit(10)}
                         standingsLoading={standingsLoading} />
            )}
          </>
        )}

        {activeTab === 'live' && (
          <section className="space-y-5">
            <SectionHeader live eyebrow="Live & Upcoming" title="All esports, live and coming up" meta={boardLive.length ? `${boardLive.length} live` : undefined} />
            {upcomingError ? (
              <div className="flex items-center justify-between gap-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                <span>Couldn&apos;t load the esports board.</span>
                <button type="button" onClick={() => setReloadTick((t) => t + 1)}
                        className="shrink-0 font-medium text-red-200 transition-colors hover:text-red-100">
                  Retry
                </button>
              </div>
            ) : !upcoming ? (
              <div className="space-y-3 animate-pulse">
                <div className="h-6 w-64 rounded bg-zinc-800" />
                <div className="h-40 rounded-xl bg-zinc-900/50" />
              </div>
            ) : (
              <>
                <LiveNow matches={boardLive} host={host} slate={boardMatches} />
                {boardLive.length === 0 ? (
                  <p className="text-sm text-zinc-500">{filteredLabel ? `No ${filteredLabel} matches live right now.` : 'No esports matches live right now.'}</p>
                ) : null}
                <div className="space-y-3">
                  <SectionHeader eyebrow="Schedule" title="Upcoming matches" />
                  <UpcomingSlate data={{ ...upcoming, matches: boardMatches }} variant="schedule" />
                </div>
              </>
            )}
          </section>
        )}

        {activeTab === 'results' && (
          <section className="space-y-5">
            <SectionHeader eyebrow="Results" title="Recent results" meta={upcoming?.matches ? `${upcoming.matches.filter((m) => m.finished).length} final` : undefined} />
            {upcomingError ? (
              <div className="flex items-center justify-between gap-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                <span>Couldn&apos;t load the esports board.</span>
                <button type="button" onClick={() => setReloadTick((t) => t + 1)}
                        className="shrink-0 font-medium text-red-200 transition-colors hover:text-red-100">
                  Retry
                </button>
              </div>
            ) : !upcoming ? (
              <div className="h-40 animate-pulse rounded-xl bg-zinc-900/50" />
            ) : (
              <UpcomingSlate data={{ ...upcoming, matches: boardMatches }} variant="results" />
            )}
          </section>
        )}

        {activeTab === 'games' && (
          <GamesSection titles={titles} titlesError={titlesError} matches={allMatches}
                        activeSlug={titleFilter} onToggle={(slug) => setTitleFilter(titleFilter === slug ? null : slug)} />
        )}

        {activeTab === 'picks' && (
          <PicksSection titles={titles} titlesError={titlesError} />
        )}
      </div>
    </>
  )
}

/* ---------------- Games — per-title context + filter ---------------- */

type TitleContext = {
  title: TitleOption
  live: UpMatch | null
  next: UpMatch | null
  recent: UpMatch | null
}

function titleContexts(titles: TitleOption[], matches: UpMatch[]): TitleContext[] {
  return titles.map((title) => {
    const ms = matches.filter((m) => m.title === title.label)
    const live = ms.find((m) => m.live) ?? null
    const next = ms
      .filter((m) => !m.live && !m.finished)
      .sort((a, b) => (a.startTime ?? Infinity) - (b.startTime ?? Infinity))[0] ?? null
    const recent = ms
      .filter((m) => m.finished)
      .sort((a, b) => (b.startTime ?? 0) - (a.startTime ?? 0))[0] ?? null
    return { title, live, next, recent }
  })
}

function startLabel(ms: number | null): string {
  if (!ms) return 'Time TBD'
  const d = new Date(ms)
  const isToday = d.toDateString() === new Date().toDateString()
  return isToday
    ? d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    : d.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

function GamesSection({ titles, titlesError, matches, activeSlug, onToggle }: {
  titles: TitleOption[] | null
  titlesError: boolean
  matches: UpMatch[]
  activeSlug: string | null
  onToggle: (slug: string) => void
}) {
  return (
    <section className="space-y-5">
      <SectionHeader eyebrow="Games" title="Titles on the board" meta={titles ? `${titles.length} titles` : undefined} />
      {titlesError ? (
        <p className="text-sm text-zinc-500">The title directory is unavailable right now — the live board still works.</p>
      ) : !titles ? (
        <div className="flex flex-wrap gap-2 animate-pulse">
          <div className="h-8 w-28 rounded-full bg-zinc-800" />
          <div className="h-8 w-24 rounded-full bg-zinc-800" />
          <div className="h-8 w-32 rounded-full bg-zinc-800" />
        </div>
      ) : (
        <>
          {/* Filter controls — selecting a title filters the Live/Upcoming/Results content */}
          <div className="flex flex-wrap gap-2">
            {titles.map((t) => {
              const active = t.slug === activeSlug
              return (
                <button
                  key={t.slug}
                  type="button"
                  onClick={() => onToggle(t.slug)}
                  aria-pressed={active}
                  className={`rounded-full border px-3 py-1.5 text-[12px] font-medium transition-colors ${
                    active
                      ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                      : 'border-zinc-800 bg-zinc-900/60 text-zinc-500 hover:text-zinc-300'
                  }`}
                >
                  {t.live_count > 0 && <span className="mr-1 text-emerald-400">●</span>}
                  {t.label}
                </button>
              )
            })}
          </div>

          {/* Per-title context: live now / next / most recent */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {titleContexts(titles, matches).map((ctx) => (
              <div key={ctx.title.slug}
                   className={`rounded-xl border p-4 ${activeSlug === ctx.title.slug ? 'border-emerald-500/40 bg-zinc-900/60' : 'border-zinc-800 bg-zinc-900/40'}`}>
                <div className="flex items-center justify-between gap-2">
                  <button type="button" onClick={() => onToggle(ctx.title.slug)}
                          className="text-sm font-bold text-zinc-100 transition-colors hover:text-emerald-400">
                    {ctx.title.label}
                  </button>
                  {ctx.live ? (
                    <span className="inline-flex items-center gap-1 rounded border border-red-500/30 bg-red-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-red-400">
                      <LiveDot /> Live
                    </span>
                  ) : null}
                </div>
                <div className="mt-3 space-y-2 text-xs">
                  <ContextLine label="Live now" match={ctx.live} />
                  <ContextLine label="Next" match={ctx.next} />
                  <ContextLine label="Recent" match={ctx.recent} />
                </div>
                <div className="mt-3 flex items-center gap-3">
                  <Link href={`/esports/${ctx.title.slug}`} className="text-[11px] font-semibold text-zinc-400 transition-colors hover:text-emerald-400">
                    Desk →
                  </Link>
                  <Link href={`/predict?title=${ctx.title.slug}`} className="text-[11px] font-semibold text-zinc-400 transition-colors hover:text-emerald-400">
                    Picks →
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  )
}

function ContextLine({ label, match }: { label: string; match: UpMatch | null }) {
  if (!match) {
    return (
      <div className="flex items-baseline justify-between gap-2 text-zinc-600">
        <span className="uppercase tracking-wider text-[10px]">{label}</span>
        <span>—</span>
      </div>
    )
  }
  const meta = match.live
    ? 'live'
    : match.finished
      ? `${match.score?.a ?? '–'} – ${match.score?.b ?? '–'}`
      : startLabel(match.startTime)
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="shrink-0 uppercase tracking-wider text-[10px] text-zinc-500">{label}</span>
      <span className="min-w-0 truncate text-right text-zinc-300">{match.teamA} vs {match.teamB} <span className="text-zinc-500">· {meta}</span></span>
    </div>
  )
}

/* ---------------- Picks — direct paths to every title and the picks board ---------------- */

function PicksSection({ titles, titlesError }: { titles: TitleOption[] | null; titlesError: boolean }) {
  return (
    <section className="space-y-5">
      <SectionHeader eyebrow="Picks" title="Make your call" />
      <div className="flex flex-col items-start justify-between gap-4 rounded-xl border border-zinc-800 bg-zinc-900/40 p-5 sm:flex-row sm:items-center">
        <div>
          <p className="text-sm font-semibold text-zinc-200">See the current esports matches on the picks board.</p>
          <p className="mt-1 text-xs text-zinc-500">Your selection and ledger live in the existing pick flow.</p>
        </div>
        <Link href="/predict" className="shrink-0 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm font-semibold text-emerald-300 transition-colors hover:bg-emerald-500/15">
          Open the picks board
        </Link>
      </div>
      {titlesError ? (
        <p className="text-sm text-zinc-500">Title links are unavailable right now.</p>
      ) : !titles ? (
        <div className="flex flex-wrap gap-2 animate-pulse">
          <div className="h-8 w-28 rounded-full bg-zinc-800" />
          <div className="h-8 w-24 rounded-full bg-zinc-800" />
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {titles.map((t) => (
            <Link key={t.slug} href={`/predict?title=${t.slug}`}
                   className="rounded-full border border-zinc-800 bg-zinc-900/60 px-3 py-1.5 text-[12px] font-medium text-zinc-400 transition-colors hover:border-emerald-500/40 hover:text-emerald-300">
              {t.label} picks →
            </Link>
          ))}
        </div>
      )}
    </section>
  )
}
