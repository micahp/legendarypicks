# BRIEF — NHL team scoring prediction model

## Question

Given a matchup, its expected lineups, and the starting goalies, how many goals should each team score against this specific opponent? From both scoring distributions, derive win probability, regulation win, puck line, game totals, and later player props.

The model should explain why it expects a game in the shape of 4–2 rather than 2–1. Hockey goals are rare, and strong possession or chance quality can still be overcome by goaltending or finishing variance. Model the opportunities and their quality, not only the final score or shot total.

## Build order

1. **Team chance creation and prevention.** Estimate opponent-adjusted, score- and venue-adjusted 5-on-5 xGF/60 and xGA/60, with shot volume and pace. Keep offense and defense separate. Use xG differential as an even-strength strength measure.
2. **Goalie adjustment.** Estimate the expected starter and adjust goals against using regressed GSAx and shot difficulty. Shrink small samples toward longer-term estimates. Update the forecast when the starter is confirmed; record both the earlier and updated forecast with their as-of times.
3. **Special teams and matchup context.** Project 5-on-5, power-play, penalty-kill, and other-strength scoring separately. Estimate penalty opportunities from penalties drawn and taken. Add lineup availability and projected ice time, rest, back-to-backs, travel, home ice, and recent underlying trends as evidence supports them.
4. **Scoring distributions and markets.** Start with team goal distributions using a Poisson-based model. Test more flexible distributions and hockey-specific adjustments against it. Simulate games to price moneyline, regulation, puck line, and totals. Handle empty-net goals, overtime, and shootouts according to each market’s settlement rules.
5. **Validation.** Backtest chronologically. Every feature must have been available before puck drop. Compare with league-average and market-implied baselines on the same games; report goal error, probability calibration, log loss, and market results. Promote features only when out-of-sample results support them.
6. **Player props later.** Once team scoring and opportunity forecasts are reliable, add player projections for shots, goals, assists, points, goalie saves, and blocked shots, tied to projected ice time, line and power-play role, and the same game simulation.

### Interpreting winner Brier scores

For a binary outcome such as home-team win, the Brier score is the mean squared error of the predicted probability:

\[
\text{Brier} = \frac{1}{N}\sum_{i=1}^{N}(p_i-y_i)^2,
\]

where `p` is the predicted win probability and `y` is 1 for a win and 0 for a loss. Scores range from 0 to 1; lower is better.

| Score or reference | Interpretation |
| --- | --- |
| 0.000 | Perfect probabilities and outcomes |
| Below the matched baseline | Better average probability accuracy than that baseline on the same games |
| 0.250 | Expected score of a constant 50% prediction; a useful no-information reference, not a universal cutoff |
| 1.000 | Worst case: confident predictions that are always wrong |

Also compare against a constant home-win probability estimated only from the training data. If that training win rate is `q`, its expected Brier score on a sample with the same prevalence is `q(1-q)`. Report the model's Brier skill relative to that baseline as `1 - model Brier / baseline Brier`; positive values indicate improvement over the baseline.

Published NHL figures are context, not a leaderboard: reported examples range from about 0.220 for the NHLPredictor ensemble to about 0.243 for a PodiumOracle Elo model, with other published estimates around 0.234–0.240. They use different seasons, samples, and validation methods, so compare them cautiously. A defensible benchmark requires scoring every model on the exact same games and outcomes. With only 82 playoff games, report uncertainty alongside Brier score and avoid treating small differences as decisive. Include log loss and calibration as complementary measures.

## Highest-priority inputs

Importance is a hypothesis for the first experiments; backtesting determines what earns a place in the model.

| Priority | Input | Use |
| --- | --- | --- |
| Critical | 5-on-5 xGF/60 and xGA/60 | Chance creation and prevention per 60 minutes |
| Critical | 5-on-5 xG differential | Underlying even-strength team strength |
| Critical | Confirmed starting goalie | Matchup-specific adjustment to expected goals against |
| Critical | Goalie GSAx | Performance relative to shot quality, regressed toward a stable estimate |
| High | High-danger chances for and against | Dangerous opportunities, especially near the net |
| High | Shot attempts for and against per 60 | Volume, possession tendencies, and pace |
| High | Power-play and penalty-kill xG/60 | Scoring outside 5-on-5, modeled separately |
| High | Penalties drawn and taken per 60 | Expected power-play opportunities |
| High | Player availability and projected ice time | Lineup changes, scratches, injuries, and role changes |
| Medium | Rest, back-to-backs, travel, home and away | Fatigue, schedule, home advantage, and matchup deployment |
| Medium | Recent xG trends | Potential changes in team performance, with shrinkage |
| Medium | Shooting percentage versus expected finishing | Repeatable finishing skill versus short-run variance |

Use score- and venue-adjusted 5-on-5 statistics wherever available. A team protecting a lead changes how it plays compared with a team chasing the score; raw full-game rates can confuse those game states with team quality.

## Why expected goals matter

Two teams can each record 30 shots on goal while creating very different scoring chances. If Team A generates 3.8 expected goals and Team B 1.9, their shot counts match but Team A generated roughly twice the expected scoring from those attempts. Rebounds and close-range attempts generally carry higher scoring probabilities than long-distance attempts.

The shot-level model should account for shot distance, angle and type; rebounds, deflections and rushes; events immediately preceding a shot; players on the ice and manpower; and empty-net situations. Keep shot volume and shot quality as distinct signals rather than treating total shots as a complete measure of offense.

MoneyPuck is a candidate source for shot-level xG and game-level skater and goalie data. Its current xG model is described as rebuilt for 2026–27; verify the feature definition and release before relying on that version. The model's xG definition is a source input, not ground truth.

## Goaltending and special teams

