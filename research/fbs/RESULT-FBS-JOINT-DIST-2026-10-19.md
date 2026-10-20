# RESULT — FBS coherent joint score distribution

**Verdict: NOT_ADOPTED.** Six of seven registered gates pass; **G-CAL fails** because randomized PIT rejects uniformity for both walk-forward marginals and for holdout total. The primary shortest 50% interval coverage passes on walk-forward, but it does not override the PIT failures. The joint score distribution is coherent by construction and passed the hard draw-level check. Phase 4b remains **NOT_ADOPTED**; its gate and thresholds are unchanged. Nothing was deployed or written to production.

The preregistration was pushed before fitting or scoring at commit `5be5e30ef04e424589e7fadeca97a6bea1924603`. This run used that protocol without threshold changes, tuning, or a second candidate.

## Population and source audit

All schedule release byte counts and SHA-256 digests matched both the preregistered values and `archive-coverage.csv`. Completed eligible FBS-vs-FBS score pairs in the candidate fit source were 772, 774, 534, 770, 776, 792, and 798 for 2018–2024, totaling **5,216**. One uncompleted 2024 game (`401640992`) was excluded. Scores were integer values within 0–120, and game IDs were unique within each season.

| Partition | n scored | Candidate fit | Exclusions |
|---|---:|---|---|
| Walk-forward, 2023–2024 | 1,590 (792 / 798) | 3,626 games through 2022 for 2023; 4,418 through 2023 for 2024 | 0 |
| Frozen holdout, 2025 | 807 | 5,216 games through 2024, frozen | 1 game (`401778314`) remains excluded under the Phase 4 population rule; the duplicate 2025 walk-forward rows were not scored again |
| Forward-only, 2026 | 350 | Same frozen 5,216-game fit through 2024 | 0 of the registered Phase 4 dev rows; 38 of the archive's 388 completed games are outside that preexisting target ledger |

Every scored row joined to a completed schedule score and matched team IDs. Six forecast rows had home/away orientation reversed relative to the schedule release; their joint matrices were transposed by team ID before scoring. No other orientation or score discrepancy was found. The H1/Constant reconstruction on the 2025 holdout reproduces the published Phase 4 values to displayed precision (e.g. Constant margin/total CRPS 12.9184/10.4052; H1 12.5615/10.3916).

## Proper scores

Lower is better. Joint Brier is over the full 14,641-cell `(home, away)` outcome; spread and total Brier are the separately pooled market-event gates. Paired differences are candidate minus H1; bootstrap intervals use 2,000 UTC-week blocks and seed 20261017.

| Partition | Model | Joint Brier | Joint log loss | Margin CRPS | Total CRPS | Spread Brier | Total Brier |
|---|---|---:|---:|---:|---:|---:|---:|
| Walk-forward, n=1,590 | Candidate | 0.99892 | 8.8064 | 9.8731 | 9.5902 | 0.17802 | 0.23803 |
|  | H1 | 1.00179 | 11.8330 | 11.9007 | 10.5994 | 0.21646 | 0.25925 |
| 2025 holdout, n=807 | Candidate | 0.99884 | 8.2436 | 10.8033 | 9.4059 | 0.19747 | 0.23871 |
|  | H1 | 1.00142 | 11.8492 | 12.5615 | 10.3916 | 0.23059 | 0.26060 |
| 2026 forward, n=350 | Candidate | 0.99875 | 8.4471 | 10.3828 | 9.1323 | 0.17290 | 0.23827 |
|  | H1 | 1.00189 | 11.9813 | 12.7220 | 10.0056 | 0.20871 | 0.25929 |

Selected paired differences:

| Metric | Walk-forward candidate minus H1, 95% interval | 2025 holdout point difference |
|---|---:|---:|
| Joint Brier | −0.002865 [−0.003070, −0.002653] | −0.002579 |
| Margin CRPS | −2.0276 [−2.2623, −1.8127] | −1.7582 |
| Total CRPS | −1.0092 [−1.1395, −0.8858] | −0.9857 |
| Spread Brier | −0.03844 [−0.04272, −0.03402] | −0.03312 |
| Total Brier | −0.02122 [−0.02385, −0.01863] | −0.02189 |

Walk-forward spread Brier also beats Constant by −0.06425 [−0.07106, −0.05699], and total Brier beats Constant by −0.02176 [−0.02458, −0.01908]. 2026 is descriptive only: its candidate-minus-H1 point differences are −0.003139 joint Brier, −2.3392 margin CRPS, −0.8733 total CRPS, −0.03581 spread Brier, and −0.02102 total Brier.

