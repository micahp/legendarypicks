# Index: NFL model research, where everything is (2026-10-12)

Read this first. It lists every lever and stat we have considered, what happened to it, where the data
is, and where the code and results are. Update the status column when something changes.

Reconciled 2026-10-19. The evidence table in section 7 classifies each data row and gives its artifact path and commit. Historical research gates are not adoption or production approvals. The active PROE row is preserved unchanged and excluded from the audit.

## 1. Levers for the game model (Brier against the benchmark ladder)

Source plan: [RESEARCH-nfl-model-inputs-2026-10-11.md](RESEARCH-nfl-model-inputs-2026-10-11.md).

| Lever | Status | Result | Where |
|---|---|---|---|
| Offense-EPA blend into v1 margin (old v2, `nfl_epa_efficiency.py`; ridge on team-game offensive EPA, blended walk-forward, weight tuned on a grid) | tested 10-09, **gate failed, not adopted, retired** | 2025 holdout (n 255): blend Brier 0.2304 vs v1 0.2287, margin MAE 10.73 vs 10.67; both lose to the market (0.2137). Pooled 2024+2025 favours the blend (0.2232 vs 0.2256) only because of 2024, which is why the holdout is the gate. Weeks 5-18: blend 0.2134 vs 0.2163; weeks 2-4: tie | [RESULT-nfl-epa-v2-2026-10-09.md](RESULT-nfl-epa-v2-2026-10-09.md), [REVIEW-nfl-epa-v2-2026-10-09.md](REVIEW-nfl-epa-v2-2026-10-09.md); code stays on branch `feat/nfl-epa-efficiency`. Superseded by the per-play model in `nfl_epa_model.py` |
| Team shotgun share differential (offense takes snaps from shotgun instead of under center; season to date, home minus away) | **untested** | The proposed team-level feature has not been run. This is separate from the league-wide shotgun era test below. | [RESEARCH-nfl-model-inputs-2026-10-11.md](RESEARCH-nfl-model-inputs-2026-10-11.md); [RESULTS-nfl-elo-and-era-2026-10-13.md](RESULTS-nfl-elo-and-era-2026-10-13.md) |
| Offseason carryover (shrink, prior games) | tested, no change | 21 settings, none passes the rule on 2024 and 2025 | [RESULTS-nfl-ladder-carryover-2026-10-12.md](RESULTS-nfl-ladder-carryover-2026-10-12.md), `backend/nfl_ladder.py` |
| Preseason market prior | tested, kept | +0.0055 Brier gain, market-derived. **Micah 10-12: not our forecast.** Our own model is v1 plus EPA by unit | [RESULTS-nfl-features-vs-market-2026-10-11.md](RESULTS-nfl-features-vs-market-2026-10-11.md) |
| EPA per play by unit (v2 stack column) | tested, historical research keep rule met (marginal) | +0.0019 gain, 2011 to 2023; this is not a serving or adoption verdict | same as above |
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
| `elo_diff` (538 Elo replica stacked on frozen v1 margin) | **SHIPPED to the Model tab as a research challenger; not the adopted baseline** | 2011-2023 Brier 0.2197; F-B -0.0032 [-0.0050, -0.0014]; the historical keep rule was met | [RESULTS-nfl-elo-and-era-2026-10-13.md](RESULTS-nfl-elo-and-era-2026-10-13.md); `backend/lock_nfl_elo.py` |
| League-wide shotgun era (level and slope) | **TESTED-WORSE; not kept** | `era_shift` Brier 0.2279, F-B +0.0050 [+0.0027, +0.0074] on 2011-2023; distinct from the untested team differential above | [RESULTS-nfl-elo-and-era-2026-10-13.md](RESULTS-nfl-elo-and-era-2026-10-13.md) |
| Success-rate differentials (pass and rush), also called consistency | **NO-GO; no established gain, not kept** | M0 EPA Brier 0.2243, M1 EPA plus success 0.2242; paired week-clustered interval spans zero. Success-only Brier 0.2275. | `docs/RESULTS-nfl-success-rate-and-distributions-2026-10-18.md` on `feat/nfl-success-rate-and-distributions` at `0440911980d5ed3f161fff7da274fc2e9f1554b8` |
| Joint score-pair distribution (nearest-neighbor sampler) | **TESTED; registered gate failed, not adopted** | On 2020-2025, winner Brier 0.2355 vs Normal 0.2285 and cover calibration SSE 0.3105 vs 0.2115; stop rule applied, no retuning | [RESULTS-A2-nfl-score-dist-2026-10-11.md](RESULTS-A2-nfl-score-dist-2026-10-11.md) |
| Independent Normal margin and total marginals | **TESTED; cover and over are not forecasts** | On 2023-2025, winner Brier 0.2243 vs constant 0.2474; cover 0.2646 vs 0.2498 and over 0.2634 vs 0.2499. This is not a joint score distribution. | `docs/RESULTS-nfl-success-rate-and-distributions-2026-10-18.md` on `feat/nfl-success-rate-and-distributions` at `0440911980d5ed3f161fff7da274fc2e9f1554b8` |
| History-window ablation for frozen v1 | **NO-GO; no wider arm met the registered keep rule** | Pooled 2013-2020 Brier differences were at most 0.0001 and intervals spanned zero; 2024 and 2025 holdouts did not qualify | `research/nfl/RESULT-nfl-history-window-2026-10-19.md` on `research/nfl-history-window-2026-10-19` at `8a591e72af967e457b9601a4432d058e02471b66` |

