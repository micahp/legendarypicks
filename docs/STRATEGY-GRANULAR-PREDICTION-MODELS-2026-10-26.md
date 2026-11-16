# Legendary Picks: Granular Prediction Modeling Strategy

**Document ID:** LP-GRANULAR-MODELS-2026-10-26  
**Status:** Research strategy and architecture; not an authorization to deploy  
**Date:** October 26, 2026; **evidence/roadmap update:** October 27, 2026  
**Applies to:** Legendary Picks across leagues, with NFL statistical full-game simulation and Gridiron Physics as current testbeds

**Related documents:**
- [Prediction Modeling Platform](SPEC-modeling-platform-2026-07-16.md)
- [Contextual NFL Full-Game Simulation](SPEC-NFL-CONTEXTUAL-FULL-GAME-SIMULATION-2026-10-25.md)
- [Forecasting North Star](STRATEGY-forecasting-north-star-2026-10-10.md)
- [Proprietary Modeling Phases (updated roadmap)](SPEC-proprietary-prediction-system-phases.md)
- [Situational Research Matrix](research/NFL-SITUATIONAL-RESEARCH-MATRIX-2010-2026.md)
- [Historical NFL Rule Regimes](research/NFL-RULE-REGIME-REGISTRY-2010-2026.md)

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

---

## 16. Evidence update and model roadmap, 2026-10-27

This dated section **updates the execution order in §§12–13**; earlier methodological principles and experiments remain part of the research record. Cross-sport architecture is unchanged: distinct target-specific models, a shared frozen state, and separate local-predictive, global-predictive and legal/physical-validity gates. The [phased modeling roadmap](SPEC-proprietary-prediction-system-phases.md) should be read with this update rather than its July 22 "not started" labels.

### 16.1 Independent football-data forecast policy

**Official team/player/game data and verified pregame context are model inputs. Sportsbook moneylines, spreads, totals, player lines, implied probabilities and market-projected stats are NOT training, calibration, feature-engineering, prior-selection or inference inputs for the independent model.** Do not use bookmaker consensus to patch underpredicted games. Captured market information is allowed in a sealed **external evaluation and product-comparison layer after our forecast is frozen**, with its timestamp and de-vig procedure recorded. Reporting a wager/lean is a separate consumer policy, not permission for price leakage into forecasts. ESPN/publisher projection benchmarks must likewise stay outside independent-model features unless separately and explicitly classified as an external benchmark.

The 2026 Week 7 Dallas–Philadelphia game finished **DAL 38, PHI 21 (59 total)**, whereas the integrated contextual S1 mean was DAL 20.8081, PHI 19.9695 (40.7776 total); the recorded v1 reference was DAL 23.1421, PHI 23.1840 (46.3261 total). This is a **single observed tail outcome and diagnostic case, not a tunable target**. Examine the full score, drive, quarter, player-opportunity and turnover distributions over many held-out games before claiming systematic underprediction.

### 16.2 Audited full-game simulator status, not a promotion claim

The completed DAL–PHI research batches are documented in [the run ledger](reports/nfl-dal-phi-10k-run-ledger-2026-10-26.md) and [the integrated report](reports/nfl-dal-phi-s1-integrated-10k-2026-10-27.md). These reports were pushed on another research branch; links describe evidence, **not files newly introduced by this update**.

| Batch | Valid complete, untied / attempts | Limits |
|---|---:|---|
| Unconditional S0 | 7,993 / 10,000 (79.93%) | Dirty producer and different observed references |
| First contextual S1 | 8,825 / 10,000 (88.25%) | Different producer/reference hash; incomplete overtime/blocked-kick transitions |
| Integrated contextual S1 | 9,820 / 10,000 (98.20%) | 173 blocked, one error, six additional complete games that appear tied and require status verification |

The integrated producer was `709fb75959c16adc74baf42e986d4fb85974e0cc`; its **input cutoff preceded kickoff** but its **merged output was frozen after kickoff**. Its recorded v1 lock has unverified schedule provenance. All three runs are **engineering/exploratory**, not a fair prospective performance improvement or a same-engine paired ablation. The reported 2026 matchup included the correct depth-rank QB1s, Dak Prescott and Tanner McKee, but only **41 offensive skill-position depth-chart rows** (18 DAL, 23 PHI), without verified active/inactive game-day flags or full line and defense. Correct QB ID does not validate the rest of the roster.

**Release gates:** preserve an immutable per-seed ledger (score, status, blocker/trace, overtime/tie state, rules, input hashes), correctly retain final regular-season ties as third outcome, identify/resolve every error, implement or explicitly quarantine legal kick/return/penalty states, and compare matched S0/S1 under one engine and one cutoff. Current blocking categories include blocked kicks/recoveries (105), thin extremely long FG cells (45; `yardline_100 >= 50` means roughly 67+ yard kicks, not ordinary 50-yard kicks), and safety free kicks (23). Report coverage and conditional-on-valid score forecasts separately. A high completion rate alone is not predictive skill.

