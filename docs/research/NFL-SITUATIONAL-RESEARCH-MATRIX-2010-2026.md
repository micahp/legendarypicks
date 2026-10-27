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
| TEAM-01 | Records | 2–4 vs 2–4, 5–1 vs 2–4; record difference vs quality | team-game; margin, scoring | schedule prior scored games | Record is noisy; condition on opponent-adjusted strength |
| TEAM-02 | Form | 1/3/5-game weighted form, streaks, blowouts vs close games | team-game; team scoring | schedule, historical PBP | Use preceding games only; shrink early-season samples |
| TEAM-03 | Division/rivalry | Divisional rematch, familiarity, preceding head-to-head | game; margin, pace, strategy | div_game, schedule | Division may proxy quality/venue; no motivational multiplier |
| TEAM-04 | Playoff incentives | Clinch, eliminated, seeding, rest starters, winner-take-all | game; starters, usage, decisions | derived standings and schedule | Historical as-of playoff probabilities required |
| TEAM-05 | Coaching | Coach/OC/DC changes, tenure, home/road playcalling | game/play; pass share, fourth-down choices | schedule coach names + historical roster/coach join | Coaching changes need event dates and confounding treatment |
| MATCH-01 | Offense × defense | Run/pass efficiency, pressure, explosive, red zone by opponent | drive/play; points, event probabilities | nfl_pbp + chronologically fitted team rating | Must compare against v1 and opponent-adjusted baselines |
| MATCH-02 | Style interaction | High-pass offense vs high-blitz defense, slow vs fast tempo | play/drive; pace, turnovers | PBP, advanced charting | Coverage/blitz not uniformly recorded all years |
| QB-01 | Starter vs backup | Announced starting QB out, backup starts, replacement skill | game; pass rate, sack rate, score | depth charts, dated reports, roster history, PBP | Actual postgame starter is NOT pregame information |
| QB-02 | Midgame QB change | Starter exits Q2; backup enters; offense response | in-game drive; success probability, pace | play IDs, QB attribution, participation | Selection bias: exits may be due to blowout/injury |
| QB-03 | Rookie/experience | Career starts, first season starter, returning from missed games | team-game/player-play; decision/outcome | player ID registry, career game logs | Count experience strictly before game |
| INJ-01 | QB availability | DNP/questionable/out, starter limited vs absent | team-game; score, sacks, playcalling | injury_reports + nfl_hist_injuries + roster snapshots | Historical reporting/ingest stamps incomplete; prospective strict |
| INJ-02 | Position groups | Multiple OL out; top WRs out; CB room depleted; RB committee | team-game/play; usage, points, pressure | injuries, expected roles, snap counts | Weight by pregame expected usage, avoid hindsight snaps |
| INJ-03 | Return to play | After concussion, ACL, missed weeks, snap limitation | player-game; attempts, performance | dated transactions, injury reports, snaps | Major selection and survivorship biases |
| PHASE-01 | Quarter | Q1 vs Q4 by team, offense/defense, close games vs garbage time | drive/play; EPA, explosive, turnovers | PBP qtr, game_seconds_remaining | Separate quarter effect from score/clock/possession |
| PHASE-02 | Score state | Up 7/14/21; down 7/14/21, tied; two-minute drill | play; pass/run, pace, 4th downs | PBP score_diff, down/clock | In-game-only feature; no pregame hindsight |
| PHASE-03 | Workload | Defensive snaps to date, possession length, prior drive, drive count | play/drive; explosive allowed, run/pass and fatigue | ordered PBP, snap participation | Q4 "fatigue" needs controlling score/game state |
| PHASE-04 | Field | Own 5, midfield, red zone, goal-to-go, FG range | play/drive; event and scoring | PBP yardline_100/down/togo | Valid for time-of-play only, legal state reducer |
| DEC-01 | 4th down | Punt vs FG vs go, by yardline, to-go, score, time and team | **opportunity**; P(action) | PBP all fourth-down opportunities | Avoid only fitting taken kicks/tries; data denominator matters |
| DEC-02 | After TD | Kick or go for 2, by margin, clock and era | TD opportunity; choice+conversion | observed try data, rule registry | Explicit 2015 PAT and OT regimes; holdout untouched |
| DEC-03 | Overtime toss | Toss winner, kick/receive, home and coach choices | OT game; P(choice) and receiver | official gamebooks/source-linked toss registry | PBP lacks toss winner; record provenance |
| DEC-04 | Clock decisions | Team timeouts, spike, kneel, conserve clock and challenge | play/decision point | PBP + extra clock/replay data | Requires legal action eligibility and era |
| ST-01 | Kickoff | Landing-zone, touchback, return selection, onside | free kick; start spot and outcome | PBP, kick fixtures, rule registry | Critical 2011/2016/2018/2023/2024/2025/2026 shifts |
| ST-02 | Field goals | Distance × wind × time; attempt vs make/miss/block | fourth-down opportunity then attempt | PBP, special teams fixtures | `yardline_100>=50` is ~67+ yard attempts, NOT 50-yard FG |
| ST-03 | Blocked kicks | FG/punt block, recovery, return and special penalties | kick opportunity; terminal outcome | classified blocked kicks | Existing measured 2022–25 outcome pool |
| VEN-01 | Surface | Natural grass, hybrid, artificial turf; surface changes | player-game/game; injuries, routes, yards | schedule.surface, venue history | Strong home-team/era confounding; no blanket turf benefit |
| VEN-02 | Roof | Closed dome, open stadium, retractable open/closed | game/play; passing, kicks, pace | schedule.roof | Roof state and stadium identity need normalization |
| VEN-03 | Weather | Forecast wind/temp/rain/snow, gusts and wind direction | game/kick/play; scoring, fg make | timestamped forecasts plus observed weather | Observed gametime weather is hindsight as pregame feature |
| VEN-04 | Elevation | High altitude, temperature & travel effects | game/team-play; stamina, kick distance | geocoded venue + schedule | Venue fixed effect confounded; measure separately |
| PLAYER-01 | Usage | Targets, carries, routes, snaps; opponent and context | player-game/play; prop distributions | weekly logs, participation, PBP | Snap counts postgame cannot be pregame input |
| PLAYER-02 | Splits | WR on turf vs grass, dome vs outdoors, Monday vs Sunday | player-game; yards, catches, targets | schedule joined to player logs | Require sample size and shrinkage, avoid "9 games 8 wins" claims |
| PLAYER-03 | Matchup | DB vs WR, OL vs DL, coverage vs receiver route | player-play; contested catch, pressure | charting, tracking where licensed/available | Not derivable faithfully from basic PBP alone |
| ERA-01 | Rules | Before/after try, OT, kickoff, catch/replay changes | season regime; all dependent targets | rule registry & official NFL documents | Source and target regimes tracked separately |
| ERA-02 | Schedule structure | 16 vs 17 games, weeks 17 vs 18, new postseason | season; standings/rest/incentives | schedules, rule registry | Normalize season totals and weeks |
| MISC-01 | Officials | Referee/crew and penalty enforcement tendencies | game/play; foul rates | schedule referee + penalty logs | Small and nonrandom assignments; verify identity |