## 1b. Player-prop distribution research

| Item | Status | Result | Where |
|---|---|---|---|
| Existing rushing-carries distribution v1 | **NOT_ADOPTED; coverage gate failed** | CRPS improved, but 50/80/90% coverage moved farther from nominal in both seasons. It does not change the carry mean and remains a frozen research candidate. | `docs/RESULTS-nfl-rushing-carries-dist-v1.md` on `feat/nfl-rushing-carries-dist-v1` at `24d793c6fc10b0a0fee53b651aa1c8771eeca6db` |

## 2. Stats: stability and status

Stability = first half of a season against the second half (r). Each season is its own test: the
per-season spread is shown, not pooled, because the r moves a lot from one year to the next.

**Which split (Micah, 10-12: early season and late season differ, many teams check out).** Measured
10-12, 2010 to 2025, median r across seasons, team level. Computed by a read-only query in that
session, not a committed script. The alternate-split values below remain unverified; the stability
results artifact supports first-half versus second-half values only. Re-derive before citing these
numbers to two decimals.

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
| Target share (per player) | derivable from `nfl_pbp` | +0.71 (+0.62 to +0.77) | Spec B has since been built and evaluated; no isolated target-share lift test is reported | input for player props |
| Carry share (per player) | derivable from `nfl_pbp` | +0.75 (+0.65 to +0.83) | Spec B has since been built and evaluated; no isolated carry-share lift test is reported | input for player props |
| Receiving TD share | derivable | +0.30 (+0.16 to +0.47) | Spec B prop projections have separate evaluations; no isolated share lift test is reported | noisy, do not weight |
| Rushing TD share | derivable | +0.46 (+0.26 to +0.56) | Spec B prop projections have separate evaluations; no isolated share lift test is reported | noisy |
| Pressure generated (`qb_hit` per dropback) | yes, since 10-11/12 | +0.34 (+0.02 to +0.50) | tested, not kept | weak carryover |
| Sack rate allowed | yes (`sack`) | +0.35 (+0.11 to +0.61) | tested, not kept | |
| QB scramble rate | yes, since 10-11/12 | +0.69 (+0.49 to +0.89) | not tested alone | team style |
| No-huddle rate | yes, since 10-11/12 | +0.83 (+0.53 to +0.96) | not tested | team style, probably totals not margin |
| Penalties committed per game | yes, 2010 to 2025 (`penalty`, `penalty_team`) | +0.79 (+0.70 to +0.89), unverified one-off stability value | tested, not kept | the stability value has no committed script; the predictive result is recorded in the 10-12 context |
| Turnover margin per game | yes, 2010 to 2025 (`fumble_lost`, `interception`) | +0.17 (-0.38 to +0.45), unverified one-off stability value | tested, not kept | the stability value has no committed script; the predictive result is recorded in the 10-12 context |
| Giveaways per game / takeaways per game | yes, same columns | +0.21 / +0.11 (medians), unverified one-off stability values | not tested alone | the stability values have no committed script; takeaways range -0.12 to +0.49 in the original query |
| Blitz rate, pass rushers, QB out of pocket, QB-fault sacks | FTN, 2022 to 2025 only (`nfl_hist_ftn_charting`) | not measured for stability | blitz was tested in two variants and not kept; the other listed rates were not tested | about 1,100 games, keep feature count small |

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