## Calibration and coherence

The registered shortest contiguous 50% interval is authoritative. Walk-forward shortest coverage is **0.4987 for margin** and **0.5157 for total**, both within `[0.45, 0.55]`. Central 50% coverage, reported as a diagnostic, is 0.5365 for margin and 0.5094 for total.

| Randomized PIT KS p-value | Walk-forward | 2025 holdout | Required |
|---|---:|---:|---:|
| Margin | 0.02220 — fail | 0.09931 — pass | `> 0.05` in both |
| Total | 0.000406 — fail | 0.000068 — fail | `> 0.05` in both |

Thus G-CAL fails three of its four registered PIT checks. Shortest and central coverage at 80%/90%, along with holdout intervals, are in `summary.csv`; they do not change the gate.

For G-COHERENCE, the evaluator drew **10,000 pairs per target game**, 27,470,000 draws total. Every draw satisfied exact integer identities `total = home + away` and `margin = home − away`; every scored marginal was derived by pushing forward the same joint matrix. The hard gate passes.

## Discrete score-grid diagnostic

Entries are observed terminal-digit rate / mean predicted probability. The full 0–9 table for home and away is in `terminal_digit_calibration.csv`.

| Partition / side | Digit 0 | Digit 3 | Digit 6 | Digit 7 | Digit 8 |
|---|---:|---:|---:|---:|---:|
| Walk-forward home | .118 / .117 | .088 / .091 | .064 / .058 | .137 / .141 | .104 / .106 |
| Walk-forward away | .138 / .139 | .102 / .105 | .066 / .064 | .147 / .151 | .084 / .092 |
| 2025 home | .116 / .117 | .082 / .091 | .072 / .059 | .134 / .140 | .099 / .106 |
| 2025 away | .162 / .139 | .102 / .103 | .069 / .064 | .149 / .149 | .088 / .090 |
| 2026 home | .074 / .115 | .086 / .089 | .077 / .058 | .134 / .138 | .091 / .108 |
| 2026 away | .171 / .141 | .109 / .105 | .091 / .065 | .157 / .151 | .077 / .088 |

The model retains the integer score grid and reproduces substantial mass at the listed terminal digits. The 2026 digit rates are forward diagnostics and show visible departures (notably zero and six); they were not used to adjust the model or gates.

## Gate table

| Gate | Result | Basis |
|---|---|---|
| G-SAMPLE | PASS | 1,590 walk-forward; 807 holdout |
| G-DIST | PASS | Margin and total CRPS beat H1 under the registered walk-forward intervals and holdout point checks |
| G-CAL | **FAIL** | Three PIT checks reject uniformity; shortest 50% coverage itself passes |
| G-SPREAD | PASS | Beats Constant and H1 on walk-forward Brier intervals; negative holdout point difference vs H1 |
| G-TOTAL | PASS | Beats Constant and H1 on walk-forward Brier intervals; negative holdout point difference vs H1 |
| G-JOINT | PASS | Joint Brier interval is below zero on walk-forward and point difference is negative on holdout |
| G-COHERENCE | PASS | All 27,470,000 sampled pairs satisfy both exact identities |

G-CAL is binding; the candidate is **NOT_ADOPTED**. There was no gate loosening, refit on 2025/2026, 4b artifact reuse, or production change.

## Reproducible artifacts

- `backend/fbs_joint_dist_2026.py` — preflight, fit, scoring, bootstrap, and gate runner.
- `research/fbs/joint-dist-2026-10-19/run.json` — source audit, splits, gates, and coherence counts.
- `research/fbs/joint-dist-2026-10-19/per_game_scores.csv` — paired per-game proper scores and pooled market-event scores.
- `research/fbs/joint-dist-2026-10-19/summary.csv` — split/model summaries and calibration values.
- `research/fbs/joint-dist-2026-10-19/paired_comparisons.csv` — week-block comparisons.
- `research/fbs/joint-dist-2026-10-19/terminal_digit_calibration.csv` — observed and predicted digit probabilities.
- `research/fbs/joint-dist-2026-10-19/candidate_fit_folds.csv` — fit seasons and sample counts.

Re-run from this worktree with:

```bash
/root/legendarypicks/backend/venv/bin/python backend/fbs_joint_dist_2026.py \
  --source-root /root/lp-fbs-archive/research/fbs
```
