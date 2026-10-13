# Handoff: NFL forecasting model, 2026-10-11 (step-by-step for Sonnet or Haiku)

You are picking up a long session. This file is written so you can work without asking the
previous session anything. Follow it literally. Where it says STOP, stop and tell Micah.

## How to use this file (read first)

1. Read sections 0 to 3 fully before running anything. They are short and every line came from a
   real mistake.
2. Do the tasks in section 4 in order. Each task has: goal, files, exact steps, a test list, a
   real-data check, a definition of done, and pitfalls. Do not start a task until the previous
   one's definition of done is met and committed.
3. Save tokens. Every tool call re-sends the whole conversation, so many small calls are what burn
   Micah's limit, not long answers. Rules:
   - Batch: one Bash call that runs several commands beats five calls.
   - Never `cat` a big file. Use `grep -n` to find the part, then read only that range.
   - Never print whole test output. Pipe to `tail -5`. Pipe query output through `head`.
   - Do not re-read a file you just wrote.
   - Do not re-run a check that passed.
   - When a task is done, give Micah a 5-line report, not a summary of everything.
4. Never write a number you did not get from a command in this session. Never write a name, team
   or player that is not in the data. If unsure, say "not checked".

## 0. Hard rules (break one and you will damage something)

| Rule | Why |
|---|---|
| Work only in `/root/lp-nfl-lock-by-version` (branch `feat/nfl-model-foundation`). | `/root/legendarypicks` is the managed dev checkout; the live dev site and tunnel run from it and other agents have uncommitted work in it. |
| Never `git switch`, `git stash`, `git checkout -- <path>`, `git add -A`, `git push`, `git merge` into dev. | Shared repo; other sessions. Stage files by name. Merging and pushing need Micah. |
| Never run `npm`, `npx`, `yarn` anywhere. | A worktree npm run once deleted the shared `node_modules` and took the dev site down. Use `/root/legendarypicks/node_modules/.bin/tsc` and `.../jest`. |
| Never start, stop, kill or restart a dev server, a tmux competition loop, or a systemd unit/timer. | Externally managed. A timer change needs Micah's OK. |
| Dev DB only: `/root/legendarypicks/backend/data/picks.dev.db`. Never `picks.db` (prod). | Prod gets changes only through a release. |
| Always set `LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db`. | Without it, scripts in the worktree default to `backend/data/picks.dev.db` inside the worktree, which does not exist. Tests that need it silently SKIP. |
| Python is `/root/legendarypicks/backend/venv/bin/python` (3.8). | No `zoneinfo` in 3.8. Use `pytz` (installed). No `match`, no `X | Y` types without `from __future__ import annotations`. |
| No em dashes in anything you write (code comments, docs, commits, replies). | Micah's standing rule. Use commas, colons or periods. |
| No AI attribution in commits. Plain human messages: what changed and why. | Hooks enforce it. |
| Before any job that loops over seasons or plays: run `uptime; free -h`. If available RAM is under 1.5 GB, STOP. | 5.8 GB box shared with live sites. |
| Load the skills before code: `.claude/skills/published-first/SKILL.md`, `fail-loudly`, `falsify-before-merge`, `measurement-is-a-claim`; `honest-data-ui` before any UI; `resource-check` before batch work. Read only the "rules" sections if short on budget. | They encode the repo's past failures. |

## 1. Commands you will use (copy exactly)

```bash
# variables used below
WT=/root/lp-nfl-lock-by-version
PY=/root/legendarypicks/backend/venv/bin/python
DB=/root/legendarypicks/backend/data/picks.dev.db
HIST=/root/nfl-v1-rehearsal.d0IcMW/nflverse_2010_2023

# all NFL backend tests (baseline 10-11: 421 passed, 1 skipped)
cd $WT/backend && LP_DB_PATH=$DB $PY -m pytest -q $(ls test_nfl*.py test_*nfl*.py | sort -u) 2>&1 | tail -3

# one test file
cd $WT/backend && LP_DB_PATH=$DB $PY -m pytest -q test_nfl_seeding.py 2>&1 | tail -15

# frontend checks (baseline: 19 suites, 89 tests; tsc: no errors in changed files)
cd $WT && /root/legendarypicks/node_modules/.bin/jest components/Leagues pages 2>&1 | tail -5
cd $WT && /root/legendarypicks/node_modules/.bin/tsc --noEmit -p . 2>&1 | grep -E "<changed file names>" | head

# commit (always name the files)
cd $WT && git add backend/file1.py backend/test_file1.py && git commit -q -m "What changed and why" && git log --oneline -1

# read a DB fact
sqlite3 $DB "select ... limit 20"
```

