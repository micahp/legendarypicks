# Guide: Sports modeling and simulation architecture

**Reference:** DraftKings Engineering's public Sports Intelligence articles  
**Reviewed:** October 14, 2026  
**Purpose:** A practical reference for designing, validating, and extending Legendary Picks' match, game, and player-projection models across sports.

This is a modeling guide, not an implementation task or a specification of DraftKings' undisclosed production systems. It distinguishes **published DraftKings methods** from **proposed Legendary Picks applications**. Read the [general architecture article](https://medium.com/draftkings-engineering/intro-sports-intelligence-draftkings-51c285bb3737) first; the sport-specific articles illustrate parts of that architecture.

Related internal documents: [modeling platform](SPEC-modeling-platform-2026-07-16.md), [NFL research handoff](HANDOFF-nfl-model-2026-10-11.md), [tennis prediction brief](BRIEF-tennis-prediction-model.md), [tennis player-projection plan](RESEARCH-tennis-player-projections-2026-10-14.md).

## 1. General model architecture

### The cross-sport method

**Primary source:** Robin Mohseni, Ian Dorward and Prashant Singh, [*Intro — Sports Intelligence @ DraftKings*](https://medium.com/draftkings-engineering/intro-sports-intelligence-draftkings-51c285bb3737) (July 14, 2023).

DraftKings describes **the majority** of its core sports engines as Monte Carlo simulators. They represent games as stochastic processes; machine-learning models estimate the transitions between states. The unit of simulation varies with the sport. The engineering architecture also supports historical event replay, live data, model deployment, distribution generation and sportsbook pricing.

The general design pattern:

```text
Historical events and outcomes
           |
           v
Data cleaning, identities and timestamped features
           |
           v
Player/team strength and opportunity estimates
           |
           v
Conditional models for the next event
           |
           v
Rules-aware simulation of one complete game
           |
           v
Game state + shared player/team event records
           |
           v
Repeat many complete simulations
           |
           v
Distributions of game results and player statistics
           |
           v
Backtest, calibrate, and serve probability projections
```

For every sport, define these five components separately:

| Component | Contents | Key design question |
|---|---|---|
| **Inputs / priors** | Player and team strength, surface/venue, roster, workload, environment, format; all known as of the forecast timestamp | What information is actually available before this event? |
| **Simulated state** | Score, period, ball/serve/possession, clock, players active, fatigue or accumulated counts if modeled | What facts determine the next legal event? |
| **Transition models** | Probabilities of action selection and conditional outcomes, estimated from historical data | Which next event happens, and what is its conditional probability? |
| **Outcome records** | Shared player/team counts, score path, sequence of events, match totals | Which projections must reconcile on a single trajectory? |
| **Aggregation / evaluation** | Forecast distributions, quantiles, threshold probabilities, calibration, historical replay | Are the distributions accurate, not merely internally consistent? |

### Why simulate rather than directly regress every market?

A direct regression may forecast each player's stat independently. A full-event simulator can make those forecasts **coherent**:

- A tennis player's aces depend partly on how many service points they are expected to play.
- A receiver's yards depend on passing volume, target allocation, receptions, and yards per reception.
- A goalie makes saves only on opponents' shots on goal that are not goals.
- A game cannot award more receptions to receivers than completed passes attributed to a quarterback, under the corresponding counting rules.

Coherence is an architectural benefit, **not proof that the resulting probabilities are well calibrated**. A simpler direct count model should be the comparison point for every prop distribution.

### DraftKings' model engineering workflow

The [cross-sport article](https://medium.com/draftkings-engineering/intro-sports-intelligence-draftkings-51c285bb3737) describes: defining a pricing question; examining curated data; fitting and validating ML components; encoding sport rules; integrating live data; producing market probabilities from simulation records; and handing probabilities to trading/pricing systems. It mentions Python model services on Kubernetes, APIs, Kafka, SQL, Snowflake and AWS. These are deployment choices, **not requirements** for Legendary Picks.

For LP, retain a clean contract:

```text
make_priors(as_of, participants, event_context)
  -> simulate(priors, scoring_rules, random_seed)
  -> {event_trajectory, team_records, player_records}
  -> aggregate(simulations)
  -> {probabilities, count_distributions, confidence, provenance}
```

Version each prior, transition model, rule set, input snapshot, and simulation run. Historical replay must reconstruct what could have been known **at that earlier timestamp**.

## 2. Sport-by-sport modeling guide

The table below is a **design guide for Legendary Picks**, not a list of which sports DraftKings supports. Its simulation units, baseline choices and feature suggestions for sports without published breakdowns are **LP research proposals**. The last column points to the most useful DraftKings article where one exists.

| Sport | Simulation unit / state | First probabilities and inputs to model | Target projections | Baseline and first validation | Reading |
|---|---|---|---|---|---|
| **ATP / WTA tennis** | Service point; server, game/set score, tiebreak | Serve-point win vs returner, surface, match format; service-point exposure and ace/DF rates | Match and set scores, total games, tiebreaks, aces, double faults, breaks | Elo for match winners; direct service-point and ace/DF count distributions for props | [Tennis](#3-tennis-point-level-simulation) |
| **NFL** | Snap; down, distance, field, score, clock, personnel | Run/pass choice, completion/INT/sack, target/carry allocation, YAC, penalties, runoff | Scores, passing/rushing/receiving yards, attempts, receptions, TDs | Direct player volume and yards models; drive/score and prop distribution accuracy | [Football](#4-nfl-play-by-play-simulation) |
| **College football** | Snap/drive with college scoring and clock rules | Team tendencies, talent difference, pace, down-distance, roster, conference context | Points, spread, totals and player production | College-only chronological direct baselines vs candidate simulator | [Football adaptation](#4-nfl-play-by-play-simulation) |
| **NBA / WNBA** | Possession or stint; active lineup, score, clock | Minutes, lineup/rotation, pace, on-court usage, shooting/assists/rebounds, player impact | Team points; player points, rebounds, assists, threes | Direct minutes × usage/rate; count distributions conditioned on rotations | [Player ratings](#5-nba-player-ratings-as-simulation-inputs) |
| **NHL** | Shot/shift/penalty event; score, clock, manpower, goalie | Shot volume/quality, on-ice exposure, shot on goal, save/goal, penalty and line effects | Team goals, shots on goal, goalie saves, player goals/points | Direct shot and save count models; clock/manpower and count reconciliation | [Hockey blueprint](#6-nhl-proposed-modeling-blueprint) |
| **MLB** | Pitch or plate appearance; outs, runners, inning, pitcher/batter | Strike/ball/ball-in-play, hit/out/BB/K, baserunning, pitcher workload, bullpen | Runs, strikeouts, hits, total bases, RBIs | Direct pitcher K/hitter event and plate-appearance exposure baselines | [Other sports](#7-other-sports-adaptations) |
| **MLS / Liga MX / soccer** | Possession/shot or time interval; score, clock, manpower | Team possession, chances, shot/SoT, conversion, on-field minutes, substitutions | Goals, scoreline, shots, SOG, assists, cards, saves | Direct Poisson/Dixon-Coles-type goal and player shot models | [Other sports](#7-other-sports-adaptations) |
| **UFC** | Fight action/time interval; round, clock, position, damage if observed | Strikes/takedown attempts, accuracy, control, transitions, finish hazard | Winner/method, rounds, strikes, takedowns, finish time | Direct win and count/survival models with censoring | [Other sports](#7-other-sports-adaptations) |
| **Esports** | Game/map/round, depending on title; series state | Team/player map strength, veto/map pool, side/map effects, format | Map winner, series winner, total maps, title-specific player props | Elo/Glicko or map-specific strength and series-length baselines | [Other sports](#7-other-sports-adaptations) |

**Use the smallest simulation unit that is (a) observable historically, (b) necessary for the desired outputs and (c) feasible to validate.** Do not start with a full tracking-level physics simulator just because one could be imagined.

### Data inputs shared across sports

1. **Ability:** historic performance, opponent-adjusted strength, ratings, uncertainty.
2. **Opportunity:** plays, possessions, minutes, service points, plate appearances or shifts.
3. **Environment:** surface, altitude, weather, venue, rest and travel when available.
4. **Personnel:** confirmed starters, absences, roles, substitutions and expected replacements.
5. **Rules:** actual scoring and timing rules for the competition and season.
6. **Live evidence:** event feed with observation time and feed availability time, plus market snapshots when licensed.
7. **Research-only signals:** timestamped commentary and tactical observations, evaluated separately for incremental value.

Not every input belongs in the initial model. Require enough history and measurable validation gains before adding complexity.

## 3. Tennis: point-level simulation

**DraftKings source:** Ian Dorward, [*Building a Tennis Simulation*](https://medium.com/draftkings-engineering/building-a-tennis-simulation-d6afdaa97d19) (August 17, 2023).

### Algorithm in the article

1. Start with two estimates of the probability that each player wins a point while serving.
2. Track score, who serves next, tiebreak state and set/match state.
3. Sample the outcome of each service point; update the score and appropriate outcome record.
4. Stop on a legal match conclusion. Repeat to obtain match-winner, correct-set-score, total-games and related probability distributions.
5. Configure the format (best-of-3/5 and relevant tiebreak rules) instead of hardcoding one tournament.
6. Optionally update beliefs about a player's **match-day serve probability** as service points are observed, using Beta prior/pseudo-count logic. The term “momentum” in the article should not be interpreted as demonstrated psychological causation.

The article's sample is an **educational simplification**, not the complete production tennis engine. Its demonstration uses 100,000 simulations.

### Extension to tennis player props (LP proposal)

To produce **aces** and **double faults** rather than only point winners, estimate mutually consistent point outcomes:

```text
Ace                   -> server wins point; server ace +1
Double fault          -> server loses point; server DF +1
Other point won       -> server wins point
Other point lost      -> server loses point
Each case             -> server service_points +1, update match state
```

Aces and double faults **must not** be independent extra draws layered on top of a separately determined winner. Counts derive from the same point event. Start with service-point exposure, then conditional ace and DF rates; compare simulated **count distributions** against direct Poisson, negative-binomial or beta-binomial alternatives when their assumptions fit.

**Validation sequence:** (a) service-point and match-length distribution, (b) ace and DF rates/count distribution, (c) player over/under threshold calibration, (d) joint dependence with sets/games.

LP's existing **standalone point-model match-winner forecast has not earned a GO**. In the inspected 2023–2026 development sample, Elo beat it on ATP (Brier 0.2280 vs 0.2353) and WTA (0.2160 vs 0.2288). That result does **not** evaluate ace/DF count distributions; those need their own experiments. See [tennis brief](BRIEF-tennis-prediction-model.md) and [player-projection plan](RESEARCH-tennis-player-projections-2026-10-14.md).

## 4. NFL: play-by-play simulation

**DraftKings source:** Ian Dorward, [*Modeling Football: Combining ML models and Monte Carlo simulations*](https://medium.com/draftkings-engineering/modeling-football-combining-ml-models-and-monte-carlo-simulations-170fd58cbe11) (February 7, 2024).

### Algorithm in the article

For each simulated state, the article describes:

1. A **team-specific action classifier** for pass vs rush, conditioned on game context.
2. On passes, an intended depth class and pass outcome (e.g. completion, incompletion, interception or sack), then conditional yards after catch.
3. Relevant fumbles and **pre-snap/post-snap penalties**, with appropriate state updates.
4. Separate **fourth-down decision** models for whether teams *will* go for it versus punt or try a field goal. That behavioral prediction is not a prescriptive “should they go for it?” analysis.
5. A **clock runoff model**; advance time until the game can legally end.
6. Player/team simulation records updated after each play, yielding distributions across complete games.

The article discusses logistic and multinomial models and why logit-space adjustments keep probabilities within their valid range. The full trained production model, coefficients and prop backtest are **not** published.

### What LP should model explicitly

The game trajectory should allocate **opportunities** before their outcomes: team plays → pass attempts/carries → intended targets → completions/yards. Personnel availability and role redistribution can change target/carry probabilities. Use the same player and team record to reconcile completed passes, receptions and receiving yards.

Compare the result with an independent player-volume model on identical games. Start with the [NFL handoff](HANDOFF-nfl-model-2026-10-11.md) to avoid rebuilding or overwriting existing LP work.

## 5. NBA: player ratings as simulation inputs

**DraftKings source:** Robert Barnes, [*Kalman Filters For NBA Player Ratings*](https://medium.com/draftkings-engineering/kalman-filters-for-nba-player-ratings-d3bb9365221b) (September 19, 2023).

This article is **not** a published NBA possession simulator. It focuses on an important upstream problem: player value changes over time, and changing a lineup changes the expected team outcome.

### Method and usage

- Estimate offensive and defensive player impact from historical possessions involving the players on court.
- Carry both **ability estimates and uncertainty**, updating them after new observations with Kalman-filter logic.
- Track covariance across player ratings where modeled.
- Incorporate **usage** so replacing a player affects how involved the remaining players become.
- The tutorial's equal **10% usage** example is pedagogical, not a disclosed production share for every player.

For LP, a practical adaptation is: **lineup and expected minutes → possessions → usage/opportunities → player outcomes**. Validate usage and minutes predictions independently, particularly around injury, foul trouble, starters and substitutions, before adding simulation complexity.

DraftKings' later [basketball engineering careers article](https://careers.draftkings.com/life-at-draftkings/engineering/building-game-ready-models-in-london/) discusses pregame/live player props, including women's basketball, but does not provide a technical NBA/WNBA simulation specification.

## 6. NHL: proposed modeling blueprint

**No dedicated DraftKings Engineering NHL simulation methodology was located in the public source review.** The design below is **Legendary Picks' proposal**, not an attribution to DraftKings.

### Recommended state and transitions

- **State:** score, period/time, regulation or overtime/shootout, manpower, current penalty clocks, goalie/pulled-goalie state; lineups and zone state if data supports them.
- **Exposure:** team and player ice time, shifts, shot attempts, goalie shots faced.
- **Events:** shot attempts → blocked/missed/on goal → save or goal; penalties; faceoffs; transitions and stoppages when reliably captured.
- **Records:** team goals and shot totals; player shots on goal, goals/assists/points; goalie saves; penalty/power-play totals.
- **Constraints:** on-goal shot is saved or scored, while missed/blocked attempts are not goalie saves. Handle scoring and market settlement definitions separately.

**Start with direct models** of player shots on goal and goalie saves, conditioned on ice time, opponent and manpower. Then test whether event simulation improves the count tails, interval coverage and correlations with goals/scoreline. Audit play-by-play and on-ice data coverage before defining the transition granularity.

## 7. Other sports: adaptations to investigate

These are research blueprints for LP, **not methods publicly disclosed by DraftKings** in the cited articles.

| Sport | Start simple | Add event-level simulation if… | Important complication |
|---|---|---|---|
| **MLB** | Plate appearances, pitcher K and hitter outcome counts | Pitch/PA transitions improve correlated runs and player counts | Pitcher changes, batting order, handedness, outs/runners |
| **Soccer** | Team goal intensity and player shots/SoT rates | Possession/shot progression improves timing or correlated player/team props | Lineup, substitutions, cards, game-state effects, stoppage time |
| **UFC** | Bout winner and round/finish hazard; strike/takedown rates | Action/time transitions improve finish time and prop tails | Censoring on finish, sparse opponent pairings, striking vs grappling |
| **Esports** | Map/team rating and match format | Round/map mechanics materially improve series-length or player props | Rules and patch/version effects differ by title |
| **College football** | Team strength, pace, snap volume and basic player usage | A play simulator adds value over a college-specific direct baseline | Historical rule variations, roster turnover and conference differences |

Do not force all sports into one shared event taxonomy. Share **interfaces and validation**, not the event physics.

## 8. Model evaluation and acceptance guide

**Evaluate the distribution for the actual target being shipped.** A model that is good at predicting winners can still be poor at prop counts, and the reverse is possible.

| Forecast type | Strong first baseline | Proper primary evaluation | Required diagnostics |
|---|---|---|---|
| Game / match winner | Global or blended Elo, rating-based/logistic baseline | Brier or log loss | Reliability, season/surface/roster splits, paired differences |
| Score and total points/goals/games | Direct count/score distribution | Discrete log score or CRPS, as appropriate | Tails, interval coverage, mean bias, joint consistency |
| Player count props | Rolling shrunk rate × expected opportunity; Poisson/NB alternatives | Count log score / CRPS | Count tails, volume calibration, history-depth splits |
| Line-threshold probability | Probability mass above/below a specified line | Brier or log loss on matched posted lines | Calibration by line/market, settlement/void handling |
| Live forecasts | Same model with earlier state only | Chronological as-of log score or Brier | Feed latency, timestamp leakage, price snapshot availability |

### Minimum research protocol

1. Fix eligible matches, target labels, historical as-of cutoff, and scoring rules.
2. Separate opportunity, conditional outcome and game-state uncertainty.
3. Establish strong direct baselines **before** measuring simulator incremental value.
4. Use chronological replay with reproducible input snapshots; report sample count and coverage by league/era.
5. Verify mechanical invariants independently (legal scores, time/clock, player/team count reconciliation).
6. Assess probability calibration and a paired uncertainty interval against the strongest baseline on the **same events**.
7. Freeze the chosen approach and score truly new events without retuning to the inspected period.
8. Keep research-only and commercial data licenses separate; the Sackmann tennis data currently used by LP is **non-commercial** pending licensing decision.

A healthy outcome of testing may be **NO-GO on simulation for a particular prop**, with a direct count model retained for production. The point of this architecture is measured forecasts, not maximizing simulation complexity.

## 9. Sources and reading path

### Primary DraftKings Engineering articles (read in this order)

1. **Cross-sport framework:** Robin Mohseni, Ian Dorward, Prashant Singh. [*Intro — Sports Intelligence @ DraftKings*](https://medium.com/draftkings-engineering/intro-sports-intelligence-draftkings-51c285bb3737). **July 14, 2023.** Read for data assets, Monte Carlo architecture, model replay, real-time service and pricing boundaries.
2. **Tennis:** Ian Dorward. [*Building a Tennis Simulation*](https://medium.com/draftkings-engineering/building-a-tennis-simulation-d6afdaa97d19). **August 17, 2023.** Read for input/simulated/record objects, point scoring, configurable match formats and in-match Beta updating.
3. **NFL:** Ian Dorward. [*Modeling Football: Combining ML models and Monte Carlo simulations*](https://medium.com/draftkings-engineering/modeling-football-combining-ml-models-and-monte-carlo-simulations-170fd58cbe11). **February 7, 2024.** Read for conditional decision chains, penalties, fourth downs, time runoff and shared state.
4. **NBA player ratings:** Robert Barnes. [*Kalman Filters For NBA Player Ratings*](https://medium.com/draftkings-engineering/kalman-filters-for-nba-player-ratings-d3bb9365221b). **September 19, 2023.** Read for time-varying player impact, covariance/uncertainty, and lineup usage effects.

The order is pedagogical (framework → simulators → player-rating inputs), **not chronological**.

### Official companion explanations

- DraftKings Careers: [*What Is Sports Intelligence At DraftKings?*](https://careers.draftkings.com/life-at-draftkings/engineering/what-is-sports-intelligence-at-draftkings/) (September 7, 2023).
- DraftKings Careers: [*How To Build A Tennis Simulation*](https://careers.draftkings.com/life-at-draftkings/engineering/how-to-build-a-tennis-simulation/) (October 4, 2023).
- DraftKings Careers: [*Mastering the Art of Football Simulation*](https://careers.draftkings.com/life-at-draftkings/engineering/mastering-the-art-of-football-simulation/) (August 7, 2024).
- DraftKings Careers: [*Building Game-Ready Models in London*](https://careers.draftkings.com/life-at-draftkings/engineering/building-game-ready-models-in-london/) (May 20, 2026).

### Source boundaries

- **Direct published examples:** general Monte Carlo architecture, tennis scoring simulator, NFL conditional event simulator, NBA player-impact Kalman method.
- **Reasonable LP extensions, not DraftKings disclosures:** ace/DF event categorization, MLB/NHL/soccer/UFC/esports event-chain suggestions, college-football adaptation and test protocols.
- **Unverified:** precise internal DraftKings transition model parameters, full league-specific engine implementations, production prop tail calibration and profitability.
- **No dedicated NHL modeling article located** in this public review. Lack of a located article is not evidence that DraftKings does not model hockey.

This guide covers the method and identifies what to read. Any implementation plan must start with an LP data/identity/coverage audit and an explicit historical baseline for its target market.