Status note, 2026-10-19: this is a historical 2026-10-12 work queue, not a current execution order. Completed outcomes are recorded in sections 1 and 1b above.

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
5. **Spec B** (player projections), **historical instruction from 2026-10-12: start on the Spec B branch, not on this one.** The work has since been built and evaluated; see the player-prop rows in section 2 and the evidence table in section 7. Branch
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

Open decisions for Micah (historical snapshot from 2026-10-12; do not assume each is still pending):
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

## 4b. Idea: the shift from under center to shotgun, and combining features

Raised by Micah's friend, 10-13. The shotgun share of league plays went from 28.8% (2010) to 50.3% (2025),
so a team's style in that dimension is a candidate rating input, and a regime change in how the game is played
is the case where a fixed-weight model drifts. The league-wide era level/slope test was run and was worse;
the team-level differential described here remains untested. The data is already stored (`nfl_pbp.shotgun`,
2010 to 2026). Rules that apply before a team-level run, from section 6: write the definition and keep rule first.

Open design points, to settle before registering the test:
- Team shotgun rate season to date, shrunk like the others, versus the league's rate that season (a level shift
  moves every team, so a raw rate would mostly measure the year).
- Alone, and as a pair with EPA per play or pass rate. Combining features means fitting them together in the
  stack and grading the pair against each feature alone, on the same ladder and the same pooled 2011 to 2023 rule.
  Every pair tested counts against the keep rule, so the list of pairs is registered up front.
- Kept features so far are few (preseason market prior, EPA by unit). Most features here moved Brier by under
  0.001, so a combination needs a pooled interval entirely below zero to count.

## 5. Where the code and the branches are (inventory 2026-10-12, compared file by file with `dev`)

The inventory below is a dated snapshot. The current branch reconciliation is recorded in section 7.

