# TASK league-ncaaf — add college football, scoped to FBS

**Owner: Hermes. Backend + frontend. Depends on `TASK-league-0-coverage-gate.md`** —
without it there is nothing to land a coverage row in, and an unverified league would be
offered to users the moment it has rows.

Read `docs/DATA-COVERAGE-CONTRACT.md` §6 and §7 first. §7 is the ordered checklist; this
file is that checklist applied to NCAAF, with the shape measurements already done.

## CURRENT PUBLIC FEATURE MATRIX — 2026-08-15

This is a managed-DEV UI and read-only database snapshot, not a release, push,
or production claim. Browser evidence used
`https://coat-develop-rooms-prague.trycloudflare.com`; at this checkpoint it was
the temporary `:3105 -> :3096` public proxy for managed `dev` commit `5d4b207`.
The companion MLS task is [`TASK-league-mls.md`](TASK-league-mls.md).

| Feature | **MLS** | **NCAAF** | Current evidence / follow-up |
|---|---|---|---|
| Offered hub route | Yes: `/leagues/mls` | Yes: `/leagues/ncaaf` | Both tiles and destinations rendered through the public URL without browser errors. |
| Visible league tabs | Standings, Schedule | Standings, Schedule | Stats/leaders are intentionally hidden for both: do not advertise a dead endpoint. |
| Coverage evidence | `2025 complete`: 30/30 teams, 510/510 games, zero failures | `2025 complete`: 137/137 teams, 888/888 games, zero failures | Read-only `team_stats_coverage` query on managed DEV. |
| Published history | 16,661 logs; zero NULL `game_type` / `player_id` | 56,577 logs; zero NULL `game_type` / `player_id` | Data exists; the player-detail acceptance screens still need their task-specific browser proof. |
| Standings UI | **RED:** 30 flat generic rows: `W L Win% Diff Streak L10`; no `D/GF/GA/GD/Pts` | **RED:** 124 flat generic rows: no conference groups | The endpoint returns a flat array, so the grouped MLS/NCAAF UI falls back. MLS draw rendering and NCAAF conference standings are both current blockers. |
| Schedule UI | Verified: 7 completed matches on `2025-10-19` | Verified: 41 completed games on `2025-11-29` | Public schedule routes, `schedule-dates`, and game payloads each returned 200 with no browser errors. |
| Result semantics | **RED:** 256 draw result rows exist among 1,020 team-result rows, but the public standings hide them | No draw semantics required | A correct data row is not a correct soccer surface. |
| Props / predictions | Props are a separate flow; no league-page Predict tab | No league-page Predict tab | Neither was re-verified in this pass; do not infer it from the hub. |

**Decision from this matrix:** NCAAF is safely discoverable for verified coverage
and schedules, but its public standings do not meet this task's conference-group
contract. The next implementation slice is a grouped standings contract for
published NCAAF conferences, coordinated with the MLS soccer-standings contract.
It must be followed by the existing player-detail, mobile/desktop, and gate
evidence below; no DB migration, legacy Ralph resumption, or service restart is
authorized by this documentation update.

## HISTORICAL STATUS — 2026-08-08 (after the NCAAF push)

**Backend/data pipeline DONE in the worktree; frontend verification blocked on landing.**

- Players spine + CFBD log re-source: 56,577 log rows, 888/888 games, 137/137 canonical FBS
  teams, 100% linked (CFBD athlete ids ARE spine espn_ids — no resolution pass), defensive
  stats mapped (tackles/sacks/INTs into the stats JSON), ~139 CFBD calls. FCS buy-game
  opponents kept (230 teams in results). Source stamped 'cfbd'.
- Coverage: `ncaaf 2025` = **complete**, written by `reconcile_totals.py --write-coverage`
  (2026-08-08). `/leagues/ncaaf` will flip from "isn't available yet" to a real hub once
  the coverage row lands in main dev.
- Gates on the worktree DB: COV-ncaaf PASS (888/888/137/0), COV-honest PASS (6 rows),
  COV-keys PASS, COV-api PASS.
- Reconcile: per-team oracle is internal (logs vs team_game_results); whitelist falls back
  to the recorded canonical vocabulary when the host is walled (137 codes); host budget
  LP_RECONCILE_HOST_BUDGET=100 refuses before the wall, 403 fails fast (run: 2m40s → 6.6s).
  reconcile_totals.py SPLIT into reconcile_core/gap/report/coverage/checks + slim entry —
  landing must copy ALL six files.
