# Legendary Picks: Granular Prediction Modeling Strategy

**Document ID:** LP-GRANULAR-MODELS-2026-10-26  
**Status:** Research strategy and architecture; not an authorization to deploy  
**Date:** October 26, 2026  
**Applies to:** Legendary Picks across leagues, with NFL statistical full-game simulation and Gridiron Physics as current testbeds

**Related documents:**
- [Prediction Modeling Platform](SPEC-modeling-platform-2026-07-16.md)
- [Contextual NFL Full-Game Simulation](SPEC-NFL-CONTEXTUAL-FULL-GAME-SIMULATION-2026-10-25.md)
- [Forecasting North Star](STRATEGY-forecasting-north-star-2026-10-10.md)

---

## 1. Thesis

**We do not need one giant model to predict an entire sporting event. We need the right models for the distinct decisions, processes, and outcomes that create the event, and a rigorously tested way to combine them.**

A football game's winner depends on plays, drives, turnovers, scoring opportunities, time, and strategic decisions. Many of those components can be modeled directly from historical observations, with clearly defined prediction targets and measurable calibration. Some benefit from physical simulation; many do not.

The vision is a **portfolio of specialized, interoperable predictive models** rather than one opaque game-winner model or a physical simulator forced to explain everything.

Having multiple models for one league is coherent when each model serves a different target, method, horizon, or conditioning context. It is not justification for displaying many nearly identical forecasts or promoting every experiment.

**The competitive advantage is not the number of models. It is the ability to define, evaluate, compose, reject, and improve them at the appropriate granularity.**

### Non-negotiable distinction

- **Local predictive quality:** Does a component model predict the event it claims to predict?
- **Global forecast contribution:** Does using that component improve final scores, margins, totals, winners, or player distributions?
- **Simulation validity:** Are the generated sequences legal and statistically plausible?

These are three separate gates. Passing one does not imply passing the others.

---

## 2. The experiment that clarified the strategy: NFL two-point decisions

Our initial E2 simulator chose between an extra point and a two-point conversion using a single historical league-wide attempt rate, approximately 9.5%.

That correctly preserved a global frequency but applied it indiscriminately to the opening touchdown and late-game situations. Asking a narrower question changed the problem:

> What is the probability that a team **chooses to go for two**, given the post-touchdown score margin, period, clock, and whether this is an opening possession?

The two-point decision is a **binary prediction**, independent of whether the subsequent attempt succeeds.

The chronological research produced the following decision Brier scores:

| Historical test season | Unconditional | Conditional K=25 | Conditional K=1 |
|---|---:|---:|---:|
| 2023, model selection | 0.08844 | 0.07335 | **0.05250** |
| 2024, confirmation | 0.08850 | 0.06493 | **0.04619** |
| 2025, confirmation | 0.08362 | 0.05786 | **0.04256** |

On the 2025 fold, K=1 reduces **two-point decision Brier** by approximately 49% versus the unconditional decision model. This is **not** a 49% improvement in NFL game-win prediction.

The audited 2022–2025 regular-season populations also distinguish:
- First touchdown of the game: **12 / 1,079** two-point attempts (1.11%).
- Touchdown on the scoring team's opening drive: **4 / 510** (0.78%).
- Overall: roughly **9.5%** of recorded post-touchdown attempts.

These populations are different and should not be conflated. The contextual candidate is still research-only, with a reserved 2026 evaluation cohort; it has not earned a production promotion.

**Why this matters:** This particular question does not require simulating players running, blocking, or colliding. It requires reconstructing the correct historical situation, modeling a human decision, and validating the resulting probability.

The expected-points difference between the unconditional and contextual policy was small in an early simulation comparison. That does not undermine the local result: a better *decision forecast* can have a modest impact on *aggregate points*. Both facts must be reported.

---

## 3. Prediction taxonomy: model the right object

Every new model must declare which type of question it answers.

| Class | Example | What is predicted | Appropriate methods |
|---|---|---|---|
| **Decision** | Go for two? Punt or go on fourth? | Choice conditional on information available to the decision-maker | Empirical frequencies, hierarchical models, supervised classifiers |
| **Opportunity / exposure** | Number of dropbacks, possessions, service points, minutes | How many chances an outcome can occur | Pace models, count models, state-driven simulation |
| **Event outcome** | Completion, sack, turnover, shot on goal | Result of an opportunity | Conditional rates, distributions, calibrated classifiers |
| **Quantity** | Passing yards, shots, aces, points | Numeric total or per-opportunity amount | Regression, count and continuous distributions |
| **Sequence / state transition** | Drive continues, clock runs, penalty changes possession | Legal transition and timing | Shared rules reducer plus conditional event models |
| **Aggregate** | Game score, winner, spread, total | Joint consequences of many events | Coherent statistical simulation and aggregation |
| **Physical / mechanistic** | Receiver separation, pursuit angle, puck trajectory | Movement and interactions under physical constraints | Physics engine, tracking-based movement and control models |

