# SLC: Transition from historical play sampling to conditional event generation

- **Model:** SLC-CEG (conditional event generation), a new statistical SLC engine.
- **Status:** research plan, Phase 0 (dependency audit) in progress. No production model changes.
- **Branch:** `research/slc-ceg-2026-11-24`, based on the v2 engine commit `8a1d9842` (the frozen V2 historical sampler
  with backoff is arm A below). V1, V1.5, V1.6, V2, PBV1 and V1 Complete (`research/slc-v1-complete-2026-11-23`) are not
  changed.
- **Date:** 2026-11-24. Plan text from Micah, saved as written.
- **Phase 0 output:** `docs/research/slc-ceg-2026-11-24/PHASE0-DEPENDENCY-AUDIT.md`.

---

I think this should be the next major evolution of the statistical SLC engine.

**Play-by-play should become our training and validation data, not a mandatory inventory of plays that the simulator must
draw from to continue a game.**

The current system effectively asks:

> Has this specific football situation occurred in our historical dataset, and is there a usable row we can sample?

The next system should ask:

> Given the current football situation, what is the probability distribution of the legal events that could happen next?

That's an important architectural change. We retain the historical data and its correlations, but remove the requirement
that a sufficiently similar historical play must exist for every simulated snap.

This is also a continuation of our existing Granular Prediction Modeling Strategy
(`docs/STRATEGY-GRANULAR-PREDICTION-MODELS-2026-10-26.md`), rather than an entirely new research direction.

## 1. Why we should replace the existing architecture

The Week 11 experiment made the limitation particularly clear.

| Model | Failed seeds | Primary issue |
| ----- | ------------ | ------------- |
| V1 | 56 / 1,300 | Unsupported historical outcomes |
| V1.5 | 41 / 1,300 | Unsupported historical outcomes |
| V1.6 | 2 / 1,300 | Illegal sack-fumble geometry |
| V2 | 0 / 1,300 | Backoff mechanisms enabled |
| PBV1 | 0 / 1,300 | Backoff mechanisms enabled |

V2 solves much of the immediate reliability problem by progressively widening the historical sampling pool.

But widening the pool is a workaround. We are still dependent on finding historical examples.

The existing `slc_playcall.py` contains separate mechanisms for constructing sampling cells, filtering outcome rows,
finding backoff candidates, weighting outcomes and selecting individual historical samples.

A conditional generative engine would replace that dependency.

## 2. Proposed architecture: SLC Conditional

### Current SLC

Current game state -> Filter historical plays -> Apply decision and outcome weights -> Find eligible historical row ->
(no eligible rows: backoff or block) -> Historical outcome

### SLC Conditional

Current game state -> Evaluate conditional models -> Generate legal event probabilities -> Sample event and quantities
(sparse evidence: regularized probability estimates) -> Generated outcome -> **Existing SLC football reducer** (rules,
possession, downs, score, clock, statistics) -> **Next game state** -> repeat until legal game completion.

We should preserve the reducer, game state, roster resolution, player participation models, simulation runner and
portable model infrastructure.

The primary replacement is the **event-generation layer**.

This is not V1 Complete. V1 Complete remains our autonomous, spatial football simulation. Both engines can share
football rules without needing to share how outcomes are generated.

## 3. Decompose a football play into conditional events

Rather than building one enormous model that predicts every possible play outcome, build a directed sequence of smaller
models.

For a passing play, each branch has its own conditional distribution and legal outcome constraints. Throwaways,
penalties and additional exceptional events are also represented.

A completion generates passing and receiving yards from the same event. An interception changes possession. A sack never
generates a receiver target. A scramble generates QB rushing statistics.

The relationships are built into the architecture rather than repaired after sampling.

### Conditional probabilities

For a dropback outcome: P(E | S, O, D, Q, C), where

- E: event, such as a sack, scramble or pass attempt.
- S: game state.
- O, D: offense and defense information.
- Q: quarterback characteristics.
- C: available personnel and play context.

We can estimate this distribution even when the exact combination of inputs has never occurred historically.

## 4. Complete inventory of component models

