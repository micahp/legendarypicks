# Frozen goalie keep-rule learner specification

**Frozen:** 2026-10-20, after Micah approved `PREREG-GOALIE-KEEP.md` and before any fitting.

This file freezes the learner and preprocessing needed by the approved protocol. The registered six goalie fields, opening-price comparison, four edge/price candidates, 200-bet conditions, and stopping decision remain exactly as signed. This specification does not approve production use.

## Learners

Fit two separate binary logistic-regression learners for each evaluation season:

1. **Market-only calibration diagnostic:** the sole predictor is the logit of the no-vig opening probability for the canonical home team.
2. **Goalie model:** the same market-logit predictor plus the registered home- and away-side goalie inputs.

Both use `sklearn.linear_model.LogisticRegression` with `penalty="l2"`, `C=1.0`, `solver="lbfgs"`, `fit_intercept=True`, `class_weight=None`, `max_iter=2000`, `tol=1e-8`, and `random_state=0`. A convergence warning is a hard run failure. There is no hyperparameter search, class weighting, or post-fit calibration. The market coefficient and intercept provide the sole logistic calibration. The raw no-vig market remains the primary preregistered control.

The binary target is canonical `official_home_winner` (1 for canonical home, 0 for canonical away). A row is trainable only when it meets the signed complete-feature, opening-quote, and final-result eligibility rules. SBR final winners are reconciled to this target by team identity before fitting; scoreline differences are listed in `JOIN-AUDIT.md`.

## Inputs and encoding

- The first predictor is `logit(p_market_home)`, with probability clipped to `[1e-6, 1 - 1e-6]` before the logit.
- `home_starter_last` and `away_starter_last` are categorical goalie IDs. Each side has a separate `OneHotEncoder(handle_unknown="ignore", sparse_output=True)` fitted on that fold's prior training rows only. An unseen evaluation ID maps to an all-zero category vector for that side.
- The five remaining registered fields for each side enter as separate numeric columns, in this order: `starter_games_trailing10`, `starter_gsax_trailing10`, `starter_savepct_trailing10`, `team_goalie_gsax_trailing10`, `starter_changed`.
- Numeric values are used as committed, without scaling, imputation, clipping, transformations, interactions, or feature selection. A non-finite or missing value in an otherwise eligible row is a hard error.
- The goalie model includes one market-logit, ten raw numeric columns, and the two side-specific goalie-ID one-hot blocks. It has an intercept and no other predictors.

## Time boundaries and frozen policy selection

For each evaluation season, fit both learners on all eligible rows from strictly earlier seasons. Fit the categorical vocabularies on those same training rows. Never use the held-out season's labels or features to fit either learner. The evaluation sequence is 2019-20, 2020-21, 2021-22, then the partial 2022-23 archive slice.

For 2019-20, use registered candidate D because no earlier out-of-fold evaluation history exists. For each later block, apply A–D to the already generated out-of-fold goalie-model predictions and realized outcomes from earlier evaluation blocks. A candidate is selectable only with at least 200 prior OOF bets. Select the highest prior paired net units per eligible game against the no-vig market control; ties go to higher edge, then higher minimum decimal price. If none reaches 200, use D. Do not use the current evaluation block to choose its candidate.

Each candidate selects at most one side when the full model's side edge is at least the registered cutoff, the actual opening decimal price meets the registered minimum, and model expected profit at that price is strictly positive. The no-vig control selects the side with the greatest `p_market * decimal_odds - 1` only when that value is positive; otherwise it passes. A pass settles at zero units.

## Scores and uncertainty

Report Brier score and log loss for raw no-vig market, market-only calibration, and goalie model on identical OOF rows. The stopping-rule `ΔBrier` is goalie-model Brier minus raw-market Brier.

Use the standalone selectivity report's season-block bootstrap convention: 5,000 resamples and seed `20261020`, resampling complete evaluation-season blocks with replacement. For paired policy delta and paired Brier difference, use `numpy.random.default_rng(20261020)` and the 5th and 95th percentiles. For ROI, reproduce `clustered_roi_ci` from the committed matchup-strategy harness: resample only bet-bearing season blocks, with `random.Random(20261020)`, calculate pooled net units per staked bet per draw, sort the 5,000 draws, use indices `int(.05*n)` and `int(.95*n)-1`, and round each bound to three decimal places in ROI units. An ROI interval is unavailable when fewer than two seasons contain bets. These intervals are coarse with four evaluation blocks and are not deployment evidence.

## Denominators and execution

The total registered eligible population is 4,763 games, including 1,254 eligible 2018-19 training rows. The OOF evaluation denominator is 3,509 games across 2019-20 through the partial 2022-23 block. Report training and OOF counts separately, plus the per-season breakdown in `JOIN-AUDIT.md` and `RESULTS.md`.

`run_goalie_keep.py --audit-only` performs the fail-loudly source and join checks without fitting. The fitting command is `run_goalie_keep.py --fit`; it requires a clean Git worktree so the signed preregistration, this specification, join audit, and runner are frozen first. It writes one OOF CSV and one results report and refuses to overwrite either. Run once. No AUC is part of this protocol.
