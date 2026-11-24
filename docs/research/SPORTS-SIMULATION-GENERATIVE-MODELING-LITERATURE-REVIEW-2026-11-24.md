# Legendary Picks: Statistical Sports Simulation Literature Review

Date: 2026-11-24. Status: targeted literature review and proposed research program, not a production promotion or authorization to launch experiments. Primary scope: SLC V2 and SLC-CEG. Secondary scope: V1 Complete and other sports.

Related internal research: [CEG plan](SLC-CONDITIONAL-EVENT-GENERATION-PLAN.md), [CEG status](slc-ceg-2026-11-24/README.md), [Phase 7](slc-ceg-2026-11-24/PHASE7-EVALUATION-REPORT.md), [Phase 8](slc-ceg-2026-11-24/PHASE8-TEAM-STRENGTH-REPORT.md), [Phase 9 preregistration](slc-ceg-2026-11-24/PHASE9-PREREGISTRATION.md), [V2 component ablation](SLC-V2-COMPONENT-ABLATION-2026-11-05.md), [Granular Prediction Modeling Strategy](../STRATEGY-GRANULAR-PREDICTION-MODELS-2026-10-26.md), [NFL Situational Research Matrix](NFL-SITUATIONAL-RESEARCH-MATRIX-2010-2026.md), [DraftKings research note](../RESEARCH-draftkings-sports-simulation-2026-10-14.md).

## 1. Executive summary

- Conditional generative play-by-play simulation has established industry and academic precedents. CEG is a credible architectural family, not a validated forecasting model.
- Empirical historical sampling also has published precedents. V2 should be retained as an empirical control; subtractive ablation must establish which of its layers earn their place.
- Joint estimation of offense and defense, dynamic team strength, distributional yardage and hierarchical models offer alternatives to separately estimated outcome ratios.
- Overshrinkage is a known statistical problem, directly relevant to CEG's weak differentiation of teams.
- Sequence models and latent states offer ways to represent dependence beyond the visible game state; they are lower priority than basic strength and scoring.
- None of this requires a large neural network or GPU by default.
- Local prediction, global forecast contribution, realism and legal validity are distinct gates.

The literature does not establish that CEG outperforms V2. It supplies candidate methods to compare, not a mandate to implement them all.

## 2. Historical development and internal research gap

| Year | Direction |
|---|---|
| 1998 | Dynamic Bayesian NFL team strength and score prediction |
| 2010 | Hierarchical soccer scoring, attack/defense, overshrinkage |
| 2012 | Absorbing Markov model of NFL drives |
| 2016 | Multiresolution basketball stochastic processes |
| 2018–19 | Hierarchical baseball matchup and NFL player contributions |
| 2021 | Hidden Markov NFL playcalling |
| 2023 | NFLSimulatoR empirical simulation; parametric NFL rushing distributions |
| 2024 | DraftKings multistage football generation; Markov-switching trees; autoregressive soccer events |
| 2026 | Empirical-tree NFL simulation; Bayesian ball-carrier generation |

The October 14–16 DraftKings note already referenced the directly relevant football article. The October 26 granular strategy articulated separate event models and local/global/validity gates. The situational matrix identified partial pooling and sparse-cell risks. However, the November 24 CEG plan moved from internal experiments to implementation without a documented comprehensive comparison of external generative methods. The present review fills part of that gap.

## 3. Generative sports simulation

### 3.1 DraftKings: Modeling Football (2024)