Some components already exist and should be reused.

| Layer | Model targets |
| ----- | ------------- |
| Pregame | Team strength, roster eligibility, player availability |
| Personnel | Offensive personnel, defensive personnel, substitutions |
| Formation | Formation, shotgun, defensive front |
| Play calling | Designed run, dropback, kneel, spike |
| Strategic decisions | Fourth-down action, timeouts, two-point attempts |
| QB decisions | Pass attempt, scramble, sack, throwaway |
| Passing | Target selection, air yards, completion, interception, YAC |
| Rushing | Carrier selection, designed run direction, yards gained |
| Turnovers | Fumble occurrence, recovery, return yards |
| Penalties | Occurrence, type, enforcement and disposition |
| Field goals | Attempt, distance-conditioned success, block, return |
| Punts | Distance, hang-time consequences, touchback, return, block |
| Kickoffs | Touchback, return, recovery, applicable rule regime |
| Tries | Extra-point and two-point outcomes |
| Clock | Live-play duration, dead-ball runoff, clock stoppage |
| Overtime | Possession decisions, applicable overtime rules |
| Game progression | Legal transitions through the existing reducer |

The model library should be modular. We should be able to replace the rushing-yard distribution without changing the
fourth-down policy or the completion model.

## 5. Eliminate sparse-cell failures by design

Consider a fourth-and-six QB scramble near the opponent's goal line. The current approach might require historical QB
scrambles with that combination of down, distance and field position. If the cell is empty, V1 can stop.

The replacement learns from all relevant scramble observations, allowing those contextual variables to influence the
distribution: league-wide scramble data (broad evidence), down and distance (situational adjustment), field position
(contextual adjustment), quarterback tendency (player adjustment). The generated scramble distribution combines the
available evidence with regularization and football constraints. No exact historical row is required.

The underlying method could initially be regularized regression, generalized additive models or hierarchical probability
models. The crucial distinction is that we share statistical information across situations instead of repeatedly
filtering the historical database until only a few rows remain.

### Rare outcomes still require explicit treatment

We cannot simply use smoothing to make every event possible everywhere.

| Situation | Treatment |
| --------- | --------- |
| Legal and common | Learned conditional distribution |
| Legal but rare or unseen | Regularized population estimate or documented uncertain prior |
| Illegal under football rules | Zero probability |

The goal is **zero runtime failures caused by empty historical sampling cells**. Genuine illegal states, missing mandatory
inputs and unsupported rules must still fail explicitly rather than being hidden.

## 6. Model distributions, not averages

This is especially important for player props and our favorite-compression problem.

**Rushing yards.** A rushing model should represent losses, short gains, ordinary gains, explosive gains and touchdowns.
We should initially compare a smoothed discrete yardage distribution against parametric and mixture-distribution
alternatives. There's no reason to assume the most sophisticated method will win.

**Passing yards.** Passing-yard production should arise from correlated components: Y_pass = Y_air + Y_after_catch, for
completed passes, subject to the field boundaries and proper statistical attribution. Air yards, completion probability
and YAC cannot be modeled as unrelated independent draws. Receiver, pass depth, field position and defensive context
should connect them.

**Turnovers.** A fumble needs its own conditional sequence: run, catch or sack -> fumble probability -> (no fumble: normal
play result) or (fumble: recovery and return) -> football rules reducer. This removes the need to take a sack-fumble
historical row with nine lost yards and blindly place it into an incompatible field position.

## 7. Player participation and opportunity modeling

This should be a first-class layer, not an afterthought. For a receiving prop the causal chain is
Personnel -> Pass attempts -> Targets -> Receptions -> Receiving yards. This gives us a way to diagnose where individual
projections go wrong.

| Existing problem | Conditional model solution |
| ---------------- | -------------------------- |
| Jefferson excessive targets | Separate team passing volume from target share |
| Jones versus Mason workload | Contextual carry allocation |
| Juszczyk no touches | Include eligible FB receiving and rushing opportunities |
| QB rushing projections | Separate scrambles, designed runs and kneels |
| Backup players excessive usage | Eligibility, depth, participation and opportunity constraints |

