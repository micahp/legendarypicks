# Handoff: NFL forecasting model, 2026-10-11

For the next session (Sonnet or Haiku). Read this whole file before writing code. Then read, in this
order: `docs/STRATEGY-forecasting-north-star-2026-10-10.md` (the goal),
`docs/SPEC-nfl-team-ratings-playoff-odds-2026-10-09.md` on branch `docs/spec-a-v1-v2` (v1 and v2
defined), `docs/RESULTS-A9-nfl-epa-v2-backtest-2026-10-11.md`, `docs/REVIEW-SPEC-A-2026-10-10.md`.

Micah's standard (his words, 10-11): "I'm not trying to cut corners ... if we're going to actually
use that then it can't be buggy ... I'm trying to get this ready for the long term." Every piece
below must be correct, tested against real data, and honest about what it does not do.

## 0. Rules (from AGENTS.md and the project skills; do not skip)

- Work ONLY in the worktree `/root/lp-nfl-lock-by-version` (branch `feat/nfl-model-foundation`).
  Never edit `/root/legendarypicks` (the managed dev checkout; other people's uncommitted WIP is in
  it). Never `git switch`. Never `git add -A`: stage named paths. Never push. Never merge to `dev`
  without Micah saying so.
- Dev DB: `/root/legendarypicks/backend/data/picks.dev.db`. Pass `LP_DB_PATH=` explicitly.
  Python: `/root/legendarypicks/backend/venv/bin/python` (Python 3.8: no `zoneinfo`; use `pytz`).
  Never touch prod (`picks.db`), never restart a dev server.
- Frontend: never run `npm`/`npx`. Use `/root/legendarypicks/node_modules/.bin/{tsc,jest}`. The
  worktree's `node_modules` is a symlink to the main one (created 10-11).
- Load `.claude/skills/` before code: `published-first`, `fail-loudly`, `falsify-before-merge`,
  `measurement-is-a-claim`, `honest-data-ui` (any UI), `resource-check` (any batch job).
- Check `uptime` and `free -h` before anything heavy. Box has 5.8 GB RAM.
- Report numbers with the command that produced them. Never copy printed numbers by hand into the
  DB: scripts write their own results (`--record` pattern in `nfl_epa_backtest.py`).
- No em dashes anywhere (replies, commits, docs, UI copy). No AI attribution in commits.
- Run the NFL tests after every change:
  `cd backend && LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db /root/legendarypicks/backend/venv/bin/python -m pytest -q $(ls test_nfl*.py test_*nfl*.py | sort -u)`
  (10-11 baseline: 421 passed, 1 skipped with LP_DB_PATH set). Plus jest:
  `/root/legendarypicks/node_modules/.bin/jest components/Leagues pages` (89 passed).

## 1. Where things stand (verified 10-11)

### Branches (all local, none pushed, none merged to dev)

| Branch | Worktree | What |
|---|---|---|
| `feat/nfl-model-foundation` | `/root/lp-nfl-lock-by-version` | Everything below, in order: `546ef62` lock per model version; `9bac332`..`d6044cd` v2 pure EPA model, backtest, results; `3a23d65` shared lock path (kickoff guard, line snapshots, grader, model name); `ff8ad73` v2 on the shared path, `--record`; `844f15a` input-completeness guard; `05ec0a5` NFL Model tab page; `34d3f98` seeding by the official procedure (IN PROGRESS, see 2.1) |
| `docs/spec-a-v1-v2` | `/root/lp-spec-a-v1-v2` | `a902ad8` Spec A rewrite: v1 points, v2 pure EPA, separate models |
| `feat/nfl-epa-efficiency` | `/root/lp-nfl-epa` | The OLD failed blend. Retired. Do not build on it. |

### Dev DB state written 10-11 (dev only)

- `game_projections` has `model_version` and `line_snapshot_id` columns; locked index is per
  (league, game_id, model_version). New table `nfl_line_snapshots`. Unique index on
  `projection_grades(league, game_id, model_version)`.
- Week 5 of 2026 locks: 14 legacy (10-09, cap 21, margin only), 13 frozen v1, 13 v2 untuned (half_life
  6, lam 150). PHI@JAX and TB@DAL not locked by v1/v2 (already started). Grades: none yet.
- `model_runs`: v2 2024 grid (9 rows, status `tuning`) and 2025 second look (status `holdout`),
  written by the backtest itself.

### Models (all numbers in the RESULTS-A9 doc and model_runs)

- v1 points: adopted. v2 pure EPA: ties v1 on 2025 (Brier +0.0003, CI -0.0083/+0.0087), trails on
  2024. Neither knows player availability. Both trail the market.
- Codex's 2010-2023 run (old blend code, which has the neutral-site bug): v1 beats both blends
  across 3,408 games, season-block CIs exclude zero. Report:
  `/root/nfl-v1-rehearsal.d0IcMW/nflverse_2010_2023/REPORT.md`.

### Historical data (Codex, 10-11)

