# Simulation learnings: Legendary Picks × Gridiron Physics

**Status:** Living research document · **Established:** 2026-10-22 · **Branch:** `dev`  
**Scope:** NFL predictive play-by-play, Gridiron Physics, and transferable simulation lessons from NHL and other sports.  
**Purpose:** Preserve what we have actually learned, what remains a hypothesis, what we have decided, and what experiment would change our minds.

> **Core question:** Can we move from independently sampling plausible outcomes to generating coherent plays, drives, games, and player statistics from the abilities, decisions, and interactions that cause them?
>
> **Guardrail:** A realistic-looking play, a realistic average score, and an accurate prediction are three distinct achievements. None proves the others.

This document is a **running synthesis**, not the source of record for evaluations. Keep the dated reports, code revisions, raw results, and held-out boundaries immutable; link them here. Update this file when research changes our understanding. Do not rewrite failed experiments into successes.

## 1. Research thesis

A conventional statistical game generator estimates `P(next event or outcome | observed game state)`. A physical/behavioral generator can instead sample **causes** (player roles, choices, physical attributes, initial conditions, execution uncertainty) and calculate how their interactions produce an outcome.

This changes *what randomness represents*, but does not eliminate randomness. Play calls, attention, reaction, execution error, unobserved traits, injuries, initial conditions, and uncertainty in the model still require stochastic treatment. Physics supplies constraints and dependencies; it cannot recover information we do not have.

**Our intended architecture:**

1. **Predictive layer:** As-of-time team/player strengths, usages, calibrated expectations and uncertainty. Retain simple statistical forecasts as challengers and potentially as priors.
2. **Game/drive decision layer:** Game state, legal transitions, formations, personnel, play calls, fourth-down choices, clock, field position, scoring and possession.
3. **Physical/behavioral layer:** 3D player motion, routes, coverage, blocking, throw and ball flight, catches, tackles, after-contact movement, and eventual turnovers. The engine must resolve unconstrained outcomes for *prospective* experiments.
4. **Evaluation layer:** Test physical plausibility, play distributions, drive realism, game distributions, and held-out prediction skill separately. Include runtime costs and sensitivity to uncertain ratings.

These are composable layers, **not** a commitment that every production forecast must run full 3D physics. Compare statistical-only, physics-driven and hybrid approaches on the **same eligible games and starting conditions**.

## 2. Confirmed evidence: NFL sequence engine v0.1