We should reuse the existing participation and player-share models wherever they have demonstrated value. A game-level
latent workload or game-plan variable could eventually capture correlated player opportunities, but that should be an
optional challenger after the simpler version is evaluated.

## 8. Team strength without repeating failed experiments

Our previous transition-strength experiments found that adding team-strength effects made predictions worse than a
simple league baseline.

| Evaluation season | League baseline log loss | Historical team-strength candidate |
| ----------------- | ------------------------ | ---------------------------------- |
| 2025 | **1.9920** | 2.0576 |
| 2026 | **1.9811** | 2.0450 |

We should not rebuild those same models under a different name. Instead, start with an independently evaluated,
context-conditioned league model for each event. Then test separate offensive, defensive and player effects as
challengers. For example: logit(p_sack) = f(context) + alpha_offense + beta_defense + gamma_QB. Every additional term
must earn its inclusion on chronological validation.

This gives us a clean path toward studying favorite compression without forcing team margins or win probabilities to
match the sportsbook.

## 9. Existing infrastructure to reuse

| Existing component | Plan |
| ------------------ | ---- |
| `slc_playcall.py` | Replace historical-row execution with a conditional generator |
| `decision_layer.py` | Audit and reuse supported decision distributions |
| `pre_event.py` | Preserve player selection and opportunity infrastructure |
| `formation_layer.py` | Reuse personnel and formation priors |
| `reducer.py` | Preserve authoritative football transitions |
| `game_state.py` | Preserve game state |
| `game_stats.py` | Preserve statistical accounting |
| `slc_engine.py` | Integrate new event-provider interface |
| Conditional clock model | Reuse and expand only where necessary |
| Two-point decision model | Reuse evaluated candidates |
| Long field goal model | Reuse |
| Playbook priors | Reuse where independently useful |
| Portable model compiler | Extend for conditional model artifacts |

The historical sampler should remain available as a frozen research baseline, not be deleted.

## 10. End-to-end research and implementation roadmap

| Phase | Work | Exit gate |
| ----- | ---- | --------- |
| 0 Dependency and coverage audit | Inventory every runtime historical-row draw, exact-cell dependency, fallback, event category, participant mapping and reducer requirement. Freeze V1, V1.5, V1.6, V2 and PBV1. | Complete dependency matrix and baseline reproduction |
| 1 Canonical training dataset | Build cutoff-safe event tables from existing PBP, participation, snap counts and roster sources. Separate decision-time features, event labels and post-event measurements. | Reconciled denominators, provenance and rule-regime coverage |
| 2 Conditional scrimmage generator | Designed runs, dropbacks, sacks, scrambles, completions, interceptions, yardage and fumbles. Remove runtime historical-row dependence for these events. | Legal distributions for every supported scrimmage state |
| 3 Player opportunity models | Carries, targets and player attribution with existing participation and eligible roster constraints. | Team and player statistical reconciliation and local predictive evaluation |
| 4 Special teams and rare events | Replace punt, kickoff, field goal, penalty, try and exceptional turnover sampling dependencies. Cover regulation and overtime boundaries. | Complete legal-event coverage |
| 5 Full-game conditional runtime | Integrate every component with the reducer, clock, statistics and portable runtime. Run complete games with historical source rows unavailable. | End-to-end proof of row-independent execution |
| 6 Team and player differentiation | Event-specific strength effects, player tendencies, game-plan dependencies and favorite-compression diagnostics. | Independently measured improvements over conditional league baselines |
| 7 Walk-forward full-game evaluation | Compare against frozen SLC versions, simple statistical baselines and timestamped markets. | Simulation validity, calibration, statistical realism and forecast performance |

## 11. Experimental model arms

We isolate the benefit of the architectural change from the benefit of adding new predictive features.

| Arm | Description |
| --- | ----------- |
| A | Frozen V2 historical sampler with backoff |
| B | Conditional generator with league-level event distributions |
| C | B plus situational conditioning |
| D | C plus conditional player opportunities |
| E | D plus validated offensive and defensive effects |
| F | E plus validated sequence and latent game-plan dependencies |

