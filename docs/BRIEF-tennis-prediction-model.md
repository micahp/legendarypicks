# BRIEF: Tennis match prediction and player projections

Revised 2026-10-14, twice. The first revision moved the starting point from the point model to Elo after the backtest.
The second adds a player-projection track (service points, aces, double faults, breaks and games), read from the same
simulator and validated on its own counts.

## Question

Track A, match: for a given player pair on a given surface and format, how likely is each player to win, and what are
the set score, total games, tiebreak and three-set probabilities? The match model gives the winner. The simulator gives
the set, game and tiebreak outputs.

Track B, player projections: for a player in a given match, what is the distribution of service points, aces, double
faults, break points won and games won? Those are the stat lines behind player props.

## Two tracks, one simulator

- Every point updates the match state and the players' statistics. A simulated match therefore gives the winner, the
  score and each player's stat line together, so joint outcomes stay correlated: an ace-heavy match that goes to a
  tiebreak, for example.
- Each track has its own baseline and its own validation. Track A is judged by Brier against Elo. Track B is judged by
  the log score and interval coverage of count distributions, against independent player-stat baselines. Success on one
  track does not count toward the other.
- The current simulator is points-only. It needs to know who wins each point, not what happened during the point. Track B
  needs a point-level event model (below). That is a build, not yet done.

## Architecture (target)

Player ratings and matchup conditions (Elo, serve and return, surface, form, rest)
-> point-level event model (first serve in; ace or rally; second serve: double fault, second-serve win or rally)
-> full match simulation (every point updates game, set and match state and each player's counts)
-> match markets (winner, totals, spread) and player projections (service points, aces, double faults, breaks)
-> joint outcomes (correlated props) and live projections (remaining-match distributions).

Every event probability is trained from historical counts. None is assigned by hand.

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

  logit(p_final) = logit(p_Elo) + w(n) * gamma * [logit(p_sim) - logit(p_Elo)]

  w(n) rises with the player's serving history, and gamma is fitted on rolling validation data, not on the test window.

- The simulator is unchanged. It turns serve-point probabilities into game, set, tiebreak and match-score
  distributions. Its match-winner probability is an input to the match model, not the headline.

## Models (at least three)

| Model | What it is | Question it answers |
|---|---|---|
| M1 Elo | Global Elo, K = 32, no surface term | Reference. The incumbent every model must beat. |
| M2 Blended Elo | About 50/50 overall Elo and surface Elo | Does cross-surface transfer help? |
| M3 Elo plus serve/return | M2 plus the point model's probability, weighted by serving history (above) | Does serve/return data add anything Elo does not know? This is the candidate match model. |
| M4 Full feature model | M3 plus form, workload, rank and experience. Regularised logistic regression first; XGBoost only if it beats logistic on rolling validation | Does pre-match context add anything after M3? |
| Diagnostic: point model plus simulator | Standalone, no Elo | Reported for the record. Not a candidate model. |

Track B models: B1, an independent player-stat baseline, is the incumbent for props. It fits negative-binomial or
beta-binomial counts for aces, double faults and service points, using player and surface rates. B2 is the simulator's
counts from the event model. A prop claim needs B2 to beat B1 on held-out matches.

M1 and M2 need no serve statistics, so they can use every match. M3, M4 and B2 use the matches that have serve
statistics, and their scores should also be reported on the full population so that coverage differences are visible.

## Track B: player projections

Experiments, in order, each with its success criterion:

| Priority | Experiment | Success criterion |
|---|---|---|
| 1 | Validate simulated service-point and total-game distributions | Better distributional accuracy than simple historical baselines |
| 2 | Model ace and double-fault rates with surface and opponent adjustments | Better held-out count and probability forecasts |
| 3 | Extend point simulation to record those events | Player counts agree with scoring outcomes |
| 4 | Compare full prop distributions with direct negative-binomial and beta-binomial baselines | Better log score, calibration and interval coverage |
| 5 | Elo as a prior for thin-history players (both tracks) | Less cold-start error without degrading prop distributions |
| 6 | Evaluate over and under calibration on historical sportsbook lines | Calibrated over/under probabilities before any claim of edge |

**Shared variation within a match.** A simulator that draws every point from fixed probabilities can understate how
much counts spread from match to match. Conditions are shared within a match: a day when serving is strong affects
both the aces and the hold probability. The first test, before the event model is extended, compares the observed
between-match variance of service points and aces with the variance the fixed-probability simulator produces for the
same players. If the observed variance is larger, add a per-match draw of serve effectiveness before the points are
generated. Its variance is estimated from history.

Not used as evidence: social-media win rates and ROI claims, which are self-reported and unverified. The public tennis
projects above are reference architectures for the event model, not benchmarks for our numbers.

## Build order

Track A:

1. M1 and M2 on rolling validation. Set the reference and test cross-surface transfer.
2. M3: add the point-model probability with the history weight. Test the increment over M2.
3. M4: add pre-match context, only if M3 is stable across years.
4. Simulator set, game and tiebreak outputs: validate separately against historical set and game outcomes, not against
   winners.

Track B:

5. The shared-variation test above.
6. Priorities 1 to 4 of the Track B table, with B1 as the baseline.
7. Elo prior for thin history (priority 5), applied to both tracks.
8. Sportsbook lines (priority 6), only after the licence for the line source is cleared.

## Evaluation

- **Development and confirmation are separate.** The 2023-2026 window is development now. Choose changes on rolling
  validation: for each year Y from 2019 to 2025, fit on matches before Y and predict Y. A confirmatory claim needs matches
  played after the 2026-10-14 freeze, scored once, with no change after seeing them.
- **Track A primary metric:** Brier per match. Report the Brier skill score against M1.
- **Track B primary metric:** the log score of each observed count under the predicted distribution, the coverage of
  80% and 95% intervals, and the calibration of over and under at each line. Compare on identical matches, always against
  B1.
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

A short report in `docs/` covering:

- what the data supports, with sample sizes and coverage by era;
- Brier and log loss for M1 to M4, against the same matches, with Brier skill scores and paired intervals;
- the chronological backtest against Elo and blended Elo;
- Track B: the count distributions for service points, aces, double faults and breaks against B1, with log score,
  interval coverage and sample sizes;
- a go or no-go for the simulator's set, game and tiebreak outputs, and a separate go or no-go for player projections,
  each separate from the winner decision.
