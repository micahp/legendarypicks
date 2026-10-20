# PRE-REGISTRATION — FBS coherent joint score distribution

**Availability verdict:** the on-disk schedule archive supports estimation of a joint distribution over integer FBS home/away score pairs. The published 2018–2024 schedule files contain 5,216 completed FBS-vs-FBS games with valid scores, and the frozen evaluation ledgers join to completed score pairs; no fit or evaluation score has been computed for this experiment as of this registration.

**Status:** pre-registered before candidate fitting or scoring. Branch `feat/fbs-joint-dist-2026-10-19`, based on `feat/fbs-phase5-2026-10-19` at `274d47f481698d6b834835ed76141e092293b359`. This registration must be pushed before any candidate fit, probability generation, simulation, or scoring. Phase 4b remains **NOT_ADOPTED**; its gate remains closed. No Phase 4b artifact or threshold is changed.

## 1. Question and scope

Test one new candidate: a direct, empirically dependent joint categorical distribution over `(home score, away score)`. This experiment asks whether that coherent pair distribution improves proper scores and calibration over the frozen Phase 4 controls. It does not reopen Phase 4b, select a production model, or change a gate.

Only completed FBS-vs-FBS games from seasons 2018–2024 may enter candidate training. The prospective evaluation partitions are:

| Partition | Score seasons | Candidate fit data | Expected n | Use |
|---|---|---|---:|---|
| Walk-forward | 2023–2024 | 2018–2022 for 2023; 2018–2023 for 2024 | 1,590 (792 / 798) | Gates and diagnostics |
| Frozen holdout | 2025 | 2018–2024, frozen | 807 | Gates and diagnostics |
| Forward-only | 2026 | 2018–2024, frozen | 350 on the Phase 4 dev ledger | Diagnostics only; no tuning or gate |

The Phase 4 2025 walk-forward rows duplicate the same games represented by the frozen 2025 holdout and will not be counted a second time. The 2025 holdout excludes game `401778314` under the existing Phase 4 population rule. Game `401640992` is an uncompleted 2024 schedule entry, so it is not a score pair and is not eligible for training or evaluation. The 2026 forward set is restricted to the 350 completed games in the frozen Phase 4 dev ledger; no 2026 result enters a fit or decision threshold. Any target row that fails its predeclared identity or completed-score join is reported as a coverage failure and prevents an adoption verdict; it is never silently dropped.

## 2. Source, population, and identity contract

The published SportsDataverse `cfb_schedules` Parquet releases are the source for game division, completion status, team IDs, and observed final scores. Eligibility is `fbs_game == true` and `completed == true`; both scores must be integers in `[0,120]`. Regular-season and postseason FBS-vs-FBS games are retained. Game IDs must be unique within each season. A null score, an uncompleted game, duplicate game ID, score outside support, or failed source digest is a hard data-integrity failure.

The checked release manifest is `research/fbs/archive-coverage.csv`. Each local file's byte length and SHA-256 must equal its manifest row before use:

| Season | Completed eligible games | SHA-256 |
|---:|---:|---|
| 2018 | 772 | `cf26150d2c9140a9eef90d274865bcacd6de2ce265e8254024ba5d76445e54fc` |
| 2019 | 774 | `64c23f8e70600c161136450f20e2e29965e947dd98aa252753e7b93fb0fd55a7` |
| 2020 | 534 | `58380661b434daf183b07aebf9afeeadf13450d5bc819dd0ce44ba689e96ee58` |
| 2021 | 770 | `a5577f826724bdcfe96ba829bf3055055c6e2e935cff59a7ab4a441d13925cb8` |
| 2022 | 776 | `9f23a4cfba3577f1689b9954aa31a9f42a954fcb676204c35c2cc85a76ed72b5` |
| 2023 | 792 | `58ca3ee4dae1185878feec061aa488e4298c011277cd083ab71dc233ad25f73f` |
| 2024 | 798 | `7feb11b7ac2eccd92afd741a59efeb7f1fd26bb51d15675ab1164cd01985a153` |
| 2025 | 808 | `0df9da5419dcac1ed8dcf848ef960b2cb3f90ad8d44203618b1840370709bb2e` |
| 2026 | 388 completed in archive | `9b970cff51bda692cc9d00eab06c73d63ae8e6bceac29301ff33c309f9e462bc` |

Candidate training counts by fold are 3,626 for 2023 (2018–2022), 4,418 for 2024 (2018–2023), and 5,216 for the frozen 2025/2026 model (2018–2024). The 2024 incomplete game is excluded from the 5,216. No season after 2024 contributes to candidate parameters.

