import Head from 'next/head'
import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import { EwcMatchRow, EwcModule } from '../../components/Esports/EwcModule'
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

function titleSlug(label: string): string {
  return label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
}

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
  const ewcMatches = useMemo(
    () => projection
      ? [...projection.matches.live, ...projection.matches.upcoming, ...projection.matches.completed]
      : [],
    [projection],
  )
  const activeProgramTitle = titleFilter
    ? projection?.titles?.find((title) => title.slug === titleFilter) ?? null
    : null
  const filteredLabel = titleFilter
    ? (activeProgramTitle?.name
      ?? titles?.find((t) => t.slug === titleFilter)?.label
      ?? ewcMatches.find((m) => titleSlug(m.title) === titleFilter)?.title
      ?? null)
    : null
  const boardTitleLabels = activeProgramTitle?.feedTitles ?? (filteredLabel ? [filteredLabel] : [])
  const boardMatches = useMemo(
    () => (boardTitleLabels.length ? allMatches.filter((m) => boardTitleLabels.includes(m.title)) : allMatches),
    [allMatches, boardTitleLabels],
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
          <GamesSection projection={projection} projectionError={projectionError} titles={titles}
                        activeSlug={titleFilter} onSelect={setTitleFilter} />
        )}

        {activeTab === 'picks' && (
          <PicksSection titles={titles} titlesError={titlesError} />
        )}
      </div>
    </>
  )
}

/* ---------------- Games — complete EWC event population ---------------- */

type MatchView = 'all' | 'live' | 'upcoming' | 'finals'

