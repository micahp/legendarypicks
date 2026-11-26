# CONTEXT 2026-08-03 — v0.7.0 cut and PROMOTED to prod; mock-draft pool, NFL spine and gates green

**Read this first.** Supersedes `CONTEXT-2026-08-02-HANDOFF.md` (which itself superseded
`CONTEXT-2026-07-28-HANDOFF-14.md`). The state of the work is the gates, not this file:

```
cd /root/legendarypicks && bash verify-gates.sh all
```

## 1. Where the code is

Branch `dev`, worktree `/root/legendarypicks`. **v0.7.0 is cut, tagged and pushed, and prod is promoted** (the money pane's agent hit its monthly spend limit mid-release and Reasonix took over and finished it). The 07-29 pause on prod promotion is lifted — the user ordered "update context summary, git tag, and promote prod release".

Last commits (top of `dev`, all pushed; `v0.7.0` tag points at `86131b7`):

```
86131b7 fix(deploy): backend image builds from ./backend only, so bind-mount the docs/ vocabularies it reads at import
af123a6 fix(build): a test file inside pages/ compiled as a route and broke next build
60734b2 docs(release): v0.7.0 release notes
df52817 feat(nfl): the rankings card says the season in title case, and the esports logo map catches up
86f1d48 feat(nfl): the game log's rushing columns read YDS and TD like the receiving tab
0a25654 feat(nfl): the research board stops printing the position twice
a852e39 feat(nfl): the rankings card says the season once instead of shouting twice
d43a4ca fix(gates): REG-render's xFP threshold could not be met by a virtualized table
7f9e559 feat(data): the backfill writes any past phase, and refuses to duplicate a season
b7907a3 feat(data): NFL 2025's postseason was never ingested, and ESPN hides an exhibition in it
1a58f9d fix(gates): REG-render matches the pool headers case-insensitively, like its pills
11c0953 feat(nfl): the pool prints the rank alone in the name subtitle, never the position twice
37994ac feat(nfl): the pool leads with Proj and Exp PPR/G, ahead of Bye and ADP
44af35e feat(gates): REG-render measures the pool's column order, one-line names and scroll width
98cd5b5 fix(a11y): the rankings card claimed a heading level it does not own
9d20920 fix(tests): three D/ST fixtures fell behind the League Rankings query
```

## 2. The gates

```
bash verify-gates.sh all   →   23 pass / 2 fail
```

- **PASS** REG-render (mock-draft 1024 rows, xfp=32/34, camp-tab 50 rows, board 15R x 14T) —
  green for the first time since `6ee27fc`.
- **PASS** OVL-width (28 passed, 0 failed), REG-pytest (98 passed), REG-jest (67 passed),
  REG-pool, REG-adp-dst, REG-dst, REG-modules, COV-gametype, COV-keys, COV-honest, COV-api,
  COV-nba, COV-nhl.
- **FAIL COV-source (RED ON PURPOSE)** — NFL `team_game_results` 2024 + 2026 (1,114 rows) and
  MLB `team_game_stats` (16) carry no `run_id` to attribute them from. They need re-ingest
  under a recorded run, or it stays red honestly. NFL 2024 is additionally a vocabulary
  migration (nflverse game ids → ESPN event ids), deferred past v0.7.0 by the user.
- **FAIL REG-jest-all (2 failed, 120 passed)** — the known WCContext live-context polling
  defect, unchanged. Not from this session.

## 3. What v0.7.0 ships (the mock-draft pool, the NFL spine, the gates)

1. **Exp PPR/G is back next to Proj** on both pool tables (`# · PLAYER · PROJ · EXP PPR/G ·
   BYE · ADP · AVAILABLE`), names and subtitles never wrap, and `BUF · RB · RB1` → `BUF · RB1`
   (collapses only when the two positions agree). The shared cell lives in `columns.tsx`.
2. **REG-render's three defects fixed**: the missing column (reasonix, 3 commits), the
   `StatRankCard` h2-inside-overlay strict-mode violation (`98cd5b5`), and the unsatisfiable
   `xfpPool.populated >= 150` threshold vs a virtualized table (`d43a4ca` → `rows >= 20` +
   `populated/rows >= 0.6`).
3. **NFL 2025 is 285 games** — `backfill_nfl_postseason.py` wrote the 13-game postseason and
   refused the Pro Bowl (its only tell: AFC/NFC competitors not in the 32-team list).
4. **Provenance**: `team_game_results` gained `source` + `run_id`; 5,630 historical rows
   attributed from recorded evidence; unattributable rows stay NULL on purpose.
5. **NBA 2026 and NHL 2026 are `complete`**; `game_type` stamped at the boundary from the
   publisher's own phase fields; postponed games are no longer written as played.
6. **MLB `team_game_results.season` populated** (3,364 rows / 1,682 games / 0 one-sided).
7. **Gate-suite fixes**: `verify-gates.sh` runs end to end again (24 verdicts), zero-verdict
   gates FAIL, REG-pool 4,507 is satisfiable again, B4 names all four fraction surfaces.
8. **NFL game log** renders one narrow table per tab, `max-w-[520px]` restored.
9. **Rankings card** is one title-case line (`2025 Regular Season`) with `n=16 games` on hover.
10. **Research board (camp tab)** names/subtitles never wrap, position printed once.

## 4. Prod promotion (2026-08-03 — DONE, verified live)

- **Schema**: both migrations APPLIED on `backend/data/picks.db`; `migrate_logs_to_prod
  --check` reports missing logs 0 / missing players 0 (the 07-28 blocker note is stale).
- **Data gaps closed before deploy**: `nfl_player_projections` 2026 (0 → 11,515 via
  `ingest_nfl_projections.py` with the pinned snapshot from
  `/root/lp-v0613-recut/backend/data/espn_2026_snapshot_page1.json`) and `player_stats`
  `nflverse_regular_season` 2025 (0 → 608 via `ingest_nfl_season_stats.py --year 2025
  --cache-dir /root/lp-release-artifacts/nfl-draft-20260728 --apply`).
- **Deploy**: `docker compose up -d --build` with the API keys sourced from
  `/root/.hermes/.env` (DEEPSEEK, PANDASCORE, GRID, YOUTUBE, KICK). Prod = frontend
  `127.0.0.1:3100`, backend `127.0.0.1:8100`, bind-mounted `./backend/data`.
- **Two release blockers found and fixed during the build** (both pre-existing, neither
  had ever hit a prod build):
  1. `pages/player/[id].test.tsx` compiled as a route (`/player/[id].test`) and broke
     `next build`. Moved to `components/Leagues/NflGameLog.test.tsx` (`af123a6`).
  2. The backend image builds from `./backend` only, but `team_codes.py` (added 07-27)
     reads `docs/espn-team-codes-2026-07-27.json` at import → container crashed on boot.
     Fixed by read-only bind-mounting `./docs:/docs:ro` in docker-compose (`86131b7`),
     the same pattern as `./backend/data`.
- **Tag**: `v0.7.0` was re-cut twice onto the fixed commits (`af123a6`, then `86131b7`)
  and force-pushed, so the tag equals the deployed tree. `dev` is fully pushed.
- **Verify**: live on https://legendarypicks.xyz — all six surfaces 200 (/, /mock-draft,
  /player/469, /leagues, /scores, /props); pool serves 4,507 players with
  `proj_ppr_points` populated (Gibbs 364.7, Bijan 351.6, Puka 356.2); player 469
  (Josh Allen) returns the full 2025 profile; `/api/coverage` 200 via nginx;
  `verify_ufc_rankings.py` PASSED (P4P 16/16, 11 divisions); backend restart count 0.
