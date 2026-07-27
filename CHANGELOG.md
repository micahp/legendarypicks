# Changelog

## v0.6.10 — 2026-07-27

### You can look up a player instead of paging to him

- **Search the draft board by name.** The board shipped with a position filter, a sort and
  prev/next across 522 players at 50 a page — but draft research is name-driven. You arrive
  wanting to know about one guy. Now you type him.
- **Every token has to appear in the name, in any order**, because people type fragments in
  whatever order they remember them: `ja gibbs` finds Jahmyr Gibbs, `rice` finds Rashee Rice.
- **Narrowing happens in SQL, not in the browser.** Searching for one player costs one
  player, not 522 rows filtered client-side. The input waits 250ms before asking, so typing
  a name is one request rather than one per keystroke.
- **A search that finds nothing says which search found nothing** — "No player named
  "…" on the board" — instead of rendering an empty table and leaving you to guess whether
  it broke.
- Typed `%` and `_` match themselves. LIKE wildcards are escaped, so a stray `%` finds
  nothing rather than returning the entire board.

## v0.6.9 — 2026-07-27

### The draft board is about availability now, not about who scored well when healthy

- **The board ranked on an average conditioned on the thing you were trying to predict.**
  `fantasy_ppr_g` is points per game *played* — it only counts the days a player was
  healthy enough to appear, which makes injury-prone players look safer than they are.
  Every fantasy site shows that column. Joe Burrow's 2025 reads **16.8 per game played and
  7.9 per team game** off the same season; Tyreek Hill's reads 13.4 and 3.2. Both numbers
  now ship together, always, because the gap between them *is* the information.
- **Availability is the headline: games played out of the team's 17.** A missed game has no
  row in `player_game_logs`, so absence is invisible unless you deliberately go get it. The
  denominator is a constant, verified as 32 teams × exactly 17 games in both 2024 and 2025
  — which sidesteps the `team_game_results` key-scheme problems entirely. Deriving it from
  that table is what made Joe Flacco read **13/34**; he now correctly reads 13/17.
- **Postseason weeks are excluded.** Weeks 19–22 are playoffs; counting them let a deep run
  report 21/17 and inflated both averages.
- **Expected fantasy points (xFP), from ffverse/ffopportunity.** A per-game average over a
  short sample is mostly touchdown variance; xFP prices the opportunity a player was given.
  Measured 2024 → 2025 on our own data, xFP/g predicts next season's actual PPR/g better
  than actual PPR/g does, and the margin is widest where the sample is thinnest — r=0.424
  vs 0.374 at ≤4 games, against r=0.778 vs 0.775 at 10+. Stated honestly: that makes a
  three-game sample *less misleading*, not reliable, so sample size stays on the surface.
- **Target share and the 2026 depth chart join snap share**, so a healthy player in a
  timeshare reads differently from an injured starter. Both are published values copied in,
  not derived here — nflverse already publishes `target_share` at 100% coverage.
- **Rookies read "No NFL sample" and never a zero.** A zero is a claim about the player;
  absence is a claim about us, and only the second one is true. They stay on the board on
  ADP and depth-chart rank. Jeremiyah Love — going 17th overall, 98% owned, Arizona's RB1 —
  was invisible under the old `games > 0` filter, along with 147 other ADP-ranked players.
- **ESPN's undrafted sentinel is no longer treated as a ranking.** 1,392 of 2,511 ADP rows
  sit at exactly 170.0; only 248 players carry a real ADP.
- **The accent colour marks absence, not achievement.** Every game played renders quiet;
  the one saturated colour on a row is the games missed. The availability strip shows one
  cell per game the team actually played — 17, not 18, because a bye is not an absence.
- **Nothing is labelled a projection any more**, because nothing on the board is one.
  `season_proj_pts` and its "games assumed" caption are gone.
- Three draft-board tests had been red long enough that nobody read them; they were a
  missing `nfl_adp` fixture. The suite goes from 249 passed / 4 failed to 256 passed / 1.

