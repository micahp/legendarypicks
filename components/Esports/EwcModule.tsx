import { useState } from 'react'
import LiveDot from '../LiveDot'
import { Eyebrow, SectionHeader } from './primitives'
import { LiveCard, buildBroadcastViews, localDateKey, groupTime } from '../../pages/esports'
import type { UpMatch } from '../../pages/esports'

/* ---------------- EWC 2026 focus module ----------------
 *
 * The EWC tournament center lives HERE, in the Esports league destination
 * (pages/leagues/esports.tsx). It is deliberately NOT part of pages/esports.tsx:
 * the live board /esports has no tournament-center takeover — EWC matches appear
 * there only as ordinary board rows. This module reuses the board's own
 * LiveCard/buildBroadcastViews machinery so the tournament center and the board
 * share one stream/result/match-identity pipeline; nothing is duplicated. */

export type EwcProjection = {
  eventId: string
  eventName: string
  active: boolean
  building?: boolean
  asOf?: string | null
  titles?: EwcTitle[]
  titleCount?: number
  tournamentCount?: number
  programSource?: { label: string; url: string }
  matches: { live: UpMatch[]; upcoming: UpMatch[]; completed: UpMatch[] }
}

export type EwcTitle = {
  slug: string
  name: string
  tournaments: string[]
  feedTitles: string[]
  /** Data-derived schedule coverage from the published per-title snapshot (never program weeks). */
  schedule: {
    status: 'published' | 'unavailable'
    count: number
    datedCount: number
    firstStart: number | null
    lastStart: number | null
    weeks: number[]
    reason: string | null
    source: { label: string | null; urls: string[] | null; revisions: number[] | null; publishedAt: string | null } | null
  }
  /** EWC match rows currently in the normalized slate feed for this title. */
  feedCount: number
}

type StandingRow = {
  rank: number
  clubId: string
  clubName: string
  logo?: string | null
  points: number | null
  eligibleTopEightCount?: number | null
  titleWins?: number | null
  eligibleToWin?: boolean | null
  movement?: number | null
}

export type Standings = {
  event: string
  standings: StandingRow[]
  asOf: string | null
  source: { label: string | null; url: string | null } | null
  status: 'current' | 'stale' | 'unavailable'
  reason?: string
}

export function EwcMatchRow({ m }: { m: UpMatch }) {
  const t = m.startTime ? new Date(m.startTime) : null
  const timeLabel = t ? t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''
  const stateLabel = m.live ? 'LIVE' : m.finished ? 'FINAL' : timeLabel || 'TIME TBD'
  const score = m.score
  return (
    <div className="flex items-baseline gap-3 py-1.5" data-ewc-game-row="true">
      <span className={`w-12 shrink-0 text-[11px] font-semibold tabular-nums ${m.live ? 'text-red-400' : 'text-zinc-600'}`}>
        {stateLabel}
      </span>
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex items-center justify-between gap-3">
          <span className={`truncate text-sm ${m.finished && m.winner === 'b' ? 'text-zinc-500' : 'text-zinc-200'}`}>{m.teamA}</span>
          {m.finished && score ? <span className="shrink-0 font-mono text-sm font-bold tabular-nums text-zinc-200">{score.a ?? '\u2013'}</span> : null}
        </div>
        <div className="flex items-center justify-between gap-3">
          <span className={`truncate text-sm ${m.finished && m.winner === 'a' ? 'text-zinc-500' : 'text-zinc-200'}`}>{m.teamB}</span>
          {m.finished && score ? <span className="shrink-0 font-mono text-sm font-bold tabular-nums text-zinc-200">{score.b ?? '\u2013'}</span> : null}
        </div>
        <div className="text-[11px] text-zinc-600">{m.title} · {m.league}</div>
      </div>
    </div>
  )
}

/* ---------------- Club logo — compact crest beside the club name ---------------- */

function initialsOf(name: string): string {
  const words = (name || '').split(/\s+/).filter(Boolean).slice(0, 2)
  const chars = words.map((w) => w.replace(/[^A-Za-z0-9]/g, '').charAt(0).toUpperCase()).filter(Boolean)
  return chars.join('') || '?'
}

/* A fixed 20px crest slot (layout-shift prevention): the verified logo renders object-contain
 * with alt text; a neutral initials fallback shows when there is no verified logo or the image
 * fails to load. The slot is always reserved, so rows never reflow. */
function ClubLogo({ clubName, logo }: { clubName: string; logo?: string | null }) {
  const [failed, setFailed] = useState(false)
  const show = Boolean(logo) && !failed
  return (
    <span className="flex h-5 w-5 shrink-0 items-center justify-center overflow-hidden rounded bg-zinc-800"
          data-club-logo={show ? 'image' : 'fallback'}>
      {show ? (
        <img src={logo as string} alt={`${clubName} logo`} width={20} height={20}
             loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)}
             className="h-5 w-5 object-contain" />
      ) : (
        <span className="text-[9px] font-bold uppercase tracking-wide text-zinc-400">{initialsOf(clubName)}</span>
      )}
    </span>
  )
}

