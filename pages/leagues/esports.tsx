import Head from 'next/head'
import Link from 'next/link'
import { useEffect, useState } from 'react'
import { EwcModule } from '../../components/Esports/EwcModule'
import type { EwcProjection, Standings } from '../../components/Esports/EwcModule'
import { Eyebrow, SectionHeader } from '../../components/Esports/primitives'
import LiveDot from '../../components/LiveDot'

type TitleOption = {
  slug: string
  label: string
  match_count: number
  live_count: number
  result_count: number
  next_start: number | null
}

const POLL_MS = 10_000

/* The Esports league destination under the Leagues system. Owns the EWC 2026 tournament
 * center (event focus, today/results, Club Championship rail), title discovery, and the
 * non-EWC context links. The live broadcast + match board lives at /esports and is NOT
 * duplicated here — this page links to it and reuses its LiveCard machinery via EwcModule. */
export default function EsportsLeaguePage() {
  const [projection, setProjection] = useState<EwcProjection | null>(null)
  const [projectionError, setProjectionError] = useState(false)
  const [standings, setStandings] = useState<Standings | null>(null)
  const [standingsLoading, setStandingsLoading] = useState(true)
  // The landing page requests only the rows it renders: ten on desktop, five on mobile; the
  // expand action performs the bounded follow-up request to ten.
  const [standingsLimit, setStandingsLimit] = useState(5)
  const [titles, setTitles] = useState<TitleOption[] | null>(null)
  const [titlesError, setTitlesError] = useState(false)
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

  // Title discovery — one source of truth: the backend registry + the shared slate.
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

  const ewcHasMatches = Boolean(
    projection &&
    (projection.matches.live.length > 0 ||
      projection.matches.upcoming.length > 0 ||
      projection.matches.completed.length > 0),
  )
  const liveCount = projection?.matches.live.length ?? 0

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
              {liveCount > 0 ? (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-red-500/30 bg-red-500/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-red-400">
                  <LiveDot /> {liveCount} live
                </span>
              ) : null}
            </div>
            <Link href="/esports" className="shrink-0 rounded-lg bg-zinc-800 px-4 py-2 text-sm font-semibold text-zinc-200 transition-colors hover:bg-zinc-700">
              Live esports →
            </Link>
          </div>
          <p className="max-w-2xl text-sm text-zinc-500">Tournament center, Club Championship, cross-title schedule, and results — with the live board one click away.</p>
        </header>

        {/* EWC 2026 tournament center */}
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

        {/* Game/title discovery — direct paths to title desks and picks */}
        <section className="space-y-4">
          <SectionHeader eyebrow="Games" title="All esports titles" meta={titles ? `${titles.length} titles` : undefined} />
          {titlesError ? (
            <p className="text-sm text-zinc-500">The title directory is unavailable right now — the live board still works.</p>
          ) : !titles ? (
            <div className="flex gap-2 animate-pulse">
              <div className="h-8 w-24 rounded-full bg-zinc-800" />
              <div className="h-8 w-28 rounded-full bg-zinc-800" />
              <div className="h-8 w-20 rounded-full bg-zinc-800" />
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {titles.map((t) => (
                <TitlePill key={t.slug} title={t} />
              ))}
            </div>
          )}
        </section>

        {/* Broader esports context — the live board and picks stay one click away */}
        <section className="space-y-4">
          <SectionHeader eyebrow="Live board" title="Everything, all titles" />
          <div className="flex flex-col gap-4 rounded-xl border border-zinc-800 bg-zinc-900/40 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-zinc-200">The full esports broadcast board</p>
              <p className="mt-1 text-xs leading-relaxed text-zinc-500">Confirmed-live streams, up-next continuity, the day-grouped schedule, and results across every title — including matches outside the EWC.</p>
            </div>
            <div className="flex shrink-0 items-center gap-4">
              <Link href="/esports" className="text-sm font-semibold text-emerald-400 transition-colors hover:text-emerald-300">Live board →</Link>
              <Link href="/predict" className="text-sm font-semibold text-zinc-400 transition-colors hover:text-zinc-200">Make Picks →</Link>
            </div>
          </div>
        </section>
      </div>
    </>
  )
}

function TitlePill({ title }: { title: TitleOption }) {
  return (
    <div className="inline-flex items-center gap-1.5 rounded-full border border-zinc-800 bg-zinc-900/60 px-3 py-1.5">
      {title.live_count > 0 ? <span className="text-emerald-400" aria-hidden="true">●</span> : null}
      <Link href={`/esports/${title.slug}`} className="text-[12px] font-medium text-zinc-300 transition-colors hover:text-emerald-400">
        {title.label}
      </Link>
      {title.match_count > 0 ? <span className="text-[10px] text-zinc-500 opacity-60">{title.match_count}</span> : null}
      <span className="text-zinc-700">·</span>
      <Link href={`/predict?title=${title.slug}`} className="text-[11px] font-medium text-zinc-500 transition-colors hover:text-emerald-400">
        Picks
      </Link>
    </div>
  )
}