Evaluation targets and win-probability inputs come from the frozen Phase 4 ledger. Walk-forward probability targets are Phase 3 G2h `p_g2h`; the frozen 2025 target is the Phase 4 `elo_home_prob`; 2026 forward-only uses the Phase 3 G2h `p_g2h` present in the Phase 4 dev ledger. The Phase 4 H1 probability matches those sources on every registered evaluation row. Team identity joins use stable team IDs, never names. Six 2023–2024 target rows have forecast home/away IDs reversed relative to the schedule release (`401520167`, `401520445`, `401551755`, `401551767`, `401677085`, `401677093`). The score pair and all probability matrices are transposed by ID for those rows. The home-win target is recomputed as the sum of H1 matrix cells with schedule-home score greater than schedule-away score; it is not set to `1 - p_h1`, because ties have nonzero mass. Any additional ID mismatch is a hard failure.

## 3. Candidate model: smoothed empirical joint plus win-probability tilt

The support is the integer grid `h,a ∈ {0,…,120}` (14,641 cells). For a scored season `s`, let `N_s(h,a)` be the count of prior-season eligible games in that cell and `N_s` the total count. The unconditioned joint is a single symmetric Dirichlet-smoothed empirical table:

```text
P0_s(h,a) = (N_s(h,a) + 1/14,641) / (N_s + 1)
```

This is a direct bivariate categorical model: score dependence is represented by the observed joint cell frequencies. No independence or copula assumption is made. For each target game, exponentially tilt the cells where the schedule-home score is higher:

```text
P_i(h,a) = P0_s(h,a) * exp(theta_i * 1[h > a]) / Z_i
```

Choose the unique `theta_i` so `sum(P_i[h>a])` equals the orientation-adjusted frozen Phase 4 H1 home-win probability. Use the same `[1e-4, 1-1e-4]` probability clamp as the Phase 4 H1 implementation. With positive smoothed mass on both sides, this is a closed-form one-parameter tilt. There is one candidate, no tuning grid, and no secondary arm.

Every predictive outcome is one cell `(h,a)`. For each cell, derive `margin = h - a` and `total = h + a`; obtain margin and total PMFs by summing joint cells over those exact identities. The same cell is used for joint scoring and for all derived market events. This makes disagreement between margin, total, home score, and away score impossible by construction.

The grid keeps final scores discrete, rather than approximating them with a continuous bivariate normal. The archive's integer score pairs include the aggregate effects of safeties, missed PATs, two-point conversions, and overtime; this is a final-score model, not a play-level scoring-mechanism model. As a score-grid diagnostic, report the observed terminal-digit frequencies and the mean predictive terminal-digit probabilities for home and away scores, by digit 0–9 and evaluation partition. Highlight digits 0, 3, 6, 7, and 8, but do not use this diagnostic as a tuned gate.

## 4. Frozen controls and orientation

Reconstruct the Phase 4 `Constant` and `H1` joint distributions on the same 0–120 score grid using the frozen per-game `mu_h0`, `mu_a0`, and `p_h1` parameters. `Constant` is the truncated, normalized independent league-average Poisson pair with no tilt. `H1` is that same pair tilted by `exp(theta)` on home-win cells to match `p_h1`, using the Phase 4 implementation. These controls are benchmarks only; neither their parameters nor the candidate are refit on 2025 or 2026 outcomes. Apply the same team-ID orientation normalization to the controls and target score pair.

The Phase 4b shifted-total PMF is not an input, a control, or a rescue candidate. No existing margin PMF is refit.

## 5. Metrics and fixed inference procedure

Report only proper scores and calibration diagnostics; do not report accuracy, hit rate, MAE, or RMSE.

- **Joint score:** multiclass Brier per game, `sum_(h,a) (P_i(h,a) - 1[(h,a)=(observed_h,observed_a)])^2`, and joint log loss `-log(P_i(observed_h,observed_a))`. The joint Brier is the primary joint metric.
- **Derived distributions:** discrete CRPS for margin and total; discrete randomized PIT with KS p-values; shortest and central interval coverage at 50%, 80%, and 90%. Derive all of these from the candidate joint PMF.
- **Market benchmarks:** Brier and log loss for home giving/getting 3, 7, 10, and 14 (eight events, strict cover rule `margin > line`) and over 45, 48, 52, 56, and 60 (strict over rule `total > line`). Pool each game's event losses equally across its eight spread events or five total events, matching Phase 4. These remain separate spread and total gates.
- **Score-grid calibration:** observed terminal digit rate and average predicted digit probability for each home/away digit 0–9, by partition.