**Source:** [Drive evaluation](https://github.com/micahp/legendarypicks/blob/feat/gridiron-pbp-engine/docs/DRIVE-EVAL-nfl-sequence-v0.1-2026-10-22.md) and [game-level evaluation](https://github.com/micahp/legendarypicks/blob/feat/gridiron-pbp-engine/docs/RESULTS-nfl-sequence-v0.1-2026-10-22.md), at least through [commit `51db9868`](https://github.com/micahp/legendarypicks/commit/51db9868d07c06899447c44b6d4ae82d60f8f5cc). Data: [drive results JSON](https://github.com/micahp/legendarypicks/blob/feat/gridiron-pbp-engine/docs/results/drive-report-2022-2023.json) and [representative drives](https://github.com/micahp/legendarypicks/blob/feat/gridiron-pbp-engine/docs/results/drive-examples-2022-2023.txt).

- Trained on **2010–2021** NFL play-by-play; held out **2022–2023**, **543 games**; **100 seeded simulations per game**. This is a team-agnostic statistical sequence engine, not physical execution or a Patriots–Bears forecast.
- The drive report reconstructs **11,984 real drives**, or **22.07/game**, against **22.89 simulated/game** under that report's definitions. The earlier game-level report says **22.08 simulated drives/game**; **reconcile the counting conventions** before citing one universal drive-count headline.
- Plays per drive and mean offensive yardage are reasonably close: real **5.56 run/pass snaps**, **30.4 offensive yards**; simulated **5.45**, **30.1**. Similar means do **not** prove realistic sequences.
- **Drive endings differ materially:** real vs simulated per game: offensive TD **4.54 vs 3.73**; punts **8.18 vs 9.50**; clock-expiration endings **0.59 vs 1.77**; kneel-ended drives **0.97 vs 0.07**. A coherent script can still be wrong about *how* drives end.
- Real vs simulated **third-down conversions: 40.4% vs 38.7%**; **fourth-down go shares: 18.8% vs 14.4%**; **TD conversion on red-zone entries: 54.9% vs 48.2%**. These are distinct, testable causes of excess punts and missing touchdowns.
- **Field goals:** real **2,122 attempts** (**1,814 made**, **308 missed**) across the held-out drives; attempts/game **3.91 real vs 4.17 sim**; make rate **85.5% vs 84.9%**; mean attempt distance **39.2 vs 36.6 yards**. The simulator samples kick outcomes statistically. The shorter attempts point partly to where drives stall, not necessarily a kicking-accuracy defect. Field-goal *ending* counts differ slightly from attempt counts because of returns and anomalous historical ordering.
- **Average points per team-game:** real **21.83**, simulated **18.59**, gap **−3.24**. Across two teams this is approximately **−6.47 points/game**, casually “about a field goal per team,” **not** evidence that adding a field goal would fix the game. Score standard deviation is also too small (**8.30 sim vs 9.66 real**).
- **Prediction skill has not been established.** Main model winner Brier **0.2543**, worse than constant training home-win baseline **0.2466**; winner accuracy **49.35%**. This is unsurprising for a team-agnostic engine. No adoption as a wagering or game-winner forecast.

### Diagnosed failures and next falsifiable tests

| ID | Current diagnosis | Evidence | Next test (without tuning to the holdout) |
| --- | --- | --- | --- |
| D1 | Play selection/runoff lack real time-remaining context | Late-game kneels too rare; early kneels appear; clock endings too common | Add time/score/timeout context; evaluate late-window decisions and drive endings on chronologically later data |
| D2 | Pass-yard outcomes pooled across downs | 3rd-and-5–7 pass YPA 7.29 real vs 6.65 sim; 3rd-down conversion shortfall | Condition on down + distance; examine conditional yards per completion and field-position mix |
| D3 | Fourth-down policy too conservative | Go share 18.8% real vs 14.4% sim; 1.31 excess punts/game | Test field/time/score/era-aware decision policy |
| D4 | Old kickoff rules/distributions shift starting field | Touchbacks 66.4% real vs 51.3% sim | Introduce rule-era versioning; preserve holdout separation |
| D5 | Defensive return TD mechanism missing | Defensive TDs 0.258 real vs 0.026 simulated/game; return yards sampled as zero | Model INT/fumble returns and return TDs; test post-turnover possession/score state |
| D6 | Kicks are shorter than real attempts | Mean 36.6 sim vs 39.2 real yards | Decompose drives reaching FG range, fourth-down policy and attempt placement |
| D7 | Red-zone conversion below observed | 48.2% vs 54.9% TD on red-zone entry | Inspect red-zone snap-level decisions, down/distance and yardage, not only aggregate TD rate |

**Evaluation rule:** a mechanism is only a candidate improvement if the intended downstream metric improves without hidden deterioration elsewhere. Preserve the current main model as the baseline.

## 3. Confirmed evidence: Gridiron Physics free run/pass prototype

**Source:** [Free Physics Outcome Probe](https://github.com/micahp/gridiron-physics/blob/feat/free-run-pass-physics/docs/research/FREE-PHYSICS-OUTCOME-PROBE-2026-10-22.md), [ratings documentation](https://github.com/micahp/gridiron-physics/blob/feat/free-run-pass-physics/docs/RATINGS.md), [physics source](https://github.com/micahp/gridiron-physics/blob/feat/free-run-pass-physics/engine/play.js).

- The Patriots–Bears prototype uses pregame rosters, 2025 observed playbook attribute combinations and **estimated** player skill/physical ratings. The mock selector is *not* a trained matchup forecast.
- Prospective `outcome_mode: 'free'` runs can gain **or lose** yards; passes can complete, be broken up, dropped or missed, and yield yards after catch. Same seed is reproducible. Changing defensive physical inputs/ratings can alter results, but prior interventions used intentionally extreme values.
- A narrow smoke sample (**60 passes per offense**) produced **14/60 NE** and **11/60 CHI** completions, **25/120 = 20.8% combined**, with **no observed sacks/interceptions in those samples**. This is **not** a representative calibrated completion rate or proof that those events cannot happen.
- A successful tackle is currently resolved using contact plus a ratings-based **probability draw**; a broken tackle involves stumbling/defender recovery logic. Routes, coverages, catch windows and various outcome probabilities are hand-authored or simplified. Their physical realism and ability to predict actual NFL play outcomes are **unverified**.
- Distinguish the **3D Three.js presentation and 3D ball flight** from the **player contact solver**: current player dynamics primarily use horizontal circular collision bodies, with 3D poses rendered on top. **The product requirement is genuine 3D physical player contact**, not merely a 3D visualization of a planar interaction. Keep Three.js for viewing; evaluate replacing the custom low-level player solver with an established *3D* physics engine.
- Free physics is currently limited to **run/pass** prospective mode. Other actions, including standalone prospective field goals, and genuine free fumble/loose-ball recoveries are not yet established. Historical reconstruction and outcome-constrained rendering remain separate modes.

### Physics engine architecture decision (provisional)

**Decision:** Investigate an established 3D solver; do **not** silently replace the renderer, discard the current demo, or claim a solver was chosen.

**Candidate engines:** Rapier 3D and Jolt, with PhysX as a reference if useful. Preserve Three.js, team assets, ratings/identities, playbooks, cameras, play-selection adapters and historical playback. Compare 3D rigid body/compound-collider contact, articulated joints, controlled fall/balance, repeatability, headless and browser/mobile runtime, solver stability and licensing.

**Required experiment:** Two-player tackle and QB/receiver/defender pass interactions, then 22-player benchmarks, with no forced end spot or random “tackle won” label determining the physical result. A reputable solver alone does **not** provide realistic football biomechanics, intelligence or policy.

## 4. Key learnings about randomness and ratings

**Hypothesis, not yet verified:** Model uncertainty at the level of plausible causes (play call, personnel, assignments, route, release, contact, balance and execution) may produce more coherent player/drive outcomes than separately sampling final yardage, touchdowns and props.

**Why it may help:** Shared causal interactions can connect a pass rush to throw timing, timing to separation/catch, catch to YAC and tackling, and a third-down conversion to a continued drive. A turnover or sack can propagate to field position and later scoring.

**Where it could fail:** Estimated ratings contain imputation, noise and uncertain causal meaning. Three-dimensional dynamics with inaccurate actions, initial positions or contact rules can be *less* realistic/predictive than a calibrated statistical model. Random-seed variety is not evidence of valid distributions.

**Rating audit required:** Trace each skill from source → physical parameters/behavior policy → eligibility/contact mechanics → observable play result. Intervene on **one parameter at a time** with plausible ±5/±10-rating changes and matched seeds. Test monotonicity and response curves for THA, THP, CTH, RTE, PBK, PMV/FMV, TAK, BTK/ELU, CAR and kicking; distinguish an unused attribute from a weak causal effect.

**Rare-event accounting:** Ask “how many eligible opportunities until a sack, interception, fumble, or missed field goal?” Use correct denominators: sacks/**dropbacks**, INTs/**pass attempts**, fumbles/**ball-carrying opportunities** (or named alternative), misses/**FG attempts**, with event opportunity context, confidence intervals and distributions. Never replace a missing mechanic with an invented event just to match a rate.

## 5. Evaluation ladder and promotion gates

| Level | Question | Example evidence |
| --- | --- | --- |
| **0. Provenance/state** | Is input pregame-only, event legal, and replay reproducible? | Frozen snapshots, seeds, rules, no target leakage, score/clock reconciliation |
| **1. Physics** | Are trajectories and contacts physically coherent in 3D? | Geometry, momentum, ball trajectory, reach, collision/joint stability, video/tracking comparisons |
| **2. Play** | Are outcome frequencies and *conditional* behaviors realistic? | Completion vs separation/target/pressure; rushing by gap; sacks, INTs, tackles and YAC by opportunity |
| **3. Drive** | Do plays compound into believable possessions? | Plays/yards/first downs/clock/starting field, TD/FG/punt/turnover, 3rd/4th downs and red zone |
| **4. Game** | Are score and player-event joint distributions realistic? | Team score SD/tails, margin/total, possession count, comeback/late-game logic, coherent props |
| **5. Prediction** | Does it improve **future** forecasts over a cheaper baseline? | Brier/log loss, CRPS/MAE, calibration, held-out and prospective results, uncertainty and compute cost |

**Compare at all levels:** (A) statistical-only sequence engine; (B) physics-resolved actions with identical preplay contexts; (C) a predeclared hybrid. Use the same eligible starting states and scoring definitions, record selection/fallback rates, and keep forecast-quality claims separate from visual plausibility.

**No promotion based solely on:** plausible average score, an attractive 3D replay, a single spectacular play, higher seeded diversity, or a retroactively tuned holdout.

## 6. Transferable NHL lesson

[Earlier cross-sport simulation analysis](https://github.com/micahp/legendarypicks/blob/research/simulation-architecture-learnings-2026-10-22/docs/research/SIMULATION-ARCHITECTURE-LEARNINGS-2026-10-22.md) found that NHL statistical shot-chain simulation could improve one marginal (shots on goal) while worsening goals and joint score accuracy; adjusting variance did not cure the structural failures. A rebound is a causal follow-on event, not just a separate sampled shot.

**Principle:** Preserve what predicts well, test mechanisms against actual event sequences, and reject complexity when it harms the measured goal. The physical model may be most valuable for selected interactions or to train a fast surrogate rather than running for every production game.

## 7. Open questions and prioritized work

1. **Drive definitions:** Why does the game-level report count 22.08 simulated drives/game while the drive-specific evaluator reports 22.89? Align scope, counts and conventions.
2. **Statistical drive mechanism:** Test D1–D7 one at a time, starting with clock/kneels, down-conditioned pass yardage, fourth-down decision context and red-zone diagnostic breakdown.
3. **Player mechanics:** Why is completion so low in the constrained 120-pass free-physics smoke test? Instrument release timing, route separation, target reach, catch window, drops and defender contest before changing coefficients.
4. **3D engine proof:** Compare Rapier vs Jolt on true three-dimensional tackle, failed wrap, pass/deflection and 22-player scenes. Keep physics and animation provenance distinct.
5. **Rare events:** Establish whether physics can *actually* produce sacks, interceptions, loose balls, fumble recoveries and field goals, not simply replay or assign them.
6. **Ratings reliability:** Validate player input confidence and sensitivity against actual tracking/observed outcomes where licensed data permits. Avoid interpreting overall rating as a physical law.
7. **Physics ↔ sequence integration:** Specify how free-play physical results update official down, distance, clock, possession, points and player stats. Statistical-only fallback must be explicit and separately counted.
8. **Team-specific predictions:** Add as-of team/player strength only behind held-out tests. Do not treat v0.1 team-agnostic winner probabilities as production forecasts.

## 8. Decisions ledger

| Date | Status | Decision or observation | Reason / revisit criterion |
| --- | --- | --- | --- |
| 2026-10-22 | **Agreed research principle** | Evaluate **real drives**, not just individual plays and final scores | D1–D7 were invisible in averages |
| 2026-10-22 | **Keep** | Statistical-only generator remains an experimental baseline and potential production component | Physics must earn incremental value |
| 2026-10-22 | **Requirement** | Prospective play outcomes cannot be conditioned on a real final spot, real credited tackler or the result being predicted | Prevent reconstruction masquerading as prediction |
| 2026-10-22 | **Requirement** | Player **contacts** should be resolved in genuine 3D, not only visually presented in Three.js | Essential to the intended mechanistic tackle/catch model |
| 2026-10-22 | **Research direction, not solver adoption** | Evaluate Rapier 3D vs Jolt while keeping Three.js rendering | Check determinism, contact quality, throughput, licensing |
| 2026-10-22 | **Not adopted** | NFL sequence v0.1 as a game-winner model; current free-physics outcome frequencies as calibrated NFL rates | Brier under baseline; play mechanics unvalidated |

## 9. Running experiment log

Add a new dated entry for every significant finding; link the **immutable** report or commit. Never delete a prior negative result.

### 2026-10-22 — Initial synthesis

- **Observation:** Statistical game scripts validate, but drives underproduce TDs, overproduce punts, and mishandle late clock/kneel decisions.
- **Observation:** Field-goal attempt and make averages are relatively close while attempt distance is short; location and earlier drive decisions matter.
- **Observation:** Mean team scoring is low by 3.24 points and the score distribution is too narrow; the “one FG/team” analogy is descriptive, not a fix.
- **Observation:** Gridiron free run/pass mechanics generate nonanchored gain/loss/catch variation, but a 120-pass smoke sample yielded only 25 completions. Player contact currently lacks full 3D mechanics.
- **Hypothesis:** Causal, ratings-sensitive execution can change the *structure* of randomness and drive outcomes, if physical mechanics, behavior and starting conditions are measured rather than invented.
- **Next evidence:** Paired physics-engine comparison, per-mechanism player-rating sensitivity and drive-level ablations with held-out evaluation.

### YYYY-MM-DD — [short experiment title]

- **Question / hypothesis:**
- **Baseline and treatment:**
- **Data and cutoff:** (training, tuning, holdout, prospective)
- **Sample, seeds and denominators:**
- **Results and uncertainty:**
- **Unexpected findings / known limitations:**
- **Decision:** Adopt / reject / research-only / unresolved
- **Source:** (exact report and commit)
- **Next test:**

## 10. Maintenance rules

- Edit this file **on `dev`** when new research changes the synthesis; keep evaluation reports and raw data in their relevant branches or explicitly merge them through review.
- **Always attach a date, branch/commit, eligible sample, denominator and evidence link** to new quantitative claims.
- Label every statement **observed, hypothesis, decision or unsupported**. Separate reconstruction, mock-selector free play, statistical simulation, and held-out game prediction.
- When a claim changes, add a superseding entry and explain why instead of erasing the old one.
- Record both promising and failed experiments. Avoid parameter tuning against the same test set; use dev/training partitions and fresh future evaluation to validate selected changes.
- Keep references versioned. If a linked research branch is rewritten or retired, replace its link with a pinned commit or a reviewed document on `dev`.
