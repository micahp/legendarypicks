# Research: DraftKings Engineering sports models and simulators

**Reviewed:** October 14, 2026  
**Scope:** Public DraftKings Engineering / DraftKings Careers materials relevant to Legendary Picks (LP).  
**Status:** Source review and candidate experiments, **not** a reproduction of DraftKings' production models.  
**Related:** [Tennis prediction brief](BRIEF-tennis-prediction-model.md), [Tennis player projections](RESEARCH-tennis-player-projections-2026-10-14.md), [Simulating plays from player movement](VALUE-PROP-simulating-plays-2026-10-04.md), [NFL model handoff](HANDOFF-nfl-model-2026-10-11.md), [Modeling platform](SPEC-modeling-platform-2026-07-16.md).

## Executive finding

The public technical series contains **three sport-specific deep dives** relevant to LP:

1. **Tennis:** point-by-point Monte Carlo simulation with configurable rules, tracked match state and outcome records.
2. **NFL:** linked machine-learning models that sample a sequence of football plays, outcomes, penalties, and clock runoff.
3. **NBA:** Kalman-filter offensive/defensive player-impact and usage ratings, which can supply inputs to a simulation; **not a published full NBA possession simulator**.

A fourth engineering piece explains the **cross-sport** architecture: data preparation, component ML models, sporting rules/state transitions, historical replay, deployment and market generation.

**NHL answer: no dedicated DraftKings technical article describing an NHL or ice-hockey simulator was found in the reviewed public DraftKings Engineering archive and official careers materials.** DraftKings offers hockey markets, and its general overview states its modeling organization covers major sports, but **neither proves the specific architecture or accuracy of its NHL model**. Do not describe a proposed LP hockey model as DraftKings' design.

Likewise, the review did not locate equivalent public methodology deep dives dedicated to MLB, soccer/MLS/Liga MX, UFC, college football, or esports. “Not located” is a scoped research finding, **not proof none exists**.

## 1. Original technical articles