Paired comparisons use the candidate-minus-control per-game loss, resampled by UTC calendar week with season included in the block key. Use 2,000 week-block bootstrap replicates, percentile 95% intervals, and seed `20261017`. For each replicate, sample the observed number of week blocks with replacement and average the selected per-game losses, preserving block sizes. The holdout gate uses the point difference only where Phase 4 specified that rule. Randomized PIT uniforms use seed `20261019`, generated once per game and marginal and shared across candidate/control diagnostics. No multiplicity or threshold adjustment is made.

## 6. Gates (fail closed)

All five Phase 4 gates remain separate. Adoption would additionally require the new joint gate and the hard coherence gate. A pass requires every listed condition; missing scores, absent comparison rows, non-finite metrics, or failed source checks cannot count as a pass.

| Gate | Pass condition |
|---|---|
| **G-SAMPLE** | At least 1,500 walk-forward games and 250 frozen holdout games. The registered counts are 1,590 and 807. |
| **G-DIST** | Candidate beats H1 on margin and total CRPS: both paired 95% week-block intervals are entirely below zero on 2023–2024 walk-forward, and both holdout point differences are below zero on 2025. |
| **G-CAL** | Randomized PIT KS p-value is `> 0.05` for both margin and total on walk-forward and holdout. On walk-forward, the **shortest contiguous 50% interval** is primary and its coverage must be in `[0.45,0.55]` for both margin and total. Central 50% coverage is diagnostic. Shortest and central 80%/90% coverage and holdout coverage are reported as diagnostics, not extra gates. |
| **G-SPREAD** | Candidate pooled spread Brier beats both Constant and H1 with paired week-block intervals entirely below zero on walk-forward; candidate-minus-H1 point difference is below zero on holdout. |
| **G-TOTAL** | Candidate pooled total Brier beats both Constant and H1 with paired week-block intervals entirely below zero on walk-forward; candidate-minus-H1 point difference is below zero on holdout. |
| **G-JOINT** | Candidate joint Brier beats H1 with paired week-block interval entirely below zero on walk-forward and point difference below zero on holdout. Joint log loss is reported as a proper-score diagnostic. |
| **G-COHERENCE** | Hard gate: for every generated score draw, `total == home + away` and `margin == home - away` exactly. The evaluator will draw 10,000 pairs per target game from the same normalized joint matrix and assert both equalities for every draw; any mismatch stops the run and fails the candidate. All margin/total PMFs must also equal exact pushforwards of that joint matrix. |

The 2026 forward-only results are reported separately using the frozen 2018–2024 candidate fit; they do not alter any gate or adoption verdict. Phase 4b remains NOT_ADOPTED regardless of this experiment's result.

## 7. Predeclared falsifiers and stop rules

1. If a manifest digest/byte count fails, a target score or team ID cannot be joined, a duplicate ID appears, an outcome is incomplete or outside support, or the frozen H1 probability cannot be reconciled to its declared source, stop before scoring and report the exact failure and counts.
2. If any later-season outcome enters a candidate training table, the run is invalid. Do not repair by changing folds after seeing metrics.
3. Any mismatch in a sampled pair, derived total/margin, or exact joint-to-marginal pushforward fails G-COHERENCE and stops adoption consideration.
4. Failure of any gate means **NOT_ADOPTED**. No smoothing changes, line changes, season exclusions, threshold loosening, second model, or post-holdout refit are allowed in this experiment.
5. If the candidate fails a proper-score or calibration gate, record the failure as the result. The existing Phase 4b finding and gates remain untouched.

## 8. Pre-fit availability audit

Before this file was written, and without fitting or scoring, the following were verified:

- Manifest byte counts and SHA-256s match local 2018–2025 schedule releases; the 2026 release also matches its manifest.
- The completed eligible training counts are 772, 774, 534, 770, 776, 792, and 798 (2018–2024), totaling 5,216. Scores are integer and within 0–120; game IDs are unique within season.
- Frozen Phase 4 has 1,590 2023–2024 walk-forward targets, 807 2025 holdout targets, and 350 2026 dev targets. All 2,747 target rows join to completed schedule scores and source team IDs; the 2026 forward rows are likewise complete.
- The six forecast/schedule orientation reversals are enumerated in §2; every other audited target has matching team IDs. The Phase 4 `p_h1` value matches its declared win-probability source on each target row.

No candidate fit, PMF, simulation, proper score, or calibration statistic has been computed as of this registration.