If a sqlite write says `database is locked`: open the connection with `sqlite3.connect(path,
timeout=120)` and retry once. Do not delete WAL files.

## 2. What exists (verified 10-11; re-verify anything you rely on)

### 2.1 Branches (local only)

| Branch | Worktree | Content |
|---|---|---|
| `feat/nfl-model-foundation` | `/root/lp-nfl-lock-by-version` | All work below. Commits in order: `546ef62`, `9bac332`, `4489d87`, `87904d4`, `d6044cd`, `3a23d65`, `ff8ad73`, `844f15a`, `05ec0a5`, `34d3f98`, then this handoff. |
| `docs/spec-a-v1-v2` | `/root/lp-spec-a-v1-v2` | `a902ad8`: Spec A rewritten so v1 (points) and v2 (pure EPA) are separate models. Merge alongside the main branch later. |
| `feat/nfl-epa-efficiency` | `/root/lp-nfl-epa` | OLD blend (0.4 v1 + 0.6 EPA game totals). Retired. Has a neutral-site bug and fits sigma on the scored season. Never build on it. |
| `feat/player-projections-availability` | `/root/lp-player-proj` | Spec B B1-B3, unmerged, with open review findings. |

### 2.2 Code map (backend, in the worktree)

| File | What it does | Key functions |
|---|---|---|
| `nfl_ratings.py` | v1 points ratings (ridge), expected points, win prob | `fit`, `expected_points(fit, home, away, neutral)`, `win_probability(margin, sigma)` |
| `nfl_ratings_data.py` | v1 data reads, priors | `fit_for_week`, `prior_for_season`, `teams_in_season`, `_scored_rows` |
| `nfl_backtest.py` | v1 walk-forward backtest | `backtest_season(con, season, overrides)`, `summarize` |
| `nfl_metrics.py` | Brier, log loss, ATS, de-vig, bootstrap | `ats_result(actual_margin, spread)` returns cover/miss/push for HOME; `devig_home_prob`; `bootstrap_mean_diff_ci` returns (point, lo, hi) |
| `nfl_lock.py` | THE lock path for every model | `start_run(con, run_id, season, week, model_version, params, model=...)`, `lock_week(con, run_id, season, week, project, as_of, skip_scored, now)`, `v1_projector(fit, sigma)`, `assert_inputs_complete(con, season, week, pbp=False)`, `locked_projection(con, game_id, model_version)` |
| `lock_nfl_week.py` | CLI: lock a week with frozen v1 | `--season --week [--apply]` |
| `nfl_epa_model.py` | v2 per-play EPA ratings | `plays`, `fit`, `shrink`, `predictor`, `calibrate`, `phi` |
| `nfl_epa_backtest.py` | v2 backtest, pre-registered rules in docstring | `--stage tune2024 [--record]`, `--stage holdout2025 --half-life 12 --lam 450 [--record]`; helpers `walk_forward`, `fit_abh`, `final_prior`, `season_plays`, `sched`, `teams_of` |
| `lock_nfl_epa.py` | CLI: lock a week with v2 (frozen 12 / 450) | `build(con, season, week)` returns (project, info); `--season --week [--apply]` |
| `grade_nfl_locks.py` | grades locked rows when final | `run(con, now, dry_run)`, CLI `[--dry-run]` |
| `migrate_nfl_model_tables.py` | tables + indexes, idempotent | `migrate(con)`, `EXPECTED_COLUMNS` |
| `check_nfl_schedule_scores.py` | overdue-score alert; also `kickoff_utc(gameday, gametime)` (Eastern) | reuse `kickoff_utc`, never re-implement it |
| `nfl_standings.py` | records, SoV, SoS (official definitions since `34d3f98`) | `build(teams_map, games)`, `division_record`, `conference_record`, `strength_of_victory`, `strength_of_schedule` |
| `nfl_seeding.py` | official NFL tiebreakers and seeds (since `34d3f98`) | `seeds_for_conference(teams, conf, n_seeds=7, rng=None)`, `winner`, `order`, `division_order`, `n_seeds_for(season)`, globals `COIN_FLAGS`, `DECISIONS` |
| `nfl_bracket_check.py` | seeds vs the playoff games actually played | `team_map(con)`, `seeds_from_results(con, season, tmap)`, `check(...)`, `validate_season(con, season, tmap)` |
| `nfl_sim.py` | season simulation | `inputs`, `one_run`, `run`, `sanity`. STILL uses fake scores and no rng in seeding: task 4.1 step 3 |
| `routers/nfl_model.py` | API `GET /api/nfl/model/locks?season=&week=` for the Model tab | `locks_payload(con, season, week)`, `describe(model, version)`, `ADOPTED` |

