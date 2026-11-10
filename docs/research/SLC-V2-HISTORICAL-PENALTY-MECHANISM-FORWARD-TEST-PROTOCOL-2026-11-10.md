# SLC-v2 historical mechanism, penalty, and forward-test protocol

**Date:** 2026-11-10  
**Status:** Pre-implementation research protocol; no model promotion authorized  
**Sequencing update (2026-11-10, owner decision):** PENALTY GENERATION AND FITTING ARE DEFERRED UNTIL AFTER THE STRENGTH-MODEL GATE. The controlling execution order and isolated experiment design are in [Strength-first mechanism gates](SLC-V2-STRENGTH-FIRST-MECHANISM-GATES-2026-11-10.md). This document remains the design reference for later penalty work. The historical penalty-source extract is retained as read-only research; explicit penalty simulations stay OFF during strength tests. Corrected penalty labels may be used only for consistent clean-play eligibility in BOTH controls and candidates.  

**Target branch:** `slc-v2`  
**Scope:** historical NFL PBP audit, conditional football-mechanism tests, penalty simulation, and controlled evaluation of Default V2, V2+C, and V2+D1  
**Owner decision:** team-level offensive/defensive penalties are required; player-to-team transfer effects are a separately gated bonus; QB substitutions are out of scope for this phase.

## 0. Decision and hypothesis

We will not assume that penalties alone explain SLC-v2's tendency to produce too many offensive plays, chain advancements, or touchdowns. We will **measure before modifying**, implement a legal penalty process, and compare with the immutable existing SLC-v2 arms.

Prespecified hypotheses:

- **H1 (penalty exclusion bias):** E1's `classify()` discards penalty-flagged observed plays, changing the reference outcome distribution; some observed down/yardage/clock states are systematically missing.
- **H2 (penalty process):** Explicit offensive/defensive penalties and NFL enforcement materially improve first downs, third downs, drive terminals, score tails, and clock/possession calibration.
- **H3 (conditional outcome mechanism):** Even after accounting for penalties, weak offenses and strong defenses require better matchup-conditional yardage/chain advancement and sack/turnover probabilities than current event-type-only multipliers provide.
- **H4 (fourth-down policy):** Historical cell kick shares produce excessive team-specific fourth-down go-for-it attempts, beyond any difference explained by the situations the simulator reaches.
- **H5 (workload interactions):** Penalty integration may improve scoring realism across all three arms; it is **not** assumed to make C or D1 outperform Default V2.

Reject or retain each hypothesis separately. A single observed 23-6 BUF-MIN or 17-3 SEA-ARI score is **not** an advancement test.

## 1. Frozen baseline and provenance

These are historical **game-winner** probability metrics from the *three-game* 2026 Week 9 comparison. They must never be relabeled as penalty-model improvements or as player-prop Brier scores.

| Arm | Winner Brier (lower better) | Winner log loss (lower better) |
|---|---:|---:|
| Default V2 | 0.19430 | 0.57764 |
| V2+C | 0.17793 | 0.54415 |
| V2+D1 | 0.19865 | 0.58641 |

- Sample: ARI at SEA, DAL at IND, DEN at CAR; 1,000 requested seeds per arm across games, 999 valid, same failed seed 300786 in DEN-CAR. Neither candidate passed the predeclared advancement rule.
- Frozen source: `docs/research/slc-v2-three-way-2026-11-10/README.md`, grading artifacts, archived hashes and seed tables.
- Separately, `docs/research/slc-v2-model-d1-10k-2026-11-10/` contains 9,991 valid BUF-MIN games of 10,000; nine preserved errors; source commit `8a5d809f`. This is a **single-matchup distribution audit**, not an independent 9,991-game validation sample.
- Existing original outputs did not retain ordered play rows. Never infer observed conversion rates from decision counts or retroactively fabricate play histories. New exporter defaults to box scores and ordered play rows after `092446a8`; the conversion-accounting fixes are in `bdb20f7e` and `09a794f0`.
- Model names, source commits, frozen as-of timestamps, release hashes, fit windows, seed/RNG protocol and changes to output semantics belong in every artifact manifest.
- Keep original baseline results and checksums immutable. This protocol is documentation only, not an implementation claim.

## 2. Full historical data audit: 1999 onward

