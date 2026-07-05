# SPEC — Close the MLB prop loop (line → projection → outcome), two faces on one spine

**Date:** 2026-07-04. **DB audited:** `backend/data/picks.dev.db` (dev). **Why:** per
PHILOSOPHY.md, the sellable asset is the derived layer (projections, hit-rates, prop-outcome
history). This loop is simultaneously **Phase 2 step 1** (the hit-rate DB → paid API) and the
**witching-hour hook's non-live mode** ("players about to hit today" — projection vs posted
line, no live feed needed). One spine, two monetizable faces.

## What already exists (verified against the dev DB, not assumed)

The Phase-2 data model from `PHASE-2-prop-outcome-data.md` is **already built and populated**:

| Piece | State |
|---|---|
| `props` | 36,554 rows, **MLB only**, 2026-06-15 → **2026-07-04 (still capturing daily)**, all with `player_id` set |
| `prop_results` | 33,706 rows (92% of props have a result row) |
| `prop_odds_snapshots` | 3,135 rows; schema has `is_close` + `de_vig_status` (CLV-ready) |
| `player_game_logs` | 117,922 rows (MLB 35,102) |
| API | `/api/props` (+ `/history`, `/stats`, `/slate`, `/performance`), `/api/props/ev`, `/api/props/clv`, `/api/calibration`, `/api/projections` — all live in `routers/props.py` + `routers/analytics.py` |
| Frontend | `pages/props.tsx` exists |

So this is **repair + assembly**, not a build. What blocks shipping is data quality, found by
sampling the DB:

## Defects (evidence in dev DB)

- **D1 — Batter market strings are polluted.** Pitcher markets are clean (`strikeouts`, `outs`,
  `hits_allowed`, `earned_runs`) but batter markets fused player+team into the market string:
  `total_bases___bryce_harper_(phi)`, `total_hits,_runs_and_rbis___nick_kurtz_(ath)` → **1,195
  distinct markets**. Breaks every market-level aggregation, filter, and hit-rate. (`player_id`
  is set on all of them, so it's a string fix, not a re-ingest.)
- **D2 — Zero-settlement pollution.** Settled actuals: **15,703 zeros vs 5,623 positive**.
  Sampled Harper: a prop for **today's (Jul-4) game is already settled at actual=0.0** — games
  are settled before they finish / players settled 0 without evidence they appeared. Result:
  hit-rates are poisoned (overs 15% hit, unders 83% — a mirror produced by the fake-zero mass).
- **D3 — Duplicate props with conflicting settlements.** Same game/market/line/side settled
  twice with different actuals (Harper Jul-1: actual **0.0 AND 2.0** both settled; Jun-30: 0.0
  and 1.0). No uniqueness constraint on `(game_id, player_id, market, line, side)`.
- **D4 — `player_game_logs` is stale (MLB stops 2026-06-25).** No cron exists for log ingest or
  settlement (only the esports monitor + trading watcher are scheduled) — they were manual runs.
  Projections built on these logs are 9 days old.
- **D5 — CLV/EV layers starved.** `is_close=0` on all 3,135 odds snapshots (no closing-line
  capture job), and only ~55% of props carry odds → `/api/props/ev` returns zeros and
  `/api/props/clv` is empty (matches the Jun-26 analytics finding).

## Work plan (order matters: repair → automate → faces)

### 1. Repair the data (one migration script + ingest fix)
- Parse `<market>___<player>_(<team>)` → `market` gets the bare market (`total_bases`,
  `hits_runs_rbis`); cross-check parsed player name against the linked `players.name`, log
  mismatches to `unresolved_players` rather than guessing. Fix the writer
  (`ingest_props.py`/`bovada_scraper.py`) so new rows arrive clean.
- Add `UNIQUE(game_id, player_id, market, line, side)` (dedupe first: keep the row whose
  settled actual matches the boxscore; delete conflicting siblings and their results).
- Re-settlement audit: NULL-out every result where `actual=0` and there's no positive evidence
  the player appeared (batter `PA>0` / pitcher `IP>0` in the boxscore or game log), and every
  result settled before its game went final. Re-run settlement from finals only.

### 2. Automate the loop (single daily cron block)
- `ingest_mlb_logs.py` (+ pitcher logs) nightly, backfill Jun-26 → today first.
- `settle_props.py` after finals; settlement rule hardened per repair above (never settle a
  non-final game; never settle 0 without an appearance).
- Closing-line snapshot: capture odds at T−5min from first pitch, `is_close=1` — the schema is
  already built for it; this single job unlocks `/api/props/clv`.

### 3. Face A — "About to hit today" board (consumer hook, non-live mode)
- Join today's open props (already flowing daily) to `/api/projections` output: card = player,
  market, line, projected value, lean (proj vs line), and season/last-10 hit-rate on that market.
- Ship as `/props` upgrade or a "Today" tab on it. This is the PHILOSOPHY.md thesis made
  visible: *here is the line, here is the trend, here is where it's bending.*
- v0 explicitly **non-live** (no feed, no esports dependency). Live in-game progress is a later
  adapter, per the two-mode reframe.

### 4. Face B — hit-rate history (the sellable B2B slice)
- The endpoints exist (`/api/props/history`, `/stats`); after step 1 they stop returning
  garbage. Extend `pages/props.tsx`: player search → prop rows (line/side/actual/✅❌) +
  hit-rate sparkline.
- Paywall (API keys, rate limit, CSV, Stripe) only **after** a week of clean settled data —
  don't sell poisoned hit-rates.

## Acceptance (what "closed loop" means)
1. `SELECT COUNT(DISTINCT market) FROM props` ≤ ~10 (real markets only).
2. Zero settled results for non-final games; zero conflicting duplicate settlements.
3. Settled `total_bases` zero-share ≈ league-natural (~25–30%), not 74%; over/under hit-rates
   land near the juice-implied ~50%, not 15/83.
4. `player_game_logs` MLB current through yesterday, every day, unattended.
5. `/api/props/ev` non-zero, `/api/props/clv` non-empty (is_close rows exist), `/api/calibration`
   still sane.
6. `/props` shows today's board with projection-vs-line leans and honest hit-rates — the first
   page on the site worth showing a stranger.

## Out of scope (deliberately)
- Other leagues (NBA/NFL adapters later — same spine), live in-game mode, esports board work
  (maintenance only), player-shares, payments (until data is provably clean).