A model may need several layers. For example, passing-yard forecasts require passing volume, attempt outcome, and yardage conditional on outcome, not merely a standalone yards mean.

### Important methodological distinction

Predicting an action taken by a coach is different from identifying the action that *should* maximize expected win probability.

- **Behavior model:** P(coach goes for two | observable state).
- **Decision optimization model:** Which choice has higher expected win probability under an outcome model?

They may disagree. Do not train an observed-decision model on a decision-theory recommendation or silently replace one with the other.

---

## 4. When to use statistics versus physics

### Default rule: use the simplest method capable of answering the stated question and beating its baseline.

**Prefer granular statistical modeling when:**
- The target has a clean historical label.
- Its relevant context can be reconstructed as of the decision.
- Enough comparable opportunities exist to fit and evaluate probabilities.
- The desired output is a frequency, probability, count, or numeric distribution.
- Physical microstates are not necessary to represent the important causes.

Examples: two-point decisions, fourth-down choices, overtime decisions where rules and history support them, pass/run choice, timeouts, faceoff outcomes, tennis ace rate, and team pace.

**Consider physical simulation when:**
- The question turns on spatial relationships, timing, motion, geometry, or interactions not adequately captured by available summary features.
- Position and tracking data support identification and validation.
- Changing a physical mechanism should change downstream outcomes in observable, testable ways.
- The physical model improves an appropriate baseline, not merely yields convincing visuals.

Examples: receiver separation under changing coverage, a defender's pursuit and reaction, blocked-shot trajectories, or the causal consequences of line changes and puck movement.

**Use a hybrid when useful:** A statistical model estimates event frequencies and the physics engine studies conditional microstate distributions, creates diagnostic counterfactuals, or eventually supplies validated predictors.

### Physics gate

A realistic-looking sequence is not a successful model. The physics engine must pass:
1. **Rule and conservation validity:** legal states and transitions.
2. **Local mechanism validity:** tracking or independently observed movement, contact, timing, and interactions.
3. **Aggregate realism:** possession, efficiency, scoring, and sequence distributions.
4. **Incremental forecast value:** improvement over a statistical or other simple baseline on unseen games.

Do not promote a physical model merely because it can produce a complete drive or because animations appear realistic.

---

## 5. A model-of-models, not disconnected predictions

One event can feed several dependent forecasts. The architecture must preserve those dependencies.

### NFL illustrative dependency chain

1. **Pregame context:** teams, roster, quarterback, opponent, recent form, game type, cutoff.
2. **Possession / clock exposure:** kickoff, field position, drive lengths, number of opportunities.
3. **Decision policy:** down-and-distance play choice, fourth-down action, post-touchdown try, timeout.
4. **Event outcome:** yards, completions, turnovers, sacks, kicks.
5. **Rules transition:** authoritative football reducer updates possession, downs, score, and time.
6. **Accumulated outputs:** final score and player totals.
7. **Forecast distribution:** winners, margins, totals, thresholds, prop hit probabilities.

A two-point attempt model selects the kind of try. A separate outcome model predicts whether that try succeeds. The rules reducer awards the correct points. The batch runner aggregates completed games.

**Do not independently sample every output and stitch them together if doing so creates impossible or contradictory outcomes.**

Example: receptions cannot exceed targets, team receiving yards cannot be disconnected from player contributions, and final score must reconcile with scoring events.

### Shared state, distinct model ownership

Each component owns one well-defined conditional distribution and consumes a documented subset of the shared state.

The composition layer owns:
- Which model versions participate in a simulation.
- Which upstream values each component may read.
- The order of sampling and state transitions.
- Seed, reproducibility, and scenario handling.
- Recording full dependency provenance for the final forecast.

No component may silently rewrite another component's observed inputs or its ground-truth labels.

---

## 6. Local evaluation: choose the right proper scoring rule

**Brier score is not one universal metric for everything.**

For a binary event with probability p and observed outcome y in {0,1}:

