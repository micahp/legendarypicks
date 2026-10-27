# NFL situational research matrix: every measurable nook and cranny

**Status:** Active research design; hypotheses to TEST, not facts or simulator multipliers.  
**Season scope:** 2010–2026 as eligible, with year-by-year feature coverage.  
**Rule-regime source:** [NFL-RULE-REGIME-REGISTRY-2010-2026.json](NFL-RULE-REGIME-REGISTRY-2010-2026.json) and [companion guide](NFL-RULE-REGIME-REGISTRY-2010-2026.md).

## North star

Investigate how **pregame circumstances** and **in-game state** change teams' decisions, event distributions, player usage and the final game score. Make each conditional model a measurable, chronologically validated part of the full-game simulator. Do not hard-code Monday/night/dome/turf/"must-win"/injury coefficients without evidence.

An exhaustive Cartesian decision tree is infeasible and mostly empty. Use **a factor registry + selective interactions + hierarchical partial pooling**. Keep the exact numerator/denominator, sample/cluster count and interval for every claimed tendency, including negative/null findings. Let the simulator select the appropriate posterior at each decision or event.

## The investigation registry

| ID | Factor family | Example distinctions/questions | Unit and candidate target | Current source | Availability/critical caveat |
|---|---|---|---|---|---|
| CAL-01 | Day of week | Monday vs Sunday vs Thursday; unusual Tuesday/Saturday | game; team points, margin, turnovers, pass share | nfl_schedule.weekday/gameday | Strong retrospective, but nonrandom scheduling |
| CAL-02 | Rest | 4 vs 6 vs 7 vs 10+ days; post-bye | game/team; points, EPA, injuries, pace | nfl_schedule.home_rest/away_rest | Compare relative rest, travel and opponent quality |
| CAL-03 | Kickoff slot | Noon, late afternoon, night; body-clock local time | game/drive; scoring and performance | gametime + stadium timezone | Need true timezone handling; national TV selection confounds |
| CAL-04 | Travel | Road, time zones crossed, distance, consecutive trips, short turnaround | game; team efficiency | venues, schedules, geodata | Build geographic fixture; timezone/venue changes |
| CAL-05 | Season moment | Weeks 1–3, late season, postseason; weeks since bye | team-game; strength variance | schedules/results | 2021 moved to 18-week format |
| TEAM-01 | Records | 2–4 vs 2–4, 5–1 vs 2–4; record difference vs quality | team-game; margin, scoring | schedule prior scored games; `nfl_elo_538` through 2020 | Record is noisy; condition on cutoff-safe opponent-adjusted strength; do not extend 538 coverage past 2020 |
| TEAM-02 | Form | 1/3/5-game weighted form, streaks, blowouts vs close games | team-game; team scoring | schedule, historical PBP | Use preceding games only; shrink early-season samples |
| TEAM-03 | Division/rivalry | Divisional rematch, familiarity, preceding head-to-head | game; margin, pace, strategy | div_game, schedule | Division may proxy quality/venue; no motivational multiplier |
| TEAM-04 | Playoff incentives | Clinch, eliminated, seeding, rest starters, winner-take-all | game; starters, usage, decisions | derived standings and schedule | Historical as-of playoff probabilities required |
| TEAM-05 | Coaching | Coach/OC/DC changes, tenure, home/road playcalling | game/play; pass share, fourth-down choices | schedule coach names + historical roster/coach join | Coaching changes need event dates and confounding treatment |
| MATCH-01 | Offense × defense | Run/pass efficiency, pressure, explosive, red zone by opponent | drive/play; points, event probabilities | nfl_pbp + chronologically fitted team rating | Must compare against v1 and opponent-adjusted baselines |
| MATCH-02 | Style interaction | High-pass offense vs high-blitz defense, slow vs fast tempo | play/drive; pace, turnovers | PBP, advanced charting | Coverage/blitz not uniformly recorded all years |
| QB-01 | Starter vs backup | Announced starting QB out, backup starts, replacement skill | game; pass rate, sack rate, score | `nfl_hist_depth_charts`, dated reports, roster history, PBP | The local depth history ends in 2024 and has no row publication time; the announced starter requires a cutoff-safe report. Actual postgame starter is NOT pregame information |
| QB-02 | Midgame QB change | Starter exits Q2; backup enters; offense response | in-game drive; success probability, pace | play IDs, QB attribution, participation | Selection bias: exits may be due to blowout/injury |
| QB-03 | Rookie/experience | Career starts, first season starter, returning from missed games | team-game/player-play; decision/outcome | player ID registry, career game logs | Count experience strictly before game |
| INJ-01 | QB availability | DNP/questionable/out, starter limited vs absent | team-game; score, sacks, playcalling | `nfl_hist_injuries`, dated reports, roster snapshots | 2009–2025 rows exist; 2025 lacks `date_modified`; missing status is unknown, not healthy; exact as-of provenance required |
| INJ-02 | Position groups | Multiple OL out; top WRs out; CB room depleted; RB committee | team-game/play; usage, points, pressure | injuries, expected roles, snap counts | Weight by pregame expected usage, avoid hindsight snaps |
| INJ-03 | Return to play | After concussion, ACL, missed weeks, snap limitation | player-game; attempts, performance | dated transactions, injury reports, snaps | Major selection and survivorship biases |
| PHASE-01 | Quarter | Q1 vs Q4 by team, offense/defense, close games vs garbage time | drive/play; EPA, explosive, turnovers | PBP qtr, game_seconds_remaining | Separate quarter effect from score/clock/possession |
| PHASE-02 | Score state | Up 7/14/21; down 7/14/21, tied; two-minute drill | play; pass/run, pace, 4th downs | PBP score_diff, down/clock | In-game-only feature; no pregame hindsight |
| PHASE-03 | Workload | Defensive snaps to date, possession length, prior drive, drive count | play/drive; explosive allowed, run/pass and fatigue | ordered PBP; lagged `nfl_hist_snap_counts` | Snap counts are postgame: only games completed before cutoff; Q4 fatigue needs score/game-state controls |
| PHASE-04 | Field | Own 5, midfield, red zone, goal-to-go, FG range | play/drive; event and scoring | PBP yardline_100/down/togo | Valid for time-of-play only, legal state reducer |
| DEC-01 | 4th down | Punt vs FG vs go, by yardline, to-go, score, time and team | **opportunity**; P(action) | PBP all fourth-down opportunities | Avoid only fitting taken kicks/tries; data denominator matters |
| DEC-02 | After TD | Kick or go for 2, by margin, clock and era | TD opportunity; choice+conversion | observed try data, rule registry | Explicit 2015 PAT and OT regimes; holdout untouched |
| DEC-03 | Overtime toss | Toss winner, kick/receive, home and coach choices | OT game; P(choice) and receiver | official gamebooks/source-linked toss registry | PBP lacks toss winner; record provenance |
| DEC-04 | Clock decisions | Team timeouts, spike, kneel, conserve clock and challenge | play/decision point | PBP + extra clock/replay data | Requires legal action eligibility and era |
| ST-01 | Kickoff | Landing-zone, touchback, return selection, onside | free kick; start spot and outcome | PBP, kick fixtures, rule registry | Critical 2011/2016/2018/2023/2024/2025/2026 shifts |
| ST-02 | Field goals | Distance × wind × time; attempt vs make/miss/block; 67-yard-plus attempt choice | fourth-down opportunity then attempt | PBP, special teams fixtures | Separate attempt selection from kick outcome; `yardline_100>=50` is roughly 67+ yard attempts, NOT 50-yard FG |
| ST-03 | Blocked kicks | FG/punt block, recovery, return and special penalties | kick opportunity; terminal outcome | classified blocked kicks | Existing measured 2022–25 outcome pool |
| VEN-01 | Surface | Natural grass, hybrid, artificial turf; surface changes | player-game/game; injuries, routes, yards | schedule.surface, venue history | Strong home-team/era confounding; no blanket turf benefit |
| VEN-02 | Roof | Closed dome, open stadium, retractable open/closed | game/play; passing, kicks, pace | schedule.roof | Roof state and stadium identity need normalization |
| VEN-03 | Weather | Forecast wind/temp/rain/snow, gusts and wind direction | game/kick/play; scoring, fg make | timestamped forecasts plus observed weather | Observed gametime weather is hindsight as pregame feature |
| VEN-04 | Elevation | High altitude, temperature & travel effects | game/team-play; stamina, kick distance | geocoded venue + schedule | Venue fixed effect confounded; measure separately |
| PLAYER-01 | Usage | Targets, carries, routes, snaps; opponent and context | player-game/play; prop distributions | weekly logs, `nfl_hist_snap_counts`, PBP | Snap counts are postgame and 28 PFR player IDs lack a GSIS crosswalk in the measured Dev snapshot; participation is not an individual-player snap feed |
| PLAYER-02 | Splits | WR on turf vs grass, dome vs outdoors, Monday vs Sunday | player-game; yards, catches, targets | schedule joined to player logs | Require sample size and shrinkage, avoid "9 games 8 wins" claims |
| PLAYER-03 | Matchup | DB vs WR, OL vs DL, coverage vs receiver route | player-play; contested catch, pressure | `nfl_hist_participation`, FTN charting, licensed tracking | Participation is 2016–2025 play-level charting with no individual player IDs; only 94.5% of its keys matched stored PBP in the measured Dev snapshot; coverage fields are sparse and change by season |
| ERA-01 | Rules | Before/after try, OT, kickoff, catch/replay changes | season regime; all dependent targets | rule registry & official NFL documents | Source and target regimes tracked separately |
| ERA-02 | Schedule structure | 16 vs 17 games, weeks 17 vs 18, new postseason | season; standings/rest/incentives | schedules, rule registry | Normalize season totals and weeks |
| MISC-01 | Officials | Referee/crew and penalty enforcement tendencies | game/play; foul rates | schedule referee + penalty logs | Small and nonrandom assignments; verify identity |

