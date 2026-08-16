# RALPH-NCAAF-PLAN — add college football, scoped to FBS

Source request: `.ralph/request.md` (TASK-league-ncaaf.md). Owner: Hermes, backend +
frontend. This plan governs the multi-session Ralph process (max 100 sessions, 3
retries per task, stagnation after 3 no-progress sessions).

# Objective

Add **college football (NCAAF), scoped to FBS**, to Legendary Picks so a user can
open the league and get working **scores, props, game detail, last season's stats
(player AND team), and player detail**. The feature is DONE (Micah's definition,
2026-08-09) when those five surfaces answer for `ncaaf` — not when a gate is green on
a surface nobody can click.

# Constraints

- **Prod is off-limits.** No `docker compose`, no container restarts, no writes to
  `backend/data/picks.db` (prod), no `git push`. All work on `picks.dev.db` (dev).
- **Never run npm/npx/yarn from this worktree.** `node_modules` is a shared-install
  symlink; an install or `npx` can empty it and break every frontend on the box. Use
  `/root/lp-league-mls-ncaaf/node_modules/.bin/next` / `jest` / `tsc` directly.
- **Know which DB you opened.** `LP_DB_PATH` is relative to process cwd. The dev DB is
  `/root/lp-league-mls-ncaaf/backend/data/picks.dev.db`, which is a symlink to the
  canonical dev database. Always set this absolute `LP_DB_PATH`; verify `PRAGMA
  quick_check` and real row counts before trusting any HTTP 200.
- **Use only the isolated worktree stack:** frontend `http://127.0.0.1:3110`, backend
  `http://127.0.0.1:8110`, tmux session `ralph-stack`, with logs in this worktree.
  Other development stacks and their checkouts are externally managed: do not inspect,
  edit, start, restart, kill, or reconfigure them.
- **Do not touch** `backend/_core.py`, `ingest_nfl_*.py`, `ingest_wc_logs.py`, anything
  under `components/MockDraft/`, `NflDraftRoom.tsx`, `NflCampHero.tsx`,
  `NflOffseasonMovers.tsx`, `/etc`, systemd, cron.
- **FBS only.** An FCS row in the table is a denominator bug waiting to happen. Scope
  is group 80; record the group id as data in the league registry, never as a filter
  sprinkled through queries.
- **No invented data / no fabricated zeros.** A missing record reads as absence (dash),
  never as 0-0. Omit soccer-only fields (points/GF/GA/GD) from CFB — do not fabricate.
- **Skills before touching:** `published-first` (before any ingest; rung 5 is the one
  this league breaks), `honest-data-ui` (any surface showing numbers), `resource-check`
  (before batch ingest), `espn-request-budget` (before any ESPN call), and the
  engineering reference at `.ralph/engineering-reference.md` (this process's governing
  procedure).
- Backend tests: from `backend/`, use
  `/root/lp-league-mls-ncaaf/backend/venv/bin/python -m pytest` (whole suite or one
  file). Frontend: `/root/lp-league-mls-ncaaf/node_modules/.bin/jest`. Build with the
  direct `/root/lp-league-mls-ncaaf/node_modules/.bin/next build` binary, never an npm
  wrapper. Gates: set `LP_GATE_W=/root/lp-league-mls-ncaaf`,
  `LP_GATE_B=http://127.0.0.1:8110`, and `LP_GATE_F=http://127.0.0.1:3110` together or
  `verify-gates.sh` may grade the wrong stack while this code never runs.

# Engineering Reference

The governing procedure is `.ralph/engineering-reference.md` (engineering-distillation).
Load it before any phase. Binding rules this process must not violate:

- **Understand → Recon → Assumptions → Plan → Implement → Verify → Report**, in order.
- **Never invent repository facts.** A path/function/column/route you did not read does
  not exist. Inspect before editing, and read the caller too.
- **Evidence labels:** FACT (cite a path:line or command), ASSUMPTION (with a
  consequence-if-wrong), HYPOTHESIS (with a discriminating experiment), DECISION (with
  what was rejected), RESULT (with the command + exit code). Never "likely/probably"
  as a conclusion.
- **Verify against the requirement, not against your own output** (AGENTS.md §3). A
  200 or a green gate is not acceptance; render the surface and read the numbers.
- **Scope control (§16):** Required + Supporting implement; Optional propose; never
  touch Out-of-scope. No drive-by refactors, no reformatting, no dependency upgrades.
- **Doom-loop prevention (§13):** never repeat the same fix without new evidence; 2
  strikes → back to diagnosis; 3 → recheck premises; never catch-and-ignore; never
  weaken types/validation/authz to pass a gate; never delete/skip a test.