**Brier = mean((p - y)^2).**

Examples: whether a coach attempts two, whether a particular pass completes, whether a team wins, whether a player beats a prop threshold.

**Log loss** supplies a complementary, more severe penalty for confident mistakes. Report both when applicable.

For a multi-class decision (run/pass/punt/kick, when the labels are mutually exclusive), use multiclass log loss and a clearly specified multiclass Brier convention. Do not compare the numerical magnitude of differently normalized multiclass and binary Brier scores as if they were interchangeable.

For yardage, point totals, count distributions, or margin forecasts, use:
- MAE and RMSE for point estimates.
- CRPS, log score where tractable, or other proper distribution scores for forecasts with uncertainty.
- Interval coverage and distribution calibration.
- Threshold-specific Brier/log loss only when predicting a particular over/under event.

### Every score needs a declared target

Every reported metric must specify:
- Target and label definition.
- Unit of observation (try, play, drive, game, player-game, or contract).
- Population and exclusions.
- Season/time window and train-test design.
- Forecast timestamp and features permitted at that time.
- Baselines, model version, sample size, and uncertainty interval.

Do not present a Brier score for a two-point *decision* as the model's Brier score for NFL *game winners*.

### Two distinct evaluation scales

**Local scorecard:** Does the new component predict its own target better on future or withheld events?

**Global scorecard:** Does installing the component improve complete-game probabilities and distributions on the same, independently evaluated set of games?

A strong local improvement with no global gain is valuable research, but not sufficient justification to promote the component into the production game forecast.

---

## 7. Research design: avoid false improvements

### Chronological evaluation and cutoff safety

Train only on data that was available when the prediction would have been made. Use walking-forward seasons or weeks; do not use results from the target game or future updates to its historical record.

Where a timestamp is missing, fail closed or clearly label the experiment as non-as-of-safe.

### Selection versus confirmation

Pick hyperparameters on a designated selection period. Report later confirmation periods separately. Preserve untouched prospective or chronological holdout data for the final decision.

The K=1 choice on the 2023 selection fold, with 2024 and 2025 confirmation, is a useful research pattern. Those years are no longer a fully untouched final holdout for future revisions informed by their scores.

### Correct uncertainty

Decisions inside the same game are correlated; player-game props also share game-level exposure. Prefer game-clustered uncertainty or game-level resampling where appropriate, and disclose the confidence-interval method.

Use independent seeds where needed, and *paired* seeds for ablation comparisons when inputs and seed derivation are the same. Report a changed snapshot hash or random-number construction; matching numeric seed IDs do not guarantee a fair paired experiment.

### Sparse cells

Use explicit, documented hierarchical fallbacks or shrinkage. Never interpret 0/1 observations as a guaranteed 0% or 100% probability.

Record effective sample size and the full smoothing path. Evaluate alternative shrinkage strengths chronologically. Avoid choosing a parameter because it makes simulated aggregate frequencies match a desired rate.

### Correct denominator

- A two-point policy is evaluated per *eligible post-TD try*.
- A pass-completion policy is evaluated per *eligible targeted attempt* as defined.
- A sack model needs an appropriate *dropback* denominator.
- A player prop needs a defined set of *player-games / market opportunities* and the correct settlement rules.
- A game winner model is evaluated per *game*.

An invalid, unresolved, or unobserved event is not automatically a loss.

---

## 8. Game-level evaluation and the composition test

Better component decisions do not necessarily improve team scores. Model errors may cancel; component changes may shift the distribution of opportunities; rules gaps may selectively invalidate difficult simulations.

For every composite simulator candidate report:
- Valid completed games / attempted seeds.
- Blocked, tied, unsupported, and failed outcomes, with exact reasons.
- Team score means and distributions; margin, total, and winner probabilities.
- Brier/log loss for game winner and threshold events.
- MAE/RMSE/CRPS or equivalent appropriate score-distribution metrics.
- Player distribution coverage and consistency.
- Simulated versus historical drives, plays, pace, sacks, turnovers, scoring mix, and state-conditional behavior.
- A comparison against the existing production points model and independently timestamped market baseline.

Do not compute the primary forecast only on a selected subset of valid seeds without showing selection bias and coverage. Improving one component while reducing validity may be a regression.

**Two gates are mandatory: local predictive gain AND non-degrading or improving global forecast quality, with sound rule validity.** A component with a strong local score but negligible global impact may remain in the research library or power an independent consumer prediction; it need not be forced into every game simulation.