`/root/nfl-v1-rehearsal.d0IcMW/nflverse_2010_2023/`: 14 nflverse PBP parquets, `games.parquet`
(all columns incl. `div_game`, `gameday`, `gametime`, `result`, `overtime`, QB ids), and a scratch
SQLite `nflverse_2010_2023.sqlite` with tables `nfl_schedule` (game_id, season, game_type
REG/WC/DIV/CON/SB, week, teams, location, scores, lines, moneylines) and `nfl_pbp` (season, week,
game_id, home/away, posteam, epa, pass_attempt, rush_attempt; NO defteam column, derive it as the
other team). Counts reconciled with the publisher (`source_counts.json`). Team codes in the SQLite
are already the current franchise codes (2010 shows LAR, LV, LAC, WSH). NOT yet confirmed: how
Codex mapped STL/SD/OAK/LA/WAS (grep of its loader found no literal map; the 10-11 check was cut
off). Confirm before using: compare `games.parquet` raw codes to the SQLite codes per game_id.
Codex had about 4% of its 5h limit left at 12:31 CDT 10-11.

### Weekly operations that are still manual

- Week 6 locks before Thursday 10-15 SEA@DEN (kickoff 20:15 ET):
  `LP_DB_PATH=... python lock_nfl_week.py --season 2026 --week 6 --apply` and
  `LP_DB_PATH=... python lock_nfl_epa.py --season 2026 --week 6 --apply`. Both refuse (by design)
  until every week 1-5 game has nflverse's `result` and, for v2, play-by-play. Week 5 pbp had 1 of
  15 games on 10-11: run `ingest_nfl_pbp_logs.py --year 2026` and the schedule refresh first.
- Grading: `LP_DB_PATH=... python grade_nfl_locks.py` once week 5 games are final (4 h after
  kickoff and `result` published). Dry run first (`--dry-run`).

## 2. Work queue, in order

Each task: its own commit, tests that plant the failure, a real-data check, and a short report with
the commands and raw output. Stop and report if a check fails; do not tune to pass.

### 2.1 Finish the season engine (IN PROGRESS)

Done in `34d3f98`: `nfl_seeding.py` implements nfl.com's procedure exactly (reference text in
`docs/REFERENCE-nfl-tiebreaking-procedures-2026-10-11.md`): every step incl. combined ranking,
net points, net touchdowns, coin toss; restarts after eliminations; wild-card step 1 division
reduction with the original within-division order kept; division winners ordered by wild-card
tiebreakers; real random coin when given an `rng`; `n_seeds_for(season)` (6 before 2020).
`nfl_standings.py`: strength of victory/schedule now use full combined records, ties half (the old
code excluded games against the team: wrong). `nfl_bracket_check.py` handles both eras. 34 tests
pass.

Remaining, in order:
1. **Historical validation, 2010-2025.** Write `backend/validate_nfl_seeding_history.py` (read-only):
   for each season, seeds from regular-season results only, compared with the WC and DIV games
   actually played (`nfl_bracket_check.check`). 2010-2023 from the Codex SQLite, 2024-2025 from the
   dev DB. Team map: dev `nfl_teams` 2026 (`nfl_bracket_check.team_map`), but FIRST verify it per
   season: for every REG game in `games.parquet`, `div_game` must equal "same division under the
   map" after code mapping; any disagreement stops that season. Print per season: ok, seeds, the
   `nfl_seeding.DECISIONS` list (which step settled each tie) and `COIN_FLAGS`. Expected: 32 of 32
   conference-seasons ok. Any mismatch is a finding: investigate, never patch the check. Known
   traps: 2022 BUF@CIN week 17 was cancelled (no score; standings over 16 games, pct still right);
   the 2022 AFC title game was neutral.
2. **Targeted unit tests** in `test_nfl_seeding.py`, each failing on the old engine: (a) 3-team
   wild-card tie with two teams from one division: only the higher-ranked of them survives step 1;
   (b) head-to-head SWEEP decides a 3-team wild-card tie, and a non-sweep does not; (c) combined
   ranking with a shared position ("tied for first both get 1, next is 3"); (d) after a step
   eliminates one of three, the remaining two restart at the two-club step 1 (head-to-head);
   (e) division winners tied on record ordered by wild-card rules; (f) 6-seed season has two byes.
3. **Simulation (`nfl_sim.py`)**: pass `rng` into `seeds_for_conference` (real coin) and
   `n_seeds=nfl_seeding.n_seeds_for(season)`. Replace the fake scores (`20 +- margin/2`) with draws
   from the score distribution of 2.2 so ties, real score shapes and the points/net-points
   tiebreakers are meaningful. Keep the existing sanity asserts (sum of p_playoffs = 14, seeds sum
   to 1) and the two-seed stability check (spec 6.3). Measure run time for N = 20000 with
   `resource-check` first; spec limit is 5 minutes.
4. Re-run the A5 sim backtest (`nfl_sim_backtest.py`) and record before/after.

### 2.2 Score distribution (joint home/away scores)