Frontend: `components/Leagues/NflModelTab.tsx` (the Model tab), wired in
`pages/leagues/[league].tsx`, `components/Leagues/types.ts` (`HubTab` includes `'model'`),
`components/Leagues/hooks/useLeagueRouteState.ts` (NFL tabs list). URL: `/leagues/nfl?tab=model`.

### 2.3 Data facts (each was checked; do not "fix" them)

- `nfl_schedule.spread_line` is the HOME team's expected margin: positive means home favored.
  Example: ARI@LAR week 6 2026 spread_line 10.5 = LAR favored by 10.5.
- `gameday` + `gametime` are US Eastern (nflverse convention). Always convert with
  `check_nfl_schedule_scores.kickoff_utc`. PHI@JAX London game: gametime 09:30 Eastern.
- `nfl_schedule.result` = home score minus away score, published by nflverse. It is the "game is
  final" signal used by the grader and the completeness guard.
- `nfl_pbp.game_id` matches `nfl_schedule.game_id` (format `2025_01_ARI_NO`). Coverage 10-11: 272
  of 272 REG games for 2024 and 2025; 2026 had 65 of 65 scored games.
- Dev DB team codes are ESPN style: `LAR`, `WSH`. nflverse raw uses `LA`, `WAS`. Ingests map at the
  boundary. Never compare raw nflverse codes to DB codes without mapping.
- `nfl_teams` (season 2026) has the 32 codes with conference/division. Divisions have not changed
  since 2002; relocated teams kept their divisions.
- Codex's historical SQLite (`$HIST/nflverse_2010_2023.sqlite`): tables `nfl_schedule` (game_id,
  season, game_type in REG/WC/DIV/CON/SB, week, home_team, away_team, location, home_score,
  away_score, spread_line, total_line, home_moneyline, away_moneyline) and `nfl_pbp` (season, week,
  game_id, home_team, away_team, posteam, epa, pass_attempt, rush_attempt). NO defteam, NO gameday,
  NO result, NO div_game, NO touchdowns, NO passer ids. `games.parquet` in the same folder has every
  nflverse column (gameday, gametime, result, overtime, div_game, qb ids, spread/total odds) with
  RAW codes. Its SQLite team codes look already mapped to current codes (2010 lists LAR, LV, LAC,
  WSH) but the mapping was NOT verified: do task 4.1 step 1a first.
- 2022 week 17 BUF@CIN was cancelled: in the schedule with no score. Standings must just skip it.

### 2.4 State of the dev DB (written 10-11)

```bash
sqlite3 $DB "select substr(model_version,1,30), count(*), min(locked_at) from game_projections where season=2026 and week=5 and locked=1 group by model_version"
```
Expected: v2 untuned 13, v1 frozen 13, legacy 14. Grades: none until week 5 is final.

## 3. Pitfalls already hit (do not repeat)