---

## 9. Cross-sport opportunities

This method extends beyond NFL. These are **research questions**, not claims that the corresponding production models already exist.

| Sport | Granular target | Composition opportunity | Does it initially require physics? |
|---|---|---|---|
| NFL | Go for two; fourth-down choice; pass/run choice | Drives, score, clock, possessions | No |
| NFL | Sacks, completions, yards after catch | QB and player props, team points | Not initially; physics may add explanatory spatial features |
| NHL | Penalty frequency, power-play opportunity and conversion | Goals, totals, player shots | No |
| NHL | Goalie pulled and empty-net decisions | Late-game goals and win probabilities | No for policy; physics may help movement outcomes |
| NBA | Possession pace, shot mix, playing time | Points, rebounds, assists, totals | No |
| Tennis | First-serve-in, serve-point win, ace/DF events | Games, sets, matches, ace props | No |
| Soccer | Shot opportunity, shot-on-target, conversion | Goals, match totals, player markets | No |
| Esports | Map veto/selection, map winner, series length | Series winner, total maps, tournament | No |

For every sport, the first job is to inventory reliable labels, exposures, timestamps, and baselines. Some targets will be too sparse or too inconsistently published to justify a new model.

### Special warning about correlations

Independent player-prop models may each be well calibrated yet jointly imply impossible team-level output. Exposure and shared game state should couple them.

Examples: a team's tennis match length affects both players' ace opportunities; an NFL quarterback's passing volume affects receivers' targets; NBA minutes constrain all box-score accumulation.

---

## 10. Component contract and model registry

A model is not production-ready merely because a notebook or script outputs a probability.

Every component should have a **Model Card** with:

| Field | Required meaning |
|---|---|
| Model ID and version | Unique, immutable prediction mechanism |
| League and target | Precisely defined label and eligible population |
| Context schema | Inputs, source and cutoff restrictions |
| Forecast horizon | Pregame, possession, play, point, or live |
| Output contract | Probability, class distribution, numeric distribution, units |
| Exposure | Per try, dropback, play, game, point, etc. |
| Training manifest | Data hashes, seasons, model inputs and code commit |
| Validation report | Chronological splits, metrics, calibration, subgroup results |
| Baselines | Constant, empirical, previous version, market, or other simple reference |
| Fallback | Documented sparse-data or missing-input behavior |
| Dependency list | Upstream inputs and downstream consumers |
| Computational cost | Runtime, storage, data freshness requirements |
| Status | Proposed / Audited / Candidate / Research-Adopted / Production / Rejected |

Do not create a large model platform before confirming the first few contracts are useful. Start with a small file-backed manifest and comparable reports; add a service or registry only when multiple teams or engines need it.

### Example component interface (illustrative)

~~~text
predict(
  game_snapshot_hash,
  simulated_game_state,
  event_context,
  model_version
) -> {
  target,
  eligible,
  probability_or_distribution,
  exposure,
  fallback_used,
  training_manifest_hash,
  model_version
}
~~~

The model may only read information that would exist at its forecast instant, including its simulated scenario state for an in-simulation decision. Actual future outcomes remain available only to the evaluator.

---

## 11. Multiple models in one league: where they make sense

Multiple NFL models can be legitimate because they answer different questions:
- A model of **coach behavior** predicts fourth-down and conversion choices.
- A model of **play success** predicts the consequence of the chosen play.
- A model of **drive scoring** approximates a whole possession.
- A model of **game points** directly forecasts final scores.
- A model of **physical trajectories** estimates local interactions.

It can also make sense to maintain different approaches to the *same* target (e.g., direct points versus simulated points) as research competitors.

But multiple models should not be presented as if all are equally reliable.

The app should show the **best earned forecast for a target** by default, with provenance, model version, explanation, and historical record accessible in detail. Alternate research models can appear in development comparisons, not as confusing parallel claims on the consumer card.

A direct score model may remain better than an event simulator. If so, retain it. The simulator can still supply scenario exploration or independently valuable event probabilities.

---

## 12. Prioritization: which granular question next?

Prioritize targets using measurable criteria, not novelty:

1. **High downstream leverage:** the event materially affects scoring, opportunities, or important props.
2. **Reliable event labels and exposure:** the event can be audited.
3. **Recoverable pre-event context:** no leakage and enough feature coverage.
4. **Enough examples:** sufficient effective sample size, including important situations.
5. **Simple, meaningful benchmark:** a clear baseline can be beaten.
6. **Integration path:** a valid place in the existing reducer or forecast dependency graph.
7. **Reasonable evaluation cost:** fast enough to run a valid chronological test.
8. **Potential consumer value:** score, prop or explainable signal that fans can use.

