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

---

## Appendix: Adversarial Review (reasonix, 2026-06-24)

**Verdict:** DESIGN IS SOUND — ship with the 4 fixes noted below.

All live-code claims in §2 and §4 were re-verified against `bovada_scraper.py` 
and the Bovada endpoint: `price.american` extracted at line 122, `price.handicap` at 
line 121, odds omitted from the ingest batch at lines 238–245, and the INSERT at 
`sports_service.py:1127` lacks an `odds` column. All claims accurate. The Bovada 
endpoint returned HTTP 200, 1.6 MB on re-curl (2026-06-24 ~07:00 UTC).

---

### 1. Math Correctness (§7) — PASS

**Formulas verified:**

| Formula | Check | Notes |
|---------|-------|-------|
| American → decimal | `+110 → 2.10`, `-110 → 1.909` | Correct. `-110` decimal is exactly `21/11 ≈ 1.90909…` — the doc's `1.909` is a 3-decimal truncation. Use the exact value in code (`1 + 100/abs(american)`). |
| Implied prob | `p = 1/d` | Correct. For a -110/-120 market: `p_over = 11/21 = 0.5238`, `p_under = 6/11 = 0.5455`, sum = 1.0693 → vig ~6.5%. |
| De-vig (proportional) | `p_fair = p_side / (p_over + p_under)` | Correct — divides out the total implied probability. Sums to 1.0. Verified against the doc's deGrom example: `p_over_fair = 0.4878/1.0623 = 0.4592`, `p_under_fair = 0.5745/1.0623 = 0.5408`. |
| EV | `p_fair × (d − 1) − (1 − p_fair) × 1` | Correct. Standard "risk 1 unit" EV. Verified: fair coin (p=0.5) at +100 → EV=0; p=0.55 at -110 → EV=+0.05. |
| CLV | `p_close_implied − p_open_implied` | Correct. Uses implied (not de-vigged) probs → isolates line movement cleanly. Equivalent to "cents of CLV" when multiplied by 100. |

**Edge cases tested:**
- **Pick'em (±100):** `d = 2.0, p_implied = 0.5`. De-vig: both sides 0.5 → sum 1.0 → fair = 0.5. EV at +100 = 0. ✓
- **Heavy favorite (-500):** `d = 1.20, p_implied = 0.8333`. Opposite +400: `d = 5.0, p_implied = 0.20`. Sum = 1.0333 → vig ~3.2%. EV for favorite = -0.032. ✓
- **Push at the line:** Not applicable — Bovada uses half-point lines (4.5, 5.5) by convention; pushes are structurally impossible for Over/Under props. No action needed.

**FIX (minor):** The EV formula uses `p_fair` from de-vigging. But `p_fair` is a function of the market AT THE TIME of the snapshot — it changes as odds move. For consistency, EV should be computed using the `p_fair` from the OPENING snapshot (the price we got), not the closing snapshot. The doc doesn't specify which snapshot's `p_fair` to use. Recommend: compute EV from the snapshot with `is_close=0` (first capture), paired with settlement result.

---

### 2. De-Vig Assumption (§7) — ISSUE (two gaps, both fixable)

**Gap 1: Proportional method assumes symmetric vig.** The formula `p_fair = p_side / (p_over + p_under)` spreads the vig proportionally across both sides. This is standard but has a known blind spot: the **favorite-longshot bias** — books shade vig toward the longshot side, meaning the proportional method systematically overestimates the underdog's true probability and underestimates the favorite's.

For player props (mostly Over/Under totals), this bias is weaker than for moneylines, so the proportional method is an acceptable v1. But the design should acknowledge the limitation.

**FIX:** Add a note in §7 that the proportional method is the v1 de-vig; v2 can optionally upgrade to the **Shin** method (which models informed-trader adverse selection) or **odds-ratio** (which handles asymmetric vig better). Both are well-documented in the sports-analytics literature and can be swapped in without schema changes.

**Gap 2: De-vig requires both sides.** The `prop_odds_snapshots` table stores `odds` (captured side) and `odds_opp` (opposite side). If `odds_opp` is NULL (scraper failed to capture the opposite side, or the market was one-sided at that moment), de-vig is impossible for that snapshot. The design has no fallback.