| Published | Article and author | What was disclosed | Why LP should read it |
|---|---|---|---|
| **2023-07-14** | [Intro — Sports Intelligence @ DraftKings](https://medium.com/draftkings-engineering/intro-sports-intelligence-draftkings-51c285bb3737), Robin Mohseni (co-written with Ian Dorward and Prashant Singh) | Mostly Monte Carlo core models; sport-specific state transitions; model replay, features, registry, Kafka, Python/Kubernetes, pricing workflow | Shared research, simulation, validation and production interfaces |
| **2023-08-17** | [Building a Tennis Simulation](https://medium.com/draftkings-engineering/building-a-tennis-simulation-d6afdaa97d19), Ian Dorward | Toy point simulator with serve-point probabilities, game/set/match rules, format variation and outcome records; in-match updating of win-probability estimates | ATP/WTA match-state and service-point exposure |
| **2023-09-19** | [Kalman Filters For NBA Player Ratings](https://medium.com/draftkings-engineering/kalman-filters-for-nba-player-ratings-d3bb9365221b), Robert Barnes | Possession-derived offensive/defensive player impact, uncertainty/covariance, time-varying ratings and usage | NBA player value and minutes/role substitution |
| **2024-02-07** | [Modeling Football: Combining ML models and Monte Carlo simulations](https://medium.com/draftkings-engineering/modeling-football-combining-ml-models-and-monte-carlo-simulations-170fd58cbe11), Ian Dorward | Context-conditioned play selection and outcomes, penalties, fourth-down choices, clock model | NFL coherent team and player count distributions |

**Companion official summaries, not additional detailed engines:**

- [How To Build A Tennis Simulation](https://careers.draftkings.com/life-at-draftkings/engineering/how-to-build-a-tennis-simulation/), DraftKings Careers, 2023-10-04.
- [What Is Sports Intelligence At DraftKings?](https://careers.draftkings.com/life-at-draftkings/engineering/what-is-sports-intelligence-at-draftkings/), DraftKings Careers, 2023-09-07.
- [Mastering the Art of Football Simulation](https://careers.draftkings.com/life-at-draftkings/engineering/mastering-the-art-of-football-simulation/), DraftKings Careers, 2024-08-07.
- [Sports Data Science At DraftKings](https://careers.draftkings.com/life-at-draftkings/engineering/sports-data-science-at-draftkings/), DraftKings Careers, 2024-02-22, team discussion.
- [Building Game-Ready Models in London](https://careers.draftkings.com/life-at-draftkings/engineering/building-game-ready-models-in-london/), DraftKings Careers, 2026-05-20: basketball pre-live/live player props and women's basketball; **no end-to-end possession model published**.

## 2. Tennis deep dive

**Source:** Dorward 2023, *Building a Tennis Simulation*. **Caveat:** DraftKings explicitly says the article's worked model is simpler than the production system.

### Disclosed design

- **Input features** include estimates of each player's probability of winning a service point.
- **Simulated features** represent the changing game state: server, point score, games, sets, tiebreak and match state.
- **Simulation records** capture outcomes needed to price different markets.
- Sample service-point winners, apply legal scoring rules, update state and records, finish the match and repeat many times. The article illustrates **100,000** simulated matches.
- Parameterize scoring formats, such as best-of-three, best-of-five and tiebreak variations.
- Its later “momentum” section describes **Beta-distribution updates** of beliefs about match-day serve ability from in-match service points; these are uncertainty updates, **not demonstrated proof of psychological momentum**.

### What is *not* provided

- Full production features and model weights; independently reproducible market probabilities; standardized historical Brier/log loss; per-player ace/DF prop results.
- Evidence that a fixed per-point simulator must beat Elo on match winners.
- Historical evaluation of the article's demonstrated momentum technique against stronger pre-match baselines.

### Direct LP application

LP's current point-model plus simulator **lost to global Elo on match-winner probability**:

| Tour | Matches in development backtest | Global Elo Brier | Standalone point simulator Brier |
|---|---:|---:|---:|
| ATP | 11,777 | **0.2280** | 0.2353 |
| WTA | 13,066 | **0.2160** | 0.2288 |

Those are LP's results, **not DraftKings' results**. The reported simulator arithmetic checks do not constitute validation of match-length or ace distributions.

**Next tennis question:** does full-match simulation predict **service-point opportunity counts** and **aces/DF prop distributions** better than well-calibrated direct count models? Follow the [player-projections plan](RESEARCH-tennis-player-projections-2026-10-14.md). Test point-by-point Bayes updating, score effects, and shared serve-day variation only as chronological ablations.

## 3. NFL deep dive

**Source:** Dorward 2024, *Modeling Football: Combining ML models and Monte Carlo simulations*.

### Disclosed design

- At each snap, predict **pass versus rush** from situation (down, distance, field position, time, score).
- For pass plays, sample attempted pass depth, then pass outcomes such as completion, incompletion, interception or sack.
- When completed, model additional yards after catch; represent turnover/fumble possibilities.
- Include pre-snap and post-snap **penalties** and corresponding changes to game state.
- Model **fourth-down choices** to go for it, punt or attempt a field goal, describing expected *coach behavior* rather than an optimal action.
- Model **clock runoff** so the simulator advances to a realistic final whistle.
- Persist the same evolving game state and per-player/team records across each simulated trajectory; repeat to derive coherent distributions.

The article discusses logistic and multinomial models, transformations on a log-odds scale, and dependence between markets.

### What is *not* disclosed

- Production source code, trained weights, entire feature inventory or data licensing.
- A complete auditable injury-to-target-share and player-personnel allocation system.
- Distributional player-prop backtest tables showing calibration or superiority over direct count models.

### LP application

**Volume first, outcome second:** possessions → plays → player opportunities (targets, attempts, carries) → player production. Player totals and team totals reconcile within each simulation. Fit each transition to historical context, with personnel/usage as explicit priors, and **compare against direct player-prop models on matched test games**. Do not rebuild LP's existing NFL model without first reviewing its [handoff](HANDOFF-nfl-model-2026-10-11.md).

## 4. NBA ratings article (distinct from a simulator)

**Source:** Barnes 2023, *Kalman Filters For NBA Player Ratings*.

### Disclosed design

- Each possession provides an observation involving its offensive and defensive players and points scored.
- Maintain time-varying estimates of player offensive and defensive impact and uncertainty; covariance allows related ratings to update together.
- The tutorial assumes equal **10% usage** for illustration only.
- Replacements matter: removing a player does not simply subtract his rating; the incoming player's impact and teammates' changing usage alter the result.
- Suggests usage-specific estimates from possession actions, with logit-space modeling necessary when usage is probabilistic.

**Do not claim:** this is DraftKings disclosing its full NBA possession simulator or a validated player-prop algorithm. A May 2026 official careers article says basketball teams build pre-live/live player props and work on women's basketball, but does not supply the missing algorithm.

### LP application

Start with player opportunities (minutes, on-court possessions, usage) conditional on rotations and absences. Then generate points, assists, rebounds or relevant events. Test time-varying Kalman-style ratings against simpler shrunk rolling performance and regularized regression baselines before deployment.

## 5. Cross-sport process and production architecture

**Source:** Mohseni / Dorward / Singh 2023, *Intro — Sports Intelligence @ DraftKings*.

DraftKings describes the following pipeline:

1. Data engineering curates historical assets and makes events replayable.
2. Train and validate contextual component models.
3. Encode sport rules into stochastic **play-by-play or time-based state transitions**.
4. Replay past games for model evaluation.
5. Run prediction services in production using real-time feeds, model registries and trader inputs.
6. Aggregate simulation results to probability distributions used for markets and correlated same-game parlays.
7. Apply market-specific margin, trader adjustments and risk controls downstream.

The public stack includes Python/Kubernetes model services and data infrastructure such as Kafka, C#, SQL, Snowflake and AWS. DraftKings says **the majority** of its core sports models use Monte Carlo, **not all markets in all sports**. This is a description of their disclosed architecture, not proof that each sub-model is calibrated.

### Recommended common LP contract

`historical evidence → pregame player/team priors → context-conditioned event models → rules-aware event simulation → consistent game/player records → calibrated distributions → product projections`

Keep sport-specific components independent. Ensure predictions expose vintage/as-of timestamps, sample sizes, data provenance, model version, confidence/calibration status, and known gaps.

## 6. League coverage inventory

| Sport LP covers | Detailed DraftKings public methodology found? | Evidence / boundary | Candidate LP modeling unit (proposal, **not** a DK attribution) |
|---|---|---|---|
| **ATP / WTA** | **Yes, tennis simulation** | Educational point model, formats and records | Service point → game/set/match → service-point and ace/DF counts |
| **NFL** | **Yes, NFL play simulator** | Conditional branches and clock, but no full production code | Snap → opportunity → outcome → player box score |
| **College football** | **No distinct write-up located** | NFL approach may transfer; rules, talent and data differ | Drive/snap with college-specific rules |
| **NBA** | **Yes, player-rating article only** | Does not document a full NBA simulator | Rotation/possession → usage → player events |
| **WNBA** | **Official team/profile reference** | 2026 careers article says development work; method undisclosed | League-specific rotation and possession model |
| **NHL** | **No NHL technical deep dive located** | Hockey markets exist, engine structure not disclosed | Shift/shot/penalty/goal event chain |
| **MLB** | **No MLB technical deep dive located** | General cross-sport claims only | Pitch/plate appearance → outs/runs/player stats |
| **MLS / Liga MX / soccer** | **No soccer technical deep dive located** | No verified event-transition specification | Possession → shot → goal and player shots |
| **UFC** | **No UFC technical deep dive located** | No verified fight-simulation specification | Time/round → action → finish/decision |
| **Esports** | **No esports technical deep dive located** | No verified game/map simulator specification | Map → series → tournament outcomes |

**No public NHL implementation was verified.** A DraftKings hockey sportsbook page is evidence of **market coverage**, not how those markets are calculated. Do not cite it as an engineering specification.

## 7. NHL-specific research opportunity

A useful NHL architecture should be independently designed from verified hockey data, league rules and the target props. A **candidate** event state:

- Score, game clock/period, home/away, manpower, penalties, goalie/pulled goalie, and where possible which skaters are on ice.
- Events: shot attempt → blocked/missed/on goal → save or goal; turnovers; penalties; faceoffs and stoppages.
- Outputs: team goals, player shots on goal/points, goalie saves, power-play exposure and correlated markets.
- Special handling: regulation/overtime/shootout and historical rule changes; separate market settlement/void semantics.
- Validation: compare direct Poisson/negative-binomial shot and save baselines against a staged opportunity model **before** building a complex full-game engine.

These are **LP proposals**, not known DraftKings internals. Check completeness and historical coverage of shot-by-shot data, skater minutes, line combinations, goaltending and player IDs. Use LP's existing NHL canonicalization/audit results as the first constraint.

## 8. Commentary vs statistics: separate research hypothesis

The simulation articles mostly explain how to make related outputs **coherent** using existing inputs. They do **not** establish that a cleverer simulator obtains *new* information.

LP's differentiated hypothesis is that **timestamped commentator observations of mechanics, strategy, fatigue or injury supply predictive signal beyond structured box-score statistics and the market**. Distinguish:

1. Recitation of a statistic already present in the feed.
2. Interpretation/selection: which stat is highlighted, and when.
3. Direct physical/tactical observation (e.g., degrading serve toss, bad footwork, coverage failures).
4. Unsupported storytelling/speculation.

Test an identical stats-only vs stats-plus-commentary system on exactly matched forecast timestamps with strict latency/leakage checks; also compare both after including contemporaneously available market probabilities. Predeclare proper-score/calibration targets and sample sizes. A research improvement does **not** imply a real pricing edge. Investigate audio/transcript rights and commercial training permissions separately.

## 9. Proposed read/build order

1. **Read the cross-sport intro** for the shared architecture and model-replay principle.
2. **Read tennis**, then test the modest first-step question: service-point exposure accuracy and ace/DF distributions versus direct count forecasts. Do **not** overturn the match-winner no-go without new evidence.
3. **Read football** and compare its event/state choices to LP's current NFL implementation; list missing transitions and validate opportunity distributions incrementally.
4. **Read NBA player ratings** as a player-role estimation approach, not proof of an NBA simulation scheme.
5. **For NHL**, begin from LP's NHL data audit and public league event definitions; avoid attributing any NHL-specific pipeline to DraftKings.
6. **Run a small historical commentary ablation** on already timestamped feeds before attempting a full multimodal model.

## Source index

**Primary DraftKings Engineering (verified article text)**

- Mohseni, R., Dorward, I., Singh, P. (2023-07-14). [Intro — Sports Intelligence @ DraftKings](https://medium.com/draftkings-engineering/intro-sports-intelligence-draftkings-51c285bb3737).
- Dorward, I. (2023-08-17). [Building a Tennis Simulation](https://medium.com/draftkings-engineering/building-a-tennis-simulation-d6afdaa97d19).
- Barnes, R. (2023-09-19). [Kalman Filters For NBA Player Ratings](https://medium.com/draftkings-engineering/kalman-filters-for-nba-player-ratings-d3bb9365221b).
- Dorward, I. (2024-02-07). [Modeling Football: Combining ML models and Monte Carlo simulations](https://medium.com/draftkings-engineering/modeling-football-combining-ml-models-and-monte-carlo-simulations-170fd58cbe11).

**Official companion material (verified)**

- DraftKings Careers (2023-09-07). [What Is Sports Intelligence At DraftKings?](https://careers.draftkings.com/life-at-draftkings/engineering/what-is-sports-intelligence-at-draftkings/).
- DraftKings Careers (2023-10-04). [How To Build A Tennis Simulation](https://careers.draftkings.com/life-at-draftkings/engineering/how-to-build-a-tennis-simulation/).
- DraftKings Careers (2024-02-22). [Sports Data Science At DraftKings](https://careers.draftkings.com/life-at-draftkings/engineering/sports-data-science-at-draftkings/).
- DraftKings Careers (2024-08-07). [Mastering the Art of Football Simulation](https://careers.draftkings.com/life-at-draftkings/engineering/mastering-the-art-of-football-simulation/).
- DraftKings Careers (2026-05-20). [Building Game-Ready Models in London](https://careers.draftkings.com/life-at-draftkings/engineering/building-game-ready-models-in-london/).

**Research limitations:** search of DraftKings Engineering and official careers materials as of October 14, 2026; no internal access, no claimed reproduction of pricing engines, and no independent verification of the model accuracy. When adding new articles, record exact title, author, date, source URL, and whether it is a modeling disclosure or a marketing/organizational summary.