## Data availability and cutoff eligibility

The factor list above follows Agent 1's `docs/RESEARCH-SITUATIONAL-CHECKLIST-2026-10-26.md` at commit `c3dfd663`. Its broader inventory was checked against the local Dev database on 2026-10-26. The detailed counts below are from read-only queries against `/root/legendarypicks/backend/data/picks.dev.db`; they describe that database snapshot, not every nflverse release or a production database.

For `nfl_hist_injuries`, `nfl_hist_snap_counts`, `nfl_hist_participation`, `nfl_hist_ftn_charting`, and `nfl_hist_depth_charts`, every season file recorded in `nfl_hist_loads` has equal `file_rows` and `stored_rows` (17/17, 13/13, 10/10, 4/4, and 15/15 files respectively). This proves that the loaded rows match the downloaded files; it does not prove that a publisher file is complete, that a row was available before a historical kickoff, or that a join is complete. Prior audit found no preserved publisher acquisition timestamps for these historical files; `nfl_hist_loads.loaded_at` is LP's load time, not the file's original publication time.

| Local source | Measured presence and row/key coverage | What it can support | Pregame/time limitation |
|---|---|---|---|
| `nfl_hist_injuries` | 90,752 rows, 2009–2025; all rows have `gsis_id`. 10,934 rows have no `date_modified` and 30,243 have no `report_status`. All 6,068 rows in 2025 lack `date_modified`; 3,105 regular-season 2025 rows also lack `report_status`. | Historical injury-report features where status, player identity, week, and source timestamp are all usable. | The table has no row-level LP ingest/version timestamp. `date_modified` is absent in 2025 and must not be treated as a verified publication time without validating the source semantics. A missing status is unknown, not “available.” |
| `injury_reports` | 14,070 NFL rows for seasons 2024–2026; stored `ingested_at` values run from 2026-10-09 through 2026-10-20. `date_modified` is absent for 2025–2026 rows. | Current/retrospective source inspection and prospective snapshots when captured immutably. | `ingested_at` records when LP loaded a row, not when an old game’s report was available. This table alone cannot reconstruct historical injury-report versions. |
| `nfl_hist_snap_counts` | 324,612 rows, 2013–2025, including regular and postseason. Each regular-season year has 32 team codes. All rows have `pfr_player_id`; 7,067 of 7,095 distinct PFR IDs map to GSIS through `nfl_hist_player_ids` (28 unresolved). The 2012 publisher file is empty. | Prior-game player workload, role, and usage features after resolving the player crosswalk and reporting the unmatched population. | These are postgame observations. For a game cutoff, include only snap-count rows from games already completed and available by that cutoff. The target game’s snaps are leakage. |
| `nfl_hist_participation` | 478,989 unique `(nflverse_game_id, play_id)` rows, 2016–2025; no null key fields. 452,618 keys match `nfl_pbp` on `(game_id, play_id)` (94.5%); 26,371 do not. | Play-level formation/personnel and charting features, after explaining unmatched keys and measuring per-field, per-season completeness. | This table has no individual player IDs and is not a snap/participant list. Rows from the target game are in-game evidence only. `defense_coverage_type` is null for all 2016–2017 rows and partial from 2018 onward; time-to-throw is filled on roughly 38–44% of rows. Several fields jump from roughly 38% (`was_pressure`) and 76% (personnel) coverage through 2022 to near/at 100% in 2023–2025. Treat that as a source/coverage regime change; do not fill nulls as zero or pool without a year-specific audit. |
| `nfl_hist_ftn_charting` | 185,215 unique game-play rows, 2022–2025; all four season loads match their manifests. 176,711 keys match stored `nfl_pbp` (95.4%); 8,504 do not. | Recent play-level charting features after reconciling unmatched keys and checking field coverage and licensing. | Retrospective charting is not player participation or pregame information. Treat its 2022–2025 availability as a distinct source window, not a league-wide historical feature. |
| `nfl_hist_depth_charts` | 552,514 rows, 2010–2024; all 15 season files match their load counts. Every season has 32 club codes; `gsis_id` and `depth_position` are non-null in all stored rows. | Historical depth/rank as a role prior, with explicit week, team, position, and player-ID joins. | No row-level `published_at` or `ingested_at` is stored. Prior audit found week+1 charts align more closely with that game's starters (0.93–0.95) than same-week charts (0.88–0.91), but cannot establish whether the week+1 chart was published before or after the game; never shift a chart forward to improve starter agreement. A weekly row is not proof of the official active lineup. The 2025 publisher schema changed to dated snapshots and is not mapped here; no historical 2025–2026 rows are loaded. The mutable `nfl_depth_chart` table is not a substitute for a frozen as-of snapshot. |