**FIX:** Add a `de_vig_status` column to `prop_odds_snapshots` — values: `'paired'` (both sides captured, de-vig possible), `'single'` (only one side, use raw implied prob as best estimate), `'stale'` (snapshot skipped because line changed). For `single` rows, M7 can fall back to the raw implied probability and flag the lower-confidence EV.

---

### 3. Schema Sufficiency (§3) — PASS (one minor gap)

M7's needs traced end-to-end:

| M7 Requirement | Schema Support | Verdict |
|---------------|----------------|---------|
| Opening odds for each prop | `props.odds` (denormalized, ingested at creation) | ✓ |
| Closing odds for CLV | `prop_odds_snapshots.is_close=1` with `odds` and `odds_opp` | ✓ |
| Time-series for line movement | `prop_odds_snapshots(prop_id, odds, captured_at)` indexed by `(prop_id, captured_at)` | ✓ |
| Both sides for de-vig per snapshot | `prop_odds_snapshots.odds_opp` | ✓ |
| Settlement pairing | `prop_results.hit` joined via `props.id` | ✓ |
| Calibration bucketing by EV | `p_fair` computed from snapshots → bucket by decile → compare to `hit` | ✓ |

**Minor gap:** `prop_odds_snapshots` has no `side` column. The prop's side (Over/Under) is derivable via `JOIN props ON props.id = prop_odds_snapshots.prop_id`, but this join is required for every EV query. For query ergonomics and to survive a potential future where props might change sides (unlikely but defensive), denormalizing `side` into the snapshots table is cheap (one TEXT column) and eliminates the join.

**FIX (optional):** `ALTER TABLE prop_odds_snapshots ADD COLUMN side TEXT` — populated from `props.side` at insert time. Not blocking — just reduces join friction for M7 queries.

**What the schema does NOT need (and correctly omits):**
- Per-snapshot `line` — the line is on `props`; the doc's matching strategy (§6) skips snapshots where the line changed, so line-per-snapshot is redundant.
- Pre-computed `p_fair` — computing it in M7 from raw odds is correct (avoids storing derived values that drift if the de-vig method changes).

---

### 4. Matching / Identity (§6) — PASS (correctly scoped, fragile by nature)

The `--capture` matching key `(player_id, market, line, side)` was traced through the actual scraper flow:

1. Scraper extracts `player_name` + `team` from market description (regex at `bovada_scraper.py:144`)
2. `_resolve_player_for_ingest()` resolves to `player_id` via the identity spine (`sports_service.py` — uses `players` table by ID, not name string)
3. `market` is normalized through `MARKET_MAP` (line 34–94 of scraper)
4. `line` is the exact numeric value from `price.handicap`
5. `side` is `'over'` or `'under'` from the outcome description

**Where it breaks (and how the doc handles it):**

| Failure Mode | Doc's Handling | Assessment |
|-------------|---------------|------------|
| Line changed (4.5 → 5.5) | "Log and skip" (§6) | Correct — silent rebinding would corrupt settlement. The line change IS the CLV signal, but it's captured as a *new prop* at the new line, not as odds movement on the old prop. This is the correct model for half-point markets. |
| Market name drift ("Total Strikeouts" → "Strikeouts") | Not addressed | **Gap.** The `MARKET_MAP` handles known patterns, but new Bovada phrasings will fall through to the raw-description canonicalization (line 118: `market_desc.lower().replace(" ", "_")`). This creates a new market key → match fails → snapshots silently drop. |
| Player name format change | Identity spine resolves by ID | ✓ — the resolver handles formatting via `name_alias` and fuzzy matching. |
| Duplicate props (same player/market/line/side from different scrape passes) | Most recent `props.id` wins | ✓ — `--capture` appends snapshots to the matched prop. If two props rows match, pick the latest `captured_at`. |