export function ClubStandingsRail({ standings, onExpand, expanded, loading }: {
  standings: Standings | null
  onExpand: () => void
  expanded: boolean
  loading: boolean
}) {
  if (loading && !standings) {
    return (
      <div className="space-y-3">
        <Eyebrow>Club Championship</Eyebrow>
        <div className="space-y-2 animate-pulse">
          <div className="h-4 w-3/4 rounded bg-zinc-800" />
          <div className="h-4 w-2/3 rounded bg-zinc-800" />
          <div className="h-4 w-4/5 rounded bg-zinc-800" />
        </div>
      </div>
    )
  }
  if (!standings || standings.status === 'unavailable') {
    return (
      <div className="space-y-3">
        <Eyebrow>Club Championship</Eyebrow>
        <div className="rounded-lg bg-zinc-900/60 px-4 py-4">
          <p className="text-sm font-semibold text-zinc-300">Standings unavailable</p>
          <p className="mt-1 text-xs leading-relaxed text-zinc-500">
            The published Club Championship snapshot is not readable right now. We are not
            guessing the table — it stays off until a valid published run exists.
          </p>
        </div>
      </div>
    )
  }
  const stale = standings.status === 'stale'
  const rows = standings.standings
  const asOf = standings.asOf ? new Date(standings.asOf).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : null
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <Eyebrow>Club Championship</Eyebrow>
        {stale ? (
          <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-400">
            Stale
          </span>
        ) : null}
      </div>
      {asOf ? <p className="text-[11px] text-zinc-600">Points · as of {asOf}</p> : null}
      {/* Open, border-light table: no outer border, no vertical rules, aligned tabular numbers. */}
      <div className="divide-y divide-zinc-800/60">
        {rows.map((r) => (
          <div key={r.clubId} className="flex items-center gap-3 py-2">
            <span className="w-5 shrink-0 text-right font-mono text-xs tabular-nums text-zinc-600">{r.rank}</span>
            <ClubLogo clubName={r.clubName} logo={r.logo} />
            <span className="min-w-0 flex-1 truncate text-sm font-medium text-zinc-200">{r.clubName}</span>
            <span className="shrink-0 font-mono text-sm font-bold tabular-nums text-zinc-100">
              {r.points === null ? '\u2013' : r.points}
            </span>
          </div>
        ))}
      </div>
      {standings.source?.label ? (
        <p className="text-[11px] text-zinc-600">
          Source: <a className="text-zinc-400 underline decoration-zinc-700 underline-offset-2 hover:text-zinc-200" href={standings.source.url || '#'} target="_blank" rel="noreferrer">{standings.source.label}</a>
        </p>
      ) : null}
      {!expanded ? (
        <button type="button" onClick={onExpand}
                className="text-xs font-semibold text-zinc-400 transition-colors hover:text-zinc-100">
          Show full top ten →
        </button>
      ) : null}
    </div>
  )
}

export function EwcModule({ projection, host, standings, standingsLimit, onExpandStandings, standingsLoading }: {
  projection: EwcProjection
  host: string
  standings: Standings | null
  standingsLimit: number
  onExpandStandings: () => void
  standingsLoading: boolean
}) {
  const live = projection.matches.live
  const upcoming = projection.matches.upcoming
  const completed = projection.matches.completed
  const now = Date.now()
  const broadcasts = buildBroadcastViews([...live, ...upcoming], live, now)
  const featured = broadcasts[0]
  const rest = broadcasts.slice(1)
  const today = localDateKey(now)
  const todaysUpcoming = upcoming.filter((m) => localDateKey(groupTime(m)) === today)
  const laterUpcoming = upcoming.filter((m) => localDateKey(groupTime(m)) !== today)
  const rail = (
    <ClubStandingsRail standings={standings} onExpand={onExpandStandings}
                       expanded={standingsLimit >= 10} loading={standingsLoading} />
  )
  return (
    <section className="rounded-xl bg-zinc-900/50 px-4 py-5 sm:px-6 sm:py-6">
      {/* One subtle plane for the EWC focus; no border, no shadow, no nested card walls. */}
      <SectionHeader eyebrow={projection.eventName} title="EWC 2026" meta={live.length ? `${live.length} live` : 'Tournament center'} live={live.length > 0} />

      <div className="mt-5 grid gap-8 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0 space-y-8">
          {featured ? (
            <div className="space-y-3">
              <LiveCard key={featured.key} m={featured.match} host={host} featured
                        upNext={featured.upNext} watchOverride={featured.watch}
                        startingSoon={featured.state === 'starting'}
                        broadcastKey={featured.key} broadcastState={featured.state} />
              {rest.length ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  {rest.map((b) => (
                    <LiveCard key={b.key} m={b.match} host={host} upNext={b.upNext}
                              watchOverride={b.watch} startingSoon={b.state === 'starting'}
                              broadcastKey={b.key} broadcastState={b.state} />
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}

          {upcoming.length ? (
            <div className="space-y-3">
              <SectionHeader eyebrow="Schedule" title={todaysUpcoming.length ? 'Today across titles' : 'Next EWC matches'} />
              <div className="space-y-1">
                {todaysUpcoming.length ? todaysUpcoming.map((m, i) => <EwcMatchRow key={i} m={m} />)
                  : laterUpcoming.slice(0, 5).map((m, i) => <EwcMatchRow key={i} m={m} />)}
              </div>
            </div>
          ) : null}

          {completed.length ? (
            <div className="space-y-3">
              <SectionHeader eyebrow="Results" title="EWC results" />
              <div className="space-y-1">
                {completed.slice(0, 8).map((m, i) => <EwcMatchRow key={i} m={m} />)}
              </div>
            </div>
          ) : null}
        </div>

        <aside className="min-w-0">{rail}</aside>
      </div>
    </section>
  )
}