1. Hand-copying printed numbers into the DB. Scripts write their own results (`--record`).
2. Hard-coded labels (the model name bug). Pass names through, test that they are stored.
3. Quoting an in-sample score as evidence. Only walk-forward numbers on games the fit never saw.
4. Inventing names. A ticker or code is not a team name. Show the code.
5. Trusting that a passing historical check proves a definition. The old SoV/SoS definition was
   wrong and still matched 28/28 seeds. Cite the publisher's text.
6. Locking on partial data. `assert_inputs_complete` refuses; never bypass it, fix the data.
7. Tests written from the author's own assumptions. Each test must plant the specific wrong
   behaviour and fail on the old code. Check one fixture against one real row.
8. Silent skips. If pytest shows more skips than the baseline, find out why (usually `LP_DB_PATH`
   missing) before claiming green.
9. `git add -A` or committing files you did not change. `git status --short` before every commit.
10. Changing code while a related test fails and calling it unrelated. Every failure is yours until
    proven otherwise with a command.

## 4. Work queue (in this order)

---------------------------------------------------------------------------------------------------
### Task 4.0 (time-critical, before Thursday 10-15 20:15 ET): week 6 locks and week 5 grading

Goal: both models locked for every week 6 game before its kickoff; week 5 graded.

Steps:
1. Refresh data. Run the ingest scripts from the WORKTREE's backend with `LP_DB_PATH` set (same
   scripts as dev). First `cd $WT/backend && LP_DB_PATH=$DB $PY ingest_nfl_schedule.py --help` and
   read the flags; then run it for 2026. Then `LP_DB_PATH=$DB $PY ingest_nfl_pbp_logs.py --year
   2026`. If `--help` shows anything unexpected (writes prod, calls ESPN), STOP and ask Micah.
2. Check completeness (read-only):
   ```bash
   cd $WT/backend && LP_DB_PATH=$DB $PY -c "import sqlite3,nfl_lock; c=sqlite3.connect('$DB'); print(nfl_lock.missing_inputs(c,2026,6,pbp=True))"
   ```
   Must print `{'unscored': [], 'no_pbp': []}`. If not: nflverse may not have published yet. Wait
   and retry later; never edit the guard. If a game stays missing more than a day after it was
   played, STOP and tell Micah which game.
3. Dry runs (write nothing), then read them:
   ```bash
   LP_DB_PATH=$DB $PY lock_nfl_week.py --season 2026 --week 6 | head -25
   LP_DB_PATH=$DB $PY lock_nfl_epa.py --season 2026 --week 6 | head -25
   ```
   Sanity: 14 games each; projected scores between about 10 and 40; v2 `calib` line prints a, b,
   h, sigma (10-11 values: a 23.1, b 0.88, h 1.8, sigma 13.2). Big jumps from those mean something
   changed: investigate before applying.
4. Apply both (`--apply`). Output ends with `applied run=... new_locks=14 ... started=none`.
   If `started` lists games, they had already kicked off: that is correct behaviour, report it.
5. Verify:
   ```bash
   sqlite3 $DB "select substr(model_version,1,20), count(*), max(locked_at) from game_projections where season=2026 and week=6 and locked=1 group by 1"
   sqlite3 $DB "select count(*) from nfl_line_snapshots s join game_projections g on g.line_snapshot_id=s.snapshot_id where g.week=6 and g.locked=1"
   ```
   Expect 14 and 14, and 28 snapshots.
6. Grade week 5 when final (4 h after the last kickoff AND `result` published):
   `LP_DB_PATH=$DB $PY grade_nfl_locks.py --dry-run` then without `--dry-run`. Expected after all
   week 5 games are final: `graded 40` the first time (14 legacy + 13 + 13), `already graded 40` on
   a second run. If it raises "published result disagrees with score": STOP, report the game.
7. Report to Micah: per model, week 5 Brier mean and margin MAE:
   ```bash
   sqlite3 $DB "select substr(g.model_version,1,24), count(*), round(avg(brier),4), round(avg(abs(margin_err)),2), sum(ats_result='win'), sum(ats_result='loss') from projection_grades g join game_projections p on p.game_id=g.game_id and p.model_version=g.model_version and p.locked=1 where p.week=5 group by 1"
   ```
   Say plainly that one week is far too small to compare models.

