# BRIEF: Tennis match prediction and player projections

Revised 2026-10-16. The 2026-10-14 revisions moved the starting point from the point model to Elo after the backtest
and added a player-projection track (service points, aces, double faults, breaks and games), read from the same
simulator and validated on its own counts. This revision adds a coverage audit for further inputs and outcomes.

## Question

Track A, match: for a given player pair on a given surface and format, how likely is each player to win, and what are
the set score, total games, tiebreak and three-set probabilities? The match model gives the winner. The simulator gives
the set, game and tiebreak outputs.

Track B, player projections: for a player in a given match, what is the distribution of service points, aces, double
faults, break points won and games won? Those are the stat lines behind player props.

## Two tracks, one simulator

- Track A is match outcomes: winners, set scores, total games and tiebreaks. Track B is player counts: service points,
  aces, double faults and break points.
- Each track has its own baseline and its own validation. Track A is judged by Brier against Elo. Track B is judged by
  log score, interval coverage and exceedance calibration against direct statistical baselines. Success on one track
  does not count toward the other.
- Track B does not start with the simulator. Its first steps are a data audit and direct count baselines, which need no
  simulation. The simulator enters at Gate C, if the gates before it pass.

## Architecture (target)

Player ratings and matchup conditions (Elo, serve and return, surface, form, rest)
-> point-level event model (first serve in; ace or rally; second serve: double fault, second-serve win or rally)
-> full match simulation (every point updates game, set and match state and each player's counts)
-> match markets (winner, totals, spread) and player projections (service points, aces, double faults, breaks)
-> joint outcomes (correlated props) and live projections (remaining-match distributions).

Every event probability is trained from historical counts. None is assigned by hand.

## Follow-up coverage audit (2026-10-16)

The architecture above names the main inputs and outputs, but the following details must also be represented in the
feature and outcome inventory. A statistic being present in a source or named in this brief does not mean it is already
modeled or validated.

| Area | Status in the current research | Requirement to track |
|---|---|---|
| Serve and return quality | Partial. The point model uses surface-level serve and return point rates. Match rows include first-serve and second-serve counts, but the current point model does not separately estimate all serve and return splits. | Preserve first-serve-in rate, first-serve points won, second-serve points won, first- and second-serve return points won, overall service/return points won, hold rate and return-game win rate. Test opponent-adjusted server-versus-returner estimates with shrinkage. |
| Surface and conditions | Surface and surface Elo are represented. | Track indoor/outdoor, court speed, altitude, temperature, wind and humidity when reliable pre-match history exists. Treat each as a candidate feature; require coverage, timestamp and out-of-sample evidence before adoption. |
| Form and physical workload | A two-year decay for serve/return counts was tested. Rest was measured but rejected: `tourney_date` is the event start, not the match date, so it cannot establish days since a player's previous match. | Compare recent point-performance windows (last 5/10/20 matches and 30/90/365 days) with opponent strength. Track actual match dates, minutes, sets played, consecutive playing days and tournament workload. Do not label event-start gaps as rest. Use injuries or retirement history only when reliably documented before the forecast cutoff. |
| Match and betting outcomes | Winner probability, set/game/tiebreak outputs, total games, and a spread are in the target architecture. Several simulator outputs still require their own historical validation. | Keep full distributions for set scores and total games; explicitly evaluate game-spread cover, over/under probabilities at stated lines, hold/break outcomes, tiebreak occurrence and deciding-set occurrence. Apply the correct best-of-three/five and market settlement rules. |
| Player-stat exposure | P0/P1 already compare per-match counts with service-point exposure for aces and double faults. | Retain service-point counts and full ace/DF count distributions. Track breaks of serve as a distinct outcome from break points won; derive prop probabilities from simulated opportunity and count distributions, not only expected averages. |
| Tactical and pressure features | Not in the current match-level inputs. | Park handedness matchups, rally length, return depth, serve direction, unreturned serves and tiebreak serve/return rates for a later research phase. Shrink break-point, tiebreak and head-to-head rates toward broader ability estimates; adopt only if they improve a held-out baseline. |

Every candidate feature must be available as of the forecast timestamp, with source, coverage and missingness recorded. Keep the current chronology and per-target scoring gates: a feature or simulator can be accepted for one output only if it improves that output's declared validation measure. Market-edge claims still require calibrated probabilities, timestamped historical prices and a cleared data licence.

### Data-source gates

- The available match rows contain useful first/second-serve and player-count fields, but do not by themselves establish historical coverage for court conditions, workload or injury status. Audit each field by tour, year, surface and format before modeling it.
- Official tour statistics are a candidate source for serve/return splits; confirm historical delivery, definitions and commercial-use rights before relying on them.
- Shot-charting fields such as serve direction, return depth and rally outcomes require a separate charted-data source. The cited Match Charting Project is CC BY-NC-SA; keep it in research unless commercial permission is obtained.
- Historical sportsbook odds and player-prop lines remain a separate licensed-data dependency. Prices may be evaluation benchmarks, not model inputs, unless the model design explicitly changes and is validated.

## Data available

Sackmann match rows already carry what Track B needs, for both winner (`w_`) and loser (`l_`): `svpt`, `1stIn`, `1stWon`,
`2ndWon`, `ace`, `df`, `SvGms`, `bpSaved` and `bpFaced`. Shot-level outcomes (winners, unforced errors, forehand and
backhand) are not in these data. They are not needed for aces, double faults or breaks.

Not in the repo: sportsbook prop lines. Historical lines are required before any over/under calibration claim, and the
licence for any line source must be cleared first.

## Status (2026-10-14)

Measured on the 2023-2026 test window. That window has now been inspected, so it is development, not confirmation.
Best-of-three matches with complete scores. Brier skill score (BSS) is against Elo: 1 - Brier(model) / Brier(Elo).

| Model | ATP Brier (n = 11,777) | ATP log loss | WTA Brier (n = 13,066) | WTA log loss |
|---|---|---|---|---|
| M1 Elo (global, K = 32) | 0.2280 | 0.6490 | 0.2160 | 0.6210 |
| Point model + simulator, standalone | 0.2353 (BSS -0.032) | 0.6628 | 0.2288 (BSS -0.060) | 0.6486 |

Verdict: the standalone point model and simulator do not beat Elo on match winners, on either tour. The simulator's
probability arithmetic is verified: it agrees with a point-by-point Monte Carlo at 200,000 matches per case, over 48
cases. Its game, set and tiebreak outputs are not yet validated against historical outcomes. Details:
`docs/TENNIS-MATCH-BACKTEST-2026-10-14.md` and `docs/TENNIS-MATCH-SIM-2026-10-14.md`, both on branch
`feat/tennis-point-model`.

## Brier score spectrum

Brier is the mean squared error of the predicted win probability. Lower is better. A constant 50/50 forecast scores
0.250. Across match-outcome forecasts the practical range is 0 to 1, and everything published sits near 0.19 to 0.23.

For each match, `p_i` must be the forecast probability for a consistently named player to win, and `y_i` must be 1 if
that same player wins and 0 otherwise:

`Brier = (1/N) * sum((p_i - y_i)^2)`

Calculate it from the paired per-match probabilities and outcomes on the same sample. Aggregate log loss or hit rate
cannot be converted into Brier; if the original probabilities were not retained, rerun the chronological forecasts.

Published numbers are project-reported, not reproduced here. Populations, date windows and rating histories differ,
so the absolute numbers are not a leaderboard. Differences of about 0.005 between sources are not evidence of anything.

**ATP, public projects (project-reported)**

| Source | Evaluation | Model | Brier |
|---|---|---|---|
| DEUCE (github.com/ARJUNVARMA2000/tennis-elo) | 2010-2026, 46,205 matches | Surface Elo with cross-surface transfer | 0.2009 |
| DEUCE | same | Serve/return point model | 0.2057 |
| DEUCE | same | XGBoost ensemble | 0.1963 |
| Tennis Prediction Engine (github.com/DhruvDhariwal/Tennis-Prediction-Engine) | 2024, 31,339 matches | Global Elo | 0.2067 |
| Tennis Prediction Engine | same | Blended surface Elo | 0.2083 |
| Tennis Prediction Engine | same | XGBoost | 0.1936 |
| ATP Tennis Predictor (github.com/ulpati/atp-tennis-predictor) | 2019-2026, 19,086 matches | Overall Elo | 0.223 |
| ATP Tennis Predictor | same | Surface Elo | 0.226 |
| ATP Tennis Predictor | same | XGBoost | 0.209 |
| **Ours** | 2023-2026, 11,777 matches | Global Elo (M1) | 0.2280 |
| **Ours** | same | Point model + simulator | 0.2353 |

**WTA, public projects**

DEUCE also publishes WTA results over 42,425 matches from 2010-2026, for surface Elo, a point model and XGBoost. The
values were only seen as a chart (roughly 0.19 to 0.22); take the exact figures from the repository before quoting them.
Ours: 2023-2026, 13,066 matches, Elo 0.2160; point model and simulator 0.2288.

**Academic and bookmaker benchmarks (read the scope before comparing)**

| Source | Evaluation | Brier |
|---|---|---|
| Penn et al. 2026, doi:10.1098/rsos.252512 | 1,684 ATP and WTA Grand Slam matches, 2024-2025 | Bookmaker odds 0.174; market-derived model 0.183; gradient boosting 0.193; surface Elo 0.198; Bradley-Terry 0.198 |
| Wilkens 2021, doi:10.3233/JSA-200463 | ATP and WTA, annual out-of-sample forecasts 2013-2019 | Bookmaker-implied 0.198; logistic regression 0.198; random forest 0.199; gradient boosting 0.199 |
| Tennis Abstract 2017 (tennisabstract.com) | About 50,000 ATP matches, 2000-2017 | Blended Elo: hard 0.202, clay 0.207, grass 0.196 |
| Tennis-Match-Predictions (github.com/nickdatak/Tennis-Match-Predictions) | ATP from 2023; Betfair on 878 matches, Bet365 and Pinnacle on about 8,000 | Bookmaker prices, XGBoost, logistic and Elo bars read from a chart; take exact values from the notebooks |

Scope limits: Penn covers Grand Slams only. Wilkens includes betting odds among its predictors. Bookmaker prices are an
evaluation benchmark, not a feature. A model that reproduces market prices answers a different question from ours.
The academic and benchmark figures above were taken from a literature review on 2026-10-14. The papers have not yet
been read in full, so check each number against its source before quoting it.

Where we sit: our Elo (0.2280 on ATP) is in the range of the published Elo baselines (0.196 to 0.226). The point model
(0.2353) is worse than Elo, as the published point models are (DEUCE's point model also trails its Elo).

## Starting point

Start from Elo, not from the point model.

- M1 (global Elo) is the match-probability reference. Every other model must beat it on Brier, on the same matches.
- The standalone point model lost to Elo on both tours. Its surface-specific serve and return data, on its own, does
  not carry the match-outcome information that Elo's accumulated record carries.
- The point model's job is to add information Elo lacks. Its weight should depend on how much serving history a player
  has. With thin history the forecast should revert toward Elo. This is the thin-history problem. In the 2026-10-14
  backtest it is the largest loss on both tours: about +0.06 log loss per match against Elo in matches where either
  player has fewer than 300 effective points on the surface.
- The known fixes (Gollub 2021, doi:10.3233/JSA-200345, as summarised in the review) are shrinkage, opponent
  adjustment and Elo-informed serve estimates. The review reports that restricting estimates to surface-specific data
  can worsen prediction, and that shrinkage, opponent adjustment and Elo improve it.
- Cross-surface transfer comes first. Blended overall and surface Elo at about 50/50 (Tennis Abstract's method)
  addresses thin surface history directly.
- The combination is logit-additive, with a reliability weight:

  logit(p_final) = logit(p_Elo) + w(n_A, n_B) * gamma * [logit(p_sim) - logit(p_Elo)]

  `n_A` and `n_B` represent effective serve/return evidence for both players. The reliability weight must fall when
  either player's matchup estimate is thin; it must not depend only on raw match counts. Fit the weighting rule and
  `gamma` on rolling validation data, never on the test window.

- The simulator is unchanged. It turns serve-point probabilities into game, set, tiebreak and match-score
  distributions. Its match-winner probability is an input to the match model, not the headline.

## Models (at least three)

| Model | What it is | Question it answers |
|---|---|---|
| M1 Elo | Global Elo, K = 32, no surface term | Reference. The incumbent every model must beat. |
| M2 Blended Elo | About 50/50 overall Elo and surface Elo | Does cross-surface transfer help? |
| M3 Elo plus serve/return | M2 plus the point model's probability, weighted by serving history (above) | Does serve/return data add anything Elo does not know? The candidate match model. |
| M4 Full feature model | M3 plus form, workload, rank and experience. Regularised logistic regression first; XGBoost only if it beats logistic on rolling validation | Does pre-match context add anything after M3? |
| Diagnostic: point model plus simulator | Standalone, no Elo | Reported for the record. Not a candidate model. |

Track B models follow the plan's ladder. P0 and P1 are the direct baselines, called B1 here: per-match and per-service-point
rates, with count families compared. B1 is the incumbent for props. P2 is the simulator with event labels (B2). P3 is the
calibrated joint simulator. A prop claim needs P2 to beat B1 on held-out matches at Gate C.

M1 and M2 need no serve statistics, so they can use every match. M3, M4 and P2 use the matches that have serve statistics.
Their scores should also be reported on the full population, so that coverage differences are visible.

## Track B: player projections

This is the next research milestone. The plan is `docs/RESEARCH-tennis-player-projections-2026-10-14.md` on this branch.
Each gate has to pass before the next step counts.

| Step | Work | Gate |
|---|---|---|
| 1 | Data audit: column inventory, counts, definitions, missingness, retirements, scoring rules and licensing | None. Finished before any model is fitted. |
| 2 | Direct baselines. P0: rolling ace and double-fault rates per match, shrunk to a tour prior, with Poisson and negative-binomial counts. P1: service points times ace and double-fault rates per service point, comparing Poisson, binomial, beta-binomial and negative-binomial | Gate B: count distributions with full coverage, and tested interval and exceedance calibration |
| 3 | Phase A: does the existing simulator predict the number of service points each player faces, against the P1 exposure baseline? | Gate A: a simulator that loses on exposure is not used for prop prediction |
| 4 | Phase C: P2, the simulator with event labels, against the best direct baseline | Gate C: beats the strongest direct baseline on a predeclared proper scoring rule, without unacceptable miscalibration |
| 5 | P3: opponent and surface adjustment, partial pooling, and per-match shared variation | Only after Gate C. Joint distributions and tails, validated separately. |

The event model splits each service point into a win, an ace, a double fault and another loss. It requires that an ace
always wins the point and a double fault always loses it, and it never clips probabilities silently after fitting. The
data has aggregated ace counts only, with no first-serve ace labels. Do not invent those labels.

**Cold start.** The surface-only point model is weakest where serving history is thin. Pool overall, other-surface and
same-surface evidence, with explicit effective sample sizes. Match-outcome Elo is a prior for these distributions only
once the service-point and exposure distributions validate on their own.

**Shared variation within a match.** A simulator that draws each point from fixed probabilities can understate how much
counts spread between matches. Estimate that variance from history before adding it (P3). Step 3 checks it: compare the
observed and simulated between-match variance of service points and aces for the same players.

Not used as evidence: social-media win rates and ROI claims, which are self-reported and unverified. The public tennis
projects above are reference architectures for the event model, not benchmarks for our numbers.

Sportsbook lines come last, after the licence for the line source is cleared and Gate C has passed. Each quote keeps its
timestamp, line, side, venue and grading rule.

## Build order

Next research milestone: Track B, starting with the data audit. Track A continues in parallel, and no longer comes first.

Track B, in the order the plan sets:

1. Data audit, written to `TENNIS-PROPS-DATA-AUDIT-2026-10-14.md`.
2. Direct baselines P0 and P1, with Gate B on the ace and double-fault count distributions.
3. Phase A, Gate A: does the existing simulator predict service-point volume well enough against the P1 exposure baseline?
4. Phase C, Gate C: P2, the simulator with event labels, against the best direct baseline.
5. P3, only after Gate C: opponent and surface adjustment, pooling, and per-match shared variation.
6. Sportsbook lines last, after the licence is cleared and Gate C has passed.

Track A, in parallel:

A1. M1 and M2 on rolling validation. Set the reference and test cross-surface transfer.
A2. M3: add the point-model probability with the history weight. Test the increment over M2. Use the same cold-start pooling as the props track.
A3. M4: add pre-match context, only if M3 is stable across years.
A4. Simulator set, game and tiebreak outputs: validate separately against historical set and game outcomes, not against winners.

## Evaluation

- **Development and confirmation are separate.** The 2023-2026 window is development now. Choose changes on rolling
  validation: for each year Y from 2019 to 2025, fit on matches before Y and predict Y. A confirmatory claim needs matches
  played after the 2026-10-14 freeze, scored once, with no change after seeing them.
- **Track A primary metric:** Brier per match. Report the Brier skill score against M1.
- **Track B primary metric:** declared for each gate before the run. Count distributions are scored by held-out log score
  where a discrete probability mass is supported, and by CRPS. Coverage is reported at 50%, 80% and 90%. Mean bias and MAE
  are secondary. Over and under scores are reported for every preregistered threshold, grouped by threshold and player,
  with the sample in each bin. Every Track B score is compared against the best direct baseline, not against match-winner Elo.
- **Track B intervals:** paired differences with bootstrap intervals at the match or tournament cluster level, by tour,
  year, surface, format, history depth and count size. Simulation seed stability is checked, so simulation noise is much
  smaller than the differences being tested.
- **Also:** log loss, a paired bootstrap 95% interval for each difference, calibration by probability bin, results by
  history size (thin, middling, deep), by year, by surface, by tour and by best-of.
- **Sides:** assign A and B at random, not winner first, so the target is not the winner.
- **Samples:** report every number with its n. Note the coverage of serve statistics by year, because history gaps
  differ by era (ATP about 60% in 2007-2009; WTA 0% before 2003).
- **Bookmaker prices:** evaluation benchmark only, never an input feature.
- **No betting-edge claim** until calibration holds on the confirmation window.

## Constraints

- Research only. Data is Jeff Sackmann's, licence CC BY-NC-SA 4.0 (decision D1 open). Product use is blocked until D1 is
  decided. Any sportsbook line source needs its own licence check. Flag every source in the report.
- Winners come from the match model. The simulator derives set, game, tiebreak and player stat outputs from
  serve-point probabilities and event probabilities. Each output is validated against its own baseline. (This replaces
  "predict points first, every market from one simulator". The 2026-10-14 backtest showed the point-first path does not
  carry to winner prediction, so the point model stops being the headline.)
- Store aces, double faults, service points and break points per match from the start. Keep them in any new table.
- Measure before you claim. Report each number with its sample size.

## Start here

- `docs/RESEARCH-tennis-player-projections-2026-10-14.md` (this branch): the Track B plan, its gates and its data limits.
- `docs/TENNIS-POINT-MODEL-STEP1-2026-10-14.md` (ATP) and `docs/TENNIS-POINT-MODEL-WTA-2026-10-14.md` (WTA), on
  `feat/tennis-point-model`: point model, form, rest caveat, WTA event decisions.
- `docs/TENNIS-MATCH-BACKTEST-PROTOCOL-2026-10-14.md` and `docs/TENNIS-MATCH-BACKTEST-2026-10-14.md`, on
  `feat/tennis-point-model`: the frozen backtest protocol and its results.
- `docs/TASK-tennis-set-scores.md`: per-set scores already flow from ESPN.
- Existing tennis spine and name-resolution work: branches `feat/tennis-spine`, `fix/tennis-unmatched-names`,
  `fix/tennis-unresolved-queue`.
- DraftKings Engineering, "Building a Tennis Simulation" (Medium). It describes a Monte Carlo point-to-match simulation,
  with a simplified model, and says the production model is more advanced. A search found the article (cur.at/NeCYkyJ)
  but did not confirm its date. The 2023-08-17 date is user-supplied. Open the page and check the date before citing it.
- Tennis simulators found by search, not yet reviewed: tennisim (PyPI, points-based simulation), bear102/tennis (GitHub,
  simulates matches and tiebreaks, with aces and double faults), Match Point AI (arXiv 2408.05960).
- DanielTomaro13/Tennis-Modelling (user-supplied, described as combining surface-adjusted serve and return profiles, Elo,
  a point-to-match simulator and ace and double-fault projections). A search did not find it. Confirm the repository exists
  before citing it or relying on its description.

## Deliverable

Reports in `docs/`, named as the plan sets out (planned names, not yet written):

- `TENNIS-PROPS-DATA-AUDIT-2026-10-14.md`: the data audit;
- `TENNIS-PROPS-BASELINES-2026-10-14.md`: P0 and P1 with Gate B;
- `TENNIS-PROPS-SIM-BACKTEST-2026-10-14.md`: P2 and P3, only after the earlier gates;
- `TENNIS-PROPS-DECISION-2026-10-14.md`: separate go or no-go decisions for exposure, ace and double-fault distributions, and
  simulation value.

Track A also reports, separately from Track B:

- Brier and log loss for M1 to M4, against the same matches, with Brier skill scores and paired intervals;
- the chronological backtest against Elo and blended Elo;
- a go or no-go for the simulator's set, game and tiebreak outputs, separate from the winner decision.
