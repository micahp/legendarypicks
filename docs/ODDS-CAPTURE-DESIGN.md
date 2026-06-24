# M6 — Odds-Capture Design

**Author:** orchestrator (inline — reasonix was idle/stuck on delegation)
**Date:** 2026-06-24
**Status:** DESIGN — read-only doc, no code changed. Implementation is a separate task.

## 1. Problem

The system scrapes Bovada player props and settles them against ESPN results, but
**throws away the odds**. `bovada_scraper.py` extracts `price.american` and
`price.handicap` (lines 122, 155) then **omits `odds` from the ingest batch**
(lines 238-245). The `props` table has no odds column at all:

```sql
CREATE TABLE props(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  game_id INTEGER REFERENCES prop_games(id),
  player_id INTEGER REFERENCES players(id),
  market TEXT NOT NULL, line REAL NOT NULL, side TEXT NOT NULL,
  source TEXT, captured_at TEXT NOT NULL)
```

Without persisted odds we cannot compute EV, CLV (closing line value), or
calibration (predicted vs realized hit-rate by EV bucket). Those are the entire
point of M7 (Kalshi crossover / win-prob / EV-CLV calibration). M6 is the
data-collection foundation M7 depends on.

## 2. Verified facts (curl-tested 2026-06-24, ~14:00 UTC)

Bovada's internal coupon API is open — no auth, no Cloudflare wall:

```
GET https://www.bovada.lv/services/sports/event/coupon/events/A/description/{sport}/{league}
```

Live MLB call returned HTTP 200, 1.6 MB, 14 events. Player-prop markets live under
`displayGroups[*]` where `description` contains "prop". Each market has `outcomes[]`;
each outcome has `price.american` (American odds, e.g. `-110`) and `price.handicap`
(the line, e.g. `4.5`). Verified samples:

| market_desc | side | line | american |
|---|---|---|---|
| Total Strikeouts - Eury Perez (MIA) | Over | 4.5 | -110 |
| Total Strikeouts - Eury Perez (MIA) | Under | 4.5 | -120 |
| Total Strikeouts - Jacob deGrom (TEX) | Over | 6.5 | +105 |
| Total Strikeouts - Jacob deGrom (TEX) | Under | 6.5 | -135 |

Two-sided markets (Over/Under) give us both sides → we can de-vig and derive a fair
probability. Yes/no props (home_run_any, etc.) are also exposed but currently
skipped by `parse_player_props` (line 134) — they carry odds but no handicap.

## 3. Schema — recommended

Two additions, additive (no migration of existing rows required):

**3a. Latest odds on `props` (denormalized, for "current line" queries):**
```sql
ALTER TABLE props ADD COLUMN odds INTEGER;          -- American odds, captured side
ALTER TABLE props ADD COLUMN odds_captured_at TEXT;
```
Populated at ingest time. Cheap, single source of truth for "what was the line
when we booked it."

**3b. Time-series snapshots (for CLV / line movement):**
```sql
CREATE TABLE prop_odds_snapshots(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  prop_id INTEGER NOT NULL REFERENCES props(id),
  odds INTEGER NOT NULL,            -- American, the captured side
  odds_opp INTEGER,                 -- American, opposite side (for de-vig)
  captured_at TEXT NOT NULL,
  is_close INTEGER DEFAULT 0        -- 1 = final snapshot at/near game start
);
CREATE INDEX idx_odds_snap_prop ON prop_odds_snapshots(prop_id, captured_at);
```

Why time-series: CLV needs the *opening* odds vs the *closing* odds, not a single
value. A snapshot table lets us replay the curve. `odds_opp` (the opposite side)
is captured in the same Bovada market response, so de-vig is exact rather than
assumed.

## 4. Scraper changes

**4a. Persist odds at ingest** — add `odds` to the batch dict in `ingest_batch`
(lines 238-245) and accept it in the `/api/props/ingest` handler + `props` INSERT.

**4b. Add a `--capture` mode** — a snapshot-only pass that, for props already in
the DB for today's games, fetches Bovada and writes `prop_odds_snapshots` rows
without creating new `props` rows. This is the CLV cadence runner (§5). Matching is
by (player_id, market, line, side) — see §6.

