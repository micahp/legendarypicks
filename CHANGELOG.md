# Changelog

## v0.6.2 — 2026-07-23

### EV/CLV: extended to NBA + NHL

Same generalization as NFL in v0.6.1, extended to the two other leagues with real per-game data
already sitting in `player_game_logs`: NBA (points, rebounds, assists, threes, blocks, steals,
turnovers) and NHL (goals, shots, assists — goalie stats like saves aren't ingested at all yet, so
left unmapped rather than guessed). Both leagues are off-season right now with zero live props, so
same caveat as NFL: verified against real historical game logs (LeBron James, Nikola Jokic,
Connor McDavid, Nathan MacKinnon), not provable end-to-end until their seasons resume.

### UFC: fighter detail + per-fight stats

- **Per-fight stats backfill** (`backend/ingest_ufc_fight_stats.py`): pulls ESPN's per-competitor
  statistics (sig strikes by target/position, takedowns, knockdowns, submissions, control time —
  43 fields) into `player_game_logs` for every UFC fighter we track. Fixes a real search bug as a
  side effect: UFC fighters only showed up in player search when they had a currently-live prop
  (search requires game_logs/props/stats, and UFC had zero game_logs rows ever); now permanent.
- **Fighter detail page**: UFC-specific Recent Fights table (opponent, date, W/L, sig strikes,
  takedowns) on the player detail page, replacing the generic per-league stats sections that don't
  apply to MMA.
- Curated the UFC stat list in the Props page's Model and Matchups tabs — those tabs generically
  iterate every stat key present, which for other leagues is a small curated set but for UFC is
  ESPN's full 43-field raw blob; restricted to the handful of headline stats (sig strikes,
  takedowns, knockdowns, submissions) instead of dumping everything.

### Props page

- Performance/Matchups/Model tabs now share one search — picking a player on one tab keeps it
  selected when you switch to another, instead of resetting the search box each time.

### Fixes

- Kick.com viewer counts were missing from the esports board on both dev and prod —
  `KICK_CLIENT_ID`/`KICK_CLIENT_SECRET` existed but were never forwarded through
  `docker-compose.yml`'s environment block (same class of gap as the PANDASCORE/GRID/YOUTUBE keys
  before it).
- `scripts/hermes-worktree.sh down` killed processes by hardcoded port instead of verifying they
  actually belonged to that task's worktree — took down the live dev tunnel's backend/frontend
  twice in one session as collateral damage. Now checks each candidate process's actual working
  directory first.

### Docs

- `docs/UNDERDOG-API-RECON-2026-07-23.md` / `docs/UNDERDOG-PROPS-BOARD-AND-SETTLEMENT-2026-07-23.md`:
  Underdog Fantasy's `over_under_lines` API is real and unauthenticated (PrizePicks' equivalent
  403'd). Confirms live UFC/MLB/tennis/esports markets and a new MLB 1st-inning market category we
  don't ingest today; what settlement would take per sport (MLB/NBA/NHL/UFC already have durable
  actuals, esports has live-only data with nothing persisted, tennis has no actuals pipeline at
  all yet).

## v0.6.1 — 2026-07-23

### EV/CLV: extended from MLB to NFL