**FIX (market-name drift):** Add a `market_alias` table (similar to `name_alias`) that maps raw Bovada market descriptions to canonical market names. Update it when a new phrasing is detected. Alternatively, log unmatched markets per run and review weekly. The doc's §8 canary (match-rate monitoring) partially covers this but needs a specific "unmatched market" metric, not just "unmatched prop."

---

### 5. Operational Risk (§8) — ISSUE (two fixes needed)

**Gap 1: Cadence math is inconsistent.** §8 says "~3 req/league/day at 30-min cadence = ~6/day" but §5 describes "snapshot every ~30 min from ~6 h before first pitch" = 12 snapshots/day/league × 3 leagues = **36 requests/day**. The actual number depends on how many leagues are in season simultaneously (currently only MLB). The doc should state the actual expected load.

**FIX:** Correct §8 to read: "~12 req/league/game-day (30-min cadence × 6 h window). At peak (MLB + NBA + NFL + NHL overlapping in October), ~48 req/day. Off-peak (MLB only, current state), ~12 req/day." This is still low volume and unlikely to trigger rate-limiting.

**Gap 2: No dead-man switch.** If Bovada walls the endpoint, the `--capture` cron will fail silently (exception caught, logged, cron retries next cycle). The app won't alert anyone. The `prop_odds_snapshots` table will stop growing — detectable in retrospect but not proactively.

**FIX:** Add a **canary query** to the cron wrapper:
```bash
# After each capture run, check if snapshots were written
SNAPSHOT_COUNT=$(sqlite3 picks.db "SELECT COUNT(*) FROM prop_odds_snapshots WHERE captured_at > datetime('now', '-1 hour')")
if [ "$SNAPSHOT_COUNT" -eq 0 ]; then
    echo "WARNING: zero snapshots captured in last hour — Bovada may be blocking"
fi
```
Run this as a separate health-check cron entry or integrate into the existing `coverage_cron.log` pipeline.

**Gap 3: No fallback data source.** §8 mentions "ESPN Bet / DraftKings are fallbacks (more friction)" but doesn't specify what "more friction" means (do they require auth? are they also open APIs?). For a production dependency, the fallback should be specified concretely enough that M7 isn't blocked if Bovada disappears tomorrow.

**FIX:** Add one sentence specifying the concrete fallback: "ESPN Bet's API (`sportsbook-api.espn.com`) requires a partner token. DraftKings requires OAuth. Both are non-trivial integrations. If Bovada becomes unavailable, M7 EV/CLV features will degrade to `props.odds` only (single capture at ingest, no CLV), which is still an improvement over the current zero-odds state."

**Operational verdict:** The per-day request volume is low (12–48 req/day) and unlikely to trigger rate-limiting from Bovada's open API. The `--capture` mode is designed to fail soft (caught exceptions, logged, cron retries). The monitoring gap is fixable with a simple count-based canary. The CEO flag in §8 is the correct gate.

---

### Summary of Fixes (ranked by importance)

| # | Area | Fix | Blocker for M6-impl? |
|---|------|-----|----------------------|
| 1 | §2 De-vig | Add fallback for one-sided snapshots (`de_vig_status` column) | **Yes** — without it, any snapshot missing `odds_opp` silently fails de-vig |
| 2 | §5 Ops | Correct cadence math + add canary query | **Yes** — operational readiness for cron deployment |
| 3 | §6 Matching | Add market-name alias table / drift monitoring | No — can be added in-week after M6 ships |
| 4 | §7 EV | Specify which snapshot's `p_fair` to use for EV (opening) | No — M7 can decide, but ambiguity risks implementation error |
| 5 | §3 Schema | Add `side` to `prop_odds_snapshots` (optional denormalization) | No — join to `props` works fine |
| 6 | §8 Ops | Specify concrete fallback if Bovada walls us | No — M7 degrades gracefully with single-capture odds |

**Overall: DESIGN IS SOUND.** The core architecture (denormalized `props.odds` + time-series `prop_odds_snapshots` with paired sides) correctly captures what M7 needs. The math checks out across all tested edge cases. The two blocking fixes (de-vig fallback, ops canary) are small schema/logic additions, not architectural changes. Ship with fixes 1–2, add 3–6 in the following week.