function GamesSection({ projection, projectionError, titles, activeSlug, onSelect }: {
  projection: EwcProjection | null
  projectionError: boolean
  titles: TitleOption[] | null
  activeSlug: string | null
  onSelect: (slug: string | null) => void
}) {
  const [matchView, setMatchView] = useState<MatchView>('all')
  const buckets = projection?.matches
  const all = buckets ? [...buckets.live, ...buckets.upcoming, ...buckets.completed] : []
  const labels = Array.from(new Set(all.map((m) => m.title))).sort((a, b) => a.localeCompare(b))
  const options = projection?.titles?.map((title) => ({
    label: title.name,
    slug: title.slug,
    tournaments: title.tournaments,
    feedTitles: title.feedTitles,
    scheduleStatus: title.schedule?.status ?? 'unavailable',
    scheduleCount: title.schedule?.count ?? 0,
    scheduleWeeks: title.schedule?.weeks ?? [],
    count: title.feedCount ?? all.filter((m) => title.feedTitles.includes(m.title)).length,
  })) ?? labels.map((label) => ({
    label,
    slug: titles?.find((t) => t.label === label)?.slug ?? titleSlug(label),
    tournaments: [label],
    feedTitles: [label],
    scheduleStatus: 'unavailable' as const,
    scheduleCount: 0,
    scheduleWeeks: [],
    count: all.filter((m) => m.title === label).length,
  }))
  const activeOption = options.find((option) => option.slug === activeSlug) ?? null
  const activeLabel = activeOption?.label ?? null
  const filter = (matches: UpMatch[]) => activeOption
    ? matches.filter((m) => activeOption.feedTitles.includes(m.title))
    : matches
  const titleLive = filter(buckets?.live ?? [])
  const titleUpcoming = filter(buckets?.upcoming ?? [])
  const titleCompleted = filter(buckets?.completed ?? [])
  const titleMatchCount = titleLive.length + titleUpcoming.length + titleCompleted.length
  const live = matchView === 'all' || matchView === 'live' ? titleLive : []
  const upcoming = matchView === 'all' || matchView === 'upcoming' ? titleUpcoming : []
  const completed = matchView === 'all' || matchView === 'finals' ? titleCompleted : []
  const visibleCount = live.length + upcoming.length + completed.length
  const representedTitleCount = options.filter((option) => option.count > 0).length
  const tournamentCount = projection?.tournamentCount
    ?? options.reduce((total, option) => total + option.tournaments.length, 0)
  // PandaScore ids are not globally unique across titles, so identity must include
  // the event context. A bare psId causes React to retain a row when title filters
  // change if two EWC games from different titles share the same provider id.
  const matchKey = (m: UpMatch) => [
    m.psId ?? 'no-ps-id',
    m.title,
    m.league,
    m.startTime ?? 'tbd',
    m.teamA,
    m.teamB,
  ].join(':')
  const matchViews: { key: MatchView; label: string; count: number }[] = [
    { key: 'all', label: 'All', count: titleMatchCount },
    { key: 'live', label: 'Live', count: titleLive.length },
    { key: 'upcoming', label: 'Upcoming', count: titleUpcoming.length },
    { key: 'finals', label: 'Finals', count: titleCompleted.length },
  ]
  const selectTitle = (slug: string | null) => {
    setMatchView('all')
    onSelect(slug)
  }

  return (
    <section className="space-y-5">
      <SectionHeader eyebrow="Games" title="EWC 2026 game titles"
                     meta={projection ? `${options.length} titles · ${tournamentCount} tournaments` : undefined} />
      <p className="max-w-2xl text-sm text-zinc-500">
        The complete official EWC program. Match coverage currently includes {all.length} live,
        scheduled, and final rows across {representedTitleCount} titles.
      </p>
      {projection?.programSource ? (
        <a href={projection.programSource.url} target="_blank" rel="noreferrer"
           className="inline-block text-xs font-medium text-zinc-500 transition-colors hover:text-zinc-300">
          Source: {projection.programSource.label} ↗
        </a>
      ) : null}
      {projectionError ? (
        <p className="text-sm text-red-300">The EWC game tracker is unavailable right now.</p>
      ) : !projection ? (
        <div className="space-y-3 animate-pulse">
          <div className="h-8 w-64 rounded bg-zinc-800" />
          <div className="h-48 rounded-xl bg-zinc-900/50" />
        </div>
      ) : (
        <>
          <div className="-mx-4 flex snap-x snap-mandatory gap-2 overflow-x-auto px-4 pb-2 sm:hidden [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
               aria-label="EWC title row" data-ewc-mobile-title-row="true">
            <button type="button" onClick={() => selectTitle(null)} aria-pressed={!activeSlug}
                    className={`min-w-max shrink-0 snap-start rounded-lg border px-3 py-2.5 text-left ${
                      !activeSlug
                        ? 'border-emerald-500/40 bg-emerald-500/15'
                        : 'border-zinc-800 bg-zinc-900/60'
                    }`}>
              <span className="block whitespace-nowrap text-xs font-semibold text-zinc-200">All 24 titles</span>
              <span className="mt-1 block whitespace-nowrap text-[11px] text-zinc-500">{all.length} tracked matches</span>
            </button>
            {options.map((option) => {
              const active = option.slug === activeSlug
              // Week label is DATA-derived from the published schedule snapshot (ISO weeks of
              // dated matches); 'Schedule pending' when the source has not published dates.
              const weekLabel = option.scheduleWeeks.length
                ? `Week${option.scheduleWeeks.length > 1 ? 's' : ''} ${option.scheduleWeeks.join('–')}`
                : 'Schedule pending'
              return (
                <button key={option.slug} type="button" onClick={() => selectTitle(active ? null : option.slug)}
                        aria-pressed={active}
                        className={`min-w-max shrink-0 snap-start rounded-lg border px-3 py-2.5 text-left ${
                          active
                            ? 'border-emerald-500/40 bg-emerald-500/15'
                            : 'border-zinc-800 bg-zinc-900/60'
                        }`}>
                  <span className="block whitespace-nowrap text-xs font-semibold text-zinc-200">{option.label}</span>
                  <span className="mt-1 block whitespace-nowrap text-[11px] text-zinc-500">
                    {weekLabel} · {option.count > 0 ? `${option.count} matches` : 'feed pending'}
                  </span>
                </button>
              )
            })}
          </div>

          <div className="hidden grid-cols-3 gap-2 sm:grid lg:grid-cols-4" data-ewc-title-catalog="true">
            {options.map((option) => {
              const active = option.slug === activeSlug
              // Week label is DATA-derived from the published schedule snapshot (ISO weeks of
              // dated matches); 'Schedule pending' when the source has not published dates.
              const weekLabel = option.scheduleWeeks.length
                ? `Week${option.scheduleWeeks.length > 1 ? 's' : ''} ${option.scheduleWeeks.join('–')}`
                : 'Schedule pending'
              return (
                <button
                  key={option.slug}
                  type="button"
                  onClick={() => selectTitle(active ? null : option.slug)}
                  aria-pressed={active}
                  className={`min-h-[78px] rounded-lg border p-3 text-left transition-colors ${
                    active
                      ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                      : 'border-zinc-800 bg-zinc-900/60 text-zinc-500 hover:text-zinc-300'
                  }`}
                >
                  <span className="block text-xs font-semibold leading-snug text-zinc-200">{option.label}</span>
                  <span className="mt-1 block text-[10px] uppercase tracking-wide text-zinc-600">
                    {weekLabel} · {option.tournaments.length} tournament{option.tournaments.length === 1 ? '' : 's'}
                  </span>
                  <span className="mt-1 block text-[11px] text-zinc-500">
                    {option.count > 0 ? `${option.count} tracked matches` : 'Match feed pending'}
                  </span>
                </button>
              )
            })}
          </div>

          {all.length > 0 && titleMatchCount > 0 ? (
            <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:hidden [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
                 aria-label="EWC match view">
              {matchViews.map((view) => (
                <button key={view.key} type="button" onClick={() => setMatchView(view.key)}
                        aria-pressed={matchView === view.key}
                        className={`whitespace-nowrap rounded-full border px-3 py-1.5 text-xs font-semibold ${
                          matchView === view.key
                            ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                            : 'border-zinc-800 bg-zinc-900 text-zinc-500'
                        }`}>
                  {view.label} {view.count}
                </button>
              ))}
            </div>
          ) : null}

          {activeOption && titleMatchCount === 0 ? (
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 px-4 py-4">
              <p className="text-sm font-semibold text-zinc-300">{activeLabel} is in the official EWC program.</p>
              <p className="mt-1 text-xs text-zinc-500">Its match schedule is not available in the normalized live feed yet.</p>
            </div>
          ) : all.length === 0 ? (
            <p className="text-sm text-zinc-500">No EWC match rows are published in the live feed right now.</p>
          ) : visibleCount === 0 ? (
            <p className="text-sm text-zinc-500">No {matchViews.find((view) => view.key === matchView)?.label.toLowerCase()} matches are available for this title.</p>
          ) : (
            <div className="space-y-8">
              {live.length > 0 ? (
                <div className="space-y-2">
                  <SectionHeader live eyebrow="Live" title="Live now" meta={`${live.length} games`} />
                  <div className="divide-y divide-zinc-800/60">
                    {live.map((m) => <EwcMatchRow key={matchKey(m)} m={m} />)}
                  </div>
                </div>
              ) : null}
              {upcoming.length > 0 ? (
                <div className="space-y-2">
                  <SectionHeader eyebrow="Schedule" title="Upcoming" meta={`${upcoming.length} games`} />
                  <div className="divide-y divide-zinc-800/60">
                    {upcoming.map((m) => <EwcMatchRow key={matchKey(m)} m={m} />)}
                  </div>
                </div>
              ) : null}
              {completed.length > 0 ? (
                <div className="space-y-2">
                  <SectionHeader eyebrow="Results" title="Finals" meta={`${completed.length} games`} />
                  <div className="divide-y divide-zinc-800/60">
                    {completed.map((m) => <EwcMatchRow key={matchKey(m)} m={m} />)}
                  </div>
                </div>
              ) : null}
            </div>
          )}
        </>
      )}
    </section>
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