The MLB EV/CLV fix (real per-game stats as an independent fair-probability source, landed
2026-07-22) only covered MLB — the market→stat mapping and game-log query were hardcoded to it.
Generalized to a per-league lookup and added the NFL mapping (passing/rushing/receiving
yards+TDs, receptions — matched exactly against `bovada_scraper.py`'s own market names and real
`nflverse` per-game data, not guessed). NFL has zero live props right now (off-season, Bovada
hasn't posted any) so this is verified against real historical game logs, not provable end-to-end
until props exist again in August.

### NFL: ADP ingest + data-freshness

- Fixed a real infinite-loop bug in `ingest_nfl_adp.py`: ESPN's fantasy-players endpoint ignores
  `limit`/`offset` and returns the full player pool on every call, so the old pagination
  termination check never tripped.
- `docs/DATA-FRESHNESS-SPLIT-2026-07-23.md`: catalogued the three data-freshness strategies
  already in the codebase (systemd timer, in-process lazy warmer, manual one-off script) and put
  NFL ADP + transactions on new daily timers as a result — closing the same class of gap that let
  Recent Trades ship empty to prod.
- Cached the Recent Trades significance lookup (was rebuilding ~9.6k players + ~2.5k ADP rows into
  fresh dicts on every request; that data now only changes once a day).

## v0.6.0 — 2026-07-23

### NFL: Draft Room → Player Rankings

- **Real ADP** (`backend/ingest_nfl_adp.py`): ingests ESPN's own fantasy API (free, unauthenticated) for real 2026 average-draft-position data, joined on the existing `players.espn_id` spine. Always-visible column next to whatever stat you're sorted by, with owned% as a sanity check.
- **Season-projected fantasy points**: recency-weighted per-game projection (`analytics/projections.py`) × games assumed (capped at 17), surfaced as its own always-visible column. Fixed a bug where it was silently built from stale 2024 data only (2024/2025 ingests use different stat key names for the same stat).
- Sort row now leads with ADP + Season Proj (ADP is the default sort), instead of trailing after last-season per-game stats.
- Renamed "Draft Room" → "Player Rankings" and dropped the card wrapper — it's a ranked cheat-sheet, not an interactive draft experience.
- Training Camp countdown card reworked into a scoreboard-style readout (milestone name, countdown, and a month/day date tile) instead of a generic status-pill widget.
- **Recent Trades** (`components/Leagues/NflOffseasonMovers.tsx`, replacing the old unfiltered "Offseason Movers" feed): shows trades only instead of every roster move (signings/waives/IR noise). Bundled multi-sentence transactions are split so each trade gets its own line; mirrored entries (ESPN logs one row per team in a deal) are deduped by player names, keeping whichever side gave up the more significant player (real ADP as the significance signal). Player names bolded.
- NFL sub-tabs: renamed the camp tab to "Home," dropped hardcoded years from tab labels, added a season toggle to the Stats tab (generic across all leagues, not NFL-only).

### MLB props: EV/CLV fix landed and verified

- `analytics/projections.py`'s `prob_over()` wired in as an independent fair-probability source for EV (previously fell back to a tautological single-side implied-vs-own-odds comparison that was always zero). CLV now derives "close" from real captured-odds timestamps instead of a never-set flag. Verified against real data: 72 props flipped from zero EV to positive, projection-backed.

### Esports

- Hid the esports card on the Leagues page — it linked straight into a sub-tab (Call of Duty) that can be empty, and there's no content-aware default yet.
- Added a "Make Picks" button on the esports page, linking directly to the pick desk (`/predict`).

### Fixes

- **Live Discounts widget**: stopped matching a live game's Kalshi price to a settled/finalized market from an earlier game the same day (doubleheader mismatch) — was showing a dead 1¢ "live" price on an actual 60¢+ market.
- Schedule nav: dropped a redundant loading spinner in favor of the existing skeleton state (two competing loading indicators doing the same job).
- Copy cleanup: removed em dashes from the Leagues page card descriptions.

### Docs / infra

- NFL product-direction spec (moat-adjacency framework: sit-start/waiver as props-as-fantasy, ranked feature priority) + the technical build-sequence spec, plus specs for a possible NFL mock draft simulator and a UFC lineup generator.
- `docs/RUNBOOK-parallel-dev-servers-and-hmr.md`: resource limits and gotchas running multiple delegated-task dev-server stacks on this box (port collisions, inotify exhaustion, live-editing under a running server).
- `hermes-worktree.sh`: documented that worktree isolation doesn't cover host-level config (`/etc`, systemd, cron).

## v0.5.10 — 2026-07-22

- **LiveNow** (`pages/scores.tsx`): Reverted featured game to horizontal two-row layout (team name + score per row) — cleaner, closer to original.

## v0.5.9 — 2026-07-22

### Design — Broadcast Rail live cards

- **LiveNow** (`pages/scores.tsx`): Replaced red-bordered opacity-hack card with solid zinc-900 surface + emerald left edge. All live games shown as compact inline chips — no toggle. Esports link demoted to quiet right-aligned text.
- **LiveDiscounts** (`components/LiveDiscounts.tsx`): Replaced amber-bordered opacity-hack wrapper with solid zinc-900 + amber static left edge. DiscountCards use subtle `border-zinc-800/40` instead of heavy card frames.
- **CSS** (`styles/globals.css`): Added `.live-edge` (emerald) and `.amber-edge` (amber) utility classes for the edge-bar design vocabulary.
- **Docs** (`docs/DESIGN-live-card-rail.md`): Design rationale and before/after.

## v0.5.8