- **Four states (§6):** every async surface ships loading, empty, success, error.
  "Only success" is incomplete.
- **Verification ladder (§Phase F):** static → format → types → lint → targeted unit →
  integration → build → runtime → regression → security → a11y → user-visible
  acceptance. Run every available rung; report unavailable rungs as limitations, not
  skipped steps.
- **Per-task completion (§17):** all hold, including "the build succeeds where a build
  exists" and "no claim you did not observe."

# Definition of Done

**Feature done** (Micah, 2026-08-09) — all five surfaces answer for `ncaaf`:
1. **Scores tab** — NCAAF appears in the /scores filter and the All-view fetch; games
   render. *(Data done: COV-ncaaf PASS 888/888; branch scores.tsx has the filter — must
   be seen on the isolated stack.)*
2. **Props tab** — the /props surface answers for ncaaf. *(**NOT DONE by data:** 0 ncaaf
   `player_stats` rows, 0 props joined to ncaaf players. Requires a season-aggregate
   and/or props acquisition source. An honest empty state is not "answers".)*
3. **Game detail** — data-backed (888 team_game_results + 1776 team_game_stats), render
   path shared with other leagues. *(Done data-side; render on the isolated stack must
   be seen.)*
4. **Last season's stats — player AND team** — player side verified (12-row / 1-row /
   empty). Team side: 1776 team_game_stats rows exist; the team-stats surface render is
   the last unverified piece.
5. **Player detail** — overview + game log + honest empty states. *(Verified on branch;
   must be seen on the isolated stack.)*

**Process done** additionally requires:
- All task-owned UI/backend hunks remain in `/root/lp-league-mls-ncaaf` and are visible
  through the isolated `:3110`/`:8110` stack. Do not copy them to another checkout.