### Known

- `players.nfl_gsis_id` mixes two id schemes: 651 active players carry an ESPN-style
  synthetic key (`LOV121782`) in a column named for gsis, and all 651 have zero game logs.
  The depth-chart ingest works around it via `espn_id`; the spine itself is unrepaired.
  Recorded as ROADMAP B7 with the measured fix.

## v0.6.8 — 2026-07-27

### NFL: the numbers now come from the published source, and the calendar exists

- **Per-game NFL stats are copied from nflverse's maintained weekly box score instead of
  re-derived from play-by-play.** `ingest_nfl_pbp_logs.py` aggregated a 372-column
  play-by-play feed into per-player-game lines, justified by a docstring claiming the
  weekly summary "404s for 2025". It does not — the release was renamed `player_stats` →
  `stats_player`, returns 200 for both 2024 and 2025, and carries 145 columns including
  `passing_epa` and `passing_cpoe`. Every defect fixed in the previous release was a bug in
  a reimplementation of arithmetic nflverse already does correctly. Verification against a
  copied source is tautological; against a derivation it is a permanent project.
- **The 2025 postseason exists for the first time — 258 player-games.** Weeks 19–22 had
  zero rows. The play-by-play path had never produced playoff data at all, so no amount of
  fixing it would have surfaced Stafford's wk19–21 run or Rodgers' wk19.
- **Fantasy points are correct.** The hand-rolled scorer omitted fumbles lost (184 rows),
  two-point conversions (83) and special-teams touchdowns (15). All 5,635 stored rows now
  reconcile against the published artifact with zero mismatches.
- **The 2026 schedule is ingested** — 272 regular-season games from nflverse's `games.csv`,
  opener 2026-09-09, into a new `nfl_schedule` table plus reciprocal `team_game_results`
  rows at `status='scheduled'`. Nothing in the database previously held an NFL schedule:
  the only writer accepted games whose ESPN status was already `post`, so by construction
  it could never record a fixture that had not been played. With the season 44 days out,
  "who does this player face in week 1" was unanswerable.
- Schedule rows carry kickoff time, rest days, roof and surface, spread and total lines,
  coaches and starting-QB ids — the inputs a draft or sit/start board needs.
- **Play retention is unaffected.** `nfl_pbp` keeps its 46,452 plays; only the rollup half
  of that ingest was retired. Raw plays are additive, the derived summary was not.
- Guards on the schedule ingest, both mutation-tested: empty source cells read as NULL
  rather than 0, so an unplayed fixture is never stored as a completed 0–0 tie; and scores
  upsert through `COALESCE`, so re-running a season in progress cannot blank a result.
  No `team_stats_coverage` manifest is written for 2026 — the NFL aggregate is bounded by
  the newest manifest, and one would have pulled 272 unplayed games into season totals.
- Ingests print their artifact's sha256 on every run. nflverse rewrites files in place, so
  the digest is the only thing that makes a run reproducible.
- **+23 tests**, each assertion checked against a deliberately broken implementation rather
  than only a passing one.

### UFC: the fight-stats ingest can no longer lose data

- **Rebuilt as a planned, additive write.** The whole plan is fetched and validated before a
  writable connection is opened, then applied in one short transaction, with typed plan
  structures so what will be written is inspectable first.
- The only log write is `INSERT OR IGNORE`. There is no `DELETE`, no `DROP` and no
  `INSERT OR REPLACE` in the module, so a re-run cannot erase another ingest's enrichment —
  the failure mode that cost the NFL 2024 season its snap and Next Gen keys twice over.
- `--dry-run` and `--apply` are mutually exclusive with no default write, and `--apply`
  requires an integrity-checked pre-write backup path. Identity and game-link updates only
  fill blanks and raise rather than overwrite an existing link.
- A distinct `SourceUnavailable` error keeps an upstream failure from being recorded as
  "this fighter had no stats."