Initially, B and C matter most. If a simple conditional engine can match V2's predictive performance while eliminating
dependence on historical source rows, that's already a valuable architectural achievement. We can then determine which
additional layers genuinely improve predictions.

## 12. Evaluation and acceptance criteria

| Dimension | Metrics |
| --------- | ------- |
| Reliability | Completion rate, unsupported cells, illegal transitions |
| Local prediction | Event Brier, log loss, calibration, yardage CRPS |
| Statistical realism | Plays, drives, sacks, third downs, turnovers, scoring, usage |
| Forecast accuracy | Winner Brier, margin and total error, distribution calibration |
| Player props | Brier, distribution scores, opportunity accuracy, price-aware returns |

The initial engineering acceptance tests include all 97 unsupported-cell failures from V1 and V1.5 in Week 11, plus the
two V1.6 geometry failures (`docs/research/week11-rerun-preflight-2026-11-23/seed_completion.json` on
`fix/roster-preflight-2026-11-22`).

We should also construct synthetic legal game states covering rare down, distance, field-position, clock and possession
combinations. This is much more informative for structural coverage than immediately launching another 10,000-seed
batch.

A particularly important test: **compile the conditional model package, remove access to all historical PBP rows, and
successfully simulate complete games.** Historical data should only be necessary when building or updating the model
package, not when executing each play.

## 13. Model packaging

Each fitted component produces a versioned, portable artifact containing: `model_id`, `prediction_target`,
`input_schema`, `output_distribution`, `training_data_hashes`, `training_cutoff`, `rule_regime`, `model_parameters`,
`uncertainty_metadata`, `validation_results`, `legal_support_contract`, `dependency_versions`.

A complete statistical simulation becomes a manifest specifying which version of each component is active. This lets us
improve individual mechanisms without continually creating monolithic versions of SLC that bundle unrelated changes.

## 14. How this fits the larger simulation strategy

Shared NFL data and model infrastructure (rosters, ratings, participation, playbooks, PBP) feed two engines:

- **SLC Conditional:** statistical event generation, fast Monte Carlo forecasts.
- **V1 Complete:** autonomous Gridiron execution, spatial simulation and gameplay.

Both use shared football rules and accounting (legal transitions, clock, score, player statistics). The statistical
engine does not need to simulate all 22 players physically to predict a sack, just as the autonomous engine should not
need a historical sack outcome to execute a tackle. They become two independently evaluable methods of generating
football events.

## 15. First assignment

The objective is to eliminate runtime dependency on narrowly filtered historical play-by-play sampling throughout the
statistical SLC engine.

Read the Granular Prediction Modeling Strategy, NFL Situational Research Matrix, Simulation Learnings, Week 11
seed-completion report, and existing transition-strength experiments.

Begin with Phase 0: a comprehensive dependency audit. Inventory every historical-row sampling dependency across
scrimmage, playcalling, player selection, yardage, turnovers, penalties, special teams, clock, tries and overtime. For each
dependency, document:

- Source file and function.
- Current filtering and sampling methodology.
- Required inputs and historical labels.
- Existing conditional models that could replace it.
- Known sparse-cell failures.
- Proposed conditional probability or quantity distribution.
- Legal event constraints and reducer requirements.
- Local and full-game evaluation methodology.
- Migration dependencies and acceptance tests.

Map the entire game lifecycle, from coin toss through regulation and overtime completion. Reuse previously validated
components. Explicitly identify previous failed modeling experiments so we do not repeat them. Design a versioned
event-generation interface compatible with the existing SLC reducer, statistics and portable runtime.

The final architecture must execute complete games without runtime access to historical play-by-play source rows.

Start with simple conditional statistical baselines. Do not introduce global team-strength multipliers, broad
tracking-data fitting, automatic market calibration or new production model changes. Preserve all existing SLC versions.
Do not merge this research into V1 Complete or modify Gridiron's autonomous execution. Complete the audit and
implementation roadmap before fitting new models.

We're moving from **recombining historical football plays to learning the underlying probability distributions that
generate football games.**
