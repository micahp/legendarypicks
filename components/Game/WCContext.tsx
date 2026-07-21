import { useEffect, useState } from 'react'

type Scorer = { team: string; player: string; odds: number }
type Prop = {
  player: string
  market: string
  line: string
  lean: 'back' | 'fade' | 'watch'
  price_as_of?: string
  quote_age_seconds?: number
}
type MatchStat = { key: string; label: string; unit?: string; away?: string | null; home?: string | null }
type RouteMatch = {
  game_id: string
  round?: string
  date?: string
  opponent: { abbr?: string; name?: string }
  score_for?: number | null
  score_against?: number | null
  result: 'W' | 'L'
  extra_time?: boolean
  penalties?: boolean
}
type TeamHistory = { rest_days?: number | null; extra_time_matches: number; extra_time_minutes: number; matches: RouteMatch[] }
type History = { teams?: Record<string, TeamHistory>; head_to_head?: unknown[] }

type CatchUpReceipt = {
  ref: string
  kind: 'fact' | 'booth'
  scope: 'current_match' | 'historical_reference' | 'mixed'
  text: string
  captured_at?: string
  observed_at?: string
}
type CatchUpLine = {
  headline: string
  source?: 'fact' | 'booth' | 'combined'
  evidence_items?: CatchUpReceipt[]
  prop?: Prop
}

type MatchPhase = 'pregame' | 'first_half' | 'halftime' | 'second_half' | 'extra_time' | 'final' | 'live'
type BoothEpisode = {
  id: string
  headline?: string
  quote: string
  subject: string
  tag: string
  phase: MatchPhase
  latest_capture_at?: string
  match_time?: { display: string }
}
type BoothStatus = 'current' | 'quiet' | 'stale' | 'complete' | 'unavailable'

type Ctx = {
  headline: string
  status?: string
  current_phase?: MatchPhase
  teams: { home: { abbr: string; name: string; form?: string | null }; away: { abbr: string; name: string; form?: string | null } }
  top_scorers: Scorer[]
  match_stats?: MatchStat[]
  history?: History
  right_now?: CatchUpLine[]
  featured_episodes?: BoothEpisode[]
  coverage?: {
    booth_status: BoothStatus
    capture_latest_at?: string | null
    phases: { key: MatchPhase; label: string; episode_count: number }[]
  }
  social_sentiment?: { status: 'unavailable' | 'current'; reason?: string }
}

const POLL_MS = 30_000

