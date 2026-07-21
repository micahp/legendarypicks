import { useEffect, useState } from 'react'
import ListenLive from '../ListenLive'

type Prop = {
  player: string
  market: string
  line: string
  lean: 'back' | 'fade' | 'watch'
  quote_age_seconds?: number
}
type MatchPhase = 'pregame' | 'first_half' | 'halftime' | 'second_half' | 'extra_time' | 'final' | 'live'
type TimeScope = 'current_match' | 'historical_reference' | 'mixed'
type BoothStatus = 'current' | 'quiet' | 'stale' | 'complete' | 'unavailable'

type Receipt = {
  id?: string
  quote: string
  captured_at?: string
  time_scope?: TimeScope
  subject_raw?: string
}

type Episode = {
  id: string
  headline?: string
  analysis?: string
  quote: string
  subject: string
  tag: string
  phase: MatchPhase
  time_scope: TimeScope
  priority: 'availability' | 'storyline'
  latest_capture_at?: string
  receipt_count: number
  receipts: Receipt[] // newest first, up to 3 in the list payload
  match_time?: { display: string }
  prop?: Prop
}

type PhaseInfo = { key: MatchPhase; label: string; episode_count: number }

// CoD's backend (cod_context.py) has not moved to the wc-context-v2 episode/phase
// shape — it still returns a flat `insights` array. Both are supported here so
// this shared component doesn't regress the CoD detail page.
type LegacyInsight = {
  id?: string
  tag: string
  subject: string
  quote: string
  strength: number
  ts?: string
  headline?: string
  analysis?: string
  prop?: Prop
}

type BoothContext = {
  episodes?: Episode[]
  insights?: LegacyInsight[]
  coverage?: {
    current_phase: MatchPhase
    selected_phase: MatchPhase
    booth_status: BoothStatus
    phases: PhaseInfo[]
  }
}

type EpisodeDetail = {
  episode_id: string
  receipt_count: number
  receipt_order: 'oldest_to_newest'
  receipts: Receipt[]
  match_time?: { display: string }
}

const POLL_MS = 30_000
const DEFAULT_LIMIT = 8
const PHASE_BROWSE_LIMIT = 20

