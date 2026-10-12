# Index: NFL model research, where everything is (2026-10-12)

Read this first. It lists every lever and stat we have considered, what happened to it, where the data
is, and where the code and results are. Update the status column when something changes.

## 1. Levers for the game model (Brier against the benchmark ladder)

Source plan: [RESEARCH-nfl-model-inputs-2026-10-11.md](RESEARCH-nfl-model-inputs-2026-10-11.md).

| Lever | Status | Result | Where |
|---|---|---|---|
| Offseason carryover (shrink, prior games) | tested, no change | 21 settings, none passes the rule on 2024 and 2025 | [RESULTS-nfl-ladder-carryover-2026-10-12.md](RESULTS-nfl-ladder-carryover-2026-10-12.md), `backend/nfl_ladder.py` |
| Preseason market prior | tested, kept | +0.0055 Brier gain, market-derived, so not our own forecast | [RESULTS-nfl-features-vs-market-2026-10-11.md](RESULTS-nfl-features-vs-market-2026-10-11.md) |
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
per-season spread is shown, not pooled, because the r moves a lot from one year to the next. Source:
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
subset, so none of these are in the DB yet.

| Idea | Published columns (nflverse pbp) | Stored? | Notes |
|---|---|---|---|
| Penalties | `penalty`, `penalty_team`, `penalty_yards`, `penalty_type`, `penalty_player_id`, `first_down_penalty` | yes: `penalty`, `penalty_team` (not yards or type) | the referee is in `nfl_schedule.referee` (check its coverage first) |
| Turnover luck | `fumble_lost`, `interception`, `fumble` | yes: all three | new idea, untested; test whether fumble and interception rates carry over before adjusting ratings |
| Third-down and drive luck | `third_down_converted`, `third_down_failed`, `drive_time_of_possession`, `drive_play_count` | no | new idea, untested |
| Pass rate over expected | `xpass`, `pass_oe` | no | new idea, untested |
| Yards after catch and expected EPA | `yards_after_catch`, `xyac_epa` | no | new idea, untested |
| Win probability and field goal probability | `vegas_wp`, `fg_prob` | no | probably not needed (market-derived) |
| Participation (formations, personnel, defenders in the box, coverage) | not in the nflverse pbp file; a separate release | yes: `nfl_hist_participation`, 2016 to 2025 (10 seasons), keyed on `(nflverse_game_id, play_id)`; columns `was_pressure`, `defense_man_zone_type`, `defense_coverage_type`, `defenders_in_box`, `number_of_pass_rushers`, `time_to_throw`, personnel and formation | pressure and coverage matchups tested, not kept (section 1); coverage labels are null through 2017 and unlabelled sacks through 2022 |
| Time to throw, Next Gen Stats | not in the pbp file; separate release | no | which seasons are covered is **not checked** |

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
   enough to carry into a model. Participation is not tested.
5. **Spec B** (player projections), **start on the Spec B branch, not on this one.** Branch
   `feat/player-projections-availability`, worktree `/root/lp-player-proj`. Its work is B1 to B3
   (10 commits not in `dev`, plus 1 uncommitted doc). Order:
   a. Review findings (`docs/REVIEW-SPEC-player-projections-availability-2026-10-10.md`). Status
      2026-10-12: the five findings (partial snap feed, refresh never rebuilds, log-only player-games,
      splits universe, stale team-file cache) are addressed in commit `fd9ad96`, with tests. The
      focused suite passes, 52 tests. **Still open:** the B2 air-yards denominator (355 of 355 2026
      season rows differ from the team-game totals, ARI 935 vs 944), and the real 2025 WR1-out example
      for B3. Both need the dev DB rebuild from a fresh publisher file.
   b. Read `docs/SPEC-player-projections-availability-2026-10-09.md` sections 2 and 4 only.
   c. Use the target and carry shares from this branch as inputs. Do not rebuild them here.
   d. The checklist before anything goes to `dev` is in `docs/HANDOFF-nfl-model-2026-10-11.md`
      (Task 4.4 and "Before anything goes to dev").

Open decisions for Micah:
- Schedule the weekly pbp ingest in `dev`: `scripts/nfl-availability.sh` on branch
  `feat/nfl-epa-efficiency` has the step (Tuesday 09:30); `dev` does not.
- Push `dev` (local, 58 commits ahead of origin's `dev`, not pushed) and this branch.
- Recurring line capture and the Sam recorder (approved 10-11, not set up).

## 5. Where the code and the branches are

| Thing | Location | Status |
|---|---|---|
| Model harness, features | `backend/nfl_feature_backtest.py` on `feat/nfl-model-foundation` | committed `cde089a` |
| Ladder and carryover | `backend/nfl_ladder.py` on `feat/nfl-model-foundation` | committed `f3b5dda` |
| Model page (v1 locks) | `dev` | merged 10-12, live on :3096 `/leagues/nfl?tab=model` |
| Spec A doc (v1 and v2 separate) | `dev` | merged 10-12 (`8d7840f`) |
| Old EPA blend (retired) | branch `feat/nfl-epa-efficiency` | worktree removed; code kept on branch only |
| Old EPA blend result and review | `dev` (docs only) | archived 10-12 (`3e5d3cc`) |
| Spec B (player projections) | branch `feat/player-projections-availability`, worktree `/root/lp-player-proj` | 10 commits not in dev, 1 uncommitted doc |
| NFL ratings, grading, tiebreakers | worktree `/root/lp-nfl-ratings` | **keep**: 31 uncommitted entries (10-12), 6 not in dev (`nfl_grading.py`, `nfl_tiebreaker_data.py`, their tests, model systemd unit and timer) |
| All Day lineups (not model) | worktree `/root/lp-nfl-allday` | unrelated to the model |
| Clean worktrees with nothing unique | `/root/lp-nfl-data-foundation`, `/root/lp-nfl-schedule-a0` | safe to remove, not removed yet |

## 6. Rules that apply to all of this

- Pre-registered rules are written before the run. Parameters are fixed in the docstring first.
  Do not loosen a rule after seeing a result.
- Keep rule for features: pooled 2011 to 2023 interval entirely below zero, and the 2024 and 2025
  point differences not above zero.
- The dev DB is read-only for analysis. Backfills write only the added columns, keyed on
  `(game_id, play_id)`. Never `ingest_nfl_pbp_logs.py --year` on past seasons.
- Check RAM before batch work (available memory has been about 1 GiB).
- Pushes and merges into `dev` only when asked.
