# Play-call table gate: result

Status: FAIL. Branch `pbv1-integration-2026-11-02`, 2026-11-02. The lineup layer and the feature flag stay off until the gate passes.

Reproduce: `python3 scripts/nfl_sequence/playcall_eval.py --raw-dir /root/gridiron-playbooks-research/data/raw --artifact docs/research/SLC-PLAYCALL-ARTIFACT-FIT-2010-2024-v1.json --out-dir docs/research/PLAYCALL-TABLE-2026-11-02` (about 2.5 minutes, one process). The full numbers are in `playcall_eval.json` next to this file.

## Folds

Each fold fits the table only on seasons before the test season. 2023 is fitted on 2022, 2024 on 2022 to 2023, 2025 on 2022 to 2024. The 2026 table is not prepared, because the gate has not passed.

## Criteria (fixed before the run; not edited after it)

| # | Criterion | Result | Measured |
|---|---|---|---|
| C1 | Joint log loss of the team-aware table below league-only and team-rate in every fold | FAIL | see table below |
| C2 | Run-or-pass family log loss no worse than PlayCallLayer on 2025 | FAIL | table 0.619 vs PlayCallLayer 0.590 (league-only 0.599) |
| C3 | Calibration gap at most 0.03 on 2025 | PASS | 0.024 |
| C4 | Personnel total variation at most 0.05 in every fold | FAIL | 2023 0.035, 2024 0.034, 2025 0.069 |
| C5 | Team pass-rate correlation at least 0.80 on 2025 | FAIL | 0.42 |
| C6 | Two-team acceptance: same state, opposite histories, gap at least 0.05 in the history's direction | PASS | CIN 0.542 vs BAL 0.416 sampled pass rate, gap 0.126 |
| C7 | Every sampled call legal (joint support at least 5 plays) | PASS | legal share 1.0 for both teams |
| C8 | Same seed, same calls | PASS | deterministic |
| C9 | League-wide pass rate higher on 3rd and 11+ than 1st and 10 | PASS | |

Overall: FAIL.

## Joint log loss (no formation), per fold

| Test season | Table (team-aware) | League-only | Team rate |
|---|---|---|---|
| 2023 | 3.528 | 3.484 | 3.502 |
| 2024 | 3.403 | 3.302 | 3.411 |
| 2025 | 3.749 | 3.555 | 3.680 |

The team-aware table is worse than league-only in every fold. It is also worse than the team-rate baseline in 2023 and 2025.

## Fallback rates (share of calls that fell back to a coarser context)

| Test season | Step C | Step P | Step R |
|---|---|---|---|
| 2023 | 0.067 | 0.466 | 0.646 |
| 2024 | 0.039 | 0.333 | 0.749 |
| 2025 | 0.054 | 0.251 | 0.649 |

Most run-step contexts are sparse at team level. Fallback is recorded, as the acceptance criteria require.

## In-sample check (scoring sanity)

A one-off check, not committed as a script. Fit on 2022 to 2023 and score 2023, then fit 2022 and score 2022:

| Scored season | Table | League | Rate |
|---|---|---|---|
| 2023 in-sample (fit 2022 to 2023) | 2.788 | 3.122 | 3.212 |
| 2022 in-sample (fit 2022) | 2.796 | 3.150 | 3.263 |

The team-aware table beats league by about 0.33 in-sample and loses out-of-sample by 0.05 to 0.10 (2023 and 2024 rows above). A model that is better in-sample and worse out-of-sample is the signature of cells that memorise their own season. The out-of-sample numbers come from the same scoring code, so they are the honest test. The gap is a design result, not a sign that the scorer is broken.

## What this means

- The team-level cells do not transfer across seasons under equal weighting. The team-aware table's advantage comes from the season it was fitted on.
- The gate was pre-declared. Its thresholds stay as written. A change to the table (for example recency-weighted counts or a previous-season team prior) is a new design. It must be declared before it is scored, and scored on a fold that has not informed the change.
- Not activated: the lineup layer, the feature flag and the 2026 table. Nothing here changes the engine.
