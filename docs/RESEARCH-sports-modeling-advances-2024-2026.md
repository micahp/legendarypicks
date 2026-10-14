# Sports Modeling Advances, 2024–2026

**Research reference | October 14, 2026**  
**Scope:** Public research, league data releases and inspectable independent projects published or materially updated from 2024 to October 2026.  
**Purpose:** Identify methods and information sources that might improve Legendary Picks forecasts beyond conventional box scores, ratings and Monte Carlo simulations.  
**Status:** Literature review and proposed experiments. Nothing here is a validated Legendary Picks model or a commercial-data clearance.

This document stands alone. For a separate treatment of DraftKings' 2023–2024 methods, see [DraftKings sports modeling guide](RESEARCH-draftkings-sports-simulation-2026-10-14.md). For LP's current research and limitations, see [tennis match model](BRIEF-tennis-prediction-model.md), [tennis player-projection plan](RESEARCH-tennis-player-projections-2026-10-14.md), [sports simulation and movement vision](VALUE-PROP-simulating-plays-2026-10-04.md), and [NFL research handoff](HANDOFF-nfl-model-2026-10-11.md).

## 1. Research map

A simulator transforms estimated event probabilities into coherent distributions. A more detailed simulator does not automatically supply more predictive information. Recent research offers additional ways to estimate **player ability, opponent interactions, action selection, physical condition and temporal state** before the next event takes place.