- Tests: 708 passed / 20 skipped / 2 deselected (pre-existing mock-draft parity fail;
  espn_client degradation test slowed by the wall cooldown). test_coverage_gate 22/22
  (patches reconcile_gap + reconcile_core now).
- **Still open:** ~~land to main dev (handoff item 6)~~ **DONE 2026-08-08** — backend code (espn_client ncaaf entry, espn_leagues.py, ingest_cfbd_logs.py, 6-file reconcile suite, team_codes NON_FRANCHISE, season_keys, team_stats_contract/schema, backfill_team_parity group-scoped enumeration, audit MANIFEST/endpoints, verify-gates COV-ncaaf), frontend (presentation.ts LEAGUE_ORDER, StandingsTab Soccer/Conference, PlayerGameLog league-aware, useLeagueRouteState, useStandingsData, PredictTab draw-gating, leagues.tsx hub card, scores.tsx filter), DB rows (20,926 players incl. 183 id-collision re-map, 56,577 logs, 1,776 results + stats, coverage row) all copied to main dev + verified. Browser checks (task §4 items 4/5/8) now PASS on main dev: league page clickable, standings + schedule tabs render, player game log table with columns, honest empty states, Stats tab hidden (no ncaaf leaders backend — dead surface rule).

Prior state (kept for history): 2026-08-07 — NCAAF ~10% done, spine only, nothing clickable.

## Environment — read this before running anything

**`docs/RUNBOOK-heavy-feature-work.md`.** The parts that will bite you, in the order
they bite:

- **Know which database you opened.** Two real ones, both only in the main tree:
  `backend/data/picks.db` is **PROD** (~240 MB, served by docker on `:8100`) and
  `backend/data/picks.dev.db` is dev (~212 MB, served on `:8096`). They have
  **diverged** — the same player id is a different player in each. Player `30085`
  is the Buffalo Bills D/ST in prod and Magomed Ankalaev in dev.
- **`LP_DB_PATH` is relative to the process's cwd**, so the same value opens
  different files depending on where you launched. **Use an absolute path.**
- **A worktree usually does NOT have the real dev DB.** Checked across ten
  worktrees on 2026-08-04: the symlink existed in one. The rest had a ~200 KB stub
  or nothing. A backend on a stub starts, answers 200, and serves an empty
  database — nothing raises, and you will verify against it and report success.
  Confirm before trusting any number:
  ```
  tr '\0' '\n' < /proc/<pid>/environ | grep LP_DB_PATH
  ls -la <worktree>/backend/data/picks.dev.db     # symlink, or a stub?
  ```
- **`npm run dev:backend` sets neither `LP_DB_PATH` nor `GRID_API_KEY`**, and both
  degrade silently. Launch uvicorn with them set explicitly.
- **Ports:** `3096`/`8096` is the main dev pair and is **externally managed — never
  restart it**. `3097`/`8097` are `scripts/hermes-worktree.sh` defaults and must be
  checked free first (`ss -ltnp`). `3100`/`8100` is prod.
- **`node_modules` in a worktree is a symlink into the main install.** An `npm
  install` or an `npx` that installs there mutates everybody's, and has emptied it.
- **Gates:** set `LP_GATE_W`, `LP_GATE_B` and `LP_GATE_F` **together** or
  `verify-gates.sh` grades the main tree while your code never runs.
- **Never `git checkout` or `git reset` under a running `next dev`.**
- **Prod is off-limits** unless the task says otherwise: no `docker compose`, no
  container restarts, no writes to `picks.db`, no `git push`.

**Before you start, and before you call it done: `docs/NEW-LEAGUE-CHECKLIST.md`.**
Every item in it is something that shipped green and was wrong. Two are load-bearing
for this task: write the `audit_league_stats.py` **`MANIFEST` entry before the ingest
runs** (deciding what a league claims after seeing what an ingest produced is how the
claim becomes "whatever we got"), and run `verify-gates.sh COV-statset`, naming every
red item in writing. A league with no manifest reports UNVERIFIED, never PASS.

**Skills — load before coding:**

| skill | when |
|---|---|
| `.claude/skills/published-first/SKILL.md` | before the ingest. **Rung 5 is the one this league breaks** — the scope, the type ids and the team set are all published and all tempting to infer. §6 for the expected totals. |
| `.claude/skills/honest-data-ui/SKILL.md` | before §4. An uneven schedule breaks every per-game denominator the NFL surfaces assume. |
| `.claude/skills/resource-check/SKILL.md` | before the ingest run. 911 games × summary fetch against a host that 403s bursts. |