### 16.3 Next core model: projected game-day personnel, not a static 53-man list

**Distinguish these states:** roster membership/transaction eligibility; official practice participation (DNP/limited/full); official game-status designation (Out, Doubtful, Questionable, no designation); expected game-day dressing; verified published inactive list (~90 minutes pre-kickoff); emergency third-QB conditional eligibility; and **actual play/snap workload**. A player who dresses but receives zero snaps is NOT inactive. `ACT` in nflverse weekly rosters is NOT guaranteed to mean on the final game-day dressed list. `INA` may include stale/disconnected roster records. Do not map `RES` as a complete, error-free IR indicator. `INA` is absent in 2016–2018 weekly files; it becomes a candidate label from 2019 onward only after verification.

**2024 validation already in progress:** 64 games (weeks 1–4), 806 official list entries, 812 nflverse `INA` rows. An initial name-based reconciliation matched 783 exactly plus 21 aliases, with 25 emergency-QB entries; it still had two reported `ACT` conflicts and eight `INA`-only rows before third-source adjudication. Manual aliases, late announcement amendments (e.g., Evan Engram), former-team players, trades/waivers/IR, and incorrect team-code mapping (`LA`/`LAR`, `WAS`/`WSH`) make an unverified 99% headline insufficient. **Do not mark any final precision/recall, GSIS coverage or fitted questionable/doubtful rate as established yet.** Preserve official `game_id`, team, source URL, publication/observation version, timestamp, GSIS ID or unresolved ID, inactive/emergency status, dated transaction evidence and adjudication reason. Work on official inactive collection was delegated to a separate agent; its still-pending revised output is not a shipped artifact.

**Current archived support:** `nfl_hist_injuries` 90,752 rows (2009–2025), `nfl_hist_snap_counts` 324,612 (2013–2025), `nfl_hist_depth_charts` 552,514 (2010–2024), `nfl_hist_participation` 478,989 play keys (2016–2025), `nfl_hist_ftn_charting` 185,215 play keys (2022–2025). These are **development snapshot measurements**, not assured complete sources. Historical injuries contain missing `date_modified` and `report_status`; 2025 injury rows lack `date_modified`. The 2023 injury table has incomplete playoff coverage. Some historical depth charts lack publication times and 2025 changed schema. `nfl_hist_participation` in the measured local copy has no individual player IDs; inspect newer/raw releases before declaring player-level coverage absent globally.

**Models, each separately graded:**
1. `P(dressed | information available at cutoff)`: historical official inactive outcome; do not substitute "had a snap."
2. `P(position-group/role | dressed, team, opponent, game plan)`: replacement and formation assignments; projected full offensive/defensive/special-teams units and bench.
3. `P(snap/routes/targets/carries | dressed, role, game context)`: workload distribution, including active-but-limited players.
4. `P(stat outcome | opportunity, ability, opponent, venue, in-game state)`: player props, with uncertainty and player-team stat conservation.

Do not hardcode "Questionable = 50%" or "Doubtful = 25%" for the current designation regime. The NFL removed `Probable` in 2016; later status labels are qualitative. Estimate empirically with hierarchical smoothing and report subgroup coverage and out-of-sample calibration. The prior `QBI` and `AVAIL` features were **not adopted** in earlier evaluation; this opportunity-based model is a distinct challenger, not a claim those failures never happened.

**Product horizon:** issue and grade independent forecasts **early week, during practice reporting, at final game-status report, and after official inactives**. Freeze each cutoff and publication evidence. User forecasts must not depend on waiting until 90 minutes before kickoff. Publish scenario-mixture uncertainty early, then narrow it when statuses resolve. Store both `P(dressed)` and `P(performance | dressed)`; keep an unconditional DNP-inclusive distribution separate from conditional-on-dressed prop projections and settlement rules.

### 16.4 Complete situational/context factor research without empty Cartesian cells

The [NFL situational matrix](research/NFL-SITUATIONAL-RESEARCH-MATRIX-2010-2026.md) enumerates day of week, kickoff slot, rest/bye/travel/time zones, team records and form (including 2–4 vs 2–4), coach, divisional stakes, Q1 vs Q4, score/clock and fatigue, down/distance/field, quarterback replacement, offensive line and defensive absences, venue surface/roof, weather/elevation, passing/rushing styles, fourth-down/try/kick/timeout decisions and player exposure. Investigate interaction hypotheses, **not an exhaustive unshrunk decision tree**. Use opportunity denominators, as-of features, opponent/era controls, shrinkage, matched same-engine ablations and game-clustered uncertainty. Publish null results, including previously unsuccessful pressure/coverage/FTN and availability features.

**Available supporting context:** nflverse schedule includes date/weekday, kickoff, rest, stadium/roof/surface, referee, temperature/wind and prior scores; NFL `load_officials()` has historical multi-person crew data (coverage beginning 2015, subject to checks). **Attendance and TV broadcast are not standard schedule fields** and need separately timestamped external sources if studied. Stadium geolocation is an enrichment. Observed game-time weather, final attendance or roof state cannot be imported as a future kickoff forecast without a separately recorded pregame estimate.

