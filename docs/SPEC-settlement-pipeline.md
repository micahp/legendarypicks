# SPEC → DeepSeek: Prop Settlement Pipeline (the core product)

Onboard via ORIENTATION.md → AGENTS.md → this. Do AFTER the identity spine lands (settlement matches
prop→stat by `player_id`, which the spine provides). Phase by phase, fresh subprocess each, build-
verified + committed per phase. Don't touch `scores.tsx`/`GameCard.tsx`.

## Why
`prop_results = 0`. We capture 472 props but grade ZERO. A "prop-outcome data company" with no outcomes
is just a prop *display*. Settlement = the product: after a game finals, tie each prop to the player's
ACTUAL game stat, grade hit/miss, store it. The Model tab + hit-rate history all read `prop_results`.

## Key correctness point (don't get this wrong)
Settlement needs the player's **per-GAME box-score stat**, NOT season aggregates. `player_stats` holds
SEASON stats — wrong for grading a single prop. Pull the **game box score** for the prop's game
(`prop_games.espn_event_id` → `espn.boxscore(league, game_id)`), find that player's stat for the
market, compare to the line.

## Phase 1 — market→stat mapping + single-game settler
- A per-league mapping `MARKET_STAT = {('mlb','strikeouts'): boxscore field, ('nba','points'): 'pts',
  ('nfl','passing_yards'): 'passYards', ('nhl','shots'): 'shots', ...}`. Cover the markets in `props`.
- `settle_game(game)`: for a finaled `prop_games` row, pull its box score, and for each prop on that
  game: resolve `prop.player_id` → the player's box-score line (match by the spine's source id, not
  name), read the market stat, compute:
  - OVER: `hit = actual > line`; UNDER: `hit = actual < line`; `actual == line` → **push** (hit=null).
  - player DNP / stat missing → **void/no-action** (not a loss) → log, don't fabricate a 0.
  Write `prop_results(prop_id, actual_value, hit, settled_at)`. **Idempotent** — skip already-settled.

## Phase 2 — drive it + backfill
- `settle_props.py`: find all `prop_games` that are FINAL and have unsettled props → `settle_game` each.
- Backfill historical finaled games so hit-rate history isn't empty.
- Report: # props settled, # void, # unmappable-market (→ a log/queue, never silently skipped).

## Phase 3 — wire the read side + verify the product
- `/api/props/stats` (Model tab) and `/props/player/{id}/performance` aggregate from `prop_results`
  (hit-rate L5/L10/L20/season). Confirm the Model tab + Performance hit-rates now SHOW data.

## Phase 4 — schedule it (with ingestion)
- A cron (like the certbot one) that runs the pipeline on a cadence: ingest props/stats/box scores →
  settle finaled games → refresh coverage report. Idempotent so re-runs are safe; don't race the DB.
- This is also where the broader **scheduled data plane** lives (ingests were manual until now).

## Edge cases
- Postponed/suspended games (not truly final) → don't settle. Pushes → hit=null, exclude from hit-rate%.
- Combo/alt markets you can't map → unmappable log, not a wrong grade. Non-team sports (tennis/UFC/COD)
  → out of scope for v1 unless trivial.

## Verification (paste numbers; verify against ground truth, not the code that wrote it)
- A spot-checked prop graded correctly vs the REAL box score (e.g., a pitcher's strikeouts: line X,
  actual from ESPN box = Y, hit/miss matches). Check an independent source, not our own settler output.
- `prop_results` populated for finaled games; re-running settle is idempotent (no dupes).
- Model tab + Performance hit-rates render real numbers; build compiles.

## Deliverable
Per-phase commits, before/after `prop_results` counts + a spot-check table in
`docs/HANDOFF-deepseek-to-claude-other-leagues-2026-06-15.md`, ping per phase.