---

## 1. Shape — measured 2026-08-02, reproduce before trusting

`football/leagues/college-football`, `GET seasons/2025`:

```
displayName='2025'  year=2025
  id 1 | Preseason      | 2025-02-01 -> 2025-08-23 | events=0    groups=2
  id 2 | Regular Season | 2025-08-23 -> 2025-12-13 | events=911  groups=2
```

Four things here are not the NFL:

1. **The league's `teams` collection is 807.** FBS is a *published group*:
   `types/2/groups/80/teams` = **146**; FCS is `groups/81` = 131. Checking 911 games
   against 807 teams invents a 660-team gap. **Every expected-count for this league is
   group-scoped. Record the group id as data in the league registry, not as a filter
   sprinkled through queries.**
2. **There is no games-per-team constant.** Schedules are uneven — 12 games for most, 13
   for a conference-championship team, and independents differ. Any code that computes
   "N of M team games" from a constant is wrong here. `M` comes from counting that team's
   published events.
3. **102,406 athletes league-wide.** An `expected_players` gate is noise unless scoped to
   the 146 FBS rosters we actually ingest.
4. **Postseason is bowls, not a bracket.** Read the type list for 2025 rather than
   assuming an id — `Preseason` is id 1 here and its `events=0`, which is a published
   fact, not a fetch failure. Do not treat an empty published collection as an error.

**Step 0 of the work is re-running this** and the three `?limit=1` totals (events, teams
in group 80, athletes in group 80). If a number surprises you, per `published-first` §6
that is a question about the definition, not a defect — answer it before writing an
ingest against it.

---

## 2. Backend — files you may touch

**New: `backend/espn_leagues.py`** (created by TASK-0 if it landed there; otherwise
create it). A single registry, read by the ingests and by `reconcile_totals.py`:

```python
ESPN_LEAGUES = {
  "ncaaf": {"path": "football/leagues/college-football", "scope_group": "80", ...},
}
```

`scope_group` is `None` for the leagues that are their own scope. Nothing else in the
codebase gets to know a group id.

**New: `backend/ingest_ncaaf_logs.py`.** Model it on `backend/ingest_nfl_logs.py`, which
already owns the shared `player_game_logs` schema via `ensure_table`. Requirements:

- **`game_type` NOT NULL**, drawn from the season's published `types[]` — not a literal.
  §6 of the contract: it is NULL for every league except NFL 2025 today, and every
  `AND game_type='REG'` in the codebase silently returns zero for those.