### World Cup

- **Clipped-nickname player names resolve.** Feeds can combine a nickname with a shortened
  surname while ESPN uses the formal first name ("Alex Grimald" vs "Alejandro Grimaldo").
  The new last-resort match requires same team, matching first initial and a five-character
  surname prefix identifying exactly one player, and declines rather than guessing.

> Data-layer release. The corrected numbers, the postseason and the 2026 schedule reach
> users on the next production deploy; prod continues to serve the previous data until then.

## v0.6.7 — 2026-07-26

### NFL player page: usage is now its own tab

- **Player page restructured into Overview │ Usage │ Game Log.** The usage card is role-driven —
  it reads the player's position first and picks columns off that, because the underlying feeds
  do not cover every position equally.
- **Four positional tile sets.** QB Snap%/Att-g/CPOE/EPA-per-dropback · RB Snap%/Car%/Tgt%/PPR
  (Rushing sorts before Receiving) · WR/TE Snap%/Tgt%/WOPR/Separation, plus the full Next Gen
  band. Share columns carry a magnitude bar.
- **Seven ingested-but-unrendered keys exposed** on `/api/nfl/usage`, plus a derived
  `epa_per_db` — `pass_epa` is stored as a game total, so a 40-attempt game and a 20-attempt
  game were not otherwise comparable.
- **Rushing usage added** (carries / carry share). Without it an RB's usage table was almost
  entirely dashes.
- **Two sparkline bugs fixed:** shares were forced onto a 0–100% axis, so a 21%→37% climb
  rendered as eight identical stubs; and a negative CPOE drew a short bar growing *upward*.
  Diverging metrics now hang below a zero line.
- **Season Stats zero wall removed.** Stat blocks are selected by position before values are
  pruned. Rendered zero/None tiles across all 1,217 NFL rows: **7,255 → 408**, with no player
  losing a section.
- **Performance:** the usage endpoint's team-wide target/carry sums had no covering index and
  scanned every NFL row twice per request. Two indexes on `player_game_logs`
  (`league,game_id,team` and `league,season,game_no,team` — the 2024 rows carry no `game_id`).
  Team-sum query 70–100ms → 0.5ms; full request **~180ms → ~13ms**. A response cache was
  considered and rejected: it would have hidden the scan rather than removed it.
- **`usage_trend_viewed`** (defined but unwired in v0.6.5) now fires on entry into the Usage tab.
- Verified at 1280px and 390px; the week column is pinned so a scrolled 14-column table keeps
  row identity.
- **+16 tests**, each assertion checked against a mutated implementation rather than only a
  passing one.
- **Test isolation fix:** `LP_DB_PATH` leaked between suites, so three real-DB tests failed in a
  whole-suite run but passed file-by-file. The full suite is usable as a gate again.
- New reference docs: `docs/NFL-DATA-INVENTORY.md`, `docs/NFL-CHART-CONTENT-RESEARCH.md`.

## v0.6.6 — 2026-07-26

### Esports: broadcast source reliability

- **Official simulcast siblings.** When a real per-match source attests a known official Twitch
  broadcaster whose organizer also simulcasts on YouTube, the backend adds that organizer's
  official YouTube channel as a candidate. The mapping is broadcaster-level and case-insensitive
  (VCT EMEA and BLAST Premier today), so it covers every event from that broadcaster rather than
  a single match or league label. Rule-only Twitch guesses cannot trigger it.
- The resolver checks YouTube's `/streams` page first at zero Data API quota; the budget-capped
  Data API search is only a fallback, and ambiguity still fails closed to Twitch/Kick.
- **Viewer counts persist between matches** instead of blanking during the gap.
- **Missing Kick viewer counts are retried** rather than left empty for the rest of the session.
- `docs/ESPORTS-EXPECTED-BEHAVIOR.md` updated in step, per the rule at the top of that file.

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