Pitfalls: do not add `--skip`-style flags back; the kickoff guard decides. Do not lock week 7 early
"to save time": week 6 results must be in first (the guard will refuse anyway).

---------------------------------------------------------------------------------------------------
### Task 4.1: finish the season engine (season odds)

Background: `34d3f98` rewrote seeding to nfl.com's procedure (reference copy:
`docs/REFERENCE-nfl-tiebreaking-procedures-2026-10-11.md`). 34 tests pass. Not yet validated on
history, and the simulation still has fake scores.

#### Step 1a: verify the historical team codes (read-only, ~1 call)

```bash
cd $HIST && $PY -c "
import pandas as pd, sqlite3
g=pd.read_parquet('games.parquet'); g=g[(g.season>=2010)&(g.season<=2023)][['game_id','home_team','away_team','div_game']]
c=sqlite3.connect('nflverse_2010_2023.sqlite')
s=pd.read_sql('select game_id, home_team h2, away_team a2 from nfl_schedule',c)
m=g.merge(s,on='game_id',how='outer',indicator=True)
print(m['_merge'].value_counts())
pairs=sorted(set(zip(m.home_team,m.h2))|set(zip(m.away_team,m.a2)))
print([p for p in pairs if p[0]!=p[1]])"
```
Expect every game in both, and a short list of (raw, mapped) pairs such as (STL, LAR), (SD, LAC),
(OAK, LV), (LA, LAR), (WAS, WSH). Any other pair, or a raw code mapped to two codes: STOP.

#### Step 1b: write `backend/validate_nfl_seeding_history.py` (read-only script)

Skeleton (fill in, keep it read-only):
```python
"""validate_nfl_seeding_history.py -- seeds from regular-season results vs the playoff games
actually played, 2010-2025. Read-only. 2010-2023 from the Codex historical SQLite, 2024-2025 from
the dev DB. Team map: dev nfl_teams 2026, verified per season against nflverse div_game first.
Exit 1 if any conference-season does not match.
Usage: LP_DB_PATH=<dev db> python validate_nfl_seeding_history.py --hist <sqlite> --parquet <games.parquet>
"""
import argparse, sqlite3, sys
import pandas as pd
import nfl_bracket_check as bc, nfl_seeding as sd

def verify_map(tmap, games_df, code_map, season):
    # for every REG game of the season: div_game == (division(home) == division(away)) under tmap
    # games_df has RAW codes; code_map maps raw -> DB code (from step 1a). Return list of mismatches.
    ...

def main():
    # dev = sqlite3.connect(LP_DB_PATH); tmap = bc.team_map(dev)
    # for season in 2010..2023: con = hist; for 2024, 2025: con = dev
    #   mism = verify_map(...); if mism: print and mark season FAILED, continue
    #   sd.COIN_FLAGS.clear(); sd.DECISIONS.clear()
    #   rep = bc.validate_season(con, season, tmap)
    #   print(season, rep['ok'], per conference ok, len(sd.DECISIONS), sd.COIN_FLAGS)
    #   on not ok: print expected vs actual WC and DIV pairs
    # print totals "conference-seasons ok: X of 32"; exit 1 if X < 32
```
Note: `bc.regular_games(con, season)` and `bc.playoff_games(con, season, 'WC'|'DIV')` read
`nfl_schedule` with columns that exist in BOTH databases. Check that before running
(`grep -n "SELECT" nfl_bracket_check.py`).

Run it. Expected: 32 of 32 conference-seasons (16 seasons x 2). For each failure:
- print the regular-season standings of the tied teams and which step decided (`DECISIONS`);
- compare with the published bracket (nfl.com or Pro Football Reference for that season);
- if our seeding is wrong, fix `nfl_seeding.py` and add a unit test that reproduces that exact
  case with the real records; if the CHECK is wrong (for example a pairing rule of that era), fix
  the check and say why.
Never edit the check to make a season pass without a published reason.

Commit: the script and any fixes, message saying how many matched.

