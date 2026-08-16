# TASK league-mls — add MLS, and build the soccer scaffolding EPL will reuse

**Owner: Hermes. Backend + frontend. Depends on `TASK-league-0-coverage-gate.md`.**
**Do this before `TASK-league-epl.md`** — MLS has a calendar-year season and no
relegation, so it isolates the soccer-shape work from the season-key and roster-churn
work. EPL then adds exactly those two things to a scaffold that already works.

Read `docs/DATA-COVERAGE-CONTRACT.md` §6 and §7 first.

## CURRENT PUBLIC FEATURE MATRIX — 2026-08-15

This is a managed-DEV UI and read-only database snapshot, not a release, push,
or production claim. Browser evidence used
`https://coat-develop-rooms-prague.trycloudflare.com`; at this checkpoint it was
the temporary `:3105 -> :3096` public proxy for managed `dev` commit `5d4b207`.
The companion NCAAF task is [`TASK-league-ncaaf.md`](TASK-league-ncaaf.md).

| Feature | **MLS** | **NCAAF** | Current evidence / follow-up |
|---|---|---|---|
| Offered hub route | Yes: `/leagues/mls` | Yes: `/leagues/ncaaf` | Both tiles and destinations rendered through the public URL without browser errors. |
| Visible league tabs | Standings, Schedule | Standings, Schedule | Stats/leaders are intentionally hidden for both: do not advertise a dead endpoint. |
| Coverage evidence | `2025 complete`: 30/30 teams, 510/510 games, zero failures | `2025 complete`: 137/137 teams, 888/888 games, zero failures | Read-only `team_stats_coverage` query on managed DEV. |
| Published history | 16,661 logs; zero NULL `game_type` / `player_id` | 56,577 logs; zero NULL `game_type` / `player_id` | Data exists; the player-detail acceptance screens still need their task-specific browser proof. |
| Standings UI | **RED:** 30 flat generic rows: `W L Win% Diff Streak L10`; no `D/GF/GA/GD/Pts` | **RED:** 124 flat generic rows: no conference groups | The endpoint returns a flat array, so the grouped MLS/NCAAF UI falls back. This task's draw-rendering gate remains open; the companion task's conference-standings gate is not currently green. |
| Schedule UI | Verified: 7 completed matches on `2025-10-19` | Verified: 41 completed games on `2025-11-29` | Public schedule routes, `schedule-dates`, and game payloads each returned 200 with no browser errors. |
| Result semantics | **RED:** 256 draw result rows exist among 1,020 team-result rows, but the public standings hide them | No draw semantics required | A correct data row is not a correct soccer surface. Do not close MLS until a drawn match renders in standings, game log, and momentum. |
| Props / predictions | Props are a separate flow; no league-page Predict tab | No league-page Predict tab | Neither was re-verified in this pass; do not infer it from the hub. |

**Decision from this matrix:** MLS and NCAAF are safely discoverable for their
verified coverage and schedules, but neither standings implementation meets the
league-specific task contract. The next implementation slice is a grouped
standings contract: published MLS soccer fields (including draws) and published
NCAAF conference groups. It must be followed by the existing player-detail,
mobile/desktop, and gate evidence below; no DB migration or service restart is
authorized by this documentation update.

## HISTORICAL STATUS — 2026-08-07 (before NCAAF work resumes; MLS paused, not closed)
> **Superseded on the two standings rows, 2026-08-16.** The matrix above was written
> against `dev` before `feat/league-mls-ncaaf` landed. Both **RED** standings rows are
> now closed by the 08-13 work recorded immediately below — MLS renders P W D L GF GA
> GD Pts from `team_game_results`, and NCAAF renders ESPN's conference groups. Every
> other row in the matrix still stands as written.

## STATUS — 2026-08-13 (standings draws CLOSED and committed; league still not closed)

Branch `feat/league-mls-ncaaf` @ `/root/lp-league-mls-ncaaf`. **Committed to the
branch, NOT landed to main dev (`/root/legendarypicks`) and NOT pushed.**
The 08-07 status below is kept as written and is superseded on items #4, #6 and
#7 only — every other line in it still stands.

**#4 draw rendering — the standings half is DONE and independently verified.**
`/api/mls/standings` no longer calls live ESPN; `_mls_standings_from_db(season)`
aggregates the published per-game rows in `team_game_results` (P/W/D/L are counts
of the publisher's own `result` values, GF/GA sums of its own scores, GD = GF-GA,
Pts = 3W+D). `StandingsTab.tsx` renders P W D L GF GA GD Pts through an
`isSoccer` branch — mls was **not** bolted onto `isWorldCup`, so EPL extends the
branch without touching the WC path. Commit `98c60e1` (3 files); the unrelated
EWC/LCUP hunks that shared `games.py` went in first as `8988345` so the MLS
commit stayed clean.

Verified 08-13, not just claimed:
- DB: 1020 team-game rows / 30 teams / 510 games; 256 `result='D'` rows, every
  draw paired 2-per-game (128 drawn matches); every team P == W+D+L.
- **Reconciled against ESPN's published 2025 standings — 30/30 teams identical**
  on group, rank, P, W, D, L, GF, GA and Pts; zero disagreements. The raw
  unmodified publisher body is committed at
  `render-evidence/espn-mls-2025-standings-raw.json` (134,794 bytes, URL and
  fetch timestamp recorded in `REPORT-mls-draws.md` §3); re-shaped copies are
  labelled `-normalised-derivative.json` so the payload can't be confused with a
  derivative. Note the *bare* `/standings` endpoint serves the in-progress 2026
  season — `?season=2025` is the apples-to-apples comparison.