Track GSAx/60, save percentage adjusted for shot difficulty, high-danger save percentage, rebound control, recent workload, rest since last start, and longer-term performance. Regress goalie estimates so a few games at an unusually high save rate do not create an implausibly large projection. Treat the starter as uncertain until confirmed, then re-run and timestamp the forecast.

Project expected power-play goals separately:

\[
E[\text{PP goals}] = E[\text{PP minutes}] \times \frac{\text{adjusted PP xG/60}}{60}
\]

Adjust power-play strength for the opponent's penalty kill and estimate expected opportunities from both teams' penalty rates. Combine the resulting scoring components only after each strength situation has its own estimate.

## Outputs

For every forecast, store the model version, input availability, and as-of time. Show projected home and away goals, total, goal differential, and the distributions and probabilities for supported markets. A projected differential alone is not a win probability: probabilities come from the scoring distributions and explicit overtime and settlement handling.

Illustrative only — hypothetical matchup, not a real game prediction:

| Pregame projection | Value |
| --- | ---: |
| Home expected goals | 3.4 |
| Away expected goals | 2.8 |
| Projected total | 6.2 |
| Projected goal differential | Home +0.6 |

The simulated scoring distribution should produce probabilities for home win, regulation win, home −1.5 puck line, and totals such as over/under 5.5 or 6.5. Each market needs its own settlement logic; empty-net, overtime, and shootout outcomes can affect markets differently.

For player props, prioritize opportunity and role alongside conversion:

| Prop | Main inputs |
| --- | --- |
| Shots on goal | Individual attempts/60, expected ice time, power-play role, opponent shots allowed |
| Goals | Individual xG/60, shot volume, finishing estimate, opposing goalie |
| Assists and points | Expected assists, line combinations, linemate scoring, ice time, power-play involvement |
| Goalie saves | Opponent shot-on-goal projection and expected goalie workload |
| Blocked shots | Defensive ice time, opponent attempts, player blocking rate |

A sustained shot-volume increase after a player moves to the first line is a stronger opportunity signal than a short burst of goals on very few shots.

## Data and constraints

| Source | Candidate use |
| --- | --- |
| MoneyPuck | Shot-level xG, goalies, skaters, and team game-level data |
| Natural Stat Trick | 5-on-5 analytics, shot attempts, danger chances, and situational splits |
| NHL API | Schedules, play-by-play, box scores, rosters, and player game logs |
| Daily Faceoff | Starting-goalie information and lineup context |

MoneyPuck is reported to provide historical shot data from 2007–08 through 2025–26, along with game-level player and goalie datasets. Confirm current coverage and definitions before ingest. The NHL API is a candidate source for game-level ingestion. Because MoneyPuck's downloadable data is described as non-commercial absent separate permission, resolve commercial licensing before using it in a Legendary Picks production service. Record source, coverage, field definitions, and license for every dataset.

## Version one

Train on roughly the last five completed seasons, weighting recent games more heavily while using older history to stabilize estimates. At the start of a season, combine previous-season team ratings with roster-adjusted priors; do not overreact to the first few games. Measure the useful history window and recency weights through chronological validation.

Start with these five feature groups:

1. Adjusted 5-on-5 xGF/60 and xGA/60.
2. Opponent-adjusted shot volume and shot quality.
3. Starting goalie and regressed GSAx.
4. Power-play and penalty-kill strength with expected opportunities.
5. Rest, home ice, and lineup availability.

The first model should estimate each team's scoring distribution, then derive multiple market probabilities from the simulated outcomes. Keep a league-average baseline and market-implied baseline in every comparison. Lock each game's forecasts in the one-minute window from 90 to 89 minutes before puck drop, with a separate immutable row for every model version. A missed lock window is recorded as missed; the pipeline never backfills it with a late forecast. Grade locked forecasts daily from completed official NHL results after a four-hour finality grace period. Preserve the official winner and official score separately from the goal target that excludes the shootout-deciding goal. Lineup or goalie updates create a new timestamped forecast version rather than rewriting an earlier lock.

The standalone lock database is `backend/data/nhl-model.dev.sqlite3`; it is separate from both Legendary Picks SQLite databases. The frozen research runner writes per-model forecasts to `research/nhl/prospective-2026-27/forecasts.jsonl`; the forecast timer refreshes that ledger near each game's T−90 window. `backend/lock_nhl_models.py` stores one immutable row per game, model, and model version. `backend/grade_nhl_models.py` grades those rows against NHL gamecenter landing results. The read-only page API is `/api/nhl/model/locks?season=2026`. Timer definitions live in `ops/systemd/legendarypicks-nhl-forecast.{service,timer}`, `legendarypicks-nhl-lock.{service,timer}`, and `legendarypicks-nhl-grade.{service,timer}`. These are research/dev jobs; they do not write to either Legendary Picks picks database. MoneyPuck commercial data rights remain unresolved, so this pipeline is not authorized for commercial production use.

## Constraints

- Predict each team's goals first; a winner-only rating cannot explain the expected scoring shape or price totals and team totals.
- Treat expected goals as a modeled estimate of chance quality, not an observed outcome or a guarantee of future scoring.
- Shrink small samples, especially goalie and finishing rates, toward longer-term or league-level estimates.
- Separate 5-on-5, power-play, penalty-kill, and other-strength scoring before combining them.
- Use only information available at the forecast's recorded as-of time. Preserve pre-confirmation and confirmed-starter forecasts separately.
- Report sample size, calibration, and uncertainty. Do not claim a betting edge from projected score differences alone.
- Resolve source definitions, historical coverage, and commercial data rights before production use.

## Deliverable

A short research report documenting source coverage and licensing, feature definitions, a chronological baseline comparison, goal and probability calibration, and a go/no-go for the team scoring simulator. Player props follow only after the team model demonstrates reliable out-of-sample scoring distributions.