Ian Dorward, DraftKings Engineering. [Original article](https://medium.com/draftkings-engineering/modeling-football-combining-ml-models-and-monte-carlo-simulations-170fd58cbe11).

Closest published commercial architecture to CEG. Uses team-specific action classifiers, logistic regression for binary decisions and multinomial logistic regression for categorical events. The illustrative pass sequence is action -> attempted air yards -> pass outcome (completion, incompletion, interception or sack) -> YAC if completed -> fumble where applicable -> state/stat updates. Rushing has a separate yardage model. Fourth-down decisions and penalties are discussed; predicting what a coach will do is distinct from optimizing what the coach should do.

| Aspect | Published DraftKings description | Current CEG |
|---|---|---|
| Generation | Conditional | Conditional |
| Binary decisions | Logistic regression | Smoothed empirical distributions |
| Categorical decisions | Multinomial regression | Hierarchical cell estimates |
| Yardage | Fitted classifiers | Discrete hazards |
| Team effects | Team-specific models | Shrunk component adjustments |
| Runtime historical rows | Not required by described classifiers | Not required |

Application: evaluate regularized regression against CEG's current estimators (already backlog E9). Reproduce the methodology, not proprietary parameters. Public disclosure does not establish comparative forecast accuracy, exact data, or full production details.

### 3.2 Goldner: A Markov Model of Football (2012)

Keith Goldner, Journal of Quantitative Analysis in Sports. [DOI](https://doi.org/10.1515/1559-0410.1400).

An absorbing Markov chain represents NFL drives using down, distance and field position. Transitions lead to terminal drive outcomes and expected points. A first-and-ten can transition to second-and-four, second-and-ten, a new first down, etc., eventually ending in a touchdown, field goal, punt, turnover or other supported state.

Application: independent simplified drive diagnostic for CEG's scoring deficit. Examine continuation, explosive plays, red-zone conversion, fourth-down choices and termination probabilities. For a finite absorbing chain with transient matrix Q and terminal matrix R, absorption probabilities are (I-Q)^(-1) R where the assumptions hold. This is a proposed LP diagnostic, not a claim that the complete engine is a small homogeneous Markov chain.

### 3.3 NFLSimulatoR (2023)

Williams, Palmquist and Elmore, Annals of Operations Research. [Paper](https://doi.org/10.1007/s10479-022-04524-7), [R package](https://cran.r-project.org/package=NFLSimulatoR), [source](https://github.com/rtelmore/NFLSimulatoR).

Historical play resampling supports simulation of drives and evaluation of fourth-down/run-pass strategies. Documentation illustrates stratification by team passing ability. This legitimizes V2's foundational approach, not every filter or modifier. The published applications do not establish superiority at pregame game-winner or player-prop forecasts.

Application: finish V2 subtractive ablations and retain a simple empirical situational control.

### 3.4 Minimally Sufficient: Inside the Simulation Model (2026)

[Technical article](https://minimallysufficient.com/posts/nfl-simulation-model/). Independent implementation, not peer-reviewed.

A hybrid learns football decisions and partitions with decision trees, then samples empirical outcomes from terminal leaves. This avoids manually intersecting every historical variable, retains relationships between yardage and duration, models timeout and onside-kick decisions, and uses specialized parametric kicking estimators. The author reports over 600,000 plays/sec on a laptop; this is unreplicated, not an LP benchmark.

Application: if V2 ablations support joint sampling, test a learned empirical partition/distributional tree with supported leaves, legal-state masks and fallback. Bounded challenger only.

## 4. Mathematical architecture

CEG is a factored probabilistic generator with autoregressive game progression and deterministic rules transitions. It does not require an LLM.

    A_t ~ P_theta(A | S_t)
    Y_t ~ P_phi(Y | A_t, S_t)
    S_(t+1) = reducer(S_t, A_t, Y_t)

Illustrative passing factorization, with intent I, dropback event E, depth D, completion outcome C, YAC Y, fumble F:

    P(I,E,D,C,Y,F | S)
      = P(I | S) * P(E | I,S) * P(D | E,I,S)
        * P(C | D,E,I,S) * P(Y | C,D,E,I,S)
        * P(F | Y,C,D,E,I,S)

Evaluate only applicable branches: sacks do not generate targets or YAC. This schematic is not an assertion that every parent variable is used by current CEG.

Multiplying sequential conditional probabilities follows the chain rule. Multiplying independently estimated adjustments to the same outcome weight is different and requires justification under a joint estimator. Neither multiplication nor empirical sampling is intrinsically wrong. CEG's factorization and independence assumptions require validation too.

Monte Carlo is a sampling mechanism, not an estimator; empirical distributions, regression, Bayesian and neural models can all supply probabilities.

## 5. Offensive and defensive strength

Previous V2 transition-strength candidates worsened log loss. CEG Phase 8 found that per-play tuning over-shrank useful team differences at drive level. These are failures of particular estimators, not evidence that team effects are intrinsically useless.

### 5.1 Biro and Walker: Parametric Modeling and Analysis of NFL Run Plays (2023)

Journal of Sports Analytics. [Paper](https://journals.sagepub.com/doi/10.3233/JSA-220657).

Models rushing yards using a skew-t distribution, context and team-specific adjustments, with 2017–18 PBP. Distribution parameters describe location, scale, skewness and tail weight. Identical mean yards per carry can mask different third-down conversion and explosive-play chances.

Application: compare discrete hazards against team-specific distributional regression/skew-t; assess losses, short gains, long gains, tails and goal-line boundaries. The published work primarily studies rushing offense; joint opponent defense and full-game forecasting require new evidence.

### 5.2 Baio and Blangiardo: Bayesian Hierarchical Model for Football Results (2010)

Journal of Applied Statistics. [Paper](https://discovery.ucl.ac.uk/id/eprint/16040/).

Association-football scoring with separate attacking and defending abilities; explicitly addresses overshrinkage of extreme teams and explores mixture priors. Relevant analogy to favorite compression, not proof of an NFL fix.

CEG Phase 8:

| Quantity | Between-offense PPD SD | Correlation with actual PPD |
|---|---:|---:|
| Actual | 0.458 | — |
| Simple shrunk past-PPD R | 0.263 | 0.669 |
| League C | 0.175 | -0.097 |
| E6 | 0.161 | 0.040 |
| E8 | 0.166 | 0.189 |

These SDs contain sampling noise; simulated variation was close to its Monte Carlo floor. E8 vs C drive-points squared-error improvement did not meet preregistered significance. See Phase 8; not a fresh prospective holdout.

Application: estimate hierarchical variance and compare ordinary Gaussian priors with heavier-tailed or mixture alternatives where justified, rather than manually scaling team effects.

### 5.3 Glickman and Stern: A State-Space Model for National Football League Scores (1998)

Journal of the American Statistical Association. [Paper](https://doi.org/10.1080/01621459.1998.10474084).

Dynamic NFL team strength models week-to-week and season-to-season changes with Bayesian predictive inference for scores.

Proposed event-level adaptation (not the original paper's full model):

    O[i,w] = rho_O * O[i,w-1] + epsilon[i,w]
    D[i,w] = rho_D * D[i,w-1] + eta[i,w]

Application: evaluate dynamic strength against existing walk-forward previous/current-season estimates before introducing it into CEG.

### 5.4 Joint offense/defense estimation

Fit effects simultaneously under one likelihood, with identifiability constraints and regularization:

    logit(P(sack)) = intercept + f(context)
                    + offense_effect + defense_effect + QB_effect
    P(Y=k | X) = exp(eta_k) / sum_j exp(eta_j)

Compare league-only, offense-only, defense-only, joint and player terms. Use chronological data and opponent controls. Add interactions only with evidence.

| Event | Offense | Defense |
|---|---|---|
| Sack | Protection/QB | Pass rush |
| Completion | QB/receiver | Coverage |
| INT | QB accuracy/decision | Interception tendency |
| Run yards | Rushing | Run defense |
| YAC | Receiver | Pursuit/tackling |
| Fumble | Ball security | Forced fumbles |

These are conditional statistical contributions, not identified causal player abilities. Public data may confound QB, OL, receiver and team effects. Additive log-odds also multiply odds ratios; the goal is coherent joint estimation, not eliminating multiplication.

## 6. Player modeling

### 6.1 Yurko, Ventura and Horowitz: nflWAR (2019)

Journal of Quantitative Analysis in Sports. [Preprint](https://arxiv.org/abs/1802.00998), [published version](https://doi.org/10.1515/jqas-2018-0010).

Multilevel models estimate offensive skill-player contributions and distinguish context from observed performance; drive-level resampling preserves some dependence.

Application: separate opportunity from execution. Receiving chain: team pass opportunities -> eligible participation/substitution -> target allocation -> target outcome and depth -> YAC -> aggregate receiving yards. Preserve team/player statistical identities. Reuse existing opportunity models where supported. nflWAR is not a ready-made prop simulator.

### 6.2 Hierarchical Bayesian log5 (2018)

PLOS ONE. [Modeling the probability of a batter/pitcher matchup event: A Bayesian approach](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0204874).

Extends log5 using hierarchical Bayes for sparse batter/pitcher matchups; the reported example improves on conventional alternatives.

Application: compare opponent-adjusted QB/defense, receiver/coverage and rush offense/run defense estimates. Baseball's two-participant structure cannot simply be copied into multi-player NFL interactions.

## 7. Sequential dependencies and latent states

### 7.1 Predicting Play Calls in the NFL Using Hidden Markov Models (2021)

IMA Journal of Management Mathematics. [Paper](https://academic.oup.com/imaman/article/32/4/535/6211379).

289,191 NFL observations, hidden states for changing run/pass propensity. Reports 71.6% out-of-sample classification accuracy on 2018, comparable to established approaches.

### 7.2 Markov-Switching Decision Trees (2024)

AStA Advances in Statistical Analysis. [Paper](https://link.springer.com/article/10.1007/s10182-024-00501-6).

319,369 NFL plays, team-specific models. Standard decision tree classification error 28.8%, switching tree 28.6%; switching trees were shallower. Incremental predictive improvement modest.

Application: later compare a persistent run/pass game-plan state against state-only conditioning. Hidden states are estimates, not proof of coach intent. Generated context must not use future observed labels.

### 7.3 Marked spatio-temporal point processes (2023)

Narayanan, Kosmidis and Dellaportas, JRSS Series C. [Paper](https://academic.oup.com/jrsssc/article/72/5/1095/7253039).

Bayesian soccer event-sequence model separates timing and event marks with history and context. NFL discrete snaps may favor simpler duration models; continuous-flow hockey and soccer are natural applications.

### 7.4 Large Events Model for Soccer (2024)

Machine Learning. [Paper](https://link.springer.com/article/10.1007/s10994-024-06606-y).

Language-model-inspired sports-event generation learns next-event attributes and recursively generates trajectories. NFL analogy: first-and-ten/run +4; second-and-six/pass +8; first-and-ten/sack -6; next pass incomplete. Evaluate CPU-friendly sequence models before a neural autoregressive challenger. No evidence yet that a large event model beats simpler NFL alternatives.

## 8. V1 Complete references

Separate autonomous track; do not reopen broad movement fitting before complete game execution.

| Publication | Relevance |
|---|---|
| [A Simulation Model for American Football Plays (1981)](https://www.sciencedirect.com/science/article/pii/0307904X81900536) | Monte Carlo player positions, velocities, periodically selected strategies; passing excluded |
| [Cervone et al., A Multiresolution Stochastic Process Model for Predicting Basketball Possession Outcomes (2016)](https://doi.org/10.1080/01621459.2016.1141685) | Combine continuous movement with discrete possession events; [preprint](https://arxiv.org/abs/1408.0777) |
| [Simulating Defensive Trajectories in American Football (2021)](https://pmc.ncbi.nlm.nih.gov/articles/PMC8353517/) | Multi-agent imitation learning for defensive positioning |
| [NFL Step-and-Turn: A Generative Framework (2026)](https://arxiv.org/abs/2603.17866) | Bayesian multilevel ball-carrier movement and posterior predictive generation; preprint |

## 9. Architecture comparison

| Method | Benefit | Limitation | CPU suitability (not benchmarked) |
|---|---|---|---|
| Historical rows | Observed joint outcomes | Sparse support | Excellent |
| Learned empirical trees | Data-driven partitions | Leaf sparsity/extrapolation | Excellent |
| Conditional empirical generator | Interpretable | Coarse buckets | Excellent |
| Regularized regression | Generalizes | Functional form | Excellent |
| GAM | Nonlinear effects | Fit complexity | Good |
| Hierarchical Bayesian | Pooling/uncertainty | Inference/specification | Good with compiled parameters |
| Distributional regression | Mean, variance, tails | Distribution assumptions | Good |
| HMM | Persistent strategy | Identifiability | Good |
| Neural autoregressive | Flexible dependence | Data and compute | Variable |
| Autonomous multi-agent | Explicit interaction | Physical/behavioral complexity | Engine-dependent |

Preferred statistical research direction: cutoff-safe pregame strengths/eligibility -> game state -> decision estimators (regression/GAM) and execution distributions (joint hierarchical estimation) -> conditional events -> shared rules/accounting -> joint game/player distributions -> next state. Reuse CEG's architecture; no new engine is needed to test an estimator.

## 10. Local versus global calibration

[Gneiting and Raftery (2007), Strictly Proper Scoring Rules, Prediction, and Estimation](https://doi.org/10.1198/016214506000001437): log score, Brier, CRPS, energy score.

[Scheuerer and Hamill (2015), Variogram-Based Proper Scoring Rules](https://doi.org/10.1175/MWR-D-14-00269.1): additional evaluation of dependence in multivariate predictions.

| Level | Target | Metrics |
|---|---|---|
| Play | Decision or categorical outcome | Brier/log loss |
| Play | Yardage | CRPS, quantile calibration |
| Drive | Terminal outcome | Multiclass Brier |
| Drive | Points | Distribution score, expected-points error |
| Team | Offense and defense efficiency | Error, ranking, variance, calibration |
| Game | Winner | Brier/log loss |
| Game | Scores/margin/total | CRPS, MAE |
| Player | Opportunities, yards, receptions | CRPS, prop Brier |
| Joint | Correlated team/player outputs | Energy/variogram scores |

Also compare rare-event rates, scoring, drive length, play count and league/team distributions. Local conditional likelihood is coherent for a correctly specified joint model, but local gains under misspecification, limited data or generated context need not improve long-horizon predictions. Phase 9 drive-level calibration is reasonable but must not buy points by distorting component behavior.

CEG Phase 7 context: 300/300 realism and 1,160/1,160 forecast games completed in the tested runtime; winner Brier for 13 examined Week 11 games (40 CEG seeds/game): market .183, V2 .205, V1.6 .230, CEG .245, coin .250. League-average CEG points 20.11 vs actual 23.01, yards 303.1 vs 321.0, enforced fouls 4.93 vs 6.36. Runtime success is not predictive success. Player-specific generation and rare-event/rules coverage remain incomplete.

## 11. Bounded research program

1. **V2 subtractive ablation (already authorized).** Freeze the exact configuration. Remove active modifiers, optional filters, decision models and allocation layers separately and in groups; preserve legality and event coverage. Compare with a minimal situational sampler and team-specific playcalling/allocation without outcome modifiers. No refits.
2. **Finish CEG Phase 9 (existing bounded experiment).** Compare against simple past PPD; no indefinite parameter search.
3. **Estimator comparison.** Empirical hierarchy versus regularized logistic/multinomial regression and GAM. Same information, conditioning target, chronological splits and event contract.
4. **Joint offense/defense.** Compare pooled and partially pooled effects; assess shrinkage, opponent adjustment and drive/team differentiation.
5. **Distributional yardage.** Compare hazards with distributional regression/skew-t, including tails and field boundaries.
6. **Multiresolution validation.** Play, drive, game and player distributions; compare against strong direct statistical baselines and frozen SLC models.

Sequence models, latent game plans, neural generators and dynamic player strengths are subsequent candidates, not immediate implementation assignments.

Pre-register hypothesis, baseline, training cutoff, compute budget, primary metrics and stopping rule. Preserve failures; inconclusive is not evidence of improvement. Local improvement is insufficient for deployment; require global contribution and legality. Previously examined years are not fresh holdouts. Test with matched snapshots, seed IDs, and explicit invalid-run reporting. Require independent prospective confirmation. If generative candidates cannot beat simple opponent-adjusted drive baselines, reassess whether play-level decomposition contributes forecasting value.

## 12. Priority reading order

1. DraftKings football generation (section 3.1)
2. Biro and Walker NFL rushing (5.1)
3. Baio and Blangiardo overshrinkage (5.2)
4. Goldner NFL drive Markov model (3.2)
5. Glickman and Stern dynamic NFL strength (5.3)
6. NFLSimulatoR (3.3)
7. Minimally Sufficient simulation (3.4)
8. nflWAR (6.1)
9. Hierarchical log5 (6.2)
10. Proper scoring rules (10)
11. NFL HMM playcalling (7.1)
12. Large Events Model (7.4)

## 13. Final assessment and limitations

V2: legitimate empirical baseline; justify the surviving filters and modifiers through ablation.
CEG: working experimental conditional architecture; unvalidated forecasting, insufficient team differentiation, incomplete player and rare-event coverage.
V1 Complete: autonomous simulation with historical and academic precedents, separate evaluation.

The most actionable combination is DraftKings' conditional architecture, Biro and Walker's team-specific distributional modeling, Baio and Blangiardo's overshrinkage research and Goldner's drive-level diagnostics. These should guide research rather than become automatically adopted features.

This is a targeted review, not an exhaustive systematic literature search. Accessible papers, abstracts and technical descriptions informed the synthesis. Published results and throughput have not been independently reproduced, every associated codebase has not been audited, and CPU suitability is qualitative. Proposed LP adaptations, equations and experimental priorities are recommendations, not measured LP results. No claim is made that any cited approach is universally superior.