- Renders opened, not just captured: genuine 1440x900 and a true 375x812
  viewport, D column populated in both.
- Fail-loud both ways, and both directions exercised on a temp DB: `played !=
  W+D+L` 503s naming the team; a DB team set that differs from the recorded
  Eastern/Western frozensets 503s naming the unmapped/missing abbrevs. **Never a
  partial table with a 200.** The SQL is explicit (`season = ?` and
  `status='completed'`), season derived from the coverage record, not a literal.
- Conference split and display names are recorded vocabulary from ESPN's
  published standings payload (measured 08-12), because `team_game_results` has
  no conference or name column. The coverage assertion is what keeps that
  recorded list from silently dropping a club.

**#4 is NOT fully closed.** This item asks for a draw rendering correctly on the
standings table, **the game log AND momentum**. Only the standings surface was in
scope and only it has been done — the game-log and momentum draw surfaces are
untouched and unverified.

**#6 — now committed.** 8 commits on the branch (`git log 2d6ab86..HEAD`), one
per logical slice, no `venv` or logs, no AI attribution, author micahp.
Deliberately left dirty: pre-existing ncaaf/leagues work (`TASK-league-ncaaf.md`,
`esports_team_logos.json`, `useLeagueRouteState.ts`, `LeagueGameLog.tsx`,
`pages/leagues.tsx`, `pages/scores.tsx`), `RALPH-NCAAF-PLAN.md`, the context and
PRESERVE docs, logs and `venv`. Recorded in `REPORT-mls-draws.md` §10.

**#7 — partially answered.** A/required-stats[season] and D/leaders-reach-logs
flipped FAIL -> PASS, but **on the worktree DB copy, not canonical dev**. Still
red for mls, named: `C/vocabulary[position]` (two levels in one column, needs the
position_group split), `B/position-content[GK]` (GK saves published but
unmapped), `E/qualifier[season]`, `G/published-identity`.

Still open, unchanged: **#5** two-player absence screenshot; **#8** 375/1440
renders of the **game logs** (the standings renders do not satisfy this item);
**F/identity-crosswalk** single-publisher statement; result='D' not migrated on
the canonical dev DB; soccer-native team stat columns (shots_on_target,
possession, corners) still have no schema column.

**Next step and its hazard:** landing to `/root/legendarypicks`. Main has the
**newer** coverage-floor `audit_league_stats.py` — copy the mls/ncaaf MANIFEST
hunks *into* it. Copying this worktree's older file wholesale regresses the
coverage-floor machinery for every league. See `docs/PRESERVE-MLS-NCAAF-LANDING.md`.

## STATUS — 2026-08-07 (superseded on #4/#6/#7 by the 08-13 entry above)

**MLS is ~40-50% done by this task's own "Done means".** The data pipeline and
clickable surfaces all work on the main dev tree (feat/league-news-engine), but the
two task-critical items are still open. Everything below was re-verified 08-07
against the live dev DB (:8096) and browser (:3096).

DONE (verified):
- Coverage row `mls 2025` = complete (30/30 teams, 510/510 games, written by
  reconcile_totals --write-coverage 08-06). [Done #1]
- Zero `mls` rows with NULL game_type. [Done #3]
- docs/LEAGUE-STAT-GAPS.md exists (10.4 KB, 08-06). [Done #9]
- Team-stats backend works (added 08-07; was broken — contract lacked mls
  LEAGUE_CATEGORIES/_aggregate_rows branch, patched in BOTH trees).
- Props end-to-end (Bovada scraper, /api/props, /props filter, dev cron).

NOT DONE — do NOT claim this league closed without these:
- **#4 Draw rendering — THE gap.** 256 draws in team_game_results but
  /api/mls/standings returns W/L/win_pct with NO draws field, and the UI renders the
  generic TeamSportStandings (W L WIN%) for mls — the soccer P W D L GF GA GD Pts
  table (WorldCupGroups) only renders when isWorldCup=true. Draws are invisible
  everywhere. Fix = backend emit draws/GF/GA/GD/Pts for mls + frontend isSoccer
  branch (like isWorldCup). This is the item the task warns "will silently be
  wrong" and it IS wrong.
- #5 Two-player absence screenshot — not done.
- #6 git diff --stat vs file list — nothing committed (dirty working tree on
  feat/league-news-engine; Micah's git, his call).
- #7 verify-gates.sh COV-statset run+pasted — script exists, no run pasted.
- #8 375px/1440px browser renders pasted — not done.
- identity-crosswalk checkbox — unchecked, no single-publisher statement.

Other open: result='D' column not migrated on main dev DB; soccer-native team stat
columns (shots_on_target, possession, corners) have no schema column yet (documented
gap); nothing pushed.

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

- [ ] **`F/identity-crosswalk` green, or the single-publisher choice stated in
      writing.** More than one publisher reaching the same `players.id` row is
      what makes a league good — it is the only reason NFL has team, position,
      ranks, news and ADP and MLB has none of them. If this league will carry one
      publisher's id only, say so and say what that publisher does NOT print, so
      the gap is a decision instead of a discovery. See `docs/DATA-SPINE.md`.