| Thing | Location | Status |
|---|---|---|
| Model research (harness, features, ladder, participation loader) | `feat/nfl-model-foundation`, worktree `/root/lp-nfl-lock-by-version` | **Stale count:** fetched ref `f3b5ddae6caf16f7ae3a0ad22755623859d37b7d` has one commit outside current `origin/dev`, the second carryover grid, not eleven. The shared research harness is in dev. |
| Spec B (player projections) | `scratch/spec-b-rebase`, worktree `/root/lp-player-proj`; fetched ref `3768218647e3673877d6c6833068f380603e8ab2` | **Stale status:** this ref is an ancestor of `origin/dev` at `d007e540609e7ca241b82d3416499addf6a17603`; the 10-12 “not in dev” inventory no longer applies. Spec B result docs are now in dev. |
| Model page (v1 locks), Spec A, seeding, sim, lock grader (`grade_nfl_locks.py`) | `dev` | merged 10-10 to 10-12 |
| NFL playoff odds and team ratings (from the 10-10 ratings WIP) | merged into `dev` in `6e45f28e` | **Stale status corrected:** API, odds-only job, page and repo timer/service files are in dev. The timer/service are not installed. The old WIP is archived; see [PARKED-nfl-ratings-2026-10-12.md](PARKED-nfl-ratings-2026-10-12.md). |
| Old EPA blend (retired) | branch `feat/nfl-epa-efficiency`, no worktree | 2 commits. Its RESULT and REVIEW docs are in `dev`. Code (`nfl_epa_efficiency.py`, `nfl_tune_epa.py`, tests) and the weekly pbp step in `scripts/nfl-availability.sh` are only on the branch; the weekly pbp step is the one piece worth taking (see open decisions) |
| All Day lineups (not model) | `feat/nfl-allday`, worktree `/root/lp-nfl-allday` | 4 commits never landed; product call |
| Identity publishers (July) | branch `codex/nfl-v1` | **UNVERIFIED:** `origin/codex/nfl-v1` is absent and no artifact is reachable from dev or a pushed branch; the old local-branch note is not sufficient evidence. |
| Prop market suffix fix | branch `feat/prop-repair` | **UNVERIFIED:** `origin/feat/prop-repair` is absent and no artifact is reachable from dev or a pushed branch; retain this historical, non-NFL row. |
| Removed 10-12 (were already in `dev`) | worktrees `lp-nfl-data-foundation`, `lp-nfl-schedule-a0`; 15 local branches (incl. `docs/forecasting-north-star-2026-10-10`, superseded by `dev`'s rewrite `33fed50`, and `feat/job15-dst-published-adp`, landed); their origin copies are untouched | each branch tagged `archive/<branch>` first (`git branch <name> archive/<name>` restores it); the data-foundation worktree's 3 ignored run logs copied to `/root/lp-archive/2026-10-12/` |

## 6. Rules that apply to all of this

- Pre-registered rules are written before the run. Parameters are fixed in the docstring first.
  Do not loosen a rule after seeing a result.
- Keep rule for features: pooled 2011 to 2023 interval entirely below zero, and the 2024 and 2025
  point differences not above zero.
- The dev DB is read-only for analysis. Backfills write only the added columns, keyed on
  `(game_id, play_id)`. Never `ingest_nfl_pbp_logs.py --year` on past seasons.
- Check RAM before batch work (available memory has been about 1 GiB).
- Pushes and merges into `dev` only when asked.

## 7. Evidence reconciliation (2026-10-19)

`VERIFIED` means the cited result or state is reachable from `origin/dev` or a pushed branch. `UNVERIFIED` means the underlying measurement or artifact was not preserved or is not reachable. `STALE` marks a prior status superseded and corrected in the sections above. Counts cover every data row in sections 1, 1b, 2, 3 and 5, except the protected PROE row in section 3, which is unchanged and not assessed: **38 verified, 17 unverified, 8 stale; 63 rows assessed.**

| Section | Ledger row | Class | One-line evidence |
|---|---|---|---|
| 1 | Offense-EPA blend into v1 margin | VERIFIED | `docs/RESULT-nfl-epa-v2-2026-10-09.md` @ `3e5d3cc25a08bd0030545d5f099c077e15ba1137` records the failed 2025 holdout gate and retirement. |
| 1 | Team shotgun share differential | VERIFIED | `docs/RESEARCH-nfl-model-inputs-2026-10-11.md` @ `fe9b0c5046ee5bcb2cebd7f5bf968d818d1061eb` defines this as open; `docs/RESULTS-nfl-elo-and-era-2026-10-13.md` @ `c59ab7ead9777f6cf7b994a7d360780c5e9b6961` tests the distinct league-wide era variable. |
| 1 | Offseason carryover | VERIFIED | `docs/RESULTS-nfl-ladder-carryover-2026-10-12.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` reports both grids and that no setting meets the keep rule. |
| 1 | Preseason market prior | VERIFIED | `docs/RESULTS-nfl-features-vs-market-2026-10-11.md` @ `98b407a48f329f4ab06a1d32c3f5cc72fe48c8b8` identifies it as market-derived, not an independent forecast. |
| 1 | EPA per play by unit | VERIFIED | `docs/RESULTS-nfl-features-vs-market-2026-10-11.md` @ `98b407a48f329f4ab06a1d32c3f5cc72fe48c8b8` reports the marginal historical research keep result. |
| 1 | Rating uncertainty | VERIFIED | `docs/RESULTS-nfl-features-vs-market-2026-10-11.md` @ `98b407a48f329f4ab06a1d32c3f5cc72fe48c8b8` reports no pooled change. |
| 1 | Margin spread by game | VERIFIED | `docs/RESULTS-nfl-features-vs-market-2026-10-11.md` @ `98b407a48f329f4ab06a1d32c3f5cc72fe48c8b8` covers the uncertainty test and its not-kept result. |
| 1 | QB relative to team baseline (QBI) | VERIFIED | `docs/RESULTS-nfl-backfill-features-2026-10-11.md` @ `6971c0e481da93f43a94da7cf3a5e490ec5ff2bd` reports QBI not kept. |
| 1 | Availability (AVAIL) | VERIFIED | `docs/RESULTS-nfl-backfill-features-2026-10-11.md` @ `6971c0e481da93f43a94da7cf3a5e490ec5ff2bd` reports AVAIL not kept. |
| 1 | Special teams EPA | VERIFIED | `docs/RESULTS-nfl-features-vs-market-2026-10-11.md` @ `98b407a48f329f4ab06a1d32c3f5cc72fe48c8b8` reports its pooled and holdout outcomes. |
| 1 | Venue, rest and wind | VERIFIED | `docs/RESULTS-nfl-features-vs-market-2026-10-11.md` @ `98b407a48f329f4ab06a1d32c3f5cc72fe48c8b8` reports the feature was not kept. |
| 1 | Pressure matchup | VERIFIED | `docs/RESULTS-nfl-matchup-features-2026-10-12.md` @ `cde089abf24d31aa5357dd55a18f3ababfe1648d` reports pressure matchup not kept. |
| 1 | Sack matchup | VERIFIED | `docs/RESULTS-nfl-matchup-features-2026-10-12.md` @ `cde089abf24d31aa5357dd55a18f3ababfe1648d` reports sack matchup not kept. |
| 1 | Share-weighted absence | VERIFIED | `docs/RESULTS-nfl-matchup-features-2026-10-12.md` @ `cde089abf24d31aa5357dd55a18f3ababfe1648d` reports share absence not kept. |
| 1 | Turnover margin, season to date | VERIFIED | `docs/CONTEXT-nfl-2026-10-12-session.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` records the result; `backend/nfl_feature_backtest.py` @ `cde089abf24d31aa5357dd55a18f3ababfe1648d` contains the registered feature. |
| 1 | Penalties committed, season to date | VERIFIED | `docs/CONTEXT-nfl-2026-10-12-session.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` records the rerun after the no-games-to-date fix. |
| 1 | FTN blitz | VERIFIED | `docs/CONTEXT-nfl-2026-10-12-session.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` records both variants and the coefficient sign change. |
| 1 | Independent preseason prior | VERIFIED | `docs/CONTEXT-nfl-2026-10-12-session.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` records the pooled and holdout results. |
| 1 | Participation pressure matchup | VERIFIED | `docs/RESULTS-nfl-participation-2026-10-12.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` reports not kept. |
| 1 | Participation coverage matchup | VERIFIED | `docs/RESULTS-nfl-participation-2026-10-12.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` reports not kept and the 2025 positive point difference. |
| 1 | Contention | VERIFIED | `docs/RESULTS-nfl-participation-2026-10-12.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` includes the pre-registered contention result and failed keep rule. |
| 1 | `elo_diff` | VERIFIED | `docs/RESULTS-nfl-elo-and-era-2026-10-13.md` @ `c59ab7ead9777f6cf7b994a7d360780c5e9b6961` reports the test; `backend/lock_nfl_elo.py` @ `cb3245d5c43d8a2d701cf70e9c4c9da2b11ef733` calls it the fourth Model-tab model. |
| 1 | League-wide shotgun era | VERIFIED | `docs/RESULTS-nfl-elo-and-era-2026-10-13.md` @ `c59ab7ead9777f6cf7b994a7d360780c5e9b6961` reports the era level/slope test as worse. |
| 1 | Success-rate differentials / consistency | VERIFIED | `docs/RESULTS-nfl-success-rate-and-distributions-2026-10-18.md` @ `0440911980d5ed3f161fff7da274fc2e9f1554b8`, pushed on `feat/nfl-success-rate-and-distributions` at `dec84c6d3161891d68473461622a678a11379f0a`, reports intervals spanning zero. |
| 1 | Joint score-pair sampler | VERIFIED | `docs/RESULTS-A2-nfl-score-dist-2026-10-11.md` @ `64bb93e88ba7d57d674efa87be65737f585d81b6` records the failed gate and stop. |
| 1 | Independent Normal margin and total marginals | VERIFIED | `docs/RESULTS-nfl-success-rate-and-distributions-2026-10-18.md` @ `0440911980d5ed3f161fff7da274fc2e9f1554b8`, pushed on `feat/nfl-success-rate-and-distributions` at `dec84c6d3161891d68473461622a678a11379f0a`, distinguishes winner results from failed cover/over probabilities. |
| 1 | History-window ablation | VERIFIED | `research/nfl/RESULT-nfl-history-window-2026-10-19.md` @ `8a591e72af967e457b9601a4432d058e02471b66`, pushed on `research/nfl-history-window-2026-10-19` at the same SHA, reports no qualifying arm. |
| 1b | Rushing-carries distribution v1 | VERIFIED | `docs/RESULTS-nfl-rushing-carries-dist-v1.md` @ `24d793c6fc10b0a0fee53b651aa1c8771eeca6db`, pushed on `feat/nfl-rushing-carries-dist-v1` at the same SHA, reports NOT_ADOPTED after the coverage gate failed. |
| 2, alternate-split table | Offense EPA/play | UNVERIFIED | `docs/CONTEXT-nfl-2026-10-12-session.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` says the table came from a one-off query with no saved script; `docs/RESULTS-nfl-stability-stats-2026-10-12.md` @ `ab1a6639bd49c65d189ed26af427ce8fd774f700` does not contain these alternate splits. |
| 2, alternate-split table | Turnover margin | UNVERIFIED | `docs/CONTEXT-nfl-2026-10-12-session.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` says the table came from a one-off query with no saved script; the alternate-split values are absent from the committed stability result at `ab1a6639bd49c65d189ed26af427ce8fd774f700`. |
| 2, alternate-split table | Giveaways | UNVERIFIED | `docs/CONTEXT-nfl-2026-10-12-session.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` says the table came from a one-off query with no saved script; the alternate-split values are absent from the committed stability result at `ab1a6639bd49c65d189ed26af427ce8fd774f700`. |
| 2, alternate-split table | Takeaways | UNVERIFIED | `docs/CONTEXT-nfl-2026-10-12-session.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` says the table came from a one-off query with no saved script; the alternate-split values are absent from the committed stability result at `ab1a6639bd49c65d189ed26af427ce8fd774f700`. |
| 2, alternate-split table | Penalties | UNVERIFIED | `docs/CONTEXT-nfl-2026-10-12-session.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` says the table came from a one-off query with no saved script; the alternate-split values are absent from the committed stability result at `ab1a6639bd49c65d189ed26af427ce8fd774f700`. |
| 2, alternate-split table | Pressure, charted | UNVERIFIED | `docs/CONTEXT-nfl-2026-10-12-session.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` says the table came from a one-off query with no saved script; the alternate-split values are absent from the committed stability result at `ab1a6639bd49c65d189ed26af427ce8fd774f700`. |
| 2, alternate-split table | Man share | UNVERIFIED | `docs/CONTEXT-nfl-2026-10-12-session.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` says the table came from a one-off query with no saved script; the alternate-split values are absent from the committed stability result at `ab1a6639bd49c65d189ed26af427ce8fd774f700`. |
| 2, stability and status | Target share | STALE | `docs/RESULTS-nfl-stability-stats-2026-10-12.md` @ `ab1a6639bd49c65d189ed26af427ce8fd774f700` supports the stability statistic; `docs/RESULTS-nfl-decisions-2026-10-17.md` @ `2221161d2c8a6c74c3622d8e5b4867013183af2b` records later Spec B player-projection evaluation, superseding “not yet.” |
| 2, stability and status | Carry share | STALE | `docs/RESULTS-nfl-stability-stats-2026-10-12.md` @ `ab1a6639bd49c65d189ed26af427ce8fd774f700` supports the stability statistic; `docs/RESULTS-nfl-decisions-2026-10-17.md` @ `2221161d2c8a6c74c3622d8e5b4867013183af2b` records later player-projection evaluation, superseding “not yet.” |
| 2, stability and status | Receiving TD share | STALE | `docs/RESULTS-nfl-stability-stats-2026-10-12.md` @ `ab1a6639bd49c65d189ed26af427ce8fd774f700` supports the stability statistic; `docs/RESULTS-nfl-decisions-2026-10-17.md` @ `2221161d2c8a6c74c3622d8e5b4867013183af2b` records later TD projection evaluation, superseding “not yet.” |
| 2, stability and status | Rushing TD share | STALE | `docs/RESULTS-nfl-stability-stats-2026-10-12.md` @ `ab1a6639bd49c65d189ed26af427ce8fd774f700` supports the stability statistic; `docs/RESULTS-nfl-decisions-2026-10-17.md` @ `2221161d2c8a6c74c3622d8e5b4867013183af2b` records later TD projection evaluation, superseding “not yet.” |
| 2, stability and status | Pressure generated | VERIFIED | `docs/RESULTS-nfl-stability-stats-2026-10-12.md` @ `ab1a6639bd49c65d189ed26af427ce8fd774f700` reports the stability value; `docs/RESULTS-nfl-matchup-features-2026-10-12.md` @ `cde089abf24d31aa5357dd55a18f3ababfe1648d` reports no keep. |
| 2, stability and status | Sack rate allowed | VERIFIED | `docs/RESULTS-nfl-stability-stats-2026-10-12.md` @ `ab1a6639bd49c65d189ed26af427ce8fd774f700` reports the stability value; `docs/RESULTS-nfl-matchup-features-2026-10-12.md` @ `cde089abf24d31aa5357dd55a18f3ababfe1648d` reports no keep. |
| 2, stability and status | QB scramble rate | UNVERIFIED | `docs/RESULTS-nfl-stability-stats-2026-10-12.md` @ `ab1a6639bd49c65d189ed26af427ce8fd774f700` is descriptive only; no reachable predictive-test artifact for this standalone rate was found. |
| 2, stability and status | No-huddle rate | UNVERIFIED | `docs/RESULTS-nfl-stability-stats-2026-10-12.md` @ `ab1a6639bd49c65d189ed26af427ce8fd774f700` is descriptive only; no reachable predictive-test artifact for this standalone rate was found. |
| 2, stability and status | Penalties committed per game | UNVERIFIED | `docs/CONTEXT-nfl-2026-10-12-session.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` records the uncommitted stability query and the separate predictive result; the r value is not reproducible from a committed artifact. |
| 2, stability and status | Turnover margin per game | UNVERIFIED | `docs/CONTEXT-nfl-2026-10-12-session.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` records the uncommitted stability query and the separate predictive result; the r value is not reproducible from a committed artifact. |
| 2, stability and status | Giveaways / takeaways per game | UNVERIFIED | `docs/CONTEXT-nfl-2026-10-12-session.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` records these as one-off stability values; no committed script or result reproduces them. |
| 2, stability and status | FTN rates | STALE | `docs/CONTEXT-nfl-2026-10-12-session.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` records two blitz tests, both not kept; the table's blanket “not tested” status for blitz is corrected above. |
| 3 | Penalties | VERIFIED | `docs/CONTEXT-nfl-2026-10-12-session.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` records stored penalty fields; `docs/RESULTS-nfl-backfill-features-2026-10-11.md` @ `6971c0e481da93f43a94da7cf3a5e490ec5ff2bd` documents backfill reconciliation. |
| 3 | Turnover luck | VERIFIED | `docs/CONTEXT-nfl-2026-10-12-session.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` records stored turnover fields; `docs/RESULTS-nfl-backfill-features-2026-10-11.md` @ `6971c0e481da93f43a94da7cf3a5e490ec5ff2bd` documents the history data. |
| 3 | Third-down and drive luck | UNVERIFIED | The claimed 2024 nflverse PBP header/file is not present in dev or a pushed branch; `docs/RESEARCH-nfl-model-inputs-2026-10-11.md` @ `fe9b0c5046ee5bcb2cebd7f5bf968d818d1061eb` does not establish these publisher columns. |
| 3 | Yards after catch and expected EPA | UNVERIFIED | The claimed 2024 nflverse PBP header/file is not present in dev or a pushed branch; `docs/RESEARCH-nfl-model-inputs-2026-10-11.md` @ `fe9b0c5046ee5bcb2cebd7f5bf968d818d1061eb` does not establish these publisher columns. |
| 3 | Win probability and field goal probability | UNVERIFIED | The claimed 2024 nflverse PBP header/file is not present in dev or a pushed branch; `docs/RESEARCH-nfl-model-inputs-2026-10-11.md` @ `fe9b0c5046ee5bcb2cebd7f5bf968d818d1061eb` does not establish these publisher columns. |
| 3 | Participation | VERIFIED | `docs/RESULTS-nfl-participation-2026-10-12.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` records the stored release, seasons and row reconciliation. |
| 3 | Time to throw | VERIFIED | `docs/RESULTS-nfl-participation-2026-10-12.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc` records `time_to_throw` in the stored participation release and its coverage caveat. |
| 5 | Model research branch inventory | STALE | `origin/feat/nfl-model-foundation` @ `f3b5ddae6caf16f7ae3a0ad22755623859d37b7d` now has one unique commit, not eleven; `backend/nfl_feature_backtest.py` @ `cde089abf24d31aa5357dd55a18f3ababfe1648d` is in dev. |
| 5 | Spec B branch inventory | STALE | `origin/scratch/spec-b-rebase` @ `3768218647e3673877d6c6833068f380603e8ab2` is an ancestor of `origin/dev` @ `d007e540609e7ca241b82d3416499addf6a17603`; current prop result docs include `docs/RESULTS-nfl-marcel-and-calibration-2026-10-16.md` @ `441bb007e31650eab9fc750b6b19879041a1046b`. |
| 5 | Model page, Spec A, seeding, sim and lock grader | VERIFIED | `backend/routers/nfl_model.py` @ `9154b1165338b849d501b3f6df78121f6c33790c` and its lock API are in current dev. |
| 5 | NFL playoff odds and ratings | STALE | `backend/jobs/nfl_playoff_odds.py` and the API/page landed in dev in `6e45f28e`; `docs/HANDOFF-branch-cleanup-2026-10-13.md` @ `76f9ca111021da55cf2c3e1271e400d4692a4954` confirms the merge. |
| 5 | Old EPA blend | VERIFIED | `docs/RESULT-nfl-epa-v2-2026-10-09.md` @ `3e5d3cc25a08bd0030545d5f099c077e15ba1137` is in dev; code remains on pushed `feat/nfl-epa-efficiency` @ `1110654d02d9d9fcba06da886708c12c98f7d429`. |
| 5 | All Day lineups | VERIFIED | `docs/RESEARCH-nfl-allday-state-2026-07-27.md` is the dev record; pushed `feat/nfl-allday` @ `825d116c3eb0baea40fa750358dc180575c2be66` retains the four unmerged commits. |
| 5 | Identity publishers | UNVERIFIED | `origin/codex/nfl-v1` is absent; the only citation is the historical local-branch note in `docs/CONTEXT-nfl-2026-10-12-session.md` @ `1e29abe2fe0c43af9a95eb530c2e5940424446fc`. |
| 5 | Prop market suffix fix | UNVERIFIED | `origin/feat/prop-repair` is absent; the historical note in `docs/HANDOFF-branch-cleanup-2026-10-13.md` @ `76f9ca111021da55cf2c3e1271e400d4692a4954` cannot verify the missing branch artifact. |
| 5 | Removed 10-12 branches | VERIFIED | `docs/HANDOFF-branch-cleanup-2026-10-13.md` @ `76f9ca111021da55cf2c3e1271e400d4692a4954` records the archived refs and which work was already in dev. |