### Recommended NFL sequence

**First: finish current two-point research.** Preserve unconditional control; complete the pinned-snapshot validity and paired-game checks; fix snapshot reproducibility. K=1 remains a research candidate until the evidence report and untouched evaluation warrant adoption.

**Next candidate: fourth-down choice.** Predict punt, field-goal attempt, or offensive play conditional on down, yards to go, field position, score, time and context. Use a *multiclass* decision score, not a single binary Brier applied ambiguously. Follow that with distinct success/outcome models.

**Then: play-calling and pace.** Condition run/pass decisions and time consumption on in-game state. Validate that team and opponent factors add information beyond down/distance/score.

**Then: opportunity and player allocation.** Targets, carries, routes or snaps, and player-specific outcomes. Require coherence between player and team totals.

**Research later: fatigue, spatial mechanisms and physics-derived features.** Evaluate whether they outperform strong statistical controls. Do not assume their complexity guarantees more predictive power.

This order is contingent on data inventory and early ablations. Stop or reorder when a feature fails its gate.

---

## 13. Research workflow and falsifiable acceptance

### Phase A: define the question

Write down the target, unit, event eligibility, the known-at-decision context, and the null/baseline model. Identify the consumer or downstream forecast it would improve.

### Phase B: audit the historical labels

Count denominators, exclusions, ambiguous labels, missing timestamps, and subgroup coverage. Pin raw and derived artifacts, and their source hashes. Identify how the source may change after re-ingestion.

### Phase C: fit the simplest useful models

Fit an unconditional base rate, a small conditional model, and a carefully justified hierarchical candidate. Do not add dozens of features at once.

### Phase D: run local chronological tests

Report Brier/log loss for binary decisions, appropriate distributional scores for numerical outputs, calibration, subgroup diagnostics and clustered uncertainty. Predeclare selection/confirmation/holdout roles.

### Phase E: integrate behind a research flag

Keep legacy behavior as the control. Log every selected model version and predicted probability at each simulated decision.

### Phase F: run the global ablation

Use identical frozen input states and comparable random-seed construction, and preserve every attempted simulation. Assess validity, game outputs, scoring distributions and full-game forecast skill.

### Phase G: adopt, revise, reject, or retain independently

- **Research-adopt:** component's target forecast improved, contracts and data are valid; global integration still may be gated.
- **Production-adopt:** independent final evaluation supports both relevant target and product benefits.
- **Retain independently:** useful standalone prediction, but no demonstrated composite benefit.
- **Revise:** defects, sparsity, leakage, or unstable improvements remain.
- **Reject:** no credible improvement over a simpler comparator.

Every result should be reproducible from commit, dataset hashes, target definition, model version, and cutoff.

---

## 14. What this strategy does *not* mean

- Not every football event deserves its own custom model.
- Not every model needs a physics simulation.
- Not every Brier score can be compared with every other Brier score.
- Better local calibration does not prove better game-winner forecasts.
- More Monte Carlo draws reduce sampling noise, not model bias.
- A sophisticated model is not preferable to a baseline that scores better.
- Multiple models for a league do not justify multiple conflicting consumer picks.
- Postgame knowledge cannot be imported into a pregame forecast.
- A complete legal simulation is not automatically a realistic or predictive one.

---

## 15. Definition of done

This strategy is operational when Legendary Picks can:

1. Register several distinct NFL component targets with unambiguous labels, exposure units, data hashes and model versions.
2. Reconstruct historical pre-event inputs without future information.
3. Demonstrate a local improvement over a meaningful baseline for at least one component.
4. Insert or remove that component from the statistical simulator with a reproducible ablation.
5. Report how the change affects legal-game coverage, team scores, totals, margins, game-winner probabilities and relevant props.
6. Preserve the existing production model until an independently validated challenger earns promotion.
7. Apply the same contracts and scorekeeping to a second sport without forcing that sport to adopt NFL-specific mechanics.

**North star:** Legendary Picks should know not merely *which team is likely to win*, but *which predictive mechanisms earned that forecast*, at which level of granularity, and whether each one survives contact with unseen games.

**A collection of locally good models becomes an advantage only when the resulting forecasts are coherent and measurably better.**