### Previously tested dimensions

- The injury-aware expected-starter feature (`QBI`) and snap-weighted Out/Doubtful load (`AVAIL`) were tested against v1 and **not kept**. This is a result about those definitions and cohorts, not evidence that every injury or personnel effect is zero. See the [historical backfill results](../RESULTS-nfl-backfill-features-2026-10-11.md).
- Participation pressure/coverage and FTN blitz variants were tested and **not kept**. Re-register any changed definition, target, or cohort before retesting; report the prior result instead of presenting it as a new factor. See the [participation results](../RESULTS-nfl-participation-2026-10-12.md) and [NFL model research index](../INDEX-nfl-model-research-2026-10-12.md).

Other checklist inventory confirmed in this Dev snapshot: `nfl_schedule` contains 4,175 distinct regular-season games in 2010–2025; the local `nfl_pbp` table spans 2010–2026 (17 seasons, through Oct 25 in the checklist audit), and the checksummed nflverse parquet noted in the checklist provides fields missing from the database copy (kick, try, penalty-description, and roof fields). The schedule has weekday, kickoff, rest, venue, temperature, and wind fields. `nfl_elo_538` is present through 2020 only (16,810 rows total); do not treat it as a current or 2021–2026 rating feed. The Dev database currently has no `nfl_schedule_versions` table. Rain/snow/humidity, forecast vintages, travel coordinates, and full historical team/player table coverage remain source checks; table presence alone does not close them.