**Source:** NFL nflverse/nflfastR PBP supports releases from **1999 onward**. nflfastR 6.0 explicitly stopped correcting 1999/2000 because of inconsistent data sources; retain them for audit and only use fields/plays that pass checks. Use complete raw PBP for penalty analysis, not a dataset that discards administrative/no-play/timeout records. Do not replace or mutate Legendary Picks' live/dev DB.

**Sources and version references:**
- https://nflreadr.nflverse.com/reference/load_pbp.html
- https://nflreadr.nflverse.com/articles/dictionary_pbp.html
- https://nflfastr.com/news/index.html
- https://github.com/nflverse/nflverse-data/releases
- https://www.nflgsis.com/gsis/documentation/stadiumguides/guide_for_statisticians.pdf
- https://operations.nfl.com/rules-officiating/2026-nfl-rulebook

Suggested staged fit/evaluation (subject to coverage audit, never silently assumed reliable):

| Era | Role |
|---|---|
| 1999-2000 | audit/exploratory; default exclude from mechanism fit until field and transition validation |
| 2001-2015 | league priors, season/era changes and low-frequency event support |
| 2016-2021 | modern-era mechanism fitting and walk-forward historical tests |
| 2022-2025 | recent priors, holdout tests and comparison with existing E1/SLC reference window |
| 2026 completed games | current-season adaptation only when **available before target cutoff** |
| 2026 future games | untouched prospective forecasts with precommitted evaluation |

**Audit actual data coverage**, not just row totals. Save `season, source_release, source_sha256, fetch_time, game_count, row_count, scrimmage_count, pre_snap_flag_count, live_ball_flag_count, dead_ball_flag_count, no_play_count, missing_flag_type_rate, missing_penalty_team_rate, missing_player_id_rate, duplicate_event_rate, ambiguous_enforcement_rate, before_after_state_reconstruction_rate, usable_for_model_components`.

Do not assume penalty labels, clock fields, player IDs, or enforcement spots are stable across eras. Retain rule era, data vintage and provenance as separate fields. If release history is not available to reconstruct a historical publication cutoff, label that evaluation **retrospective reconstruction**, not strictly archived prospective data.

### Canonical tables

1. `slc_opportunities`: **one row per potential offensive, defensive or kick opportunity**, with `game_id`, ordered source row index, provider `play_id`, `season`, `rule_era`, offense, defense, down, to-go, field position, quarter, clock, score margin, personnel/formation if available, intended play class, before state, next effective state, effective play counted, and evidence availability cutoff.
2. `slc_fouls`: **one row per discernible foul**, keyed to opportunity plus foul index: committing team; offense/defense/special teams; category; pre-snap/live-ball/dead-ball; accepted/declined/offsetting; enforcement yards; previous/spot/succeeding spot when available; automatic first down; loss of down; repeat down; retained or nullified play; clock/reset behavior; identified player (optional); label source; confidence/ambiguity.
3. `slc_result_transitions`: the observed scrimmage/special-teams outcome **after enforcement**, before and after field/down/clock/score/possession, score type and resulting next eligible opportunity.
4. `slc_source_vintage`: immutable ingest/release SHA and availability. A source's current date of download is not proof it existed at an earlier kickoff.

Keep **multiple fouls on the same opportunity** distinct. The common `penalty_type` field may describe only the first flag. Parse `desc` cautiously and reconcile to official scoring if possible; mark unsolved offsetting and overlapping fouls as ambiguous. Preserve `no_play`, administrative rows, timeouts, first-down-by-penalty markers and original order. Never equate all `penalty==1` rows with accepted penalties or with counted snaps.

### Coverage gates

- Explicit per-era completeness, distributions and reconciliation for total/accepted/declined/offsetting flags and offensive/defensive penalty types.
- 32-team/year code identity handling including renamed/franchise codes; special-teams penalties reported separately.
- Reconstruct before/after down, to-go, yard line, possession, scoring and game clock on a held-out audit sample. Do not silently use inferred state where NFL rules or source semantics are ambiguous.
- Report penalties per **opportunity**, per 100 credited offensive snaps, and per **team game** as separate denominators.
- Show how excluding flags changes the frequency and distribution of completions, runs, sacks, explosive gains, loss plays, first downs, third down and scoring by **identical situation strata**. This tests H1 without simulating games.

## 3. Required offline historical-mechanism tests BEFORE full-game simulation

Run on observed pre-play states, with strict year/week holdouts. The offline model must output **full predicted distributions**, not sample an entire drive.

