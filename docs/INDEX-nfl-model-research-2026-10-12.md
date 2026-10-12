# Index: NFL model research, where everything is (2026-10-12)

Read this first. It lists every lever and stat we have considered, what happened to it, where the data
is, and where the code and results are. Update the status column when something changes.

## 1. Levers for the game model (Brier against the benchmark ladder)

Source plan: [RESEARCH-nfl-model-inputs-2026-10-11.md](RESEARCH-nfl-model-inputs-2026-10-11.md).

| Lever | Status | Result | Where |
|---|---|---|---|
| Offseason carryover (shrink, prior games) | tested, no change | 21 settings, none passes the rule on 2024 and 2025 | [RESULTS-nfl-ladder-carryover-2026-10-12.md](RESULTS-nfl-ladder-carryover-2026-10-12.md), `backend/nfl_ladder.py` |
| Preseason market prior | tested, kept | +0.0055 Brier gain, market-derived. **Micah 10-12: not our forecast.** Our own model is v1 plus EPA by unit | [RESULTS-nfl-features-vs-market-2026-10-11.md](RESULTS-nfl-features-vs-market-2026-10-11.md) |
| EPA per play by unit (v2 stack column) | tested, kept (marginal) | +0.0019 gain, 2011 to 2023 | same as above |
| Rating uncertainty (sigma by week) | tested, not kept | 0 change | same as above |
| Margin spread by game | covered by the rating uncertainty test | not kept | same as above |
| QB relative to team baseline (QBI) | tested, not kept | -0.0001 | [RESULTS-nfl-backfill-features-2026-10-11.md](RESULTS-nfl-backfill-features-2026-10-11.md) |
| Availability (AVAIL, snap share) | tested, not kept | -0.0001 | same as above |
| Special teams EPA | tested, not kept | +0.0006 | [RESULTS-nfl-features-vs-market-2026-10-11.md](RESULTS-nfl-features-vs-market-2026-10-11.md) |
| Venue, rest and wind | tested, not kept | +0.0003 | same as above |
| Pressure matchup (QB hit rate) | tested, not kept | -0.0002 | [RESULTS-nfl-matchup-features-2026-10-12.md](RESULTS-nfl-matchup-features-2026-10-12.md) |
| Sack matchup | tested, not kept | +0.0001 | same as above |
| Share-weighted absence | tested, not kept | -0.0000 | same as above |
| Turnover margin, season to date (takeaways minus giveaways per game, shrunk 8 games) | tested, not kept | F-B 2011-2023 +0.0002 [-0.0001, +0.0004]; 2024 -0.0001; 2025 +0.0000 | `turnover_margin` in `nfl_feature_backtest.py`, run 2026-10-12 |
| Penalties committed, season to date (per game, shrunk 8 games) | tested, not kept | F-B 2011-2023 +0.0000 [-0.0003, +0.0004]; 2024 +0.0008; 2025 -0.0006. Re-run after a fix (a team with no games to date now sits at the league average, as the registration says; 2 of 4,175 games changed, both in 2017 week 2) | `penalty_rate` in `nfl_feature_backtest.py`, run 2026-10-12 |
| FTN blitz, season to date (blitzers per dropback, shrunk 8 games). Variant A: fit 2022-23, grade 2024-25. Variant B: fit 2022, grade 2023-25 | tested, not kept (both) | A: F-B +0.0001 [-0.0001, +0.0003]; B: -0.0002 [-0.0009, +0.0005]. Fitted coefficient flips sign (A -0.99, B +3.84) | `ftn_keep_test` in `nfl_feature_backtest.py`, run 2026-10-12 |
| Independent preseason prior (last season's EPA per play, shrunk; no market data) | tested, not kept | F-B 2011-2023 -0.0008 [-0.0017, +0.0002]; 2024 +0.0007; 2025 +0.0016 | `preseason_prior` in `nfl_feature_backtest.py`, run 2026-10-12 |
| Participation pressure matchup (charted pressure, sacks count; 2016 to 2025) | tested, not kept | F-B 2017-2023 -0.0003 [-0.0010, +0.0005]; 2024 +0.0008; 2025 +0.0002 | `participation_keep` in `nfl_feature_backtest.py`; [RESULTS-nfl-participation-2026-10-12.md](RESULTS-nfl-participation-2026-10-12.md) |
| Participation coverage matchup (man vs zone, same season, sacks excluded; 2018 to 2025) | tested, not kept | F-B 2019-2023 +0.0002 [-0.0002, +0.0006]; 2024 -0.0001; 2025 +0.0000 (positive at full precision) | `coverage_keep` in `nfl_feature_backtest.py` (definition and tests in `test_nfl_participation_features.py`); [RESULTS-nfl-participation-2026-10-12.md](RESULTS-nfl-participation-2026-10-12.md) |
| Contention, has this team checked out (simulated P(playoffs) < 1%, home minus away; weeks 10+; 2010 to 2025) | tested, not kept | F-B 2011-2023 -0.0006 [-0.0017, +0.0006]; 2024 -0.0046 [-0.0089, -0.0003]; 2025 -0.0003 | `contention_keep` in `nfl_feature_backtest.py` (tests in `test_nfl_contention.py`); [RESULTS-nfl-participation-2026-10-12.md](RESULTS-nfl-participation-2026-10-12.md) |

## 2. Stats: stability and status

Stability = first half of a season against the second half (r). Each season is its own test: the
per-season spread is shown, not pooled, because the r moves a lot from one year to the next.

**Which split (Micah, 10-12: early season and late season differ, many teams check out).** Measured
10-12, 2010 to 2025, median r across seasons, team level. Computed by a read-only query in that
session, not a committed script; re-derive before citing a number to two decimals.

| Stat | 1st v 2nd half | odd v even weeks | wk 1-4 v last 4-5 | wk 5-8 v 9-12 | season to season |
|---|---|---|---|---|---|
| Offense EPA/play | +0.58 | +0.59 | +0.42 | +0.36 | +0.39 |
| Turnover margin | +0.17 | +0.17 | +0.09 | +0.06 | +0.21 |
| Giveaways | +0.21 | +0.17 | +0.10 | +0.07 | +0.16 |
| Takeaways | +0.09 | +0.07 | +0.08 | +0.04 | +0.14 |
| Penalties | +0.78 | +0.79 | +0.66 | +0.61 | +0.86 |
| Pressure, charted (2016+) | +0.33 | +0.41 | +0.24 | +0.21 | +0.36 |
| Man share (2018+) | +0.71 | +0.81 | +0.65 | +0.53 | +0.48 |

Read: first quarter v last quarter is no less similar than the two middle quarters (same 4-week size),
so the late-season change does not show up as a change in team rank. Odd v even is the cleaner split
(both halves span the season); it reads a little higher for pressure and man share. Turnover luck is
near zero under every split. The late-season effect is a level change, which r cannot see, so it was
tested directly as the contention feature (section 1, not kept). The keep tests never used this split.

Source for the table below:
[RESULTS-nfl-stability-stats-2026-10-12.md](RESULTS-nfl-stability-stats-2026-10-12.md).

| Stat | Stored in dev DB? | Stability r, per season: median (min to max) | Predictive test | Note |
|---|---|---|---|---|
| Target share (per player) | derivable from `nfl_pbp` | +0.71 (+0.62 to +0.77) | not yet (Spec B first) | input for player props |
| Carry share (per player) | derivable from `nfl_pbp` | +0.75 (+0.65 to +0.83) | not yet | input for player props |
| Receiving TD share | derivable | +0.30 (+0.16 to +0.47) | not yet | noisy, do not weight |
| Rushing TD share | derivable | +0.46 (+0.26 to +0.56) | not yet | noisy |
| Pressure generated (`qb_hit` per dropback) | yes, since 10-11/12 | +0.34 (+0.02 to +0.50) | tested, not kept | weak carryover |
| Sack rate allowed | yes (`sack`) | +0.35 (+0.11 to +0.61) | tested, not kept | |
| QB scramble rate | yes, since 10-11/12 | +0.69 (+0.49 to +0.89) | not tested alone | team style |
| No-huddle rate | yes, since 10-11/12 | +0.83 (+0.53 to +0.96) | not tested | team style, probably totals not margin |
| Penalties committed per game | yes, 2010 to 2025 (`penalty`, `penalty_team`) | +0.79 (+0.70 to +0.89) | tested, not kept | very stable; the penalty, turnover, giveaway and takeaway r values are not in the stability RESULTS file and no committed script computes them |
| Turnover margin per game | yes, 2010 to 2025 (`fumble_lost`, `interception`) | +0.17 (-0.38 to +0.45) | tested, not kept | weak, unstable |
| Giveaways per game / takeaways per game | yes, same columns | +0.21 / +0.11 (medians) | not tested alone | takeaways range -0.12 to +0.49 |
| Blitz rate, pass rushers, QB out of pocket, QB-fault sacks | FTN, 2022 to 2025 only (`nfl_hist_ftn_charting`) | not measured | not tested | about 1,100 games, keep feature count small |

## 3. Stats not yet in the model: published, not stored

Checked 2026-10-12 against the 2024 nflverse play-by-play file (372 columns). `nfl_pbp` stores a curated
subset. Since then penalties, turnovers and participation were stored (the Stored column says which).

| Idea | Published columns (nflverse pbp) | Stored? | Notes |
|---|---|---|---|
| Penalties | `penalty`, `penalty_team`, `penalty_yards`, `penalty_type`, `penalty_player_id`, `first_down_penalty` | yes: `penalty`, `penalty_team` (not yards or type) | the referee is in `nfl_schedule.referee` (check its coverage first) |
| Turnover luck | `fumble_lost`, `interception`, `fumble` | yes: all three | new idea, untested; test whether fumble and interception rates carry over before adjusting ratings |
| Third-down and drive luck | `third_down_converted`, `third_down_failed`, `drive_time_of_possession`, `drive_play_count` | no | new idea, untested |
| Pass rate over expected | `xpass`, `pass_oe` | no | new idea, untested |
| Yards after catch and expected EPA | `yards_after_catch`, `xyac_epa` | no | new idea, untested |
| Win probability and field goal probability | `vegas_wp`, `fg_prob` | no | probably not needed (market-derived) |
| Participation (formations, personnel, defenders in the box, coverage) | not in the nflverse pbp file; a separate release | yes: `nfl_hist_participation`, 2016 to 2025 (10 seasons), keyed on `(nflverse_game_id, play_id)`; columns `was_pressure`, `defense_man_zone_type`, `defense_coverage_type`, `defenders_in_box`, `number_of_pass_rushers`, `time_to_throw`, personnel and formation | pressure and coverage matchups tested, not kept (section 1); coverage labels are null through 2017 and unlabelled sacks through 2022 |
| Time to throw, Next Gen Stats | not in the pbp file; `time_to_throw` is in the participation release | yes, in `nfl_hist_participation`, 2016 to 2025, about 38 to 44% of rows filled (measured 10-12) | the NGS release itself is not checked; untested |

## 4. Next, in the order we agreed

1. ~~**Week 6 locks** before Thursday 10-15 20:15 ET~~ **Skipped on Micah's instruction (2026-10-12).**
   Locks stay out of this list until he says otherwise.
2. **Independent preseason prior.** Status 2026-10-12: pre-registered in `nfl_feature_backtest.py`
   as `preseason_prior` (last season's EPA per play, offense minus defense, shrunk by n / (n + 400)).
   Its formula has 4 passing tests (`backend/test_nfl_preseason_prior.py`). **Run 2026-10-12: not
   kept.** The pooled 2011-2023 interval includes zero, and 2024 and 2025 are both above zero. The 2010
   games (256) have no prior season in the data and carry 0, which feeds the stack's training rows.
   QB change, coach change and returning starters are left out, and each would be its own pre-registered feature.
   **Per-season diagnostic (2026-10-12, not a keep rule; the keep rule stays pooled as pre-registered).**
   F-B by season, 2011 to 2025: 2011 0.0000 (the 2010 zero column leaves the stack no training signal);
   negative in 2014 to 2023 (2021 the largest at -0.0048, se 0.0016); positive in 2012 (+0.0039, se 0.0033),
   2013 (+0.0024), 2024 (+0.0007) and 2025 (+0.0016). Most seasons sit within about 1 to 2 se of zero. Built only from published data (last season's EPA by unit, regressed
   toward average; QB change from `home_qb_id`; coach change from `home_coach`; returning starters from
   snap counts). No market input. Tested on the same ladder and the same keep rule.
3. **Penalties and turnover luck.** Status 2026-10-12: done. Columns backfilled 2010 to 2025 (update only,
   dry run then apply, every season matched its stored plays). Stability is per season (see section 2).
   Both features were tested, pre-registered, and not kept. The original plan was: backfill the published columns the same update-only
   way as the QB columns, test stability, then test prediction on top of EPA.
4. **FTN and participation last**, because their sample is small. Status 2026-10-12: participation files
   exist for 2016 to 2025 (HTTP 200 on the nflverse release; 2010 to 2015 return 404), so 10 seasons, not
   16. FTN is stored for 2022 to 2025 (about 48k plays a season). **FTN blitz tested 2026-10-12, two
   pre-registered variants, both not kept.** Variant A fits 2022-23 and grades 2024-25; variant B fits 2022
   and grades 2023-25. The fitted coefficient changes sign between the two, so the feature is not stable
   enough to carry into a model. **Participation tested 10-12: pressure and coverage matchups, both not kept**
   ([RESULTS-nfl-participation-2026-10-12.md](RESULTS-nfl-participation-2026-10-12.md)). Coverage labels change in
   2023 (sacks labelled from then, league man share 29% in 2022, 41% and 49% in 2023-24, 31% in 2025), so the
   coverage test used shares relative to each season's league and a same-season window.
5. **Spec B** (player projections), **start on the Spec B branch, not on this one.** Branch
   `feat/player-projections-availability`, worktree `/root/lp-player-proj`. Its work is B1 to B3
   (11 commits not in `dev`, nothing uncommitted, 10-12). Order:
   a. Review findings (`docs/REVIEW-SPEC-player-projections-availability-2026-10-10.md`). Status
      2026-10-12: the five findings (partial snap feed, refresh never rebuilds, log-only player-games,
      splits universe, stale team-file cache) are addressed in commit `fd9ad96`, with tests. The
      focused suite passes (the "52" does not reproduce: 44 on the review's file list, 59 with the
      shares and identity tests, all passing, 10-12). **B2 cause measured 10-12 (`585d2dd`):** the season
      rows (now 378, not 355) differ from team totals by the no-receiver pass air yards (KC, BUF, DAL exact)
      and, for ARI and SEA, by 2026 week 5 games that are in the player logs but not yet in the team file
      or `nfl_pbp`. No rebuild yet; it waits on week 5 (see open decisions). **B3 done 10-12:** Puka Nacua
      out 2025 week 7 (injury report Out), Stafford with and without, in the review doc. One game.
   b. Read `docs/SPEC-player-projections-availability-2026-10-09.md` sections 2 and 4 only.
   c. Use the target and carry shares from this branch as inputs. Do not rebuild them here.
   d. The checklist before anything goes to `dev` is in `docs/HANDOFF-nfl-model-2026-10-11.md`
      (Task 4.4 and "Before anything goes to dev").

Decided by Micah 10-12: the market prior is not our forecast; no paying for timestamped odds; participation
tested; step 6 (contention) tested.

Open decisions for Micah:
- **2026 week 5 pbp:** only 1 of 15 games stored on 10-12 although nflverse had 14 (file updated 10-12
  09:05 GMT); BUF at LA plays 10-12 night. Agreed: ingest once on 10-13 morning, after nflverse updates.
- **Weekly pbp ingest in `dev`.** Nothing schedules it. The step exists only on `feat/nfl-epa-efficiency`
  (`ingest_nfl_pbp_logs.py --year`, INSERT OR REPLACE of whole rows). Three versions of that ingest exist:
  `dev`, this branch (writes `penalty`, `penalty_team`, `fumble`, `fumble_lost`) and `lp-nfl-ratings`
  (a small uncommitted edit). Order: land this branch's ingest in `dev`, reconcile the ratings edit, then
  add the step. Otherwise the weekly replace writes rows without the four columns. The `dev` timer
  `legendarypicks-nfl-availability` (Tue 09:30) is installed and had not fired yet on 10-12.
- Push `dev` (local, 58 commits ahead of origin's `dev`, not pushed) and this branch.
- Recurring line capture and the Sam recorder (approved 10-11, not set up).

## 5. Where the code and the branches are (inventory 2026-10-12, compared file by file with `dev`)

| Thing | Location | Status |
|---|---|---|
| Model research (harness, features, ladder, participation loader) | `feat/nfl-model-foundation`, worktree `/root/lp-nfl-lock-by-version` | 11 commits not in `dev` |
| Spec B (player projections) | `feat/player-projections-availability`, worktree `/root/lp-player-proj` | 11 commits not in `dev` |
| Model page (v1 locks), Spec A, seeding, sim, lock grader (`grade_nfl_locks.py`) | `dev` | merged 10-10 to 10-12 |
| NFL ratings WIP | worktree `/root/lp-nfl-ratings`, nothing committed | **keep, unique:** playoff-odds API (`routers/models/nfl.py`), `pages/nfl/playoff-odds.tsx`, `jobs/nfl_weekly_model.py` and its systemd unit and timer, `nfl_tiebreaker_data.py` (touchdowns for deep tiebreakers). **Overlaps `dev`:** 10 files (seeding, sim, lock, standings, bracket check, migrate, their tests, spec) that `dev` also changed after 10-10; needs a reconcile, not a plain commit. `nfl_grading.py` is superseded by `dev`'s `grade_nfl_locks.py` |
| Old EPA blend (retired) | branch `feat/nfl-epa-efficiency`, no worktree | 2 commits; only the weekly pbp step is worth taking (see open decisions) |
| All Day lineups (not model) | `feat/nfl-allday`, worktree `/root/lp-nfl-allday` | 4 commits never landed; product call |
| Identity publishers (July) | branch `codex/nfl-v1` | 4 commits never landed; `dev` split every file it touched into packages on 08-18; probably superseded |
| Prop market suffix fix | branch `feat/prop-repair` | 13-line fix never landed, no equivalent in `dev` (not NFL) |
| Already in `dev`, safe to remove | `lp-nfl-data-foundation`; `lp-nfl-schedule-a0` (both timer files byte-identical in `dev`); branches `feat/nfl-season-proj`, `feat/projections-nfl` (patch-equivalent), `feat/nfl-adp` (same subject landed 07-22), and 8 fully merged NFL branches | not removed yet; archive tag before deleting |

## 6. Rules that apply to all of this

- Pre-registered rules are written before the run. Parameters are fixed in the docstring first.
  Do not loosen a rule after seeing a result.
- Keep rule for features: pooled 2011 to 2023 interval entirely below zero, and the 2024 and 2025
  point differences not above zero.
- The dev DB is read-only for analysis. Backfills write only the added columns, keyed on
  `(game_id, play_id)`. Never `ingest_nfl_pbp_logs.py --year` on past seasons.
- Check RAM before batch work (available memory has been about 1 GiB).
- Pushes and merges into `dev` only when asked.
