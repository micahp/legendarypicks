import axios from 'axios'

// Curated plays board (`plays-board-v1`). Read-only consumer of GET /api/plays/today, an
// atomically-published, API-owned snapshot. The request path makes NO Kalshi/network call and
// never places an order. This is NOT the live-signal surface — LiveDiscounts.tsx keeps its own
// endpoint (/api/live/discounts), 45s poll, and receipts. /plays composes the two independently.
// Contract: docs/API-plays-board-v1.md (in the plays-api worktree).

function normalizeBaseUrl(raw?: string): string {
  const fallback = '/api'
  if (!raw || raw.trim() === '') return fallback
  const base = raw.trim()
  if (base.startsWith('/')) return base
  if (!/^https?:\/\//i.test(base)) return `http://${base}`
  return base
}
const API_BASE_URL = normalizeBaseUrl(process.env.NEXT_PUBLIC_SPORTS_API_URL)

export type BoardStatus = 'current' | 'stale' | 'archived' | 'unavailable'
export type QuoteStatus = 'current' | 'stale' | 'unavailable'
export type EventStatus = 'open_window' | 'expired'

export interface PlaysBoardScope {
  from: string
  through: string
  label: string
}

export interface PlaysBoardFreshnessPolicy {
  quote_stale_after_seconds: number
  board_stale_after_seconds: number
}

export interface PlaysCategoryStatus {
  category: string
  status: string
  note: string
}

export interface CuratedPlay {
  category: string
  ticker: string
  title: string
  side: 'YES' | 'NO'
  current_price: number | null
  current_bid: number | null
  current_ask: number | null
  current_bid_depth: number | null
  current_ask_depth: number | null
  price_as_of: string | null
  // Optional (v1 additive): publisher market state is more authoritative than the estimated
  // resolves_at — an actively-trading market stays open_window even past its rough time. The API
  // folds these into event_status; they are also surfaced for display.
  market_status?: string
  market_result?: string
  quote_source?: string
  entry_price: number
  stop_price: number
  target_price: number
  r_target: number
  thesis: string
  entry_condition: string
  invalidation: string
  exit_rule: string
  confidence: string
  resolves_at: string
  resolves_at_note: string
  quote_status: QuoteStatus
  quote_age_seconds: number | null
  event_status: EventStatus
}

export interface PlaysBoardAvailable {
  schema_version: 'plays-board-v1'
  surface: 'curated_plays'
  mode: 'paper_research_only'
  server_time: string
  generated_at: string
  as_of: string
  published_at: string
  timezone: string
  board_status: Exclude<BoardStatus, 'unavailable'>
  status_reason: string
  board_age_seconds: number
  freshness_policy: PlaysBoardFreshnessPolicy
  scope: PlaysBoardScope
  risk_definition: string
  limitations: string[]
  category_status: PlaysCategoryStatus[]
  plays: CuratedPlay[]
  quote_status_counts: Record<QuoteStatus, number>
  event_status_counts: Record<EventStatus, number>
  // Optional (v1 additive): a quote-only shared-feed refresh updates generated_at + price_as_of but
  // deliberately preserves the selection-analysis as_of, so fresh books can't make old analysis look current.
  quote_refresh?: {
    source: 'kalshi_shared_feed'
    refreshed_at: string
    refreshed: number
    unavailable: number
  }
}

export interface PlaysBoardUnavailable {
  schema_version: 'plays-board-v1'
  surface: 'curated_plays'
  mode: 'paper_research_only'
  server_time: string
  board_status: 'unavailable'
  status_reason: string
  error_code:
    | 'snapshot_missing'
    | 'snapshot_invalid'
    | 'snapshot_unreadable'
    | 'snapshot_too_large'
  category_status: []
  plays: []
}

export type PlaysBoardResponse = PlaysBoardAvailable | PlaysBoardUnavailable

export function isBoardAvailable(b: PlaysBoardResponse): b is PlaysBoardAvailable {
  return b.board_status !== 'unavailable'
}

// The endpoint returns 503 WITH a structured `unavailable` body — that is not a thrown error, it is
// a first-class state we render. Only true network/transport failures reject.
function useFixtureSource(force?: boolean): boolean {
  if (force != null) return force
  // Explicit test-build flag — allowed in any environment (opt-in at build time).
  if (process.env.NEXT_PUBLIC_PLAYS_FIXTURE === '1') return true
  // The ?fixture=1 URL switch is a dev convenience ONLY. A public production query param must never
  // be able to swap the live API for a static fixture, so it is gated out of production builds.
  if (
    process.env.NODE_ENV !== 'production' &&
    typeof window !== 'undefined' &&
    new URLSearchParams(window.location.search).get('fixture') === '1'
  ) {
    return true
  }
  return false
}

export async function fetchPlaysBoard(opts?: { fixture?: boolean; signal?: AbortSignal }): Promise<PlaysBoardResponse> {
  const url = useFixtureSource(opts?.fixture) ? '/plays-fixture.json' : `${API_BASE_URL}/plays/today`
  const res = await axios.get<PlaysBoardResponse>(url, {
    signal: opts?.signal,
    // Cache-Control: no-store is set by the API; belt-and-suspenders on the client too.
    headers: { 'Cache-Control': 'no-store' },
    validateStatus: (s) => s === 200 || s === 503,
  })
  return res.data
}