### 16.5 Rule history is part of the data model

The expanded [2010–2026 rule registry](research/NFL-RULE-REGIME-REGISTRY-2010-2026.json) has **124 itemized change records across 17 seasons**, with an [annual guide](research/NFL-RULE-REGIME-REGISTRY-2010-2026.md). It is **not certified a complete 17-edition article-by-article audit**. A separate experimental branch may still be reading the earlier 39-record registry; reconcile current schema and source hashes before merging.

Every historical record and simulated action needs **source and target season / season type / active rules**, plus legality/compatibility tests for PAT and two-point attempts, 2024–26 kickoff/onside/touchback, 2010–12 and 2022/2025 overtime, penalties, blocked kicks, missed-FG restarts and clock. Rules determine permitted actions; historical evidence estimates probabilities. A KS test failing to reject an era difference does not authorize executing an illegal action. The 2026 contingency provision on replacement-official reviews must not be treated as automatically active.

### 16.6 Historical source and full-game evidence contracts

`nfl_schedule_versions` and `first_observed` exist on an isolated research feature branch, but the measured development DB lacked schedule versions. Overwritten schedule `ingested_at`, retrospectively inferred QB starters, final injury statuses, and published-after-lock depth charts cannot satisfy strict historical replay. Keep all inputs in one of three classes: **observed by cutoff**, **retrospective date-filtered but publication unverified**, or **unavailable**. An input can be useful for exploratory modeling without qualifying for equal-information accuracy evaluation.

Define an immutable per-game `forecast_snapshot` with source URL/hash, source publication and LP observation times, UTC cutoff, exact roster scenario mix, target rule regime, model and engine commits, team/player projection versions, seed set and independent baseline reference. All model outputs for a given cutoff are fixed **before** the game's actual result becomes available. Do not backdate a late 10,000-run result. For paired comparisons, identical seed integers are insufficient when the model fingerprints re-key random draws; use verified common-random-number streams or report independent MC uncertainty.

Score independently:
- **Labels / exposures:** inactive precision/recall, active-status Brier and calibration, snap/route/target/carry distributional scores, team-player reconciliation.
- **Situational choice / play outcomes:** log loss/Brier with correct opportunity denominator, yards/success CRPS and drive/quarter/endgame distributions.
- **Whole games:** legal transitions and tie/coverage, points/total/margin error and CRPS, three-outcome winner scoring, calibration and independent-market benchmark comparisons on identical games.
- **Replay / physics:** video fidelity, explicit possession/catch/goal-line score synchrony, 22-player movement trajectories, contact and football tracking displacement against constant-velocity and historical Big Data Bowl controls. An outcome-conditioned animation is a visualization of a sampled result, not evidence that a 3D physical process predicted it.

### 16.7 Revised execution order and explicit acceptance gates

| Order | Deliverable | Exit criterion |
|---|---|---|
| **R0** | Preserve reference/control models | Frozen v1, S0, contextual S1, and existing prop-baseline versions; no silent default/fingerprint changes; documentation, evidence and hash manifests |
| **R1** | Historical label correctness | GSIS-joined official inactive lists, dated transactions, roster-status confusion matrix by year, missing/alias/emergency-QB exclusions, holdout labels |
| **R2** | Early-week availability and workload models | Multi-horizon `P(dressed)`, `P(workload | dressed)`, and replacement opportunities, with chronological calibration and explicit unknown status |
| **R3** | Legal full-game completion and rule regimes | 2010–2026 season-specific rule resolver with source-target mapping, per-seed ledger, valid overtime ties, no untracked blockers/errors; first two arms on same engine |
| **R4** | End-to-end predictive comparison | Cohesive player stats and final score outputs; same-cutoff v1/S0/S1 ablations vs observed outcomes, untouched chronological holdout, measured tail behavior |
| **R5** | Situational ablation program | Registered day/rest/record/venue/officials/QB/injury/quarter interactions; coverage and measured incremental global benefit, nulls retained |
| **R6** | Optional physically grounded playback | Movement and contact accuracy vs tracking/constant velocity, frame-level ball and score consistency; no claim of forecast uplift without independent evidence |
| **R7** | Consumer and multi-league rollout | Early forecasts and confidence updates, publicly graded player/game/playoff outputs, independent odds comparisons and cross-sport contracts after league-specific validation |

**Merge gate:** a Phase 1 consolidation branch can merge to `dev` only when its tests, source hashes, configuration defaults, frozen forecast semantics, and old/new behavior differences are documented. `dev` integration is **not** automatic production deployment. The original statistical prediction, an outcome-conditioned 3D replay, and a physics-generated game must stay labeled as different products/claims.

**Do not overfit Dallas 38–21.** Use that game as an untuned postmortem and evaluate whether any proposed fix improves a broad later or out-of-sample set. This roadmap is not evidence that the listed work is already implemented or promoted.
