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
- `phase=pregame|first_half|halftime|second_half|extra_time|penalties|final` loads that phase
  for explicit catch-up navigation; phase-specific responses leave `right_now` and
  `featured_episodes` empty because the current catch-up was already supplied by the
  default request.
- `coverage.phases` always reports the available phases and their full episode counts,
  so a client can lazy-load a past phase without downloading the whole broadcast.
- `GET /api/wc/{game_id}/context/episodes/{episode_id}` returns the complete receipt
  stack oldest-to-newest only when a card is expanded. The phase list carries at most
  three newest-first preview receipts, keeping the initial board bounded while leading
  with the latest development.
- `captured_at` remains provenance only: it says when the extractor emitted the receipt,
  not what minute the match was in. The UI does not use it as card chronology.
- ESPN supplies both `play.wallclock` and soccer `play.clock`. The backend matches a signal
  quote back to its source transcript chunk, then aligns that source time to ESPN's period
  timeline. This preserves long halftimes, extra-time breaks, stoppage time, and the final
  whistle rather than subtracting scheduled kickoff.
- Every episode/receipt with clock coverage carries `match_time`. An unprefixed minute is
  stated in the receipt or tied to a contemporaneous ESPN event; `~83'` is an ESPN
  wallclock-aligned estimate. `HT`, `ET HT`, `Pens`, and `FT` are exact phase boundaries.
- Render `match_time.display` as the chronology. If it is absent, render the phase only—do
  not fall back to a generic local/relative capture timestamp and never show a from-to range.

## TypeScript-friendly shape

```ts
type MatchPhase =
  | 'pregame' | 'first_half' | 'halftime'
  | 'second_half' | 'extra_time' | 'penalties' | 'final' | 'live'

type TimeScope = 'current_match' | 'historical_reference' | 'mixed'
type BoothStatus = 'current' | 'quiet' | 'stale' | 'complete' | 'unavailable'

interface BoothReceipt {
  id?: string
  quote: string
  captured_at: string
  time_basis: 'broadcast_capture'
  time_scope: TimeScope
  subject_raw?: string
  match_time?: MatchTime
}

interface MatchTime {
  display: string // e.g. "44'", "~83'", "90+3'", "HT", or "FT"
  minute?: number
  source: 'espn_event' | 'booth_stated_clock' | 'espn_wallclock_alignment' | 'espn_period_boundary'
  relation: 'contemporaneous_event' | 'stated_in_receipt' | 'broadcast_aligned' | 'between_periods' | 'after_final_whistle'
  precision: 'exact_event' | 'stated' | 'estimated' | 'exact_phase'
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
  match_time?: MatchTime
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
    phase_basis: 'espn_wallclock_alignment' | 'scheduled_kickoff_and_broadcast_gap'
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
    phase_basis: 'espn_wallclock_alignment' | 'scheduled_kickoff_and_broadcast_gap'
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
  on interaction through the episode-detail endpoint and retain their own match minute and
  historical labels.
- Card and expanded-receipt chronology is `match_time.display`. A leading `~` is intentional
  uncertainty disclosure. If `match_time` is absent, show the phase without a timestamp.
- A terminal ESPN status (`completed`, `state: post`, AET, or a completed shootout) maps to
  `current_phase: final` and `booth_status: complete`; clients stop live polling and label the
  default view as match complete.
- `historical_reference` is useful context, not a leak. Label it; do not delete it or
  present it as a current event.
- Never manufacture a price/freshness or alert-gate state. No `prop` means no actionable
  player chip; do not turn the episode's contextual Bovada reference into one.