const LEAN_STYLE: Record<string, { cls: string; mark: string }> = {
  back: { cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30', mark: '▲' },
  fade: { cls: 'bg-red-500/15 text-red-300 border-red-500/30', mark: '▼' },
  watch: { cls: 'bg-zinc-700/40 text-zinc-300 border-zinc-600/50', mark: '•' },
}

function PropChip({ prop }: { prop: Prop }) {
  const s = LEAN_STYLE[prop.lean] || LEAN_STYLE.watch
  return (
    <span className={`mt-1 inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium ${s.cls}`}>
      <span className="text-[10px]">{s.mark}</span>
      <span className="uppercase tracking-wide text-[9px] opacity-70">{prop.lean}</span>
      <span className="font-semibold">{prop.player}</span>
      <span className="opacity-80">{prop.market}</span>
      <span className="font-mono tabular-nums">{prop.line}</span>
      {prop.quote_age_seconds != null && (
        <span className="opacity-60">· priced {relativeFromSeconds(prop.quote_age_seconds)}</span>
      )}
    </span>
  )
}

function FormChips({ form }: { form?: string | null }) {
  if (!form) return null
  return (
    <span className="inline-flex gap-0.5">
      {form.split('').map((r, i) => (
        <span key={i} className={`inline-flex h-4 w-4 items-center justify-center rounded-sm text-[9px] font-bold ${
          r === 'W' ? 'bg-emerald-500/20 text-emerald-300' : r === 'L' ? 'bg-red-500/20 text-red-300' : 'bg-zinc-700/50 text-zinc-400'
        }`}>{r}</span>
      ))}
    </span>
  )
}

const fmtOdds = (o: number) => (o > 0 ? `+${o}` : `${o}`)

// Relative time is the primary display everywhere capture time appears — never
// a raw ISO substring, never presented as a match minute (see docs/API-wc-context-v2.md).
function relativeFromSeconds(seconds: number): string {
  if (seconds < 10) return 'just now'
  if (seconds < 60) return `${Math.round(seconds)}s ago`
  const mins = Math.round(seconds / 60)
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  return `${hours}h ago`
}
function relativeFromNow(iso?: string | null): string {
  if (!iso) return ''
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return ''
  return relativeFromSeconds(Math.max(0, (Date.now() - parsed.getTime()) / 1000))
}
const localClock = (iso?: string | null) => {
  if (!iso) return ''
  const parsed = new Date(iso)
  return Number.isNaN(parsed.getTime()) ? '' : parsed.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

const SOURCE_STYLE: Record<string, string> = {
  fact: 'border-sky-500/25 bg-sky-500/10 text-sky-300',
  booth: 'border-fuchsia-500/25 bg-fuchsia-500/10 text-fuchsia-300',
  combined: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300',
}
const SOURCE_LABEL: Record<string, string> = {
  fact: 'ESPN / market',
  booth: 'Broadcast',
  combined: 'Facts + broadcast',
}

const STATUS_STYLE: Record<BoothStatus, string> = {
  current: 'bg-emerald-500/15 text-emerald-300',
  quiet: 'bg-sky-500/15 text-sky-300',
  stale: 'bg-amber-500/15 text-amber-300',
  complete: 'bg-zinc-700/40 text-zinc-300',
  unavailable: 'bg-zinc-700/40 text-zinc-500',
}

const shortRound = (round?: string) => ({
  'Round of 32': 'R32',
  'Round of 16': 'R16',
  Quarterfinals: 'QF',
  Semifinals: 'SF',
  Final: 'F',
}[round || ''] || round || 'Match')

function RouteToMatch({ team, history }: { team: Ctx['teams']['home']; history?: TeamHistory }) {
  if (!history || history.matches.length === 0) return null
  return (
    <div className="min-w-0">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-1.5">
        <span className="text-xs font-semibold text-zinc-200">{team.name}</span>
        <span className="text-[10px] text-zinc-500">
          {history.rest_days == null ? 'rest unavailable' : `${history.rest_days}d rest`}
          {history.extra_time_minutes > 0 ? ` · ${history.extra_time_minutes} ET min` : ''}
        </span>
      </div>
      <ol className="space-y-1.5">
        {history.matches.map(match => (
          <li key={match.game_id} className="flex items-center justify-between gap-2 text-[11px]">
            <span className="min-w-0 truncate text-zinc-500">
              <span className="mr-1.5 text-zinc-600">{shortRound(match.round)}</span>
              {match.opponent.name || match.opponent.abbr}
              {match.extra_time ? <span className="ml-1 text-amber-400/80">{match.penalties ? 'pens' : 'AET'}</span> : null}
            </span>
            <span className={`shrink-0 font-mono tabular-nums ${match.result === 'W' ? 'text-emerald-400' : 'text-red-400'}`}>
              {match.result} {match.score_for ?? '–'}–{match.score_against ?? '–'}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}

// The 15-second casual-fan catch-up. right_now[0] is the primary source; when the
// synthesis has nothing yet, the top featured episode stands in (same visual slot,
// clearly not a claim of synthesis).
function CatchUp({ line, fallbackEpisode }: { line?: CatchUpLine; fallbackEpisode?: BoothEpisode }) {
  if (line) {
    return (
      <li className="px-4 py-3">
        <div className="min-w-0">
          {line.source && (
            <span className={`mb-1 inline-flex rounded border px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide ${SOURCE_STYLE[line.source] || SOURCE_STYLE.fact}`}>
              {SOURCE_LABEL[line.source] || line.source}
            </span>
          )}
          <p className="text-sm font-semibold leading-snug text-zinc-100">{line.headline}</p>
          {line.evidence_items && line.evidence_items.length > 0 && (
            <p className="mt-0.5 text-xs leading-snug text-zinc-500">
              {line.evidence_items.map((e, i) => (
                <span key={i}>
                  {i > 0 ? ' · ' : ''}
                  {e.scope === 'historical_reference' && <span className="text-zinc-600">(past) </span>}
                  {e.text}
                </span>
              ))}
            </p>
          )}
          {line.prop && <div><PropChip prop={line.prop} /></div>}
        </div>
      </li>
    )
  }
  if (fallbackEpisode) {
    return (
      <li className="px-4 py-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold leading-snug text-zinc-100">
            {fallbackEpisode.headline || fallbackEpisode.quote}
          </p>
          <p className="mt-0.5 text-xs leading-snug text-zinc-500">Booth: “{fallbackEpisode.quote}”</p>
        </div>
      </li>
    )
  }
  return null
}

export default function WCContext({ gameId }: { gameId: string }) {
  const [ctx, setCtx] = useState<Ctx | null | undefined>(undefined)

  useEffect(() => {
    let alive = true
    let hasValue = false
    let active: AbortController | null = null
    setCtx(undefined)
    const load = () => {
      active?.abort()
      const request = new AbortController()
      active = request
      fetch(`/api/wc/${gameId}/context`, { signal: request.signal })
        .then(r => (r.ok ? r.json() : null))
        .then(d => {
          if (!alive || request.signal.aborted) return
          if (d) {
            hasValue = true
            setCtx(d)
          } else if (!hasValue) {
            setCtx(null)
          }
        })
        .catch(() => { if (alive && !hasValue && !request.signal.aborted) setCtx(null) })
    }
    load()
    const timer = setInterval(load, POLL_MS)
    return () => {
      alive = false
      active?.abort()
      clearInterval(timer)
    }
  }, [gameId])

  if (ctx === undefined) return (
    <div className="border-l-2 border-emerald-600/40 pl-3 space-y-2 animate-pulse">
      <div className="h-3 bg-zinc-800 rounded w-1/2" />
      <div className="h-3 bg-zinc-800 rounded w-3/4" />
    </div>
  )
  if (!ctx) return null

  const catchUpLine = ctx.right_now?.[0]
  const fallbackEpisode = !catchUpLine ? ctx.featured_episodes?.[0] : undefined
  const status = ctx.coverage?.booth_status
  const phaseLabel = ctx.coverage?.phases.find(p => p.key === ctx.current_phase)?.label

  return (
    <section className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-hidden">
      {/* header */}
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-2.5">
        <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-emerald-400">Game Context</span>
        <span className="flex items-center gap-1.5 text-right text-[10px] text-zinc-500">
          {status && (
            <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ${STATUS_STYLE[status]}`}>
              {status}
            </span>
          )}
          {phaseLabel || 'Live'}
          {ctx.coverage?.capture_latest_at ? ` · booth ${relativeFromNow(ctx.coverage.capture_latest_at)}` : ''}
        </span>
      </div>

      {/* Right now: the 15-second catch-up, one line, not a list of cards */}
      {(catchUpLine || fallbackEpisode) && (
        <ul className="divide-y divide-zinc-800/70">
          <CatchUp line={catchUpLine} fallbackEpisode={fallbackEpisode} />
        </ul>
      )}

      {/* form + most likely to score */}
      <div className="grid gap-px border-t border-zinc-800 bg-zinc-800 sm:grid-cols-2">
        {[ctx.teams.away, ctx.teams.home].map(t => {
          const scorer = ctx.top_scorers.find(s => s.team === t.abbr)
          return (
            <div key={t.abbr} className="bg-zinc-900 px-4 py-3">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-zinc-100">{t.name}</span>
                <FormChips form={t.form} />
              </div>
              {scorer && (
                <div className="mt-2 flex items-baseline justify-between">
                  <span className="text-xs text-zinc-500">Most likely to score</span>
                  <span className="text-sm text-zinc-200">
                    <span className="font-semibold">{scorer.player}</span>
                    <span className="ml-1.5 font-mono tabular-nums text-emerald-400">{fmtOdds(scorer.odds)}</span>
                  </span>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {ctx.match_stats && ctx.match_stats.length > 0 && (
        <div className="border-t border-zinc-800 px-4 py-3">
          <div className="mb-2 grid grid-cols-[1fr_auto_1fr] items-center text-[10px] font-medium uppercase tracking-wider text-zinc-600">
            <span>{ctx.teams.away.abbr}</span>
            <span>Match facts</span>
            <span className="text-right">{ctx.teams.home.abbr}</span>
          </div>
          <div className="space-y-1.5">
            {ctx.match_stats.map(stat => (
              <div key={stat.key} className="grid grid-cols-[1fr_auto_1fr] items-center text-xs">
                <span className="font-mono tabular-nums text-zinc-300">{stat.away ?? '–'}{stat.away != null ? stat.unit : ''}</span>
                <span className="px-4 text-center text-zinc-600">{stat.label}</span>
                <span className="text-right font-mono tabular-nums text-zinc-300">{stat.home ?? '–'}{stat.home != null ? stat.unit : ''}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Path here: collapsed by default — route history is context, not today's catch-up */}
      {ctx.history?.teams && (
        <details className="border-t border-zinc-800 px-4 py-3">
          <summary className="cursor-pointer text-[10px] font-medium uppercase tracking-[0.16em] text-zinc-500">
            Path here
          </summary>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <RouteToMatch team={ctx.teams.away} history={ctx.history.teams[ctx.teams.away.abbr]} />
            <RouteToMatch team={ctx.teams.home} history={ctx.history.teams[ctx.teams.home.abbr]} />
          </div>
        </details>
      )}

      {ctx.social_sentiment?.status === 'unavailable' && (
        <p className="border-t border-zinc-800 px-4 py-2 text-[10px] text-zinc-600">
          Social sentiment omitted — no validated, timestamped source is connected.
        </p>
      )}
    </section>
  )
}
