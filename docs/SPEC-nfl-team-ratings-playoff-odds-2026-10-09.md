# SPEC A: NFL team ratings, game projections and playoff odds, graded in public

Author intent (Micah, 2026-10-09): "Everything we've been doing is leading up to individual player
stat projections and team projections that lead up to playoff predictions, week to week. This is
the most valuable next step. If FiveThirtyEight can get acquired by ESPN then we can too." Playoff
odds were the headline FiveThirtyEight was known for; every week's movers are the news LP writes.
Everything is graded in public.

Companion: `docs/SPEC-player-projections-availability-2026-10-09.md` (SPEC B). Parent north star:
`docs/SPEC-modeling-platform-2026-07-16.md`. Method reference: `docs/PROJECTIONS-METHODOLOGY.md`.

Written for implementers (Codex, pi) who have not read the conversation. Every fact below was
measured in the dev DB on 2026-10-09 unless marked otherwise.

---

## 0. Rules for whoever builds this (read first)

1. **Load the project skills before writing code:** `ls .claude/skills/`. This work touches
   `published-first` (every derived number), `fail-loudly` (every job), `falsify-before-merge`
   (every model claim), `honest-data-ui` (the page), `espn-request-budget` (any ESPN call),
   `measurement-is-a-claim` (every number in your report).
2. **Dev DB only:** `backend/data/picks.dev.db` (the dev backend runs with
   `LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db`). Never write the prod DB. Never
   restart a dev server you did not start. Prod promotion is a separate decision by Micah.
3. **Work in your own git worktree and branch** (`git worktree add ../lp-nfl-ratings -b
   feat/nfl-ratings-playoff-odds dev`). One commit per slice below. Never `git add -A`; stage named
   paths. Never commit to `dev` directly. Do not push unless Micah says so.
4. **No derived value where a published one exists.** Divisions, conferences, scores, market
   lines, final seeds: copy them from the publisher. Your code computes ratings, probabilities and
   tiebreaks only, and every one is validated against a published answer (section 6).
5. **A missing value is `unknown`, never a guess.** An unscored final game stops the weekly run
   with a loud error; it is never treated as a tie or skipped.
6. **Report with raw output.** Each slice's report pastes the command and its output (row counts,
   test results, backtest table). "Done" without output is not accepted.

---

## 1. What exists today (measured 2026-10-09)

| Thing | State |
|---|---|
| `nfl_schedule` (nflverse games file, `ingest_nfl_schedule.py`) | 2024: 285 games, 2025: 285, 2026: 272 (weeks 1-18). Carries `spread_line`, `total_line`, moneylines, `div_game`, `location`, rest days, starting QB ids. |
| 2026 scores in `nfl_schedule` | weeks 1-3 all 16 scored; week 4: 15 of 16 (`2026_04_ATL_NO`, played 10-05, unscored); week 5: 0 of 15 (TB at DAL played 10-08, unscored). **The ingest is stale since about 10-05.** |
| `team_game_results` | NFL 2024: 570 rows, 2025: 570, 2026: 544 (team-side rows). |
| Team ratings, game projections, playoff odds | **None.** `strength_snap` stores win%/differential snapshots from ESPN; there is no model. `/api/{league}/strength` and `/api/{league}/standings` exist (`backend/routers/games/standings.py`). |
| Division/conference mapping | Not in the DB as a table. Must be copied from the publisher (nflverse `teams` file). |

The week is week 5 of 2026 (TB at DAL on Thursday 10-08 opened it).

---

## 2. Product

1. **Weekly playoff odds page** for all 32 teams: P(make playoffs), P(win division), P(first-round
   bye = seed 1), P(each seed 1-7), projected wins (mean and 10th-90th percentile), and the change
   since last week. Sorted by conference and division.
2. **Game projections** for every remaining game: projected score each side, spread, total, win
   probability, the market line next to it (nflverse `spread_line`/`total_line`, and Kalshi when
   we have it), and the gap.
3. **Public grading**, on the same page: every locked projection and its result. Brier score and
   log loss for win probability, mean absolute error for margin and total, against-the-spread record
   against the line we locked against, and a calibration chart (do our 70% picks win about 70%).
   Losses stay on the page.
4. **News feed input:** each Tuesday run emits the week's biggest playoff-odds movers (team, from,
   to, the game that moved it) as JSON for the news engine. "Seahawks playoff odds 41% to 63% after
   beating the 49ers" is the story format.

Out of scope for SPEC A: player-level anything (SPEC B), in-game live odds, other leagues (the tables
take a `league` column so NCAAF/NBA/NHL can follow the same shape).

---

## 3. Data slices (build first)

