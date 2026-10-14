# NHL baseline ladder: preregistered evaluation protocol

Registered before computing model metrics, 2026-10-14. Input artifacts are fixed by SHA-256 in the canonicalization report. Outcomes and features are joined only by `game_id`; market prices are excluded from every statistical model input.

## Chronological split

Season labels are the first year of the NHL season (for example, 2025 means 2025–26).

| Role | Seasons | Use |
| --- | --- | --- |
| Initial fit | 2008–2017 | Fit coefficients, league rates, shootout tie-break prior, and initial Elo score mapping. |
| Validation/model selection | 2018–2021 | Select only the preregistered Elo settings and Poisson regularization values; choose validation leaders by the specified primary metric. |
| Locked historical test | 2022–2024 | After selecting the specification, refit coefficients on 2008–2021 and evaluate once. No test-driven changes. |
| Final untouched season | 2025–26 | Keep out of all model/parameter selection. Evaluate only after statistical model specifications are locked; then separately compare frozen predictions with Kalshi for the covered playoff games. |

All game features use only earlier calendar dates. Games on the same calendar date are excluded from one another's recent-form and Elo state because reliable completion timestamps are unavailable. Elo is updated after all games on a date, before the next date. Validation/test game outcomes never update fitted GLM/logistic coefficients, but earlier completed dates update rolling features and Elo state as they would in a chronological forecast.

## Targets and markets

- Moneyline target: NHL official home winner, including overtime and shootouts.
- Goal targets: regulation/overtime goals; the NHL shootout-deciding goal is removed. Official final scores remain separately preserved.
- Grade winner probabilities with Brier score, log loss, calibration intercept/slope, and 10-bin expected calibration error.
- Grade goal projections with per-team MAE/RMSE, total-goals MAE, and joint independent-Poisson negative log likelihood.
- No closing/market/settlement field is a statistical feature. Kalshi is evaluated only after model locking, on games with usable quotes, using normalized two-sided YES midpoints as the comparison probability.

## Preregistered ladder

- **B0:** 50% home-win probability; training-set home/away mean goals for score metrics.
- **B1:** training-set home-win base rate; training-set home/away mean goals.
- **B2:** recent-form logistic regression: prior-10 win rate and goal differential for each team, rest difference, and non-neutral home indicator. Logistic regularization `C ∈ {0.01, 0.1, 1, 10, 100}`; select validation Brier.
- **B3:** Elo winner probabilities. Search `K ∈ {10, 20, 30, 40}` and home-ice Elo offset `{35, 65, 100}`; select validation Brier. Fit a separate Poisson goal mapping from Elo rating difference using fit data only.
- **B4:** historical-goals independent Poisson model, using rolling prior-10 goals for and goals against (minimum five valid observations).
- **B5:** xG independent Poisson model, using rolling prior-10 score/venue-adjusted 5-on-5 xGF and xGA (minimum five valid observations).
- **B6:** combined goals+xG independent Poisson model, using the B4 and B5 inputs.

For B4–B6, fit a team-side Poisson GLM with a non-neutral home indicator, own-team rolling offense, and opponent rolling defense. Search `alpha ∈ {0.01, 0.1, 1, 10}` independently per model; select validation joint goal negative log likelihood. Predict the home moneyline from the independent goal distributions; for tied regulation/overtime goal targets, use the fit-set home shootout win rate. Score distributions and official winner probabilities are graded against their separate targets.

Validation leaders are descriptive model-selection outputs, not independent performance claims. Locked-test and final-season results are the evidence for generalization. B6 (goalie) and player/line models are excluded because the immutable pregame table does not contain confirmed pregame goalie or lineup features.

## Statistical model lock and Kalshi comparison

After validation settings are selected, refit the frozen statistical specifications on seasons 2008–2021. Evaluate 2022–2024, then 2025–26, without retuning. Lock the model set and select the Kalshi comparison model by validation Brier (ties broken by simpler model order B3, B4, B5, B6). Compare that frozen model with the Kalshi midpoint baseline on the exact matched 2025–26 playoff games; report the sample size and do not impute the two games without Kalshi events.

The 80-game comparison is a small, separate market benchmark. It does not alter statistical model specifications or serve as a model feature.
