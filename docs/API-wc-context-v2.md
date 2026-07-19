# WC game context API (`wc-context-v2`)

`GET /api/wc/{game_id}/context` is the consumer-facing catch-up and booth-storyline
contract for a World Cup match. It condenses timestamped extractor observations into
phase-aware episodes. It is not a raw transcript endpoint and it is not a competing
live-market signal API.

The canonical live team-signal surface remains `GET /api/live/discounts?league=wc`.
This endpoint never calls Kalshi. A player action may appear only when the canonical
Booth alert engine has passed its evidence and exact-contract gates, the episode is
current-match evidence, its ESPN player identity exactly matches the market record,
and the timestamped executable quote is inside the response freshness policy.
Ordinary Bovada scorer captures do not satisfy that contract. Otherwise the episode
has no `prop` field.

## Query behavior

- `limit` is `1..100` and caps **episodes**, not extractor rows.
- With no `phase`, `episodes` contains the current match phase.
- `phase=pregame|first_half|halftime|second_half|extra_time|final` loads that phase
  for explicit catch-up navigation; phase-specific responses leave `right_now` and
  `featured_episodes` empty because the current catch-up was already supplied by the
  default request.
- `coverage.phases` always reports the available phases and their full episode counts,
  so a client can lazy-load a past phase without downloading the whole broadcast.
- `GET /api/wc/{game_id}/context/episodes/{episode_id}` returns the complete receipt
  stack oldest-to-newest only when a card is expanded. The phase list carries at most
  three newest-first preview receipts, keeping the initial board bounded while leading
  with the latest development.
- The source has a **broadcast capture timestamp**, not a synchronized soccer clock.
  Public receipt fields therefore use `captured_at` and `time_basis: 'broadcast_capture'`.
  They answer "when did our extractor capture this?", not "what minute was the match in?"
- A soccer minute appears only as `match_time`, when the episode links to one
  authoritative ESPN event. Do not derive match minutes by subtracting scheduled kickoff:
  kickoff delay, halftime, broadcast delay, and extractor latency make that dishonest.
- Render a linked `match_time.display` (for example `44'`) when present. Otherwise render
  phase plus recency (for example `Second half · 4m ago`). Viewer-local capture time belongs
  in expanded receipt detail. Never show a card-level capture-time range and never display
  an ISO substring as if it were match time.
- Historical extractor rows cannot honestly be retrofitted with exact match minutes. Future
  capture can support that only by persisting a synchronized ESPN `{period, game_clock,
  captured_at}` snapshot alongside each receipt (including uncertainty/broadcast delay).

## TypeScript-friendly shape

```ts
type MatchPhase =
  | 'pregame' | 'first_half' | 'halftime'
  | 'second_half' | 'extra_time' | 'final' | 'live'

type TimeScope = 'current_match' | 'historical_reference' | 'mixed'
type BoothStatus = 'current' | 'quiet' | 'stale' | 'complete' | 'unavailable'

interface BoothReceipt {
  id?: string
  quote: string
  captured_at: string
  time_basis: 'broadcast_capture'
  time_scope: TimeScope
  subject_raw?: string
}

interface LinkedMatchTime {
  display: string // e.g. "44'"
  source: 'espn_event'
  relation: 'linked_event'
}

interface MarketImplication {
  player: string
  market: string
  line: string
  lean: 'back' | 'fade' | 'watch'
  price_as_of: string
  quote_status: 'current'
  quote_age_seconds: number
  quote_source: string
  contract_ticker: string
  settlement_semantics?: string
  evidence_label?: 'information_leading' | 'discount_confirming'
}

interface BoothEpisode {
  id: string
  topic: string
  tag: string
  tags: string[]
  subject: string
  subject_id?: string | null
  subject_kind: 'player' | 'team' | 'match'
  subject_resolution: string
  team_abbr?: string | null
  entities: { id?: string | null; name: string; kind: 'player' }[]
  phase: MatchPhase
  time_scope: TimeScope
  priority: 'availability' | 'storyline'
  latest_capture_at: string
  capture_time_basis: 'broadcast_capture'
  strength: number
  quote: string
  receipt_count: number
  receipts: BoothReceipt[] // newest first, at most three in the initial card payload
  headline?: string
  analysis?: string
  match_time?: LinkedMatchTime
  match_event?: {
    clock?: string
    kind?: string
    team?: string
    players: string[]
    text?: string
    matched_players: string[]
  }
  prop?: MarketImplication
}

interface CatchUpReceipt {
  ref: string
  kind: 'fact' | 'booth'
  scope: 'current_match' | 'historical_reference' | 'mixed'
  text: string
  captured_at?: string // booth evidence only
  time_basis?: 'broadcast_capture'
  observed_at?: string // non-booth evidence only
}

interface CatchUpLine {
  headline: string
  source: 'fact' | 'booth' | 'combined'
  context_scope: 'right_now'
  evidence_refs: string[]
  evidence_items: CatchUpReceipt[]
  prop?: MarketImplication
}

interface WCContextV2 {
  schema_version: 'wc-context-v2'
  surface: 'game_context'
  game_id: string
  headline: string
  status?: string
  current_phase: MatchPhase
  server_time: string
  generated_at: string
  latest_booth_capture_at?: string | null
  time_semantics: {
    capture_time_basis: 'broadcast_capture'
    capture_timezone: 'UTC'
    phase_basis: 'scheduled_kickoff_and_broadcast_gap'
    match_clock_policy: string
  }
  teams: unknown
  match_stats: unknown[]
  history: unknown
  right_now: CatchUpLine[] // zero or one; fall back to featured episodes if empty
  featured_episodes: BoothEpisode[] // impact-ranked current-phase cards, max five
  episodes: BoothEpisode[] // selected phase, capped by limit
  coverage: {
    current_phase: MatchPhase
    selected_phase: MatchPhase
    capture_started_at?: string | null
    capture_latest_at?: string | null
    capture_time_basis: 'broadcast_capture'
    phase_basis: 'scheduled_kickoff_and_broadcast_gap'
    source_observation_count: number
    relevant_observation_count: number
    episode_count: number
    selected_episode_count: number
    returned_episode_count: number
    truncated: boolean
    booth_status: BoothStatus
    booth_age_seconds?: number | null
    phases: {
      key: MatchPhase
      label: string
      episode_count: number
    }[]
  }
  freshness_policy: {
    booth_stale_after_seconds: number
    market_quote_stale_after_seconds: number
  }
  market_context: {
    canonical_live_signal_endpoint: '/api/live/discounts?league=wc'
    player_action_rule: string
  }
}
```

## UI contract

- `right_now[0]` is the 15-second casual-fan catch-up, not another list section.
- Phase navigation uses `coverage.phases`; current phase is selected initially.
- Availability episodes are pinned before ordinary storylines within a phase.
- Cards show one takeaway and one receipt by default. Additional receipts are disclosed
  on interaction through the episode-detail endpoint and retain their own relative/local
  time and historical labels.
- Card chronology is `match_time` when event-linked; otherwise it is phase + relative
  capture recency. Capture timestamps must never be presented as soccer minutes or as a
  card-level from-to span.
- `historical_reference` is useful context, not a leak. Label it; do not delete it or
  present it as a current event.
- Never manufacture a price/freshness or alert-gate state. No `prop` means no actionable
  player chip; do not turn the episode's contextual Bovada reference into one.