### Test A: conditional yardage and first-down/success

For each eligible historical play, obtain SLC's frozen mixture over event types and its historical candidate rows **at that game's actual pre-play down, distance, yard line and game state**. Compare expected run gain, completed-pass gain, negative gain, explosive-play rate and `P(yards >= yards_to_go)` against the observed event; condition on offense/defense strength, team, home/away, current-season sample size, and opponent strength tiers. Baselines: league cell, offense-only, defense-only, present combined SLC, combined with recency, and a candidate conditional-yardage model.

Measure per-play log loss/Brier for categorical outcomes, CRPS for yardage, bias/MAE by team matchup, third-down `P(convert)`, and calibration by offense/defense strength decile. Penalized or nullified plays are scored through the penalty channel; do not label their erased gains as retained gains. Report fallback support and effective sample size.

**Key code concern:** `slc_playcall.py` reweights outcomes by team event-type ratios, but historical selected row(s) supply yardage; test whether this leaves weak offense/strong defense conditional gains too generous.

### Test B: fourth-down choices AND fourth-down state frequency

From observed historical fourth-down opportunities reconstruct **go / punt / FG / exceptional decision** eligibility and score the SLC conditional action probabilities in matched cells (down, distance, distance to goal, score, clock, team/year, weather if independently available). Baselines: league cell and smoothed team tendency; optional league fourth-down model for context, not presumed better. Use multiclass log loss, Brier, calibration, and per-team action frequency **given the observed contexts**.

Separately compare archived simulated fourth-down situation counts to real pregame team context frequencies. If go rates differ only because situations differ, don't modify decision policy without first examining upstream down success. Current BUF-MIN D1 roughly 1.88 go-for-it run/pass decisions per sim versus Minnesota's 0.86/game entering that matchup, but these rates are **not matched-context policy evidence**.

### Test C: sacks, interceptions, fumbles, turnovers

On observed pass/dropback states measure sack rate, interception conditional on pass, fumble risk conditional on contact/run/sack, and retained turnovers by offense, defense, down-distance, matchup and era. Evaluate historical offense-only and defense-only baselines against current SLC outcome reweights and candidate conditional model. Audit `restore_sack_mass` support/cell counts *offline* first. Disaggregate sacks from incompletions, designed rushes from scrambles, turnovers from turnovers on downs. Test probability of multiple turnovers using held-out team games, not treating individual modeled seeds as independent NFL matches.

Existing BUF-MIN D1 saved team distributions include MIN approximately 1.48 sacks taken, 0.49 interceptions, 0.64 turnovers/game; BUF approximately 0.72 sacks taken. Those are **simulation means**, not calibration verdicts.

### Test D: penalty occurrence and selection

Fit penalty rate and category probabilities on `slc_opportunities` and score them on historical held-out opportunities. Do not join fouls only to credited snaps; pre-snap no-plays are part of the denominator. Compare observed team offense and defense penalty rates, types, third/fourth down penalty effects, and after-play retention.

Prespecified offline benchmarks: league era rate; context-only; context + offending team's effect; context + offending team + opposing team effect; modern/current-season shrinkage. Compare rare categories by aggregated bucket and log all zero-support cases. Require improvements on historical held-out log loss/Brier/calibration rather than selecting model based only on anecdotal examples.

## 4. Penalty simulator: team-first and legally deterministic

Implement as **separate optional versioned research module** without modifying Default V2's baseline behavior.

### Stage 1: pre-snap hazards

Before the snap, sample mutually compatible pre-snap foul/no-foul outcomes conditional on offense, defense, down, distance, field, clock, score and rule era. False starts, delay of game, encroachment and neutral-zone fouls may consume a situation without a credited offensive snap. Enforce them first and return to a new effective pre-snap state.

### Stage 2: live-ball and dead-ball fouls

After choosing intended run/pass/kick and before applying the result, jointly model legally possible live-ball fouls, their interaction with retained/nullified scrimmage outcomes, defensive fouls that award first downs and post-play/dead-ball fouls. Some fouls correlate with dropbacks, failed pass protection, hard coverage, long plays, sacks, etc. Do **not** draw offensive and defensive penalties independently without first checking observed co-occurrence. An initial hierarchical categorical joint model is adequate; rare double-foul structures need explicit fallback/exclusion until verified.

### Stage 3: penalty enforcement, no learning