#### Step 2: targeted tests in `backend/test_nfl_seeding.py`

Use the existing `Builder` in that file (records against AFC filler teams XAA/XBB, NFC games only
where a tiebreak needs them). Add one test per rule. Each must fail if its rule were missing: say in the test
docstring which rule it plants. To confirm, copy `nfl_seeding.py` to the scratchpad, remove that
rule's step there, and run the test against the copy (never edit the repo file to check, never use
`git stash`):
1. 3-team wild-card tie, two of the teams from the same division: only the higher-ranked of those
   two can win step 1; the lower one must not be chosen even if it would win on conference record.
2. Head-to-head sweep: team A beat B and C; A wins the 3-team wild-card tie. Then a case where A
   beat B, B beat C, C beat A: no sweep, the step is skipped (decided later).
3. Combined ranking with a shared position: two teams tied for 1st in points scored both get 1, the
   next gets 3 (use `sd._positions` directly with a small dict).
4. Restart: three-way division tie where step 2 eliminates one team; the remaining two are decided
   by HEAD-TO-HEAD (two-club step 1), even though they differ on a later step too.
5. Division winners tied on record are ordered by WILD-CARD steps (conference record before
   division record).
6. `seeds_for_conference(..., n_seeds=6)` returns 6 seeds and `n_seeds_for(2019) == 6`,
   `n_seeds_for(2020) == 7`.

Run the file, then the full NFL suite. Commit.

#### Step 3: simulation (`backend/nfl_sim.py`)

Changes:
1. `one_run`: pass `rng=rng` and `n_seeds=nfl_seeding.n_seeds_for(inp["season"])` into
   `seeds_for_conference`. Coin flips become random; keep counting them (`len(sd.COIN_FLAGS)`).
2. Replace `games.append((wk, h, a, 20.0 + m / 2.0, 20.0 - m / 2.0))` with scores drawn from the
   score distribution of task 4.2. Until 4.2 exists, DO NOT invent a placeholder. Do step 1 now,
   step 2 after 4.2.
3. `sanity()` assumes 7 seeds (`14.0`, seeds 1-7). Make it use the season's seed count.
4. Tests in `test_nfl_sim.py`: a planted 3-way tie season run twice with different rng seeds gives
   different seed-7 teams sometimes (proves the coin is random); `sanity` passes for a 6-seed
   season.
5. Run time: before N=20000, check `uptime; free -h`, then time N=2000 and extrapolate. Spec limit
   5 minutes for 20000. Report the measured time.

Definition of done for 4.1: history script 32/32 (or every mismatch explained and fixed with a
test), 6 new tests, sim uses rng and the right seed count, full suite green, commits made.

---------------------------------------------------------------------------------------------------
### Task 4.2: score distribution (joint home and away scores)

Goal: for any game with expected scores (eh, ea), draw realistic final scores (integers, real
football shapes, ties at the real rate). Win, spread, total and team-total probabilities all come
from these draws. Used by the sim (4.1 step 3) and market probabilities (4.5).

Steps:
1. Pre-register FIRST. Create `backend/nfl_score_dist.py` with only the docstring: method, the
   training seasons (2010-2019), the test seasons (2020-2025), the K grid (25, 50, 100, 200), the
   selection rule (lowest 2010-2019 out-of-sample log loss of the score pair, ties to the smaller
   K), and the gate (below). Commit the docstring alone before running anything.
2. Build the history table (in a scratch SQLite or a CSV under the scratchpad, NOT the dev DB):
   one row per REG game 2010-2025: season, week, eh, ea (v1 walk-forward expected points, i.e. fit
   on earlier weeks only), actual home and away scores, overtime flag. For 2010-2023 use
   `$HIST/backtest_2010_2023_games.csv` ONLY after reading its header and confirming which columns
   are walk-forward v1 expected home/away points (if it only has margin and total: eh = (total +
   margin)/2, ea = (total - margin)/2; write that in the docstring). For 2024-2025 use
   `nfl_backtest.backtest_season(con, season, {"half_life": 6.0, "cap": 14.0, "cap_points": None})`
   rows (`proj_margin`, `proj_total`).