| Direction | Representative public work (year) | What it actually contributes | First relevant LP experiment | Key limit |
|---|---|---|---|---|
| **Dynamic player abilities** | [Wimbledon Bayesian skill/momentum study](https://github.com/AndyYinGL/wimbledon-2026-forecast) (2026); [Funaki demo](https://github.com/tjermann/funaki_demo) (active 2026) | Uncertainty-aware serve/return or basketball player-impact estimates, often with time updates | Test shrunk surface/overall priors and opportunity forecasts | Self-reported results, incomplete public production pipeline |
| **Autoregressive tracking simulation** | [SportsNGEN](https://arxiv.org/abs/2403.12977) (2024) | Generates linked player-and-ball trajectories; tennis rally/match simulations | Compare richer tactical outputs with a point-event baseline | Relies on high-resolution licensed tracking |
| **Interactions and tactics** | [TacticAI](https://doi.org/10.1038/s41467-024-45965-x) (2024) | Graph model of soccer corner-kick setups and likely events | Predict event likelihood from relative player positioning | Restricted tracking, specific set-piece task |
| **Movement → events** | [CourtMotion](https://arxiv.org/abs/2512.01478) (2025 preprint) | Predicts basketball trajectories/events using skeletons and team context | Test pose versus position-only next-event predictors | Not a validated NBA prop-pricing engine |
| **Public movement benchmark** | [NFL Big Data Bowl 2026](https://www.kaggle.com/competitions/nfl-big-data-bowl-2026-prediction) | Forecast player movement after release from pre-throw tracking | Predict movement, then see if it helps completion/YAC | Competition's target is position, not betting |
| **Rich physical statistics** | [MLB Statcast bat path](https://www.mlb.com/news/new-statcast-swing-metrics-2025) (2025); [NHL EDGE](https://www.nhl.com/news/nhl-edge-stats-trends-and-storylines-for-2025) (2025 review published 2026) | Measured mechanics, speed, shots and spatial summaries | Lagged mechanical-feature ablations against player stat counts | Public visualized metrics ≠ bulk licensed tracking |
| **Synthetic tracking** | [Radke & Tilbury](https://arxiv.org/abs/2503.19809) (2025) | Soccer simulations and tracking/event extraction tooling | Prototype spatial pipeline and feature extraction | Synthetic sports behavior ≠ professional match distribution |
| **Commentary timing/semantics** | [Afzal et al.](https://aclanthology.org/2026.lrec-1.722/) (2026) | Benchmark and methods for timing multimodal commentary generation | Borrow timing evaluation ideas for transcript alignment | Does **not** show commentary improves predictions |
| **Evaluation quality** | [Gregori et al.](https://doi.org/10.3389/fcomp.2026.1883327) (2026); [Chang & Chuang](https://doi.org/10.1177/22150218261493344) (2026) | Validation-method survey and direct warning against in-game/pre-game leakage | Freeze as-of feature sets and compare with strong baselines | Papers' benchmark results do not transfer between sports |

**Evidence labels used below:** peer-reviewed research; preprint; public league feature or competition; independent repository with author-reported results. Publication/availability is distinct from an improvement that Legendary Picks has reproduced.

## 2. SportsNGEN: simulate the athletes, not just the scoreboard

**Lachlan Thorpe et al., [*SportsNGEN: Sustained Generation of Realistic Multi-player Sports Gameplay*](https://arxiv.org/abs/2403.12977), icSPORTS 2024.** [Conference entry](https://www.scitepress.org/PublishedPapers/2024/128920/).

- **Method:** an autoregressive transformer trained on professional tracking sequences represents player and ball movement, together with shot events and stopping logic. Its tennis experiments generate sustained rallies and, with supporting logic, simulated entire matches.
- **Outputs evaluated by authors:** rally outcomes, shot choices, counterfactual situations and aggregate simulated-versus-real match statistics. The paper argues that sampling settings matter to realistic dynamics; authors show qualitative extension to association football.
- **LP use:** a direct methodological bridge to the original idea of footwork, shot selection, forehand/backhand performance, and matchup style. Tracking-space simulation might explain *how* a point unfolds rather than only whether the server wins it.
- **Gate:** first show tracking or tactical event features improve next-point/rally forecasting on the **same held-out matches** against the existing statistical point model; only then consider training high-cost movement generators.
- **Constraint:** high-resolution professional player/ball tracking is not generally open for commercial training. A realistic-looking rally is not automatically a calibrated ace, winner or match forecast.

## 3. TacticAI: predicting events from player relationships

**Zhe Wang et al., [*TacticAI: an AI assistant for football tactics*](https://doi.org/10.1038/s41467-024-45965-x), Nature Communications, March 19, 2024. Peer-reviewed.**

TacticAI represents set-piece participants as a graph, then predicts first receivers and shot likelihood and generates altered corner-kick setups for tactical comparison. Liverpool FC experts also assessed generated tactical alternatives. The widely reported expert preference result concerns **assessment of tactics**, not prospective betting performance.

**LP experiment:** on licensed tracking or sufficiently detailed event-and-position data, compare a graph-based receiver/shot model to a simpler distance/angle/previous-event model. Measure out-of-sample log loss/Brier and calibration for the target event before adding a match simulator.

**Limit:** a corner-kick model is not a whole soccer possession model, and professional tracking inputs are not guaranteed commercially accessible.

## 4. CourtMotion and NBA player behavior

**Omer Sela, Michael Chertok and Lior Wolf, [*CourtMotion: Learning Event-Driven Motion Representations from Skeletal Data for Basketball*](https://arxiv.org/abs/2512.01478), December 2025 preprint.**

CourtMotion combines a skeletal graph representation, temporal/interaction modeling, and task-specific heads for basketball events including passes, shots and steals. The authors report a **35% reduction in trajectory-prediction error** versus position-based baselines in their experimental setting. This is **author-reported movement error**, not a 35% improvement in win or prop accuracy.

**LP experiment:** benchmark player/pose trajectories versus positions alone for predicting next-action classes where such tracking can be sourced legally. Only then ask whether predicted actions improve player points/assists/rebound distributions.

**Complementary repository:** [Funaki demo](https://github.com/tjermann/funaki_demo) publishes basketball play-by-play ingestion and Bayesian/Kalman player ratings for NBA, while reserving parts of the game/market prediction process privately. Its recorded performance is self-reported; use the accessible implementation as a **player-prior example**, not a certified prop model.

## 5. NFL: forecasting player movement before a throw

**[NFL Big Data Bowl 2026: Prediction](https://www.kaggle.com/competitions/nfl-big-data-bowl-2026-prediction), NFL / Next Gen Stats public competition.**

The task is to predict player coordinates **during the ball's flight** using movement and contextual data available **before the ball is thrown**. Historical training data include 2023–2024 plays with a distinct unseen-game evaluation phase. This is a particularly clean formulation of an action-conditioned movement forecast.

**[NFL Next Gen Stats' 2025 additions](https://www.nfl.com/news-migrated-v2/next-gen-stats-new-advanced-metrics-you-need-to-know-for-the-2025-nfl-season)** describe transformer-based coverage-responsibility estimation, a pre-/post-snap coverage-disguise comparison, and a revised Completion Probability model. These are league descriptions of deployed metric models, **not public trained weights or a full event simulator**.

**LP experiment:**
1. Reproduce the competition's movement metric from allowed data.
2. Translate *predicted* rather than realized positioning to features available before a target is decided.
3. Compare receiver catch, target and YAC estimates against the existing NFL statistical model on an identical chronological slice.
4. Estimate whether any gains remain in actual **player-prop count distributions** after conditioning on expected pass volume and personnel.

A model that predicts coordinates accurately may add no incremental value for receptions or yards. Check the competition's data license before product integration.

**Inspectability reference:** [tim-foldy-porto/nflsim](https://github.com/tim-foldy-porto/nflsim) provides a public event-based NFL simulator with team/player output and conditional play-calling derived from nflverse. Treat documented fidelity and any reported validation as unverified until rerun.

## 6. Additional physical/statistical inputs already becoming public

### MLB: Statcast bat mechanics (May 20, 2025)

**Source:** MLB, [*New Statcast metrics measure swing path, attack angle, attack direction*](https://www.mlb.com/news/new-statcast-swing-metrics-2025); [Baseball Savant leaderboard](https://baseballsavant.mlb.com/leaderboard/bat-tracking/swing-path-attack-angle).

Metrics include swing-path tilt, vertical attack angle, ideal attack-angle range and horizontal attack direction, extending earlier bat speed and swing length tracking. These describe **how** a swing happens, and some are sensitive to pitch location and timing.

**LP experiment:** add **lagged** rolling mechanical changes to a hitter hits/total-bases or contact-quality model, with opposing pitcher repertoire and pitch mix controlled. Compare with a same-sample rolling-stat baseline. Verify how much historical coverage and automated use the publisher permits.

### NHL: EDGE skater and puck features (2025 trends, reported January 1, 2026)

**Source:** NHL, [*NHL EDGE stats: Biggest storylines of 2025*](https://www.nhl.com/news/nhl-edge-stats-trends-and-storylines-for-2025); [NHL EDGE player dashboards](https://www.nhl.com/nhl-edge/skaters/20252026/2).

Published aggregate metrics include skating bursts/speed/distance, shooting velocity, shot locations and zone-related measurements. These can act as physical-context features when forecasting shots on goal, goalie saves, and player scoring opportunities.

**LP experiment:** direct count distribution with and without pregame EDGE metrics, stratified by ice-time projection and opponent. Validate the live availability and historical-vintage issue: a present-day seasonal summary is **not** necessarily the value known before an earlier match.

**Limits:** visible public dashboards do **not** establish permission to scrape or a license for raw high-frequency puck/skater tracking. No dedicated DraftKings NHL-methodology article was found in the separate DraftKings review; this NHL proposal is independently motivated.

## 7. Synthetic soccer tracking as a development substrate

**David Radke and Kyle Tilbury, [*Simulating Tracking Data to Advance Sports Analytics Research*](https://arxiv.org/abs/2503.19809), AAMAS 2025 demonstration.**

They provide a method and **3,000 simulated soccer games** from Google Research Football in a tracking-like schema, with extracted pass/shot events and examples for expected goals and pitch control. Useful for rehearsing spatial indexing, coordinate transformations, event extraction, pipeline tests and interpretable dashboards.

**LP experiment:** prototype soccer player-and-ball movement features on synthetic data, then test whether the same definitions generalize to permitted **real** soccer tracking. Never train a production MLS/Liga MX scoring model on synthetic outcomes alone without a real-world domain-shift audit.

**Limitation:** the authors note omitted possessions and extraction edge cases. Synthetic games are tool validation data, not unbiased professional match history.

## 8. Updating player ability over time: tennis momentum and shrinkage

**[AndyYinGL/wimbledon-2026-forecast](https://github.com/AndyYinGL/wimbledon-2026-forecast), independent project (2026).**

The public repository describes a dynamic Gaussian belief over serve and return strength updated from service-point binomial observations, approximate Kalman updating, surface-specific offsets shrunk toward overall skill, and a Markov game/set/match layer. It also investigates whether observed point streaks provide incremental prediction information.

**Self-reported (not independently reproduced):** raw matchup probabilities are overconfident; some calibration and surface shrinkage help; the author's momentum study finds limited useful hot-hand information. Its quoted Pinnacle comparison gives the bookmaker the advantage on its selected 2025 match subset. The project code license and the tennis-source/odds licenses are separate.

**LP experiment:** compare global-to-surface shrinkage against the existing surface-only serve/return model, especially for **thin histories**, on chronological development folds. Score point-level log loss, match-winner Brier, service-point exposure and prop distributions as **separate targets**.

The currently documented LP ATP/WTA match-winner backtests favor global Elo over the standalone point simulator. Improvements in a public repository don't reverse that result.

## 9. Commentary and multimodal observation: an unproved forecasting hypothesis

**Reference for timing methodology:** Anum Afzal et al., [*Real-Time Generation of Game Video Commentary with Multimodal LLMs: Pause-Aware Decoding Approaches*](https://aclanthology.org/2026.lrec-1.722/), LREC 2026.

This work predicts **what and when to say** while generating game commentary and compares timing strategies on racing and fighting game datasets. It is relevant to utterance timing/segmentation, **but does not test forecasting sports outcomes from commentary**.

For Legendary Picks, test a genuinely different hypothesis: **human commentary includes physical/tactical observations that have incremental predictive value after controlling for timestamped scores, player stats and market prices**.

Proposed four-way ablation on matched sports events:

| Arm | Observations at forecast cutoff | Question |
|---|---|---|
| A: stats | Game state, player history, event history; optionally pre-cutoff market | Reference forecast |
| B: all commentary | A plus every speech segment available before cutoff | Does commentary as a whole add signal? |
| C: filtered commentary | A plus commentary excluding mere recitations of known statistics | Is selection/interpretation important? |
| D: physical/tactical only | A plus extracted mechanical, fatigue, injury or strategy observations | Do human-described conditions predict future events? |

Requirements: preserve **event time, audio acquisition time, transcript availability time and forecast time**; use the latest rather than the earliest as the information cutoff when necessary. Do not leak "what happened next" from commentary recorded after a point/play. Code spoken evaluations separately from speculation or narrative framing; measure commentator disagreement, model extraction errors, and calibration. Run the same ablation with market probabilities in the common baseline to see if information is already priced.

**Potential targets:** tennis next service game/next 10 points/remaining aces; NFL next-play pressure or receiving opportunity; NHL next-shot volume. **A good classifier of commentary statements is not itself evidence of improved forecasts.** Broadcast access, storage, redistribution and commercial training rights need explicit checks.

## 10. Evaluation research: evidence quality over model complexity

**Andres Gregori et al., [*Forecasting sports outcomes through machine learning*](https://doi.org/10.3389/fcomp.2026.1883327), Frontiers in Computer Science, September 18, 2026.** Systematic review of **118** sports ML papers from 2020–2025. Notes incomparable metrics, different validation strategies, and limited work on in-game forecasts relative to outcome prediction. Useful as a checklist of benchmark/reporting pitfalls; it does **not** validate any particular LP feature.

**Hao Chang and Kuo-Liang Chuang, [*Simple versus complex metrics in single-game baseball prediction: A temporal validation study*](https://doi.org/10.1177/22150218261493344), Journal of Sports Analytics, September 30, 2026.** On the study's CPBL data, the headline **82.4%–89.4%** classification numbers come from **in-game outcome attribution**; the authors separately report **43.6%–52.0%** for stricter *pregame* cumulative-information prediction. The task and information cutoff completely change how a score should be interpreted. Do not quote the higher figures as reproducible pregame wagering accuracy or transfer the conclusions to MLB without replication.

### Minimum LP evaluation contract

- Define the exact target: win probability, next-event probability, exposure, count distribution, or a line-specific over/under. Do not use one target's success as evidence for another.
- Snapshot all features as of the **forecast timestamp**; reserve future truly unseen data for a confirmatory test.
- Use the same events for baseline and candidate, report missingness, sample sizes and effective history.
- Include strong simple baselines: Elo, direct opportunity × event rate, Poisson/negative-binomial or calibrated regression as appropriate.
- Use **proper probabilistic scores** (Brier/log loss for events, count log score/CRPS for counts), calibration, tail/interval coverage and paired uncertainty intervals.
- Check simulator invariants: legal scores and time, player/team totals, event accounting, identical scoring/void rules.
- Evaluate predictive information **incrementally**: stats; stats + new signal; stats + market; stats + market + signal.
- Audit every paper/dataset/repository license independently. Research code being public does not imply commercial rights to its training data or media.

## 11. Research order for Legendary Picks

| Research candidate | Data available now? | First experiment | Promotion criterion |
|---|---|---|---|
| **Tennis: dynamic ability/shrinkage** | Historical serve points; research-only source | Overall/surface serve priors + exposure, against Elo and direct stat models | Improve matched out-of-sample score, particularly thin history |
| **Tennis: ace/DF distribution** | Serve points, aces, double faults in existing research DB | Direct count baselines before joint simulator | Improves count log score/CRPS and line-tail calibration |
| **NFL: movement-informed actions** | Competition tracking under its rules | Predict routes/catch-related outcomes from pre-throw state | Adds to existing NFL player-volume and outcome model |
| **MLB: mechanical form** | Published Statcast summaries, accessibility to audit | Lagged mechanical-stat ablation | Improves next-game hitter stat probabilities beyond rolling form |
| **NHL: EDGE + exposure** | Public aggregate metrics; history/license TBD | Ice time × shots/saves rates with EDGE features | Improves player shot/save count distributions |
| **NBA: movement and rotation** | Public event/minutes histories; tracking license TBD | Rating and lineup usage shrinkage before pose model | Improves minutes/usage and player-count forecasts |
| **Commentary: human observation** | Some live captured audio; historic rights/coverage TBD | Time-aligned A/B/C/D ablation above | Replicated, nonmarginal predictive improvement beyond structured inputs |

**Bottom line:** the promising development is not simply that simulations are more elaborate. Public work increasingly models *how player state, physical mechanics and interaction context lead to the next event*. LP should use that research to test new information, and retain only signals that measurably improve forecasts on future data. A coherent or visually convincing simulation is not itself a predictive advantage.

## Source register and provenance

| Source | Kind | Date | Link |
|---|---|---|---|
| SportsNGEN, Thorpe et al. | Conference paper / preprint | 2024 | https://arxiv.org/abs/2403.12977 |
| TacticAI, Wang et al. | Peer-reviewed article | 2024-03-19 | https://doi.org/10.1038/s41467-024-45965-x |
| NFL Big Data Bowl Prediction | Public competition | 2026 | https://www.kaggle.com/competitions/nfl-big-data-bowl-2026-prediction |
| NFL Next Gen Stats new metrics | League engineering explanation | 2025-09-04 | https://www.nfl.com/news-migrated-v2/next-gen-stats-new-advanced-metrics-you-need-to-know-for-the-2025-nfl-season |
| CourtMotion, Sela et al. | Preprint | 2025-12 | https://arxiv.org/abs/2512.01478 |
| MLB new Statcast swing metrics | Official data release | 2025-05-20 | https://www.mlb.com/news/new-statcast-swing-metrics-2025 |
| NHL EDGE 2025 review | Official league data | 2026-01-01 | https://www.nhl.com/news/nhl-edge-stats-trends-and-storylines-for-2025 |
| Radke & Tilbury synthetic tracking | AAMAS demonstration | 2025 | https://arxiv.org/abs/2503.19809 |
| Wimbledon Bayesian serve and momentum | Independent code / author-reported results | 2026 | https://github.com/AndyYinGL/wimbledon-2026-forecast |
| Funaki NBA player ratings | Open-source sample / some private methods | Updated 2026 | https://github.com/tjermann/funaki_demo |
| NFL simulator | Independent reference implementation | Public repository | https://github.com/tim-foldy-porto/nflsim |
| Commentary timing, Afzal et al. | LREC research paper | 2026-05 | https://aclanthology.org/2026.lrec-1.722/ |
| Systematic review, Gregori et al. | Peer-reviewed literature review | 2026-09-18 | https://doi.org/10.3389/fcomp.2026.1883327 |
| Baseball validation, Chang & Chuang | Peer-reviewed study | 2026-09-30 | https://doi.org/10.1177/22150218261493344 |

**Research boundary:** all external outcomes, especially independent GitHub results, are attributed to their authors rather than reproduced by LP. Each source may impose separate commercial, scraping, redistribution, media, or training limits.