### A0. Fix the schedule ingest (blocker)
- Find why `nfl_schedule` stopped updating around 10-05 (`ingest_nfl_schedule.py`, and the timer
  or cron that is supposed to run it: `systemctl list-timers`, `crontab -l`). Fix the cause, do not
  just re-run it.
- After the fix: every 2026 game with `gameday` before today and status final has both scores. Run
  the published-first reconcile: count of scored 2026 games equals the number of games the
  publisher lists as final. Paste the counts.
- The ingest runs on a `systemd` timer with `OnCalendar=` (not a monotonic timer: they report
  enabled while dead), at least daily and Tuesday 09:00 America/Chicago.
- Add a failing check: if any game with `gameday` older than 36 hours has no score, the job exits
  non-zero and writes an alert (fail-loudly).

### A1. Teams table (published)
- New table `nfl_teams(season, team, conference, division, team_name, source, ingested_at)` from
  the nflverse teams file (`teams_colors_logos`). 32 rows per season. Team codes must match
  `nfl_schedule` codes exactly (reconcile: every team in 2026 `nfl_schedule` appears once).

---

## 4. The model, version 1 (scores only)

Version 1 uses only final scores, home field and the schedule, because that is enough to ship
playoff odds this season. Efficiency (EPA from nflverse play-by-play, already ingested by
`ingest_nfl_pbp_logs.py`) is version 2 (section 9).

### 4.1 Ratings
For each team: offense rating `o` and defense rating `d`, in points versus an average team, and a
home-field term `h`. Expected points for team A at home against team B:

    pts_A = mu + o_A - d_B + h/2
    pts_B = mu + o_B - d_A - h/2

Neutral site (`location == "Neutral"`): `h = 0`.

Fit by weighted ridge regression (least squares on every played game, both sides' points as two
observations), solving all teams at once so opponent strength is adjusted automatically:
- **Recency weight:** game weight `w = 0.5 ** (weeks_ago / half_life)`. Start with
  `half_life = 6` weeks; tune in the backtest (section 6), report the chosen value.
- **Blowout dampening:** cap each game's margin contribution: points observations are used as is,
  but add a third observation per game, the margin, winsorized at +/-21. Tune the cap in the
  backtest (try 14, 17, 21, 28, none).
- **Prior (early season):** each team's prior is its final 2025 rating regressed one third toward
  zero (tune the fraction). The prior enters the regression as pseudo-games with weight
  `prior_games` (start at 4; tune). This is what keeps week-2 ratings sane.
- `mu` (league average points) and `h` are fitted, not hard-coded. Report the fitted values.

### 4.2 Game projection
- Projected margin `m = pts_A - pts_B`, projected total `pts_A + pts_B`.
- Win probability: `P(A wins) = Phi(m / sigma)`. Fit `sigma` from 2024-2025 residuals (actual margin
  minus projected margin); report it (published models use about 13-14 points; measure ours).
- Ties: ignore in version 1 (about 0.3% of games); note it on the page.

### 4.3 Locking
A game's projection is written once, at the first weekly run after the schedule shows both teams,
and **never overwritten** (Sam's "locked against the first line seen" rule). Store the market line
seen at lock time next to it. Later runs may write a newer row with a newer `as_of`, but grading
always uses the first locked row.

---

## 5. Season simulation and playoff odds

### 5.1 Simulation
- `N = 20000` seasons per run (report the run time; must finish under 5 minutes on this box,
  `nproc` and load checked first per the `resource-check` skill).
- Remaining games are drawn in schedule order. Version 1 is a "hot" simulation, as
  FiveThirtyEight's was: after each simulated game, both teams' ratings move by `k * (actual -
  expected margin)` with a small `k` (start 0.05; tune so simulated rating spread matches real
  week-to-week rating changes in 2024-2025). Report hot vs cold (no updates) on the backtest; keep
  whichever grades better.
- Played games use their real results.

### 5.2 Seeding rules (NFL, 2020 onward)
Per conference: 7 playoff teams. Seeds 1-4: the four division winners, ordered by record. Seeds
5-7: the three best non-division-winners by record. Only seed 1 gets a bye.

### 5.3 Tiebreakers (implement in this order, NFL's own procedure)
Two-team, division: head-to-head, division record, common games record, conference record, strength
of victory, strength of schedule, then (skip the points-based steps) coin flip (random in the sim).
Two-team, wild card: head-to-head (only if they played), conference record, common games (minimum
four), strength of victory, strength of schedule, coin flip.
Three or more teams: apply the NFL's multi-team procedure (eliminate one team at a time, restart the
two-team procedure when reduced to two; for wild card, first reduce to the highest-ranked team in
each division). Read the official procedure (NFL Record & Fact Book, "Tie-Breaking Procedures") and
cite the version in the code docstring.
- **Validation is mandatory (section 6.2).** Seeding code that does not reproduce published final
  seeds for 2024 and 2025 does not merge.