### Source-use rules

- Historical `nfl_hist_*` data is eligible for retrospective feature engineering only after season/type/key/field coverage is reported. It is eligible for a strict pregame replay only when the exact source version was observed by the replay cutoff.
- Preserve source season files, their SHA-256 values from `nfl_hist_loads`, row counts, and load times in the run manifest. Reconcile source keys to `nfl_pbp`, schedule, and the player crosswalk; report both matched and unmatched counts.
- For injuries, preserve dated report versions. A current injury row, an overwritten report, or a later LP `ingested_at` must not be backdated to simulate what was known before kickoff.
- For weekly depth charts, preserve the source publication time or a dated immutable snapshot. A rank-1 depth entry is a role signal, not a confirmed starter or inactive list.
- For snap counts and participation, construct pregame workload from games completed before cutoff only. Neither source gives license to use target-game participation as a pregame availability feature.
- Treat absent source rows, null status, null charting fields, and unresolved identities as distinct states. Do not convert any of them to zero, healthy, inactive, or a default player.

## Rules for the research engine

**Separate four types of model:**
1. **Choice**: `P(action | eligible opportunity, state, pregame context, rule regime)`; e.g. go for two, attempt FG, pass vs run, timeout, OT toss choice.
2. **Outcome**: `P(result | action, state, players, opponent, regime)`; e.g. conversion success, interception, kick block, yards gained.
3. **Exposure**: `P(player plays / receives target / carries | roster, situation)`; missing starter changes exposures across roles.
4. **Aggregate**: final points, margin, total, winners and player stat distributions implied by a legally complete simulated game.