- **Known prod gaps (not blockers)**: `momentum_crosses/state`, `nfl_pbp` tables do not exist in
  prod — the code that reads them is guarded (`_table_columns` / try-except) so endpoints
  degrade, not crash. Momentum is not frontend-wired.
- **2026-08-03 POST-DEPLOY FAILURE + FIX (this was mislabeled "not a blocker" in the original
  handoff, and that call was WRONG)**: the `team_stats_coverage` / `team_game_results` /
  `team_stats_team_inventory` / `team_stats_ingestion_failures` tables were never migrated to
  prod, so prod `/api/coverage` returned `[]` and **every league rendered "isn't available
  yet"** on /leagues while all dev gates were green. Fixed by rehearsing
  `migrate_team_stats_from_dev.py` on a disposable clone (atomic, fail-closed, quick_check ok),
  then swapping prod `picks.db` (backup `picks.db.bak-precoveragefix-*`, zero live-data loss —
  props count identical pre/post) and restarting the backend. Verified live: `/api/coverage`
  3 rows complete (nba 2026, nfl 2025, nhl 2026); /leagues/nba|nfl|nhl render with 0 console
  errors. MLB stays honestly unavailable (dev has no MLB coverage row either). Guardrail added:
  `verify-gates.sh` now has **COV-prod** (`LP_GATE_P`, default :8100) which asserts the DEPLOYED
  registry — 24 pass / 2 fail as of this fix.
