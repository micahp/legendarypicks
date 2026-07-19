# Curated plays board API (`plays-board-v1`)

`GET /api/plays/today` is the read-only contract for LegendaryPicks' curated,
non-live conditional board. It reads one atomically published, API-owned JSON
snapshot. The request path makes no Kalshi or other network call and never
places an order.

This contract does **not** replace or wrap `GET /api/live/discounts`.
`LiveDiscounts.tsx` remains the canonical live-signal UI, including its signal
classes, 45-second polling, and receipt log. `/plays` composes the two requests
as independent sections.

## HTTP behavior

- `200`: a structurally valid snapshot. Inspect `board_status`; it may be
  `current`, `stale`, or `archived`.
- `503`: no safe snapshot can be served. The response still has
  `board_status: "unavailable"`, an `error_code`, and empty `plays` and
  `category_status` arrays.
- Every response uses `Cache-Control: no-store`. The publisher, not browser
  polling, owns curated-board refresh cadence.
- Decimal price units are probabilities/dollars: `0.15` means 15 cents.

The default owned snapshot is `backend/data/plays_board.json`. An operator may
mount another API-owned path with `LP_PLAYS_BOARD_PATH`; it must not point the
serving app at the trading repository. The publisher writes via `fsync` plus
atomic replace so readers never observe a partial JSON file.

## TypeScript-friendly response types

```ts
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
  market_status?: string
  market_result?: string
  quote_source?: string
  feed_book_age_ms?: number
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
```

## Checked example

The values below illustrate one valid response shape; they are not a fallback
board and must never be rendered as current data after their timestamps expire.

```json
{
  "schema_version": "plays-board-v1",
  "surface": "curated_plays",
  "mode": "paper_research_only",
  "server_time": "2026-07-19T12:00:30Z",
  "generated_at": "2026-07-19T12:00:10Z",
  "as_of": "2026-07-19T12:00:00Z",
  "published_at": "2026-07-19T12:00:11Z",
  "timezone": "America/Chicago",
  "board_status": "current",
  "status_reason": "The board is inside its publication freshness window.",
  "board_age_seconds": 30,
  "freshness_policy": {
    "quote_stale_after_seconds": 90,
    "board_stale_after_seconds": 900
  },
  "scope": {
    "from": "2026-07-19T07:00:00-05:00",
    "through": "2026-07-19T15:00:00-05:00",
    "label": "Sunday 2026-07-19"
  },
  "risk_definition": "One risk unit is entry price minus stop price.",
  "limitations": ["Research only; no order is placed."],
  "category_status": [
    {
      "category": "mlb",
      "status": "one_conditional_play",
      "note": "No pregame buy; wait for the stated trigger."
    }
  ],
  "plays": [
    {
      "category": "mlb",
      "ticker": "KXMLBGAME-TEST",
      "title": "Boston to beat Tampa Bay",
      "side": "YES",
      "current_price": 0.54,
      "current_bid": 0.53,
      "current_ask": 0.54,
      "current_bid_depth": 1200.0,
      "current_ask_depth": 2400.0,
      "price_as_of": "2026-07-19T12:00:05Z",
      "entry_price": 0.19,
      "stop_price": 0.0,
      "target_price": 0.57,
      "r_target": 2.0,
      "thesis": "Wait for a reversible discount on the quality side.",
      "entry_condition": "Buy only after the exact live trigger and stabilization.",
      "invalidation": "No entry if the structural game state changes.",
      "exit_rule": "Exit into the comeback repricing.",
      "confidence": "medium_high_if_triggered",
      "resolves_at": "2026-07-19T19:30:00Z",
      "resolves_at_note": "Expected game-resolution window.",
      "quote_status": "current",
      "quote_age_seconds": 25,
      "event_status": "open_window"
    }
  ],
  "quote_status_counts": {"current": 1, "stale": 0, "unavailable": 0},
  "event_status_counts": {"open_window": 1, "expired": 0}
}
```

The page must always display the research/paper-only warning and treat every
play as conditional. A valid HTTP response is not proof that a quote is live;
use `board_status`, `quote_status`, and `event_status` explicitly.

When `market_status` is present, it is more authoritative than the estimated
`resolves_at` timestamp: an actively trading market remains `open_window`,
while a terminal status or non-empty result is `expired`. If publisher market
state is unavailable, the API falls back to `resolves_at`. A quote-only shared
feed refresh updates `generated_at` and `price_as_of` but deliberately preserves
the selection-analysis `as_of`, so fresh books cannot make old analysis look
current. `price_as_of` is when the healthy shared feed was observed; optional
`feed_book_age_ms` separately reports how long the unchanged book has been in
the current WebSocket generation.