## Rules for the research engine

**Separate four types of model:**
1. **Choice**: `P(action | eligible opportunity, state, pregame context, rule regime)`; e.g. go for two, attempt FG, pass vs run, timeout, OT toss choice.
2. **Outcome**: `P(result | action, state, players, opponent, regime)`; e.g. conversion success, interception, kick block, yards gained.
3. **Exposure**: `P(player plays / receives target / carries | roster, situation)`; missing starter changes exposures across roles.
4. **Aggregate**: final points, margin, total, winners and player stat distributions implied by a legally complete simulated game.

**Avoid empty cells:** Put factors in a hierarchical model, test limited two-way interactions with real support, penalize higher-order interactions, compare against larger parent buckets, and publish effective sample sizes. Do not materialize every possible cross-product of 40 factors as an independent observed statistic.

**Chronology:** For each replay, construct `as_of` features from what was available by kickoff. Distinguish (a) as-of observed, (b) retrospective date-filtered and (c) unavailable. Models trained on retrospective backfills can be useful research, but not automatically claim strict historical as-of fairness. Never use the game's final QB starter, actual inactive list received after cutoff, final weather, or final snap count as a pregame feature.

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

Compare every factor against an identical-input null/factor-off arm, then measure marginal effect on the S1 simulator's score distributions, team score MAE, margin/total errors and winner Brier relative to v1. Prefer retaining a measured null over introducing an unsupported multiplier.

**Priorities are not deferrals:** run parallel extraction/quality pipelines by family, and integrate factors only with their measured evidence and era safety.