A **deterministic, versioned, tested NFL state-transition engine** applies accepted/declined/offsetting decisions, enforcement spot, half-distance, repeat/loss of down, automatic first down, retained play, score/possession and clock effects. Consult the 2026 NFL rulebook, especially Rule 14. Model the acceptance choice as a separate decision process or deterministic clearly specified coaching heuristic where appropriate, but the resulting enforcement itself must be rule-exact. If not supported, fail with `UNSUPPORTED_RULE`; never silently invent a legal state.

### Stage 4: correct NFL statistics

NFL GSIS statistical definitions are separate from transition legality:
- A penalty-only first down counts in penalty first downs and need not count as a third-down attempt or conversion.
- A scrimmage play that itself earns a first down plus an additional penalty may have both first-down sources, with a credited conversion.
- An offensive touchdown on third/fourth down counts as a successful conversion, not as a first down earned.
- A defensive return touchdown is not an offensive conversion.
- Accepted/declined/offsetting outcomes must be reconciled against officially credited attempts and plays. Use the NFL Guide for Statisticians examples, not generic yardage comparisons.

Implementation references: `scripts/nfl_sequence/e1_drive.py` currently excludes `penalty==1` rows; `game_state.py` lists penalties unsupported; `game_stats.py` and `slc_outputs.py` have separate statistical counters and recent corrections. Hook penalty mechanism before the current transition is finalized; do not bolt a random post-hoc point or yard adjustment onto a completed play.

## 5. Model specification: team required, player bonus

**Minimum viable team model:** multiclass or staged hierarchical model conditional on game context. For foul type `k`, score a pooled era/context baseline plus **offense team's propensity to commit or draw**, **defense team's propensity to commit or induce**, and shrunk team-season effects. Use a well-defined denominator per foul class (pre-snap opportunities, dropbacks, runs, kick plays), not raw per-game counts alone. A league prior stops rare teams/cells exploding to 0% or 100%.

Candidate approximation:

`logit P(foul_k at opportunity) = era_type_intercept + situational_features + offense_effect_k + defense_effect_k + recency_blend_k`.

Avoid non-identifiable unconstrained offense+defense effects: regularize/center them. The formulation is a *candidate*, subject to historical out-of-sample comparison, not a declared winner.

**Current-season update:** preserve the existing SLC-v1.5 pregame availability discipline (90-minute pre-kickoff freeze; 10-hour after prior kickoff evidence lag) and historical-to-current shrinkage as the reference candidate (historical weight `N0/(N0+g)`, `N0=4` team games). Tune only on earlier seasons; compare alternative evidence windows rather than assuming 4 games is optimal for penalties.

**Player effect (bonus; NOT required for initial release):** estimate within-team/player-role partial-pooling adjustments only if `penalty_player_id` coverage and stable identity are adequate. Test after a player changes team using pre-transfer performance plus new team baseline, shrunk according to available opportunities. Measure whether this improves held-out prediction for transferred players over the team-only model. Do not attach player effects to QB/OL/defender IDs absent reliable participation/exposure denominators. Never allow unknown future roster status to leak into historical pregame features.

## 6. Offline candidate ranking and ablations

This work can start with no new simulation. Generate one historical *mechanism scorecard* and compare:
- Penalty-flagged row exclusion versus all opportunity-aware rows, by era and matched situation.
- Event-type-only versus event+conditional-yards outcome models.
- Fourth-down decision policies conditioned on **real fourth-down situations**.
- Team-vs-team sack, interception, fumble and down-success estimates.
- Penalty-only and combined penalty-outcome interaction fits.

For every model: train/validation/test game count and play count; year and data-vintage boundaries; loss and confidence interval clustered by game/team-week; calibration diagrams and support/fallback; error breakdowns by weak offense/strong defense, red zone, high/low score, third-and-long, rule era. Choose complexity only when it beats simpler baselines in **earlier-season holdouts**.

No full-game reruns until these component-level decisions are frozen in a preregistered `mechanism-model-manifest.json`.

## 7. End-to-end experimental design AFTER offline gates

### Paired test matrix

All three existing arms remain separate controls. The first question is the effect of penalties while holding each arm's workload estimator fixed.

| Scoring/workload arm | Existing behavior, no penalties | Same arm + tested penalties |
|---|---|---|
| Default V2 | baseline control | V2+P |
| V2+C | existing C control | V2+C+P |
| V2+D1 | existing D1 control | V2+D1+P |