**Avoid empty cells:** Put factors in a hierarchical model, test limited two-way interactions with real support, penalize higher-order interactions, compare against larger parent buckets, and publish effective sample sizes. Do not materialize every possible cross-product of 40 factors as an independent observed statistic.

**Chronology:** Every replay has one UTC information cutoff: the authentic v1 lock time when comparing with v1, otherwise a declared pre-kickoff time. Freeze the cutoff, feature snapshot, source hashes, model version, and rule-regime version before revealing the game's result. Classify each input as (a) strict as-of observed, (b) retrospective date-filtered, or (c) unavailable. Only (a) supports a fair historical forecast comparison. Retrospective backfills may support exploratory research but must not be represented as information available at the time.

Apply the following chronology at feature construction and evaluation:

1. **Use event time and observation time.** A prior game's result or play becomes eligible only after it was final and its source version was available by the cutoff. A later historical backfill does not prove that its contents were available then; `nfl_hist_loads.loaded_at` is LP's load time, not the publisher's historical release time. A schedule or injury value becomes eligible only from the immutable version observed by the cutoff. Do not use a current row's overwritten `ingested_at` as the historical version. The schedule-history integration interface is `pregame_snapshot.schedule_at(con, game_id, cutoff)`; if it has no version, refuse strict replay and label the run exploratory. The Dev database had no `nfl_schedule_versions` table at this audit, so do not claim its current schedule rows provide historical versions.
2. **Enforce per-feature cutoff rules.** Do not use postgame QB attribution, target-game snaps, target-game participation/charting, actual inactive lists published after the lock, observed final weather, or any target-game outcome as pregame input. Use forecast versions only when their issue time is at or before the lock. Same-day earlier games are usable only when their final result and source record predate the lock.
3. **Split chronologically, never by random play rows.** For each test game's cutoff, train only on eligible games completed before it. Keep every play, drive, player row, and score from a game in one fold. Use rolling-origin season folds; fit transformations and tune/shrinkage only on earlier training/development periods, and evaluate on the next untouched period. A tested period becomes development data after its result is used to change the model; reserve a later contiguous period for a one-time final report. Freeze feature definitions, fallback/shrinkage rules, and adoption criteria before opening that final period.
4. **Align baselines and preserve the denominator.** Record the authentic v1 lock timestamp, model version, and projected scores. If any is missing or later than the simulation cutoff, classify that game's v1 comparison as exploratory or exclude it from the fair cohort. Freeze S0, S1, and v1 forecasts before joining actual results. Preserve every seed, including invalid, blocked, tied, and unresolved runs; report full-run coverage and selection-bias sensitivity alongside metrics conditional on valid games. Use common random numbers only if seed construction preserves comparable draws across models; otherwise report independent Monte Carlo uncertainty.
5. **Keep the reserved 2026 two-point holdout sealed.** Do not inspect its outcomes for feature choice, calibration, rule decisions, or adoption. If an evaluation game overlaps the reserved cohort, exclude the relevant try-decision outcome from all tuning and report the holdout boundary explicitly. Prior NFL research used 2023 for try-policy selection and 2024–2025 as confirmation; do not call those years untouched confirmation for a later variant whose design was changed after seeing their results.
6. **Respect rule and data regimes.** Report each source-rule and target-rule regime separately before pooling. A historical outcome may enter a current-rule simulation only after the compatibility mapping is stated and tested. Do not interpret a season or source coverage change as a football effect.