### 5.4 Outputs
Per team per run: `p_playoffs`, `p_division`, `p_bye`, `p_seed_1..p_seed_7`, `wins_mean`,
`wins_p10`, `wins_p90`, plus the deltas from the previous week's run.

---

## 6. Validation gates (falsify-before-merge)

### 6.1 Walk-forward backtest, 2024 and 2025
For each week `w` from 2 to 18: fit using only games before week `w`, project week `w`, then grade.
Report one table per season and pooled:
- Brier score and log loss of win probability, for: (a) our model, (b) 50/50, (c) "home team wins
  57%", (d) the market's implied probability from nflverse moneylines (de-vigged).
- Mean absolute error of margin and of total: ours vs `spread_line` and `total_line`.
- Calibration: bucket win probabilities in 10% bins; count and actual win rate per bin.
- Against-the-spread record versus `spread_line` (pushes listed separately).

Pass: our Brier beats (b) and (c) in both seasons. We do **not** need to beat the market to ship;
we must report honestly where we stand against it, on the page.

**Pre-registered A3 questions and rules** (written 2026-10-09, before any backtest run; changing
them after a result is a new experiment and must be labelled as one):

Questions the backtest answers:
1. Does the model beat 50/50 and the constant 57% on Brier and log loss, in each season?
2. How far behind the de-vigged moneyline market is it? Report only.
3. Margin MAE versus `spread_line`, and total MAE versus `total_line`. Report only.
4. Calibration in 10% bins. Bins with fewer than 20 games are flagged; no claim rests on them.
5. Against-the-spread record versus `spread_line`, pushes listed separately. Report only.
6. Which parameters: `half_life`, margin cap, `prior_games`, prior shrink, the `cap_points` toggle
   (raw points capped at `mu +/- cap_points`), and `h` fitted or fixed at a league value.
7. Is `h` stable season to season? Does fixing it improve out-of-sample Brier?
8. Does capping raw points improve Brier or MAE over the current design?
9. Early-season reliability: weeks 2-4 are reported separately, not pooled silently.
10. Ties are excluded from grading and their count is reported.

Pass conditions (the only ones):
- Brier and log loss beat baselines (b) and (c) in both 2024 and 2025.
- Added: the pooled 95% bootstrap interval of the Brier difference against (b) and against (c)
  excludes zero. A difference of about 0.01 on about 256 games is not distinguishable from noise
  without it.

Parameter discipline:
- Tune on 2024 only. Freeze the chosen set. Evaluate 2025 once with the frozen set.
- Sigma is fitted from 2024 walk-forward residuals only and applied unchanged to 2025.
- Every configuration tried is written to `model_runs` with its parameters, so no tuning happens
  silently.
- The 2024 fit has no prior (no 2023 season is loaded). Its early weeks are reported as such.
- Selection rule for the 2024 tuning grid, fixed before running it: primary criterion is 2024
  Brier score over weeks 2-18; log loss is the secondary check; when two configurations tie to
  three decimals, the one with the fewer non-default parameters wins.
- Prior parameters (`prior_games`, prior shrink) have no effect on 2024, which has no prior. They
  stay at the spec defaults (4 and one third) and are not tuned. Tuning them would need 2025 and
  would spend the holdout.
- `h` stays fitted in the gated run. Its season-to-season values are reported; the fixed-`h`
  question is answered descriptively unless a fixed value can be chosen without 2025.

### 6.2 Seeding validation
Run the seeding engine on the 2024 and 2025 final regular-season standings (real results, no
simulation). It must reproduce the published 14 seeds (7 per conference) in both seasons, 28 of 28.
Paste the comparison. Any mismatch blocks the merge.

### 6.3 Simulation sanity
- The sum over teams of `p_playoffs` equals 14.00 (within 0.01) in every run; `p_seed_k` sums to
  1.00 per conference and seed. Assert it in code.
- Re-run with a different random seed: no team's `p_playoffs` moves more than 1.5 points at
  N = 20000.

---

## 7. Storage

All tables in the dev DB, created by one migration script `backend/migrate_nfl_model_tables.py`
(idempotent, `CREATE TABLE IF NOT EXISTS`). Columns not shared with any other migration.

- `model_runs(run_id, league, season, week, model, model_version, started_at, finished_at,
  params_json, status, error)`
