# FBS passing hurdle — implementation run contract

Parent: `research/fbs/direct-props-2026-10-20/PREREG-FBS-HURDLE-PASSING.md` @ `0509dd74`
(rev 4). This directory implements that document. It does **not** fit, tune or
score anything, and it never writes to the committed research outputs.

## What is implemented

| piece | where | prereg |
|---|---|---|
| season-by-season, strictly chronological membership + provenance + 2018 boundary | `cohort.py` | §2.1–§2.2 |
| the two separate priors, zero-attempt handling | `priors.py` | §6.1, §6.4 |
| smoothed participation hurdle `p_H = (s + p_prior)/(n+1)` | `model.py` | §6.1 |
| zero-truncated NB conditional count (rejection, exact) | `model.py` | §6.2 |
| one attempt draw shared by attempts and yards, unclipped yards | `model.py` | §6.2–§6.3 |
| strictly-chronological windows (5 appearances / 5 positive / 15 opportunities) | `model.py` | §6.3, §6.5 |
| committed dispersion grids, imported read-only | `model.py` | §6.6 |
| secondary comparators (fair conditional-active trailing-5, simple hurdle) | `model.py` | §3 |
| the §7 leakage assertions, as guards that raise | `leakage.py` | §7 |
| the §10 signature gate | `prereg_gate.py` | §10 |

## Commands

```bash
cd research/fbs/direct-props-2026-10-20
PY=/root/legendarypicks/backend/venv/bin/python

$PY -m pytest hurdle/tests -q          # 34 tests: unit + falsification + population
$PY hurdle/run_hurdle_passing.py --check-only
$PY hurdle/run_hurdle_passing.py --fit # REQUIRES a signed §10; refuses today
```

`--check-only` loads the read-only cache, derives membership, verifies provenance,
runs every leakage assertion, confirms the committed baselines are readable, and
reports the row sets. It estimates **no** parameter: no `p_prior`, no conditional
mean, no dispersion, no grid.

`--fit` calls `prereg_gate.assert_prereg_signed()` as its first statement. With
§10 blank it raises `PreregNotSigned`. With a signature present it still refuses
by design: the fitting path is not in this commit, because the DECISION doc and
the prereg both make fitting a separate decision from implementation.

## Invariants that must not move

* `SPREAD_R_GRID` and `SPREAD_ESD_MULT` are imported from
  `run_direct_props.py` as tuples — the committed values, not a local copy.
* The decision rule (§5) and the primary metric (§4) live in the prereg only.
  Nothing here re-implements them; scoring uses `crps_from_samples`,
  `cluster_ci` and `score_block` from the committed module.
* Baselines are read from the committed `predictions_pass_attempts.csv`. No
  baseline is refit.

## Population check, and one ambiguity that was resolved in the prereg's favour

`hurdle/tests/test_population.py` asserts the 2025 cohort is **1,175 rows /
106 athletes**, the number the prereg registers. Two readings of "athletes with
no prior-season volume" produce different populations:

| reading | 2025 rows | athletes |
|---|---:|---:|
| athlete **appeared** in the cut season (`isin(vol.index)`, `cohort_analysis.py`) — **used** | 1,175 | 106 |
| athlete recorded **positive** volume in the cut season — not used | 1,219 | 118 |

The registered population is the first, so that is the default
(`cohort.DEFAULT_PRIOR_BASIS`). The second is available as
`prior_basis="positive_volume"` and is reported by `--check-only` as
`alternate_prior_basis` (`used: false`). Switching it changes the approved
population and therefore needs a prereg amendment, not a flag.

## Not done here, on purpose

No fitting, no tuning, no dispersion refit, no 2025 scoring, no predictions, no
`RESULTS.md` edit, no dev merge, no locks, no player-facing surface.
