# TASK league-mls — add MLS, and build the soccer scaffolding EPL will reuse

**Owner: Hermes. Backend + frontend. Depends on `TASK-league-0-coverage-gate.md`.**
**Do this before `TASK-league-epl.md`** — MLS has a calendar-year season and no
relegation, so it isolates the soccer-shape work from the season-key and roster-churn
work. EPL then adds exactly those two things to a scaffold that already works.

Read `docs/DATA-COVERAGE-CONTRACT.md` §6 and §7 first.

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
| `.claude/skills/published-first/SKILL.md` | before the ingest. §5 rung 5 — the existing soccer ingest infers the season key from a date string, which is precisely what this task must not copy. |
| `.claude/skills/honest-data-ui/SKILL.md` | before §4. Soccer has draws, and every win-rate surface in this repo was written for a sport that does not. |
| `.claude/skills/resource-check/SKILL.md` | before the ingest run. |

---

## 1. Shape

`soccer/leagues/usa.1`, **31 seasons published** (measured 2026-08-02).

**Step 0, and it is not optional:** the type list and event counts below are measured;
the per-season **team** and **athlete** totals are not — ESPN rate-limited the sweep.
Get them yourself before writing anything:

```bash
# events, teams, athletes — one request each
GET .../soccer/leagues/usa.1/seasons/<year>                 # types[], displayName
GET .../soccer/leagues/usa.1/seasons/<year>/types/<id>/events?limit=1
GET .../soccer/leagues/usa.1/seasons/<year>/types/<id>/teams?limit=1
```

Pace them. ESPN 403s a burst with no `Retry-After` and the block outlives a short
backoff; `reconcile_totals.py:_get_json` already has the pacing and cache — use it rather
than writing a fresh fetch loop.

What **is** measured (2026-08-02), and what makes MLS not the NFL:

1. **MLS publishes SEVEN season types, and their ids are not contiguous.**
   `soccer/leagues/usa.1/seasons/2025`:

   ```
   id  0 | Combined                                  | events=0
   id  1 | Regular Season                            | events=510   <- the season
   id  2 | All-Star Game                             | events=1
   id  3 | Eastern Conference Playoffs - Wild Card    | events=1
   id  4 | Western Conference Playoffs - Wild Card    | events=1
   id  8 | Eastern Conference Playoffs - Round One    | events=3
   id 12 | Western Conference Playoffs - Round One    | events=3
   ```

   Three assumptions die here, and the doc's own note that MLS has "one season type"
   was **wrong** — it generalised from EPL:
   - the regular season is id **1**, not 2;
   - `for t in range(1, 6)` misses ids 8 and 12 entirely — **iterate the published
     list, never a range**;
   - `id 0 "Combined"` publishes 0 events. An empty published collection is a fact,
     not a fetch failure. Do not treat it as an error and do not skip it silently.

   **MLS files its All-Star Game as its own type (id 2).** NBA files All-Star *inside*
   the regular-season type. Two leagues, two answers, neither derivable — which is
   exactly why `explain_gap()` in `reconcile_totals.py` classifies each event from
   `competitions[].type.abbreviation` rather than trusting a type id.
2. **Draws.** `team_game_results.win` is `INTEGER` — a 0/1 flag. A draw is neither.
   Storing a draw as a loss silently corrupts every win-rate, streak and momentum
   surface. See §2.
3. **Calendar-year season**, so the key reads naturally — but confirm it from
   `startDate`/`endDate` per contract §6's corrected table. There is no league-wide ESPN
   convention: NBA and NHL key by the year the season *ends*.
4. **ESPN publishes the label.** `displayName` comes back on the season document. Copy
   it; never compose "2025 MLS" client-side.

---

## 2. Backend — files you may touch

**`backend/espn_leagues.py`** — add `mls: {"path": "soccer/leagues/usa.1", ...}` with the
type ids you measured. Data, not assumptions.

**New: `backend/ingest_soccer_logs.py`** — the shared soccer ingest, MLS first, EPL
second. Start from `backend/ingest_wc_logs.py`, which already handles ESPN's soccer
summary shape (`_roster_players`, "the current WC shape") and the goals / assists /
shots / shots-on-target stat mapping. **Three things in it must not be carried over:**