**Causality:** 'Monday' and 'turf' correlations are not a causal effect, because teams, opponents, weather and TV scheduling differ. Injury analyses should compare pregame expected starters to actual status, control prior player/team quality and opponent, and use matched event studies where possible. A QB change during a blowout is not proof the injury caused the score differential.

**Regime compatibility:** Join each play/opportunity to the rule registry. Don't fit kickoffs or OT outcomes as one stationary 2010–2026 distribution. Run source→target legal-compatibility tests when historical plays are used in current-rule simulations.

## Required outputs per hypothesis

Store a versioned `research_cell` record with:
- `hypothesis_id`, `outcome_target`, `unit`, `opportunity_definition`, `factor_values`, `interactions`
- `start/end season`, `season_type`, `rule_regime_ids`, `team_ids/player_ids`, `game_ids`
- `eligible_count`, `numerator/denominator`, `distinct_games`, `distinct_teams`, `effective_sample_size`
- `baseline_probability_or_mean`, `fitted_estimate`, `confidence_or_posterior_interval`, `method`
- `source_hashes`, `cutoff_status`, `fit_fold`, `holdout_fold`, `schema/model_version`
- `Brier/log_loss` for decisions, `log_loss/CRPS/MAE` for outcomes as applicable, plus final-game changes
- `status` (`hypothesis`, `supported`, `null`, `rejected`, `insufficient_data`), and explicit uncertainty

## Concrete first investigations

1. **Monday night:** does weekday improve held-out team score beyond opponent strength, rest, travel, home field, time-of-day and team random effects? Report game counts per weekday and out-of-sample improvement, not raw win percentage alone.
2. **2–4 vs 2–4:** compare outcomes conditional on records, prior opponent-adjusted ratings, QB availability, and home field; shrink small matchup cells.
3. **Lost starting QB:** estimate changes in pass selection, sacks and team points for verified pregame absences; separately investigate midgame substitutions. Report missing historical injury provenance.
4. **Q1 vs Q4:** compare selection, yards, turnovers, rush rates and explosive plays conditional on score, clock, opponents and current workload.
5. **Turf/grass and dome/outdoors:** estimate player and team effects while accounting for stadium, fixed home team, travel, roof state and season; publish null effects too.
6. **Rest/time-zone interaction:** short rest × away × kickoff slot vs opponent-adjusted baseline.
7. **Current-rule fourth-down and kicking matrix:** attempt choice and kick result fit separately under correct era rules.
8. **Coach and toss choice:** join separately sourced OT toss observations to game IDs; do not infer toss winner from PBP first possession.

## Scoring and adoption

Chronological rolling-origin split, with all rows of one **game** in the same fold; do not score each play as if independent games. Reserve later years for confirmation and publish clustered uncertainty. Pre-register the feature, comparison and expected outcome before observing evaluation scores.

Compare every factor against an identical-input null/factor-off arm, then measure marginal effect on the S1 simulator's score distributions and the comparable v1 baseline. Report per game and pooled: team-score MAE/RMSE, total and margin MAE/RMSE, winner Brier/log loss, calibration with uncertainty, runtime, and simulation completion/validity. Include all attempted simulations in the coverage denominator; separately label any metric conditional on valid complete games. Prefer retaining a measured null over introducing an unsupported multiplier.

**Priorities are not deferrals:** run parallel extraction/quality pipelines by family, and integrate factors only with their measured evidence and era safety.