- **Pre-existing quirk, no live impact**: the frontend image bakes the `/api` rewrite to
  `localhost:8000` at build time (the compose runtime `API_PROXY_TARGET` env does not
  reach `next build`), so `:3100/api/*` 500s if hit directly — but nginx routes all
  `/api/` traffic straight to `:8100`, so the live domain is unaffected and always has
  been (the old image has the identical baked value). Fixing it = add
  `API_PROXY_TARGET` as a Dockerfile ARG at the next image change.

## 5. Open / next

0. **MLB availability (dev first, then prod) — IN PROGRESS, Micah's corrections are
   binding.** Spec: `TASK-mlb-availability.md` (authoritative, corrected 2026-08-03).
   Dev state measured: `team_game_results` mlb 2026 = 3,364 rows / 1,682 games,
   date range 2026-03-26..2026-08-02, **no spring rows**; `team_stats_coverage` mlb row =
   **none** (that is the only thing making MLB unavailable). Hard rules: (a) NEVER
   `status=complete` for mlb 2026 — mid-season ~1,682/~2,430, and `complete` FLAPS
   (last-night games are played-and-absent until ingest → `explain_gap` → `partial` →
   MLB unavailable again a day later); the row must claim a **WINDOW**
   (season_start..checked_through, every completed game present and paired) under a
   **distinct `in_progress` status**; (c) there is NO refresh job for MLB
   `team_game_results` on this box (`legendarypicks-mlb-capture.timer` = Bovada prop
   odds, not results) — `checked_through` freezes without one; add a refresh timer +
   staleness budget; (d) scope the expected-count oracle to **season type 2** — ESPN
   publishes 451 type-1 Spring Training events for 2026, an unfiltered season count
   compares us against spring too; (e) `team_game_results` has NO `game_type` column —
   do NOT add one or delete rows (pending product decision; the 2026-03-26 date boundary
   is the only separator); (f) dev first, prod second, clone-rehearse-backup-swap-verify,
   get Micah's explicit go before the prod step. `reconcile_totals.py` already has
   `season_types()`/`season_type_id()` and `write_coverage()` (emits complete/partial
   today — needs the in_progress window variant).

1. **NFL 2024 vocabulary migration** — deferred past v0.7.0 by the user ("we don't even show
   it in the frontend"). `backfill_nfl_postseason.py` refuses without `--replace-vocabulary`.
2. **REG-jest-all** — the WCContext polling pair (known defect).
3. ~~**OVL-width**~~ **RESOLVED before the release — this item was stale when written**, and
   §2 above already records the truth: **28 passed, 0 failed**. The gate no longer asserts on
   Overview's SEASON STATS row. ESPN scrolls its own season-stats row on mobile, and the brief
   was always the per-week table, where a sideways scroll costs you the comparison between
   weeks — one season row has nothing to compare across. It is still **measured and printed**,
   because a number nobody asserts on is what tells you when it changes.
4. **NCAAF** — `TASK-league-ncaaf.md`, unblocked now that league-0 is green. Its ingest must
   filter `completed`, stamp `game_type` at the boundary, and write both sides of every game.
5. `game_type` column on `team_game_results` — deliberately deferred (would NULL every
   existing NBA/NHL/NFL row); recoverable via `game_types.py`'s measured phase windows.
6. **PROD REGRESSION FOUND POST-DEPLOY 2026-08-03 — the Bye column is empty on prod.**
   `nfl_schedule` holds **2025 only** on prod (285 rows) against dev's 2024/2025/**2026 (272)**,
   so `/api/nfl/schedule/2026` **404s** and every Bye cell renders `—`. Measured in a real
   browser on https://legendarypicks.xyz/mock-draft: **33 of 33 rows empty on prod, 0 of 33 on
   dev.** This is not cosmetic — `columns.tsx` spends the width it saves on bye week precisely
   because it "decides more picks in rounds 8-15". §4's six-surface check was 200-level and
   could not see it. Fix is one bounded command (static nflverse CSV, no pagination, dry-run
   verified against prod: 272 REG games, first kickoff 2026-09-09 NE at SEA):

       cd /root/legendarypicks/backend
       LP_DB_PATH=data/picks.db ./venv/bin/python ingest_nfl_schedule.py --season 2026 --schedule-only

   **Use `--schedule-only`** — without it the script also creates and writes `team_game_results`,
   a table prod deliberately does not have (see the known-gaps list in §4).