**4c. Capture both sides** — currently we only keep the outcome whose
`description` is "over"/"under". To get `odds_opp`, in `parse_player_props` emit
both sides of each market paired (we already iterate both outcomes). Small
restructure of the return shape.

## 5. Capture cadence

- **Pre-game:** snapshot every ~30 min from ~6 h before first pitch until game
  start (the line moves most in the final hour). Implemented as a cron entry
  calling `bovada_scraper.py <league> --capture`.
- **Close:** one final snapshot flagged `is_close=1` at game start (the
  scheduler already knows `start_time` per event).
- **At ingest** (the existing `--ingest` flow): write the first snapshot row so
  even a one-pass capture has an opening + a current.

~30 min cadence × ~6 h × ~14 games × ~20 props/game ≈ 5k snapshot rows/day —
trivial for SQLite.

## 6. Identity / matching (critical)

Bovada gives us `player_name` (e.g. "Jacob deGrom") + team abbrev + market + line +
side. Our `props` table keys on `player_id`. So `--capture` must resolve the
scraped prop to an existing `props.id` by **(player_id, market, line, side)**,
where `player_id` comes from the existing name→id resolution used at ingest
time — the **same** resolver, by ID never by name string (AGENTS §7).

Edge cases to handle in implementation:
- Line moved (Bovada now shows 5.5, our prop is 4.5) → no exact match → log and
  skip (do NOT silently rebind to the new line; that corrupts settlement).
- Player not yet in `players` → skip (capture-only, never creates players).
- Multiple props same player/market/line (different sides) → match on side too.

## 7. EV / CLV / calibration compute (M7 foundation, designed here not built)

Given persisted odds + settlement results, the math:

- **Decimal odds:** `d = american_to_decimal(a)` where `+110 → 2.10`, `-110 → 1.909`.
- **Implied prob (one side):** `p_implied = 1/d`.
- **Fair prob (de-vigged):** for a two-sided Over/Under market,
  `p_over_fair = p_over_implied / (p_over_implied + p_under_implied)`. This removes
  the vig and is the book's estimate of the true probability.
- **EV of a bet at odds `d`:** `EV = p_fair × (d − 1) − (1 − p_fair) × 1`.
  (Risk 1 unit; win `d−1`, lose `1`.)
- **CLV:** `CLV = p_close_implied − p_open_implied` for the side we bet. Positive
  CLV = we got a better-than-closing number = edge.
- **Calibration:** bucket settled props by EV decile, compare mean predicted
  hit-rate (from `p_fair` at bet time) vs realized hit-rate (`hit`). A well-
  calibrated model sits on the diagonal; systematic over/under-confidence is
  the signal to fix selection (cf. [[project_prediction_market_trading]] v3
  reckoning: edge is selection, not timing).

## 8. Risks / open questions

- **Bovada TOS:** scraping an unauthenticated internal endpoint. Low-volume
  (~3 req/league/day at 30-min cadence = ~6/day), real browser UA — but this is
  external data we don't control. Mitigate: keep cadence modest, cache per
  league, fail soft. If they wall it, ESPN Bet / DraftKings are fallbacks (more
  friction). Flagged for CEO decision before a live cron goes on.
- **Yes/no props** (home_run_any etc.) have odds but no handicap and are currently
  skipped (line 134). Defer — they need a separate matching key (no `line`).
- **Identity drift:** if Bovada changes team abbrevs or player name formatting,
  resolution silently drops props. The capture pass should log match-rate per run;
  a sudden drop is the canary.

## 9. Implementation order (when CEO greenlights)

1. `ALTER TABLE props` + create `prop_odds_snapshots` (additive; backup first).
2. Scraper 4a (persist odds at ingest) + ingest handler.
3. Scraper 4c (capture both sides) + 4b (`--capture` mode).
4. Cron entry for the §5 cadence.
5. M7 consumes the snapshots for EV/CLV/calibration.

Each step is independently testable against the live Bovada endpoint verified in §2.