3. Method: nearest neighbours. For a target game, standardize (expected margin, expected total) by
   the training set's standard deviations, take the K nearest training games, and draw one of their
   actual (home, away) score pairs uniformly. Do not shift or rescale scores.
4. Evaluate on 2020-2025 (each season uses training data from all earlier seasons only):
   - win Brier vs the current Normal(margin, sigma=13.295) model;
   - P(home covers the line) and P(over the total) calibration in 10% bins vs actual (lines from
     the schedule; ignore games without a line, count them);
   - tie frequency predicted vs actual, overall and for 2017+ (OT shortened to 10 minutes in 2017);
   - probability integral transform histogram of the actual margin (10 bins, roughly flat is good).
5. Gate (as pre-registered): ship only if win Brier is no worse than Normal and cover/over
   calibration is better (sum of squared bin errors lower). If it fails, report and STOP; do not
   tune K on 2020-2025.
6. API of the module: `sample(eh, ea, rng, n) -> list of (home, away)` and
   `probabilities(eh, ea, spread, total, n=20000, rng) -> dict(p_home_win, p_tie, p_cover, p_push,
   p_over, ...)`. Tests: planted training set where the neighbours are known; same rng seed gives
   same draws; scores are integers; ties appear when the training set has ties.
7. Then do 4.1 step 3 part 2 (sim uses `sample`).

Pitfalls: leakage (the target season must never be in its own neighbour pool); using closing lines
as features (they are not; only expectations from our own model); evaluating K on the test seasons.

---------------------------------------------------------------------------------------------------
### Task 4.3: player availability, QB first

North star rule (exact words): "A starting-quarterback change is the expected starter's effect
relative to the QB production already in the team baseline, not subtraction of his full
standalone value."

Steps:
1. Measure what is published and when (no code yet; one or two queries each):
   - `sqlite3 $DB "pragma table_info(nfl_schedule)" | grep -i qb` (expect `home_qb_id`,
     `away_qb_id`). For 2026 week 6 rows: are they filled BEFORE the games? Query now, before week
     6 kicks off, and write the answer down. If they are only filled after games, the starter must
     come from elsewhere (depth charts: `ingest_nfl_depth_charts.py` exists; injury reports).
   - `sqlite3 $DB "pragma table_info(injury_reports)"` and the latest `report_date` or equivalent
     for 2026 week 6; what statuses exist (Out, Doubtful, Questionable)?
   - The availability timer runs Tuesdays only (`systemctl list-timers | grep -i availab`, read
     only). Final injury statuses come Friday and Saturday. A Friday/Saturday refresh is a timer
     change: ask Micah, do not create it.
2. QB value: from dev `nfl_pbp`, EPA per dropback by `passer_player_id` (dropback = pass_attempt=1
   or sack=1; check the columns `sack`, `qb_epa`, `passer_player_id` exist first). Per season,
   regress each QB toward replacement level: value = (n * epa_db + k * repl) / (n + k), with k and
   repl fitted on earlier seasons only (pre-register). Replacement level = the dropback-weighted
   EPA of QBs who were not their team's main starter.
3. Team baseline QB mix: the team's recent pass rating already contains its recent QBs, weighted by
   their recency-weighted dropbacks. Adjustment for a game = (value of expected starter - dropback-
   weighted value of the recent QB mix) x expected dropbacks (team's recency-weighted dropbacks per
   game). Points conversion: for v2 use its fitted `b` (EPA to points); for v1 use 1.0 (EPA is in
   points) and say so.
