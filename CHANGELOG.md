# Changelog

## v0.6.5 — 2026-07-26

### Analytics: GA4 instrumentation

- **The app had no analytics of any kind** — no dependency, no calls, no tags. The NFL season is
  the only large traffic event on the calendar, so arriving uninstrumented would have spent the
  one annual spike and learned nothing from it.
- **GA4 wired for the pages router**: `send_page_view` is off and `page_view` fires explicitly on
  `routeChangeComplete`. LP's nav is client-side, so `config` alone would only count hard loads.
  GA4 Enhanced measurement can pick up history events, but it double-counts against a manual
  handler — the "Page changes based on browser history events" toggle is turned off on the
  property to match.
- **Five custom events**, each fired on a confirmed action rather than on render or click:
  `pick_made` (both flows — esports pick'em and UFC — only after the POST succeeds),
  `player_viewed` (resolved profile only, so 404s aren't views), `prop_chart_opened` (keyed on
  series identity, since callers swap the chart's data without remounting), `stream_watched` (the
  deliberate open, not iframe render). `usage_trend_viewed` is defined but not yet wired.
- `NEXT_PUBLIC_GA_TRACKING_ID` threaded through the Dockerfile and compose build args.
  `NEXT_PUBLIC_*` is inlined at build time, so a runtime-only variable would have produced a
  build that looked instrumented but recorded nothing.
- Verified against a production build in a throwaway worktree: the id is inlined into the `_app`
  chunk, the loader requests it, and a client-side nav produces exactly one additional
  `page_view` with no duplicate.

### Housekeeping

- **Version reconciliation.** v0.6.1 through v0.6.4 were written to this changelog and to
  `package.json` but never tagged or released — the last real tag was `v0.6.0`, so four version
  numbers were burned without a release. `package.json` and the tag are now aligned at `0.6.5`.
  The 0.6.1–0.6.4 entries are left in place as the record of what shipped; they are deliberately
  not tagged retroactively, since choosing commits for them after the fact would invent a history
  that did not happen.

## v0.6.4 — 2026-07-24

### UFC: fight_time prop chart

- **New chartable market**: `fight_time` (Underdog's Over/Under total-fight-duration prop,
  lines in minutes e.g. 2.5/7.5/12.5/14.99) now has a real per-fighter history chart. The
  underlying data — round the fight ended in, and elapsed clock within that round — was already
  being fetched from ESPN's per-fight `/status` endpoint for the result/method fields, just never
  read. Total fight time = `(round-1)*300 + clock_seconds` (UFC rounds are a fixed 5 minutes).
- Backfilled all 49 tracked UFC fighters (77/78 fight rows now carry `fight_time`; the one gap is
  a pre-existing ESPN data hole, same class as fights that were already skipped for missing stats).
- Verified against the real `/api/props/history` endpoint with an actual Underdog prop line, not
  just a database read — correct hit/miss against the line.

## v0.6.3 — 2026-07-24

### MLB: hits_runs_rbis compound prop chart, full season

- **New compound chart** (`total_hits,_runs_and_rbis`, MLB's H+R+RBI prop): `_MARKET_STAT_KEY`
  now supports list-valued stat keys that sum across multiple `player_game_logs` fields, not just
  a single stat. R and RBI aren't derivable from Statcast's pitch-level event stream (they need
  whole-game baserunner tracking), so they're pulled separately from the MLB Stats API boxscore
  (same source `settlement.py` already uses) and merged onto the existing per-game rows.
- **R/RBI backfilled across the full 2026 season** (2026-03-15 → 07-23, ~44k game-logs) — verified
  day-by-day with zero real gaps (the only 3 empty days are the actual All-Star break).
- **Real fix**: the compound chart was wired under a clean `hits_runs_rbis` key, but the real
  Bovada market string normalizes to `total_hits,_runs_and_rbis` (comma + `total_` prefix) — so it
  never actually fired from the real UI despite testing clean via a hand-typed API param. Fixed by
  mapping the real market string too, verified against a live prop row through the actual
  `/api/props/history` endpoint the frontend calls.
- **Backfill script hardened**: `ingest_mlb_logs.py` now pulls one day at a time
  (`pybaseball.statcast(day, day, parallel=False)`) instead of a whole date range in one call —
  the library's default threaded parallelism across days in a range was blowing memory/load on
  this box regardless of how the caller chunked `--start`/`--end`.

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