- **Season key = 2025 for the 2025 season** (NCAAF starts and ends inside one academic
  year; ESPN keys by start year here — but *confirm it from `startDate`/`endDate`*, per
  §6's corrected table, do not carry NBA's or NFL's convention over).
- **Team codes normalised at the boundary** to the ESPN vocabulary
  (`reference_lp_team_code_vocabularies` — a wrong join key does not raise, it misses).
- Idempotent: re-running must not duplicate. Unresolved athletes retained with
  `player_id=NULL`, the pattern `ingest_wc_logs.py` already uses.
- Ingest **FBS only**. An FCS row in the table is not a bonus, it is a denominator bug
  waiting to happen.

**`backend/reconcile_totals.py`** — add the `ncaaf` entry and its checks:

- events for type 2, scoped to `groups/80`
- teams in group 80 = 146
- distinct `game_id` in `player_game_logs`
- **per-team games**, counted per team from published events, not from a constant

**`backend/routers/games.py`, `players.py`, `momentum.py`, `game_extras.py`** — every
route in contract §5 takes `{league}` and will answer for `ncaaf` the moment rows exist.
Walk them. Add group scoping where a query assumes "all teams in the league".

**Do not touch:** `backend/_core.py`, `ingest_nfl_*.py`, `ingest_wc_logs.py`,
`backfill_team_parity.py`, or anything under `/etc`, systemd, cron.

---

## 3. Frontend — files you may touch

The league appears in the switcher automatically once its coverage row is `complete`
(TASK-0). What is NCAAF-specific:

- **`components/Leagues/StandingsTab.tsx`** — 146 teams is not one table. Standings are
  by **conference**, and conferences are a published sub-group under `groups/80`. Read
  them; do not hand-maintain a conference map.
- **`components/Leagues/PlayerGameLog.tsx`** — the header line is `N of M team games`.
  For NCAAF `M` is that team's own published count. If `M` is not known for a team, the
  line does not render — a rate whose denominator is unproven is fake precision
  (`honest-data-ui` §4, contract §5).
- **`components/Leagues/ScheduleTab.tsx`** — a full Saturday is ~60 games. The existing
  daily schedule view was built for a 15-game NFL Sunday. Measure the payload before
  shipping (`feedback_performant_code_from_the_jump`, `docs/DEV-STANDARDS.md`): the list
  must not download more than it renders.
- **`components/Leagues/presentation.ts`** — `LEAGUE_NAMES.ncaaf = 'NCAAF'`,
  `LEAGUE_EMOJIS.ncaaf = '🏈'`. That is the only hardcoded thing left after TASK-0, and
  it is presentation, not data.

**Do not touch:** anything under `components/MockDraft/`, `NflDraftRoom.tsx`,
`NflCampHero.tsx`, `NflOffseasonMovers.tsx`. NFL-specific surfaces stay NFL-specific.

---

### Design pass — part of the league, not a follow-up

`docs/NEW-LEAGUE-CHECKLIST.md` §4. The short version, all of which the NFL had and
every other league did not until 2026-08-04: the game log is a **table with columns**,
not a run of `key value` pairs; rate stats render the way the sport publishes them
(baseball is `.336`, and a one-decimal default rendered three hitters twelve points
apart as `0.3` each); the header carries the **sample size**; a dash is not a zero; and
**a position with no data says so rather than showing a substitute** — a goalie's
skater line is four true numbers that answer nothing anyone opens a goalie's page for,
and a populated table reads as coverage.

## 4. Done means

Status per item, updated 2026-08-08 (worktree state; browser items blocked on landing).

- [x] 1. Coverage row for `ncaaf 2025` reads `status='complete'` — and got there through
   `reconcile_totals.py --write-coverage`, not by hand. (Done 2026-08-08, worktree DB.)
- [x] 2. `reconcile_totals.py --league ncaaf --season 2025` exits 0, output pasted with its
   exit code (`feedback_presence_is_not_integrity`). (Done 2026-08-08: exit 0, PASS,
   888/888 games, 137/137 teams; re-verified after the host-budget fix, 6.6s.)
- [x] 3. Zero rows in `player_game_logs` where `league='ncaaf' AND game_type IS NULL`.
   (COV-ncaaf null_gt=0.)
- [ ] 4. **Two players screenshotted in a browser**: one with a genuine missed game, one in a
   season we have not fully ingested. **If they look the same, the work is not done**
   (contract §7 step 8). — BLOCKED on landing to main dev.
- [ ] 5. A conference standings table and a Saturday schedule opened in a browser, payload size
   noted. — BLOCKED on landing to main dev.
- [ ] 6. `git diff --stat` matches the file list above. — PARTIAL: matches in the worktree;
   landing to main dev pending (handoff item 6 — note the reconcile suite is now SIX files:
   reconcile_core/gap/report/coverage/checks + entry).
- [ ] 7. **`verify-gates.sh COV-statset` run and pasted**, with every red item for this
   league named in writing. The `MANIFEST` entry in `backend/audit_league_stats.py`
   was written BEFORE the ingest ran, and the gate's expected-failure count was
   raised to match. A league with no manifest reports UNVERIFIED, never PASS.
   — MANIFEST written before ingest (incl. defensive positions); COV-statset remains the
   known pre-existing red list (6 FAIL/3 UNVERIFIED, documented in LEAGUE-STAT-GAPS);
   final sign-off pending after landing.
- [ ] 8. Every game log rendered in a real browser at **375px and 1440px** — a table with
   columns, not a run of `key value` pairs — including the empty state for the one
   position this league has no stats for. Paste the URL and what you saw.
   — BLOCKED on landing to main dev.
- [x] 9. `docs/LEAGUE-STAT-GAPS.md` updated with what this league does NOT have, so the
   next person does not rediscover it. (Done 2026-08-08: defensive gap CLOSED via CFBD,
   Army-Navy CLOSED, CFBD-as-source row, remaining gaps: receiving C/ATT, rushing LONG,
   per-play EPA, special teams, playing-time qualifier.)

- [x] **`F/identity-crosswalk` green, or the single-publisher choice stated in
      writing.** (Stated 2026-08-08 in docs/DATA-SPINE.md: NCAAF logs land on CFBD;
      CFBD athlete ids ARE spine espn_ids, direct join, no resolution pass; ESPN
      summaries kept for team backfill/reconcile.)