const LEAN_STYLE: Record<string, { cls: string; mark: string }> = {
  back: { cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30', mark: '▲' },
  fade: { cls: 'bg-red-500/15 text-red-300 border-red-500/30', mark: '▼' },
  watch: { cls: 'bg-zinc-700/40 text-zinc-300 border-zinc-600/50', mark: '•' },
}

const TAG_STYLE: Record<string, string> = {
  'Key man': 'bg-amber-500/15 text-amber-300 border-amber-500/25',
  Momentum: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25',
  Tactical: 'bg-sky-500/15 text-sky-300 border-sky-500/25',
  Mentality: 'bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/25',
  Fatigue: 'bg-orange-500/15 text-orange-300 border-orange-500/25',
  Injury: 'bg-red-500/15 text-red-300 border-red-500/25',
}

const STATUS_STYLE: Record<BoothStatus, string> = {
  current: 'bg-emerald-500/15 text-emerald-300',
  quiet: 'bg-sky-500/15 text-sky-300',
  stale: 'bg-amber-500/15 text-amber-300',
  complete: 'bg-zinc-700/40 text-zinc-300',
  unavailable: 'bg-zinc-700/40 text-zinc-500',
}

// Relative time is the primary display; raw ISO substrings are never rendered as
// if they were a match minute (see docs/API-wc-context-v2.md).
function relativeFromSeconds(seconds: number): string {
  if (seconds < 10) return 'just now'
  if (seconds < 60) return `${Math.round(seconds)}s ago`
  const mins = Math.round(seconds / 60)
  if (mins < 60) return `${mins}m ago`
  return `${Math.round(mins / 60)}h ago`
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

function PropChip({ prop }: { prop: Prop }) {
  const s = LEAN_STYLE[prop.lean] || LEAN_STYLE.watch
  return (
    <span className={`mt-1 inline-flex max-w-full flex-wrap items-center gap-x-1.5 rounded-md border px-2 py-0.5 text-xs font-medium ${s.cls}`}>
      <span className="text-[10px]">{s.mark}</span>
      <span className="text-[9px] uppercase tracking-wide opacity-70">{prop.lean}</span>
      <span className="font-semibold">{prop.player}</span>
      <span className="opacity-80">{prop.market}</span>
      <span className="font-mono tabular-nums">{prop.line}</span>
      {prop.quote_age_seconds != null && (
        <span className="opacity-60">· priced {relativeFromSeconds(prop.quote_age_seconds)}</span>
      )}
    </span>
  )
}

// Chronology: an ESPN-linked match minute when we have one, otherwise phase +
// relative capture recency. Never a card-level from-to range.
function Chronology({ episode, phaseLabel }: { episode: Episode; phaseLabel?: string }) {
  if (episode.match_time?.display) {
    return <span className="font-mono text-[10px] tabular-nums text-zinc-500">{episode.match_time.display}</span>
  }
  const rel = relativeFromNow(episode.latest_capture_at)
  return (
    <span className="text-[10px] text-zinc-600">
      {phaseLabel}{phaseLabel && rel ? ' · ' : ''}{rel}
    </span>
  )
}

function ReceiptRow({ receipt, showCapturedLabel, showScopeBadge = true }: {
  receipt: Receipt
  showCapturedLabel?: boolean
  showScopeBadge?: boolean
}) {
  return (
    <p className="text-xs leading-snug text-zinc-600">
      {showScopeBadge && receipt.time_scope === 'historical_reference' && (
        <span className="mr-1 rounded bg-zinc-800 px-1 py-0.5 text-[9px] uppercase tracking-wide text-zinc-500">past</span>
      )}
      {showCapturedLabel && receipt.captured_at && (
        <span className="mr-1 font-mono tabular-nums text-zinc-500">
          {localClock(receipt.captured_at)}:
        </span>
      )}
      “{receipt.quote}”
    </p>
  )
}

function EpisodeCard({
  episode, phaseLabel, expanded, detail, onToggle,
}: {
  episode: Episode
  phaseLabel?: string
  expanded: boolean
  detail?: EpisodeDetail | 'loading' | 'error'
  onToggle: () => void
}) {
  const latestReceipt = episode.receipts[0]
  return (
    <li className="px-3 py-3">
      <div className="min-w-0">
        <div className="mb-1 flex flex-wrap items-center gap-1.5">
          {/* One category badge, not two: the tag (more specific — Injury, Fatigue,
              etc.) carries the availability warning styling instead of a separate pill. */}
          <span
            className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium ${
              episode.priority === 'availability'
                ? 'border-amber-500/30 bg-amber-500/10 text-amber-300'
                : TAG_STYLE[episode.tag] || 'bg-zinc-800 text-zinc-400 border-zinc-700'
            }`}
          >
            {episode.tag}
          </span>
          {episode.subject && <span className="text-[10px] font-medium text-zinc-400">{episode.subject}</span>}
          {episode.time_scope === 'historical_reference' && (
            <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-zinc-500">past</span>
          )}
          <Chronology episode={episode} phaseLabel={phaseLabel} />
        </div>
        <p className="text-sm font-semibold leading-snug text-zinc-100">
          {episode.headline || `${episode.subject || episode.tag} is worth watching`}
        </p>
        {episode.analysis && <p className="mt-0.5 text-xs leading-snug text-zinc-400">{episode.analysis}</p>}
        {/* The episode-level "past" badge above already covers this preview receipt. */}
        {latestReceipt && <div className="mt-1"><ReceiptRow receipt={latestReceipt} showScopeBadge={false} /></div>}
        {episode.prop && <div><PropChip prop={episode.prop} /></div>}

        {episode.receipt_count > 1 && (
          <button
            type="button"
            onClick={onToggle}
            className="mt-1.5 text-[11px] font-medium text-emerald-400/80 hover:text-emerald-300"
          >
            {expanded ? 'Hide receipts' : `Show ${episode.receipt_count} receipts`}
          </button>
        )}

        {expanded && (
          <div className="mt-2 space-y-1.5 border-t border-zinc-800/70 pt-2">
            {detail === 'loading' && <p className="text-[11px] text-zinc-600">Loading receipts…</p>}
            {detail === 'error' && <p className="text-[11px] text-red-400/70">Couldn’t load receipts.</p>}
            {detail && detail !== 'loading' && detail !== 'error' && detail.receipts.map((r, i) => (
              <ReceiptRow key={r.id || i} receipt={r} showCapturedLabel />
            ))}
          </div>
        )}
      </div>
    </li>
  )
}

// Unmodified legacy card — CoD's booth reads are not phase/episode-aware.
const rawUtcClock = (ts?: string) => (ts && ts.length >= 16 ? ts.slice(11, 16) : '')
function LegacyInsightCard({ it }: { it: LegacyInsight }) {
  return (
    <li className="px-3 py-3">
      <div className="flex gap-2.5">
        <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-1.5">
            <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium ${TAG_STYLE[it.tag] || 'bg-zinc-800 text-zinc-400 border-zinc-700'}`}>
              {it.tag}
            </span>
            {it.subject && <span className="text-[10px] font-medium text-zinc-400">{it.subject}</span>}
            {rawUtcClock(it.ts) && <span className="font-mono text-[10px] tabular-nums text-zinc-600">{rawUtcClock(it.ts)}</span>}
          </div>
          <p className="text-sm font-semibold leading-snug text-zinc-100">
            {it.headline || `${it.subject || it.tag} is worth watching`}
          </p>
          {it.analysis && <p className="mt-0.5 text-xs leading-snug text-zinc-400">{it.analysis}</p>}
          <p className="mt-1 text-xs leading-snug text-zinc-600">
            <span className="font-medium uppercase tracking-wide text-zinc-500">Booth: </span>
            “{it.quote}”
          </p>
          {it.prop && <div><PropChip prop={it.prop} /></div>}
        </div>
      </div>
    </li>
  )
}

export default function BoothFeed({ gameId, contextLeague = 'wc', showListenLive = true }: {
  gameId: string
  contextLeague?: 'wc' | 'cod'
  showListenLive?: boolean
}) {
  const [ctx, setCtx] = useState<BoothContext | null | undefined>(undefined)
  const [selectedPhase, setSelectedPhase] = useState<MatchPhase | null>(null) // null = following live
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [detailCache, setDetailCache] = useState<Record<string, EpisodeDetail | 'loading' | 'error'>>({})

  // Reset everything when the game itself changes.
  useEffect(() => {
    setCtx(undefined)
    setSelectedPhase(null)
    setExpandedId(null)
    setDetailCache({})
  }, [gameId, contextLeague])

  // Fetch the selected phase. Following live (selectedPhase === null) polls every
  // 30s; browsing a past phase is a static catch-up snapshot and does not poll.
  useEffect(() => {
    let alive = true
    let hasValue = false
    let active: AbortController | null = null
    const load = () => {
      active?.abort()
      const request = new AbortController()
      active = request
      // CoD has no phase concept — preserve its original limit=40, no-phase request.
      const limit = contextLeague === 'cod' ? 40 : selectedPhase ? PHASE_BROWSE_LIMIT : DEFAULT_LIMIT
      const phaseParam = contextLeague === 'wc' && selectedPhase ? `&phase=${selectedPhase}` : ''
      return fetch(`/api/${contextLeague}/${gameId}/context?limit=${limit}${phaseParam}`, { signal: request.signal })
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
    const timer = selectedPhase === null ? setInterval(load, POLL_MS) : null
    return () => {
      alive = false
      active?.abort()
      if (timer) clearInterval(timer)
    }
  }, [gameId, contextLeague, selectedPhase])

  const handlePhaseClick = (phase: MatchPhase) => {
    setExpandedId(null)
    setSelectedPhase(phase === ctx?.coverage?.current_phase ? null : phase)
  }

  const toggleExpand = (episode: Episode) => {
    if (expandedId === episode.id) {
      setExpandedId(null)
      return
    }
    setExpandedId(episode.id)
    if (!detailCache[episode.id]) {
      setDetailCache(prev => ({ ...prev, [episode.id]: 'loading' }))
      fetch(`/api/${contextLeague}/${gameId}/context/episodes/${episode.id}`)
        .then(r => (r.ok ? r.json() : null))
        .then(d => setDetailCache(prev => ({ ...prev, [episode.id]: d ? d : 'error' })))
        .catch(() => setDetailCache(prev => ({ ...prev, [episode.id]: 'error' })))
    }
  }

  const isLegacy = !ctx?.episodes && Array.isArray(ctx?.insights)
  const legacyInsights = ctx?.insights ?? []
  const episodes = ctx?.episodes ?? []
  const phases = ctx?.coverage?.phases ?? []
  const activePhaseKey = selectedPhase ?? ctx?.coverage?.current_phase
  const activePhaseLabel = phases.find(p => p.key === activePhaseKey)?.label
  const status = ctx?.coverage?.booth_status

  return (
    <div className="space-y-4">
      {/* The audio and its enriched reads are one booth surface. */}
      {showListenLive ? <ListenLive /> : null}

      {ctx === undefined ? (
        <div className="space-y-3 animate-pulse">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-3 bg-zinc-800 rounded w-full" />
          ))}
        </div>
      ) : !ctx || (isLegacy && legacyInsights.length === 0) ? (
        <p className="text-sm text-zinc-500 py-8 text-center">
          Nothing from the booth yet — reads appear as the broadcast calls the game.
        </p>
      ) : isLegacy ? (
        <section className="overflow-hidden rounded-lg border border-emerald-500/20 bg-ink-900">
          <div className="flex items-center justify-between gap-3 border-b border-zinc-800 px-3 py-2.5">
            <h3 className="text-[10px] font-medium uppercase tracking-[0.18em] text-emerald-400">Booth intelligence</h3>
            <span className="text-right text-[10px] text-zinc-600">newest first · quote as evidence</span>
          </div>
          <ol className="divide-y divide-zinc-800/70">
            {legacyInsights.map((it, i) => (
              <LegacyInsightCard key={it.id || `${it.ts || 'untimed'}-${i}`} it={it} />
            ))}
          </ol>
        </section>
      ) : (
        <section className="overflow-hidden rounded-lg border border-emerald-500/20 bg-ink-900">
          <div className="border-b border-zinc-800 px-3 py-2.5">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-[10px] font-medium uppercase tracking-[0.18em] text-emerald-400">Booth intelligence</h3>
              <span className="flex items-center gap-1.5 text-right text-[10px] text-zinc-600">
                {status && (
                  <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ${STATUS_STYLE[status]}`}>
                    {status}
                  </span>
                )}
                {selectedPhase === null ? 'following live' : 'catch-up'}
              </span>
            </div>
            {phases.length > 0 && (
              <div className="mt-2.5 flex gap-1.5 overflow-x-auto pb-0.5">
                {phases.map(p => {
                  const active = p.key === activePhaseKey
                  const isLive = p.key === ctx?.coverage?.current_phase
                  return (
                    <button
                      key={p.key}
                      type="button"
                      onClick={() => handlePhaseClick(p.key)}
                      className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors ${
                        active
                          ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                          : 'border-zinc-800 bg-zinc-900/60 text-zinc-500 hover:text-zinc-300'
                      }`}
                    >
                      {isLive && <span className="mr-1 text-emerald-400">●</span>}
                      {p.label}
                      {p.episode_count > 0 && <span className="ml-1 opacity-60">{p.episode_count}</span>}
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          {episodes.length === 0 ? (
            <p className="px-3 py-8 text-center text-sm text-zinc-500">
              Nothing from the booth in {activePhaseLabel?.toLowerCase() || 'this phase'} yet.
            </p>
          ) : (
            <ol className="divide-y divide-zinc-800/70">
              {episodes.map(episode => (
                <EpisodeCard
                  key={episode.id}
                  episode={episode}
                  phaseLabel={activePhaseLabel}
                  expanded={expandedId === episode.id}
                  detail={detailCache[episode.id]}
                  onToggle={() => toggleExpand(episode)}
                />
              ))}
            </ol>
          )}
        </section>
      )}
      <p className="text-[10px] text-zinc-600">
        {isLegacy
          ? 'Commentary receipts, not match facts · newest first · refreshes every 30s.'
          : 'Commentary receipts, not match facts · availability pinned first.'}
      </p>
    </div>
  )
}