- `verify-gates.sh COV-ncaaf` **PASS** and `verify-gates.sh COV-statset` run with every
  red item for this league named in writing (MANIFEST must be the newer coverage-floor
  copy, not this branch's old presence-based one — see T4 hazard).
- `reconcile_totals.py --league ncaaf --season 2025` exits 0 with the pasted output.
- Backend suite green, frontend jest green, and the direct Next build succeeds.
- Player game logs render at mobile width as a scrollable table with columns, including
  an honest empty state for a position with no stats.
- `docs/LEAGUE-STAT-GAPS.md` reflects whatever this league still lacks (so the next
  person does not rediscover it).

# Tasks

Dependency-aware, granular, acceptance-testable. Each `[TODO]` item is one session unit.

- [x] [DONE] **T0 — Recon & ground-truth baseline (session gate).** Confirm current
      state before any work: `git status`, `git branch --show-current`
      (=`feat/league-mls-ncaaf`), verify dev DB rows via absolute path
      (`players 20926 / logs 56577 / results 1776 / coverage complete`), confirm
      `player_stats` for ncaaf is 0 and props joined to ncaaf is 0. Record `uptime` +
      `free -h` before any batch work (AGENTS.md §12, resource-check).
      *Acceptance:* exact row counts pasted; no inference.
      **DONE 2026-08-11 (session 2) — observed, not inferred.** Branch
      `feat/league-mls-ncaaf`; dev DB selected by the absolute worktree path
      `/root/lp-league-mls-ncaaf/backend/data/picks.dev.db`
      (335 MB) via python sqlite3: players=20926, player_game_logs=56577,
      team_game_results=1776, team_game_stats=1776, distinct games=888, null
      game_type=0, coverage ncaaf/2025=complete, player_stats=0, props-joined-ncaaf=0.
      Load avg 1.93, Mem available 1.3 GiB (borderline; T0 was read-only, no batch).
      The original worktree stub was 0-byte; the isolation handoff replaced it with a
      verified canonical-DB symlink. **Flag for T1:** git status shows `pages/leagues.tsx`,
      `TASK-league-ncaaf.md`, `docs/LEAGUE-STAT-GAPS.md`, `backend/data/esports_team_logos.json`
      also modified (session-0001 said leagues.tsx ncaaf handling was already present) — T1's
      "diff shows exactly these files" must reconcile this.
- [~] [IN_PROGRESS] **T1 — Keep the NCAAF UI + standings backend isolated.** Maintain in
      this worktree: `pages/scores.tsx` (NCAAF in LEAGUE_PRIORITY, LEAGUES filter,
      All-view fetch), `components/Player/LeagueGameLog.tsx` (ncaaf columns),
      `components/Leagues/hooks/useLeagueRouteState.ts` (ncaaf tab-set = standings +
      schedule only), `backend/espn_client.py` (`ncaaf_conference_standings` +
      `_parse_record`), `backend/routers/games.py` (ncaaf/mls group routing),
      `backend/test_leagues_hub_assertions.py` (checks 6–8). Depends on T0.
      *Acceptance:* `git diff --stat` identifies the task-owned files; the
      `:8110` backend serves `/api/ncaaf/standings` as `{group, rows}[]`
      with ≥8 conferences and football-only columns; `test_leagues_hub_assertions.py`
      checks [6][7][8] all PASS.
      **ISOLATED 2026-08-11 after session 3's pre-isolation staging.** Task-owned
      variants were deliberately reconciled into this worktree. For the three divergent
      files (`espn_client.py`, `routers/games.py`, and `pages/scores.tsx`), the fuller
      variants were retained because each preserved LCUP/EWC/live-game behavior plus the
      NCAAF hunks. The verified snapshot preserves both pre-reconciliation versions.
      Another checkout was restored one path at a time and must not be used as a
      destination again. Worktree content: `pages/scores.tsx` (NCAAF in
      priority+filter+All-view),
      `components/Player/LeagueGameLog.tsx` (ncaaf cols), `backend/espn_client.py`
      (`ncaaf_conference_standings`+`_parse_record`), `backend/routers/games.py`
      (ncaaf/mls branches), `backend/test_leagues_hub_assertions.py` (checks 6–8).
      `useLeagueRouteState.ts` needed NO change (already had ncaaf). Verified via mock
      (ncaaf shape, empty-conf skip, football-only cols, ranks 1..N, `_parse_record`
      edges, get_standings dispatch ncaaf→conf / mls→group / nba→strength) — ALL PASS;
      route wired (log: `/api/ncaaf/standings` went 404→500 as the new function executes).
      BLOCKED items: live `/api/ncaaf/standings` render (host `site.web.api.espn.com` 403s
      this box now — concurrent agents ingesting; environmental, not a code defect), full
      `test_leagues_hub_assertions.py` run (check [1] hits walled `site.api.espn.com` and
      aborts at collection), frontend direct build/tsc (not run — Mem available 596 Mi,
      below the §12 threshold). Next: T2 browser-verify live once the host un-walls.
- [~] [IN_PROGRESS] **T2 — Browser-verify the isolated stack, all five surfaces.** Open
      `:3110` surfaces: `/scores` (NCAAF filter + All view), `/leagues/ncaaf`
      (standings tables + schedule tab + Stats tab correctly absent),
      game detail for an ncaaf game, `/player/<id>` game log (12-row vs 1-row vs empty
      all render distinctly), team-stats surface. Note payload sizes. Depends on T1.
      *Acceptance:* each surface renders real data with no `pageerror`s in console;
      empty/absent states are honest; mobile table scrolls, does not degrade to
      key-value pairs.
      **PARTIAL 2026-08-11 (session 4) — historical pre-isolation evidence, which does
      not substitute for this stack's acceptance.** The following behavior was observed
      with zero `pageerror`s before isolation:
      (a) `/api/ncaaf/standings` now 200 — 10 conferences, football-only cols, ranks 1..N
      (the T1 live-render rung that was BLOCKED in session 3 now PASS); (b) `/scores` NCAAF
      in filter + honest empty "No games scheduled" for Aug 11 (pre-season); (c)
      `/leagues/ncaaf` 10 conference tables render + schedule tab honest empty + Stats tab
      correctly absent; (d) player game logs 12-row (33336 Joker Johnson) / 1-row (33256
      Drew Nicolson) / empty (33230 Madoski) all render distinctly with table columns and
      dashes. BLOCKED: schedule populated-Saturday render (games endpoint → walled ESPN
      scoreboard → 500) and game-detail final score. FINDINGS: (1) game detail
      `/game/ncaaf/401752665` shows "SCHEDULED"/empty for a completed 2025 game (FSU 31-17
      in DB) — `get_game_detail` reads `game_context`(0 ncaaf)/`team_game_stats`(basketball
      cols)/`scoring_plays`(0), NEVER `team_game_results`, and `state` comes from walled
      ESPN → request.md's [x] "game detail data-backed via team_game_results" is NOT
      supported by the render path; (2) team-stats surface NOT reachable for ncaaf in the
      UI (`/stats` LEAGUES excludes ncaaf; `get_team_stats` rejects ncaaf as nba/nhl/nfl
      only) despite `/api/ncaaf/team-aggregates` returning `supported:True` — the plan's
      "last unverified piece" is confirmed NOT surfaced, not merely unverified. These
      findings need an authorized task (game-detail fix touches `backend/_core.py` /
      `_read_game_detail_from_db`, which the constraints forbid me to edit).
- [~] [IN_PROGRESS] **T3 — Close the ncaaf props/stats data gap (the one NOT-done surface).**
      Establish a season-aggregate and/or props acquisition source for ncaaf so the
      /props surface answers. Follow `published-first` (rung 5: a definition is always
      published somewhere — do not infer), `espn-request-budget`, and `resource-check`.
      Resolve player identity against the existing spine (CFBD athlete ids are spine
      espn_ids — direct join). Populate `player_stats` (season aggregate) for ncaaf and
      land props. Depends on T0. *Acceptance:* `SELECT count(*) FROM player_stats WHERE
      league='ncaaf'` > 0 with correct season key (2025); props join to ncaaf players >
      0; reconcile totals still exit 0; no dup players (resolve-or-queue, never DUP).
      **STATS HALF IN PROGRESS (session 5):** CFBD publishes per-player ncaaf stats
      per-game only (`/games/players`, already in `player_game_logs`); no per-player
      season endpoint exists (`/player/season` 404, `/stats/game` 404, `/stats/season`
      = team-level). So the season aggregate is a rollup of CFBD's own per-game values
      (published-first rung 4). Gate MANIFEST already declares the CFBD-keyed required
      columns. Added: `migrate_ncaaf_season_columns.py` (adds att/pass_yds/intc/
      rush_yds/rec/rec_yds to player_stats), `league_stats.py` ncaaf season contract +
      `cfbd` source ownership, `ingest_ncaaf_season_stats.py` (rollup). Verified on a
      /tmp dev-DB copy (never prod). Props half still needs a live source decision.
      **RE-VERIFIED 2026-08-11 (Hermes, on a fresh canonical-dev-DB copy at
      /tmp/picks.verify-t3-20260811.db):** migration added the 6 columns; ingest
      published **4267 player_stats rows** (all source=cfbd, all unique player_ids,
      season=2025, stat_type=season); gate flip on the copy: `A/required-stats[season]`
      FAIL→PASS (9 stats, 4267 rows) and `D/leaders-reach-logs` FAIL→PASS (4267/4267 =
      100%). COV-identity's invalid_stat_types/unowned_sources=4267 on that copy is a
      TREE artifact, not a data defect: the gate imports `league_stats` from the main
      checkout (hardcoded sys.path), whose copy has no ncaaf entry — the worktree
      contract (`canonical_stat_type('ncaaf','season')` → season,
      `source_owns_stats('ncaaf','season',2025,'cfbd')` → True) passes directly.
      COV-identity goes green for ncaaf when the league_stats change lands in main.
      NOT YET APPLIED to the canonical dev DB (0 rows there still) — applying the
      verified migration+ingest to the canonical dev DB is the smallest remaining
      data step; it needs explicit authorization per the isolation handoff.
- [ ] [TODO] **T4 — Run the league gates on the isolated stack and record every red item.**
      Ensure `audit_league_stats.py` MANIFEST is the newer coverage-floor copy
      (dict-form `position_content` + per-key `key_coverage`, incl. ncaaf DB/CB/S
      `def_int: 0.05`) — update this worktree's ncaaf MANIFEST entry in place; never
      replace the file wholesale (that could regress the coverage-floor machinery for
      every league). Set the three isolated `LP_GATE_*` values above, then
      `verify-gates.sh COV-ncaaf` (expect PASS) and
      `verify-gates.sh COV-statset` (expect the documented pre-existing red list —
      name each ncaaf item in writing). Depends on T2/T3.
      *Acceptance:* COV-ncaaf PASS with evidence; every COV-statset red item for ncaaf
      named in the report; the `def_int` expectation matches CFBD's honest-zero
      omission.
- [ ] [TODO] **T5 — Full verification sweep.** `reconcile_totals.py --league ncaaf
      --season 2025` (exit 0, output pasted), `python -m pytest backend/ -q` (whole
      suite; expect ~708 passed / 20 skipped / 2 deselected with the two known
      pre-existing exceptions named), frontend jest, and the direct worktree Next
      binary build. Never invoke npm/npx/yarn. Depends on T1–T4.
      *Acceptance:* every command's exit code and summary captured; any non-zero exit
      traced to a named pre-existing cause, not hand-waved.
- [ ] [TODO] **T6 — Update docs & final report.** Update `docs/LEAGUE-STAT-GAPS.md` and
      the TASK status section; write the session journal and result envelope per the
      Ralph contract. Depends on T5.
      *Acceptance:* docs reflect verified state; `.ralph/history/session-*.md` and
      `.ralph/results/session-*.json` are current.

### Optional (propose in report, do not fold in)
- Per-play EPA, receiving C/ATT, rushing LONG, special teams, playing-time qualifier for
  ncaaf stats (documented gaps — not required for the five done-surfaces).
- A Stats tab for ncaaf once a leaders backend exists (currently intentionally hidden —
  dead-surface rule; a 404 surface is worse than an absent one).

### Out of scope (never touch)
- MLS is on the same branch but is **not** part of this request; do not expand scope
  into MLS work beyond what the shared standings routing already does.
- World Cup, esports, and any NFL-specific surfaces.
- Prod promotion — that is a separate, explicit, authorized step after this feature is
  done and verified on the isolated development stack.

# Verification

Run the ladder per task. Commands and expected evidence:
- `git status` / `git diff --stat dev` — change-surface truth.
- `python -m pytest backend/test_coverage_gate.py -q` (22/22) and
  `python -m pytest backend/test_leagues_hub_assertions.py -q` (checks 6–8).
- `python -m pytest backend/ -q` — full suite.
- `/root/lp-league-mls-ncaaf/node_modules/.bin/jest components/Leagues` — frontend.
- `/root/lp-league-mls-ncaaf/node_modules/.bin/next build` — build (direct binary).
- `verify-gates.sh COV-ncaaf` / `COV-statset` — league gates (set all three
  `LP_GATE_*` vars).
- `reconcile_totals.py --league ncaaf --season 2025` — coverage, exit 0.
- Browser on isolated `:3110` surfaces backed by `:8110` — user-visible acceptance
  (the final rung, the one that actually decides done). Screenshots are deliverables.
- Independent truth check wherever possible: a score/record read from the DB must match
  an independent source, never re-read from the query that produced it (AGENTS.md §3).

Unavailable rungs (e.g. 375px viewport in headless browser) are reported as
limitations, not skipped — the mobile-width check is the overflow-x-auto scroll
container, not a resized screenshot.

# Current Status

Last verified (2026-08-11, isolation handoff):

- **FACT:** Branch `feat/league-mls-ncaaf`, HEAD `2d6ab86` "feat(leagues): add MLS and
  NCAAF data foundations". The complete dirty feature set and this plan live only in
  `/root/lp-league-mls-ncaaf`.
- **FACT:** The five task-owned files that had been staged elsewhere were reconciled
  into this worktree. For `backend/espn_client.py`, `backend/routers/games.py`, and
  `pages/scores.tsx`, the fuller variants were kept because they preserve the NCAAF
  changes plus LCUP/EWC/live-game behavior. The other two variants were byte-identical.
  Both original sets remain in the verified snapshot named by the isolation handoff.
- **FACT:** `/root/lp-league-mls-ncaaf/backend/data/picks.dev.db` is now a symlink to
  the canonical dev database. Read-only verification returned `PRAGMA quick_check=ok`,
  players=53,391, player_game_logs=232,669, and team_game_results=12,946. The displaced
  zero-byte stub is preserved at
  `/tmp/lp-league-mls-ncaaf-picks.dev.db-zero-byte-20260811T175000Z`.
- **FACT:** `SELECT count(*) FROM player_stats WHERE league='ncaaf'` was **0** and props
  joined to ncaaf players was **0** at the recorded baseline; the Props surface remains
  incomplete until T3 produces and verifies real acquisition data.
- **FACT:** ~139 CFBD calls, source stamped `cfbd`, 137/137 canonical FBS teams
  (230 with FCS buy-game opponents), 100% linked (CFBD athlete ids are spine espn_ids).
- **RESULT:** The worktree-only tmux session `ralph-stack` runs frontend `:3110` and
  backend `:8110`, logging to `next3110.log` and `backend/be8110.log`. Backend process
  environment contains the absolute worktree `LP_DB_PATH` and configured API keys.
- **RESULT:** `GET :8110/api/mlb/games?date=2026-08-11` returned 15 real games;
  `GET :8110/api/ncaaf/standings` returned 10 groups / 124 rows. Playwright rendered
  `:3110/scores` with title `Scoreboard — Legendary Picks` and no console, page, or
  request errors.

**Isolation status:** Ralph was cleanly interrupted after session 6. Resume only from
`/root/lp-league-mls-ncaaf`, and use only `:3110`/`:8110`.

# Next Recommended Task

**T4 — Run the league gates against only the isolated worktree stack.** Preserve the
existing T2/T3 findings as partial evidence, set all three `LP_GATE_*` values
explicitly, and do not inspect, edit, or control any other checkout or server. Then
continue with T5 and T6 in dependency order.
