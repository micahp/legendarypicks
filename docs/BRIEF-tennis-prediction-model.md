# BRIEF: Tennis match prediction model

Revised 2026-10-14. The previous version started from the point model. The 2026-10-14 backtest showed that
starting point does not beat Elo on match winners, so the starting point changed (see "Starting point").

## Question
For a given player pair on a given surface and format, how likely is each player to win the match, and what does that
imply for the set score, total games, tiebreaks and aces? Match winner comes from a match model. Game, set and tiebreak
outputs come from the simulator, which takes serve-point probabilities as input.

## Status (2026-10-14)

Measured on the 2023-2026 test window. That window has now been inspected, so it is development, not confirmation.
Best-of-three matches with complete scores. Brier skill score (BSS) is against Elo: 1 - Brier(model) / Brier(Elo).

| Model | ATP Brier (n = 11,777) | ATP log loss | WTA Brier (n = 13,066) | WTA log loss |
|---|---|---|---|---|
| M1 Elo (global, K = 32) | 0.2280 | 0.6490 | 0.2160 | 0.6210 |
| Point model + simulator, standalone | 0.2353 (BSS -0.032) | 0.6628 | 0.2288 (BSS -0.060) | 0.6486 |

Verdict: the standalone point model and simulator do not beat Elo on match winners, on either tour. The simulator's
game, set and tiebreak outputs are not yet validated against outcomes. Details: `docs/TENNIS-MATCH-BACKTEST-2026-10-14.md`
and `docs/TENNIS-MATCH-SIM-2026-10-14.md`, both on branch `feat/tennis-point-model`.

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

M1 and M2 need no serve statistics, so they can use every match. M3 and M4 use the matches that have serve statistics,
and their scores should also be reported on the full population so that coverage differences are visible.

## Build order

1. M1 and M2 on rolling validation. Set the reference and test cross-surface transfer.
2. M3: add the point-model probability with the history weight. Test the increment over M2.
3. M4: add pre-match context, only if M3 is stable across years.
4. Simulator outputs (set score, total games, tiebreaks, three-set probability): validated separately against
   historical set and game outcomes, not against winners.
5. Props later: aces (service points times ace rate), then break and double-fault rates.

## Evaluation

- **Development and confirmation are separate.** The 2023-2026 window is development now. Choose changes on rolling
  validation: for each year Y from 2019 to 2025, fit on matches before Y and predict Y. A confirmatory claim needs matches
  played after the 2026-10-14 freeze, scored once, with no change after seeing them.
- **Primary metric:** Brier per match. Report the Brier skill score against M1.
- **Also:** log loss, a paired bootstrap 95% interval for each difference, calibration by probability bin, results by
  history size (thin, middling, deep), by year, by surface, by tour and by best-of.
- **Sides:** assign A and B at random, not winner first, so the target is not the winner.
- **Samples:** report every number with its n. Note the coverage of serve statistics by year, because history gaps
  differ by era (ATP about 60% in 2007-2009; WTA 0% before 2003).
- **Bookmaker prices:** evaluation benchmark only, never an input feature.
- **No betting-edge claim** until calibration holds on the confirmation window.

## Constraints

- Research only. Data is Jeff Sackmann's, licence CC BY-NC-SA 4.0 (decision D1 open). Product use is blocked until D1 is
  decided. Flag any source in the report.
- Predict match winners with a match model. The simulator derives game, set and tiebreak outputs from serve-point
  probabilities. (This replaces "predict points first, every market from one simulator". The 2026-10-14 backtest showed
  the point-first path does not carry to winner prediction, so the point model stops being the headline.)
- Store aces, double faults and service points per match from the start.
- Measure before you claim. Report each number with its sample size.

## Start here

- `docs/TENNIS-POINT-MODEL-STEP1-2026-10-14.md` (ATP) and `docs/TENNIS-POINT-MODEL-WTA-2026-10-14.md` (WTA), on
  `feat/tennis-point-model`: point model, form, rest caveat, WTA event decisions.
- `docs/TENNIS-MATCH-BACKTEST-PROTOCOL-2026-10-14.md` and `docs/TENNIS-MATCH-BACKTEST-2026-10-14.md`, on
  `feat/tennis-point-model`: the frozen backtest protocol and its results.
- `docs/TASK-tennis-set-scores.md`: per-set scores already flow from ESPN.
- Existing tennis spine and name-resolution work: branches `feat/tennis-spine`, `fix/tennis-unmatched-names`,
  `fix/tennis-unresolved-queue`.

## Deliverable

A short report in `docs/` covering:

- what the data supports, with sample sizes and coverage by era;
- Brier and log loss for M1 to M4, against the same matches, with Brier skill scores and paired intervals;
- the chronological backtest against Elo and blended Elo;
- a go or no-go for the simulator's game, set and tiebreak outputs, separate from the winner decision.