Run *distinct subsequent ablations* (not in initial P run): `+M` calibrated matchup-conditional yards/outcomes; `+F` calibrated fourth-down policy; `+P+M`, `+P+F`, `+P+M+F`. Change only one layer at a time before testing interactions. Penalties may help or hurt each arm; test, do not assume.

**RNG pairing:** same games, cutoff snapshots, original underlying simulation RNG root and paired seed IDs. Assign penalties an **independent named RNG stream** so switching P on does not consume the base event stream. After a penalty changes the path, states may diverge; paired seeds reduce noise but do not imply identical future play histories. Record every source SHA and every ablation flag.

### Historical walk-forward

- Train historical models only with seasons before the target season; incorporate the target season's earlier *available* games through the explicit cutoff rules.
- Suggested locked evaluation periods: develop on early and middle historical seasons, choose regularization via rolling-origin validation, then score untouched recent years (e.g. 2024 and 2025) with pregame cutoffs. Because historical source-vintage audit may be incomplete, label the results as **retrospective walk-forward reconstruction** unless truly archived pregame source releases exist.
- Keep regular season and playoffs stratified; do not silently force regular-season OT or historical rule conventions into 2026 postseason.
- Stratify team strength and opponent defense; publish all target games rather than cherry-picking BUF-MIN/ARI-SEA.

### Genuine 2026 forward test

- Freeze commit, model fit tables, data vintage, forecasts and hashes **before kickoff** for every new target game; write a tamper-evident timestamped manifest and fixed report contract.
- No 2026 results acquired after kickoff can enter that game's forecast. Game-day roster/injury status must be cutoff-safe, with unknown statuses marked unknown.
- Accumulate many independent games. A thousand simulation seeds on one game is **not** a thousand independent forecast observations.
- Define and lock the advancement test and decision rules before inspecting outcomes. Use paired **game-level** confidence intervals/bootstrap, not seed-level pseudo-replication; report insufficient power when appropriate.
- Do not mix 2026 forward games with historical reconstruction as if they have identical provenance.

## 8. Required outcome and realism metrics

Score both overall and by team/matchup strength bucket. For every predicted quantitative metric save mean, median, p10/p90, and empirical observed percentile, plus failure/exclusion coverage.

**Proper scoring metrics:**
- Winner: Brier and log loss, plus calibration and sharpness.
- Team points, total, margin: CRPS or energy score for distributions, points MAE/bias for descriptive comparisons, empirical coverage for central 80% interval.
- Yardage and play event models: held-out CRPS for gains, Brier/log loss for binary/categorical events, reliability by scenario.

**Football mechanism metrics:**
- Offensive plays; per-team/combined drives; drives with/without a first down; three-and-outs.
- First downs earned **by run/pass/penalty**; 3rd/4th down attempts, credited conversions and rates; 3rd-and-long opportunities.
- 4th down go/punt/FG decision rates by matched context.
- Rush and pass success; yards per play; completion rate, yards per attempt; negative and explosive gains.
- Sacks per dropback; interceptions per attempt; fumbles/turnovers per offensive opportunity and per drive; multiple-turnover tails.
- Punts, FG attempts/makes, touchdowns, red-zone trips and TDs per trip; points/drive; score tails **0-9, 10-16, 17-27, 28+**.
- Penalties by committing/benefiting side, class, type, accepted/declined, yards, nullified/retained plays, automatic first downs, repeat/loss of down, count per opportunity.
- Per-team time of possession; clock/runoff reconciliation; quarter-level play and scoring splits.
- All fallbacks, invalid seeds, blocked/duplicate kick recoveries, and validation guard activations.

**Primary advancement principle:** improving scoring by forcing 20 fewer offensive plays or uniformly subtracting points is disallowed. A candidate must explain *where* chains and clock diverge, improve held-out calibrated mechanisms and full-game proper scores, retain realistic opportunity/role distributions, and not introduce illegal game states. A better mean score on one game is not promotion evidence.

## 9. TDD and football-rule gates