4. Historical check, 2010-2025 needs passer ids, which the Codex SQLite does not carry. Extend the
   scratch loader (copy Codex's `load_nflverse_2010_2023.py` into the scratchpad and add
   `passer_player_id`, `sack`, `qb_epa`) and load into a NEW scratch SQLite. Never into the dev DB.
   Starter per historical game: the passer with the most dropbacks in that game (state this; it
   uses the game's own data, so it is a "known starter" test, which is fine for measuring the
   adjustment's value but say so).
5. Evaluate on games where the starter differs from the team's main starter of the previous 4
   games: n, Brier and margin MAE with and without the adjustment, v1 and v2. Bootstrap by season.
6. If it helps: new model versions `nfl-v1+qb ...` and `nfl-epa-v2+qb ...`, locked weekly beside
   the others (the lock path handles any version). Show on the Model tab automatically (the API
   lists every locked version; update `describe()` labels and its test).

Pitfalls: identity. Join players on ids only, never names (AGENTS.md section 7). A QB with no NFL
dropbacks is "no sample", given replacement level and labelled so, never zero.

---------------------------------------------------------------------------------------------------
### Task 4.4: player projections (Spec B)

1. Read `docs/SPEC-player-projections-availability-2026-10-09.md` sections 2 and 4 only.
2. Read the open review findings for `/root/lp-player-proj` (search its `docs/` for REVIEW files:
   `ls /root/lp-player-proj/docs | grep -i review`). List them. Fix them in THAT worktree, one
   commit each, its own tests (`cd /root/lp-player-proj/backend && LP_DB_PATH=$DB $PY -m pytest -q
   test_player_*.py | tail -3`).
3. Then B4 (the "without player X" backend) per the spec, then projections that take team volume
   from the game model (plays and pass rate already in `nfl_epa_model.Ratings.plays_pg` /
   `pass_rate`). Rule: an injury reallocates opportunities, it never creates them twice: sum of
   player shares must equal the team total; test that.
4. Do not start this before 4.1 to 4.3 are done unless Micah says so.

---------------------------------------------------------------------------------------------------
### Task 4.5: market probabilities

1. Needs 4.2. For each locked game: p_home_win, p_tie, p_cover and p_push against the LOCKED spread
   (from `nfl_line_snapshots`), p_over against the locked total, from `nfl_score_dist.probabilities`.
2. Compare with the market: de-vigged moneyline (`nfl_metrics.devig_home_prob(home_ml, away_ml)`;
   moneylines are in snapshots from 10-11 on). For spreads and totals the price is needed:
   `games.parquet` has `home_spread_odds`, `away_spread_odds`, `over_odds`, `under_odds`; check
   whether the dev schedule ingest stores them (`pragma table_info(nfl_schedule)`). If not, adding
   them to the ingest is published-first rung 2; ask Micah before changing an ingest that prod uses.
3. Calibrate on history (2020-2025 walk-forward) before showing anything. honest-data-ui: never put
   an uncalibrated probability on the page. Show sample size beside every rate.

---------------------------------------------------------------------------------------------------
### Task 4.6: later (do not start without Micah)

- Weekly job and timer (Spec A A6): lock both versions Tuesday and Thursday, grade nightly,
  movers JSON. Timers need Micah's OK.
- v1's full tuning grid (60 configurations; the 10-09 grid ran 36) on 2010-2023 as a new labelled
  experiment, 2024-2025 as holdout.
- Pure per-play v2 on 2010-2023 (Codex only ran the old blend). Needs defteam derived as "the
  other team" and a prior chain season to season.

---------------------------------------------------------------------------------------------------
### Before anything goes to dev (checklist)

1. Full NFL suite and jest green, numbers reported.
2. Render the Model tab without the managed servers: start the WORKTREE backend on a free port
   (`ss -tlnp` first; pick an unused port like 8197, bind 127.0.0.1) with
   `cd $WT/backend && LP_DB_PATH=$DB $PY -m uvicorn sports_service:app --host 127.0.0.1 --port 8197`
   in the background, `curl -s 'http://127.0.0.1:8197/api/nfl/model/locks?week=5' | head -c 400`,
   then stop ONLY that process by its PID. A headless browser render of the page needs a frontend;
   ask Micah how he wants it checked rather than starting a second Next server (inotify/OOM risk,
   AGENTS.md section 12).
3. A Codex review of the branch (tmux pane `codex:0`; submit with `C-m`; check its status line for
   remaining limit first; give it a task file naming exact files and "report only, change nothing").
4. Ask Micah. The merge is a fast-forward of `dev` to this branch plus `docs/spec-a-v1-v2`.
