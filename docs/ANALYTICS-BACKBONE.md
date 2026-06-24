# Analytics Backbone — to-do (EV / CLV / calibration)

**Goal:** make Legendary Picks store **price/probability, not just outcomes.** Once price is
captured at ingest time, EV, CLV (closing-line value), and calibration (Brier / reliability)
all fall out as straight queries.

**Why now (2026-06-24):** expert rubric graded the app ~4.8/10 (analyst) and ~3.0/10 (bettor).
The single fatal gap: the `props` table stores `(market, line, side)` with **no odds/price**,
so hit-rate is computable but EV / breakeven vig / CLV are *structurally impossible*. Settlement is
also 8 days stale. Two external feeds already exist that close part of the gap:

- **Kalshi prices** banked in `/root/prediction-market-trading/data/orderflow/` (event-level =
  game-winner, not player-props). `espn_resolve.py` there already maps Kalshi ticker → ESPN gid.
- **ESPN win-probability** is available in the ESPN `summary` endpoint but **not currently captured**
  (`espn_pbp.py` logs play-by-play events only).

> Identity-spine discipline (AGENTS.md §7) applies to everything here: join on canonical IDs via
> crosswalk tables, **never** on display-name strings. Every new source gets a crosswalk established
> at ingest.

---

## Layer 0 — Settlement data health (DONE 2026-06-24)

**Correction of an earlier misdiagnosis:** the settlement pipeline was NOT broken or stale.
It runs daily (latest `settled_at` today 06:00) and settles resolvable props. The "unsettled
props" lines in cron logs were **permanent residue** (players with no `mlbam_id`, or DNP) that
re-appear every run because voids aren't persisted — not a breakage.

**The real gap was identity coverage.** Of 7,438 unsettled-residue props in final MLB games:
6,050 (81%) referenced players with no `mlbam_id` in the spine → settlement keys on `mlbam_id`
(MLB Stats API boxscore), so they voided unconditionally. Only 207 *distinct* players
(206 with a team set) drove all 6,050.

**Fix shipped:** `scripts/backfill_mlbam_id.py` resolves mlbam_id by normalized name + team
against the MLB Stats API 40-man roster (alias map for AZ/ATH/WSH abbrev differences).
- 204/207 resolved (3 misses: 1 junk, 2 minor-leaguers not on a 40-man).
- Re-ran settlement → **graded props 4,804 → 10,393** (76% of 13,734, up from ~35%).
  5,589 settled this run; hit-rate sanity-checked real (43% over / 57% under), not garbage.
- Verified: Jose Altuve 4 TB (over 1.5 ✓), Salvador Perez 0 H/R/RBI (under ✓).

- [x] Diagnose residue cause (identity coverage, not breakage).
- [x] Backfill `mlbam_id` (204 players); re-grade.
- [ ] **Persist voids:** store a `prop_results` row for voids (DNP / no-mlbam) so cron stops
      re-fetching + re-voiding the same residue every 30 min (waste + noisy logs). Small clean fix.
- [ ] Investigate the ~1,388 "has mlbam_id but still unsettled" — confirm they're legit DNP vs
      a matching bug. Low priority (most are DNP).

## Layer 1 — Capture price/probability (the backbone itself)

- [ ] **1a — Player-prop odds (HIGHEST leverage, expert's #1 fix):** add `odds`/`price` to the
      Bovada props capture. Store **decimal odds + implied prob + line + side**. Without this,
      player-prop EV is impossible. This is the single biggest bettor-grade grade movement.
- [ ] **1b — Game-level odds (the crossover):** import Kalshi contract prices from the trading
      repo. Reuse `espn_resolve.py` (Kalshi ticker → ESPN gid) as the crosswalk. Kalshi price =
      implied probability. *(Caveat: event-level only — fixes game EV, not prop EV.)*
- [ ] **1c — ESPN win probability:** extend `espn_pbp.py` / LP `espn_client` to pull + persist the
      ESPN `summary` win-prob time series. **Not currently captured** — this is the gap.

## Layer 2 — Store as a time-series (so movement/CLV is computable)

- [ ] `odds_snapshots` table: `(market_key, line, side, odds_decimal, implied_prob, vig,
      captured_at, source)` — **one row per capture**, keep history. This is what makes CLV
      possible (entry price vs closing price).
- [ ] Crosswalk tables (identity spine): `kalshi_event ↔ espn_game_id`; canonical `market_key`
      joining Bovada props to ESPN player stats. Resolve identity BEFORE wiring sources.

## Layer 3 — Compute the analytics

- [ ] **EV** = model_prob (predictions endpoint / ESPN win-prob) − implied_prob_from_odds.
      Surface +EV props.
- [ ] **CLV** = entry price vs closing price, from Layer-2 history.
- [ ] **Calibration** = hit-rate vs implied-probability (Brier score + reliability curve). This is
      what makes predictions sellable on trust.

## Layer 4 — Expose + UI

- [ ] `/api/props/ev`, `/api/calibration`, `/api/clv`.
- [ ] +EV surfacing + a thin bet tracker (expert's fix #3).

---

## Constraints to plan around

1. **~2 weeks of Kalshi/odds history** → CLV backtests are shallow until the bank grows. The
   *capture* is the asset — start now, depth accrues.
2. **Kalshi = event-level** → covers game-winner EV, not player-prop EV. Player-prop EV still needs
   1a (Bovada odds). Both matter; neither substitutes for the other.

## Recommended order

Layer 0 (cheap unblock, verifiable today) → 1a (biggest bettor-grade movement) → 1b/1c in parallel
(separate captures) → 2 → 3 → 4.