- `team_ratings(run_id, league, season, week, team, off, def, overall, games, as_of)`
- `game_projections(run_id, league, game_id, season, week, home, away, proj_home, proj_away,
  proj_margin, proj_total, p_home_win, market_spread, market_total, market_source, locked,
  locked_at)` with a unique index on `(league, game_id, locked)` where `locked = 1` so only one
  locked row can exist per game.
- `playoff_odds(run_id, league, season, week, team, p_playoffs, p_division, p_bye, p_seed_1 ...
  p_seed_7, wins_mean, wins_p10, wins_p90, d_playoffs, as_of)`
- `projection_grades(league, game_id, model_version, actual_home, actual_away, brier, logloss,
  margin_err, total_err, ats_result, graded_at)`

---

## 8. Jobs, API, page

### 8.1 Weekly job `backend/jobs/nfl_weekly_model.py`
Order: (1) assert schedule fresh (A0 check), (2) fit ratings, (3) write and lock projections for
the coming week's games, (4) simulate, write playoff odds, (5) grade every newly final game, (6)
write the movers JSON to `data/news/nfl_playoff_movers_<season>_w<week>.json`, (7) record the run
in `model_runs` with `status`.
- Timer: `systemd` `OnCalendar=Tue 10:00 America/Chicago` and `Thu 12:00` (Thursday re-run picks up
  late lines; it never overwrites a locked projection). Any failure exits non-zero and appears on
  the desk/alert path (fail-loudly).
- A `--season --week` flag re-runs any past week for the backtest and for repairs.

### 8.2 API (new router `backend/routers/models/nfl.py`)
- `GET /api/nfl/playoff-odds?season=&week=` (latest run if no week). Includes `as_of`,
  `model_version`, `run_id`.
- `GET /api/nfl/ratings?season=&week=`
- `GET /api/nfl/game-projections?season=&week=` (locked rows, with results and grades when final).
- `GET /api/nfl/model-record?season=` (the public grading summary: Brier, log loss, MAE, ATS,
  calibration bins, per-week table).
- Every response carries `X-LP-Data-Source` like the existing routers.

### 8.3 Page
A "Playoff odds" view (new tab in `pages/standings.tsx` or `pages/nfl/playoff-odds.tsx`; follow the
league-card design: one panel per conference with divisions inside, hairline rows, no box per item;
`docs` design principles). Per team: odds, change since last week (up/down), projected wins. A
second section: this week's game projections next to the market line. A third: the model's record
(section 2.3), including losses. Every number shows `as of` and model version. Follow
`honest-data-ui`: the accent colour marks absence (a missing line, an unscored game), never
achievement. Mobile first.

---

## 9. Version 2 and later (do not build now)
- Efficiency ratings from nflverse play-by-play EPA per play (offense and defense, pass and rush),
  regressed toward the mean, blended with the points model. Gate: must beat version 1 in the 6.1
  backtest.
- Quarterback adjustment: when the starting QB in `nfl_schedule.away_qb_id/home_qb_id` (published)
  differs from the team's regular starter, apply a QB value delta. Comes from SPEC B's availability
  layer.
- Roster delta from SPEC B (players out move the team rating).
- Kalshi game and playoff-market prices as the market comparison (we capture Kalshi tape already).
- Other leagues: NCAAF (bowl/CFP), NBA, NHL on the same tables.

---

## 10. Slices and acceptance (hand these out in order)

| Slice | Owner suggestion | Done when (paste the evidence) |
|---|---|---|
| A0 schedule ingest fix + timer + stale-score alert | Codex | All final 2026 games scored; reconcile counts pasted; timer listed with `OnCalendar`; alert fires when a score is withheld in a test. |
| A1 `nfl_teams` | Codex | 32 rows for 2026, codes reconcile with `nfl_schedule`. |
| A2 migration + ratings fit + game projection + lock | Codex | Unit tests; fitted `mu`, `h`, `sigma` reported; week-5 projections printed. |
| A3 backtest harness (6.1) | Codex | Tables for 2024, 2025, pooled; parameters chosen and why. |
| A4 seeding + tiebreakers (5.2-5.3) | Codex | 28 of 28 seeds reproduced (6.2). |
| A5 simulation + odds + sanity asserts (5, 6.3) | Codex | Sum checks pass; two-seed stability check pasted; runtime. |
| A6 weekly job + timer + grading + movers JSON | Codex | One full run recorded in `model_runs`; grades written for weeks 1-4; JSON file shown. |
| A7 API router + tests | pi or Codex | Endpoint responses pasted; tests pass. |
| A8 page | pi | Screenshot at phone and desktop width; the record section shows real graded rows. |

Each slice: its own commit with a message saying what and why; the report lists the files touched
and pastes test output. Stop and report if a gate fails; do not tune parameters to pass a gate
without saying so.