Create named unit tests before enabling the experimental feature:
- false start/delay: no credited snap; correct repeat down, 5-yard/half-distance, clock state;
- accepted offensive holding: retained or erased play per spot/enforcement, no fictitious first down;
- defensive holding/illegal contact: automatic first down and correct credited stat;
- DPI: spot of foul, defensive end-zone enforcement, correct next state;
- roughing passer, illegal formation, intentional grounding: appropriate 15/5/loss-of-down handling;
- declined, offsetting and multiple fouls: no double application; blocked unsupported combinations fail explicitly;
- foul on touchdown, quarter expiration, last two minutes, kick and turnover;
- penalty first downs vs third/fourth conversion/attempt accounting under the NFL Guide for Statisticians;
- possessions, clocks and score ledger reconcile; deterministic repeatability and independent named RNG stream;
- backward compatibility: P disabled yields identical original per-seed game result and stats at fixed historical source commit, with no off-by-one or random draw changes;
- leakage: forbidden target/future games, undated source revisions and post-cutoff player-roster rows cause clear refusal;
- full seed count/validity accounting and preservation of replayable failure envelopes.

Set a **100% legal transition and accounting requirement on supported test fixtures**; unsupported rules must be named and fail, not silently continue. Report empirical error rate separately for long-run stress tests rather than hiding invalid seeds.

## 10. Concrete work sequence and acceptance evidence

| Phase | Work, artifact | Proceed only when |
|---|---|---|
| P0 | Read-only 1999-present field audit; release/vintage manifests, penalty taxonomy and per-era coverage | All historical sources, missingness and cutoff limitations disclosed; usable training years chosen |
| P1 | Offline excluded-row bias, matchup-yardage, 4th policy, sack/turnover tests | Benchmarked walk-forward per-play scorecards and mechanism gap report produced |
| P2 | Hierarchical offensive/defensive penalty occurrence and type model | Held-out occurrence/type calibration beats or matches simple era/context baselines; fallback support audited |
| P3 | Deterministic 2026 penalty transition engine + NFL stat accounting, initially behind `--experimental-penalties` | Test matrix passes; before/after states legal; zero silent illegal transitions |
| P4 | Paired full-game tests for 3 control arms and 3 penalty arms, with same cutoffs | 2024/2025 holdout reports, team/drive metrics and score tails, independent game-level intervals; no premature promotion |
| P5 | 2026 prospective prekickoff capture and grading, weekly repeat | Forecasts archived before kickoffs; enough independent games to draw supported conclusions |
| Bonus | Player-specific penalty propensity on roster transfers | Coverage and transfer holdouts demonstrate value over team-only; explicit opt-in |

### Proposed code and research locations

- `scripts/nfl_sequence/penalty_corpus.py`: canonical opportunity/foul/transition builder; annual coverage report.
- `scripts/nfl_sequence/penalty_fit.py`: team-level hierarchical penalty model; offline scoring, shrinkage, frozen serialization.
- `scripts/nfl_sequence/penalty_rules.py`: rule-era-aware deterministic enforcement, separate from stochastic selection.
- `scripts/nfl_sequence/penalty_sampler.py`: feature-flagged independent stream; pre-snap/live/dead-ball integration.
- `scripts/nfl_sequence/eval_conditional_mechanisms.py`: observed-context offline yardage, 4th, sacks/turnovers and penalty evaluation.
- `scripts/nfl_sequence/test_penalty_rules.py`, `test_penalty_corpus.py`, `test_penalty_sampler.py`, `test_conditional_mechanisms.py`.
- `docs/research/slc-v2-penalties/`: immutable source manifest, coverage, corpus-derived summaries, model metrics, calibration, ablation setup, observed comparison and decisions.

**Do not:** mutate original 10K outputs or database; reuse 2026 Week 9 observed outcomes for their own model inputs; retrain the three existing arms and still call them original baselines; introduce player transfer modeling into the initial gate; or claim penalties have fixed SLC's scoring inflation before paired held-out results exist.

## 11. Decision requested after P1

Return a concise research scorecard answering:
1. What fraction of 1999-present PBP penalty observations are actually usable for each model component, by era?
2. Does removing penalty rows materially bias outcomes after matching down, distance, field, offense and defense?
3. Does team-level offensive/defensive penalty propensity beat league/context baselines?
4. Does the current yardage/matchup model miscalibrate weak-offense/strong-defense yards or first downs even on clean plays?
5. Is Minnesota's apparent fourth-down overaggression a decision-policy problem or an upstream state-distribution problem?
6. How much of sack/turnover miscalibration persists without penalty effects?
7. Which of P-only, M-only, F-only or interactions warrants **the next experimental simulation**, based on preregistered historical evidence?

If P1 does not answer those questions, the appropriate next action is better instrumentation or data validation, **not** another 10,000-seed run.