- `season = int(game_date[:4])` — the season key **inferred from a date string**. It
  happens to work for the World Cup and for MLS, and it is wrong for EPL, where a match
  played in January 2026 belongs to season `2025`. Take the season from the type's
  published `startDate`/`endDate` range instead. Fix it here, once, so EPL inherits a
  correct one.
- No `game_type` is written — all 3,222 `wc` rows are NULL. **NOT NULL, from the
  published `types[]`.**
- It enumerates by date window (`--start/--end`). Enumerate by season type instead, so
  the set of matches ingested is the set the publisher says exists and the reconcile has
  something to compare against.

Whether to migrate the existing `wc` rows onto this ingest is **out of scope** — note it,
do not do it.

**`backend/team_stats_schema.py` + `backend/backfill_team_parity.py`** — the draw
problem. `win INTEGER` must become a three-valued result. Preferred: add
`result TEXT CHECK(result IN ('W','D','L'))`, keep `win` as a generated/derived read for
existing callers, and make the soccer path write `result`. **Whatever you choose, a draw
must not be storable as a loss.** Grep for every reader of `.win` before you change it —
`compute_momentum.py`, `team_stats_contract.py`, `routers/momentum.py` at minimum — and
list them in the PR body.

**`backend/reconcile_totals.py`** — add `mls` and its checks: events for the published
type(s), teams, distinct `game_id` in `player_game_logs`. `check_generic()` already
handles a single-type league; verify that path actually runs for MLS rather than assuming
it (it was written against EPL's shape, untested on `usa.1`).

**Do not touch:** `ingest_nfl_*.py`, `ingest_ncaaf_logs.py`, `espn_client.py`,
`sports_service.py`, `/etc`, systemd, cron.

---

## 3. Frontend — files you may touch

- **`components/Leagues/StandingsTab.tsx`** — soccer standings are **P W D L GF GA GD
  Pts**, not W-L and not a win percentage. Points are published; do not compute them from
  a 3/1/0 rule you assume. MLS has Eastern and Western conferences — published, read them.
- **`components/Leagues/PlayerGameLog.tsx`** — the per-match stat line is goals /
  assists / shots / SOT, not the NFL columns. A substitute appearance is a **played** row,
  not an absence; minutes played is the honest denominator and must be shown
  (`honest-data-ui` §4 — sample size always visible).
- **`components/Leagues/PredictTab.tsx` and `components/Props/*`** — a two-outcome
  prediction surface is wrong for a sport with draws. Either add the third outcome or
  suppress the surface for `mls`; **do not ship a binary control over a ternary
  result.**
- **`components/Leagues/presentation.ts`** — `LEAGUE_NAMES.mls = 'MLS'`,
  `LEAGUE_EMOJIS.mls = '⚽'`.
- **`components/Leagues/hooks/useLeagueRouteState.ts`** — `validTabs` for a soccer league.
  There is already a soccer branch here (`isWorldCup`); extend the concept to
  "is a soccer league" rather than adding a second special case beside it.

**Do not touch:** `components/MockDraft/*`, `NflDraftRoom.tsx`, `NflCampHero.tsx`,
`NflScheduleTab.tsx`, `NflUsageTrend.tsx`.

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

1. Coverage row for `mls <season>` = `complete`, written by
   `reconcile_totals.py --write-coverage`.
2. `reconcile_totals.py --league mls` exits 0; output and exit code pasted.
3. Zero `mls` rows with NULL `game_type`.
4. **A drawn match** located in the data and shown to render as a draw on the standings
   table, the game log and momentum — screenshot. This is the specific thing that will
   silently be wrong.
5. The two-player absence screenshot from contract §7 step 8.
6. `git diff --stat` matches the file list above.
7. **`verify-gates.sh COV-statset` run and pasted**, with every red item for this
   league named in writing. The `MANIFEST` entry in `backend/audit_league_stats.py`
   was written BEFORE the ingest ran, and the gate's expected-failure count was
   raised to match. A league with no manifest reports UNVERIFIED, never PASS.
8. Every game log rendered in a real browser at **375px and 1440px** — a table with
   columns, not a run of `key value` pairs — including the empty state for the one
   position this league has no stats for. Paste the URL and what you saw.
9. `docs/LEAGUE-STAT-GAPS.md` updated with what this league does NOT have, so the
   next person does not rediscover it.