Goal (north star): each simulated game yields a winner, margin, total and team scores with a
realistic tie rate; win, spread, total and team-total probabilities come from the same draws.
Method to try first (simple, real scores, falsifiable):
- Build a history table of (expected home points, expected away points from v1 walk-forward,
  actual home score, actual away score) for 2010-2025 REG games. Codex's
  `backtest_2010_2023_games.csv` has per-game v1 projections; add 2024-2025 from
  `nfl_backtest.backtest_season`. Record what each column is before using it.
- Conditional resampling: for a game with expectations (eh, ea), draw an actual historical score
  pair from its K nearest neighbours in (expected margin, expected total), K chosen on 2010-2019
  only. Scores stay real integers; ties appear at their real rate.
- Gate (pre-register in the module docstring before running): on 2020-2025 walk-forward, compare
  with the current Normal(margin, sigma) model: Brier for win, calibration of P(cover) and P(over)
  against the locked lines, tie frequency vs actual, PIT histogram of margin. Ship only if no worse
  on win Brier and better calibrated on cover/over. Note the OT rule change (2017, 10-minute OT)
  changes the tie rate: check the tie rate by era.
- Module `backend/nfl_score_dist.py` + tests; then use it in the sim (2.1 step 3).

### 2.3 Player availability (QB first)

North star rule: "A starting-quarterback change is the expected starter's effect relative to the
QB production already in the team baseline, not subtraction of his full standalone value."
1. Check what is published and when (measurement-is-a-claim): does nflverse fill
   `home_qb_id/away_qb_id` before kickoff or only after? Compare `games.parquet` snapshots or the
   dev DB `ingested_at` against kickoff for 2026 weeks. Is `injury_reports` final status (Out,
   Doubtful) present by Saturday? The availability timer runs Tuesdays only
   (`legendarypicks-nfl-availability.timer`); a Friday/Saturday refresh would need Micah's OK
   (it is a timer change).
2. QB value from published EPA per dropback by `passer_player_id` (pbp has it in the dev DB
   `nfl_pbp`; the Codex scratch table does not carry passer ids, so extend the loader in scratch,
   not in dev). Regress each QB toward a replacement level by sample size; rookies/backups with few
   dropbacks get replacement level, labelled as such.
3. Adjustment = (expected starter value - value of the QB mix already in the team's recent pass
   rating) x expected dropbacks. Apply to v1 and v2 as separate model versions.
4. Backtest 2010-2025 on games where the starter differed from the team's usual starter; report n,
   Brier and margin error on those games vs the unadjusted models. Then lock weekly as its own
   version.
5. Spec B layers (other positions) after QB; the B1-B3 branch `feat/player-projections-availability`
   has open review findings (`/root/lp-player-proj`).

### 2.4 Player projections (Spec B)

Read `docs/SPEC-player-projections-availability-2026-10-09.md`. B1-B3 exist on
`feat/player-projections-availability` (worktree `/root/lp-player-proj`), unmerged with review
findings. Next: fix those findings, then B4 (without-player backend), then projections that share
team volume with the game model (north star: "An injury reallocates opportunities; it cannot create
production twice"). Grade beside ESPN projections where captured.

### 2.5 Market probabilities

From 2.2's draws: P(home win), P(home covers the locked spread), P(over the locked total), team
totals. Compare with the de-vigged moneyline (`nfl_metrics.devig_home_prob`) and the snapshot line
(`nfl_line_snapshots` has moneylines from 10-11 on). Show on the Model tab only what is calibrated
(honest-data-ui: never present an uncalibrated probability). Spread/total prices (`*_spread_odds`,
`over_odds`) are in `games.parquet` for history; the dev schedule ingest may need those columns
(published-first rung 2).

### 2.6 Also on the list (lower priority, do not start without the above)

- Weekly job + timer (A6): lock both versions Tue and Thu, grade nightly, movers JSON. Timer
  changes need Micah's OK.
- Re-run v1's tuning on the full 60-config grid on 2010-2023 (the 10-09 grid ran 36 of 60), as a
  NEW labelled experiment with 2024-2025 as holdout.
- Run the pure per-play v2 (`nfl_epa_model.py`) on 2010-2023 (Codex only tested the old blend):
  needs `defteam` (derive from home/away) and a per-season prior chain.
- Before merging to dev: render the Model tab in a headless browser at phone and desktop width
  with zero page errors (AGENTS.md section 10), have Codex review the branch
  (`falsify-before-merge`), then ask Micah. The merge is a fast-forward of 10 commits; the dev
  backend runs with `--reload`.

## 3. Things that went wrong on 10-11, so they are not repeated

- I hand-copied printed backtest numbers into `model_runs`; replaced by `--record`.
- `nfl_lock.start_run` hard-coded the model name; v2 runs were stored as v1 (fixed, row corrected).
- I quoted an in-sample Brier (0.2262) for v2 as if it were evidence; the honest figure is 0.2291.
- I invented opponent names for tickers on a published page; caught before publishing. Never
  write a fact that is not in the data.
- A dry-run lock reads partial play-by-play silently; the completeness guard now refuses.
- Strength of victory/schedule had a non-NFL definition for weeks and still matched 28/28
  historical seeds: a passing historical check does not prove a definition. Cite the publisher.
