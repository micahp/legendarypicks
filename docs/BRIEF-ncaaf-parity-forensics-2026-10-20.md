# NCAAF C2 / G2h parity forensics — 2026-10-20

**Status:** research diagnosis only, **not** a forecast, validated parity run, model adoption, or permission to merge. Origin: `dev` at `f465af89`; fix branch at `6fd06975`. Do not modify `dev`, production, locked forecasts, or model parameters from this document.

## Immediate decision

Keep C2 and G2h lock issuance **blocked**. Retain G2 (already reported exact) as an independently reproducible reference, but do not automatically grant it production publication/locking without checking the whole operational pipeline. Previews may be visible only if clearly marked uncertified/research; they must not be recorded as locked predictions or graded picks. No backdating of legacy rows. Do not schedule T-90 jobs until parity has passed and the full workflow is QA'd.

**Do not choose "raw" or "standardized" based on which Brier score looks nicer.** Reproduce the original research fitter and training cohort, then test production parity.

## Findings established directly from versioned source

1. The **original G2h ledger writer is present** in `backend/fbs_phase3_increment_g.py` on `feat/fbs-archive`. Its `main()` writes `research/fbs/phase3-g/forecasts_walk_forward.csv`. It also writes the held-out forecasts and metrics. Do not call the reference ledger untraceable until reproducing or documenting why this committed writer cannot reproduce it.
2. Before fitting, this writer merges `research/fbs/phase3/game_features.csv` for `epa_diff`, merges drive features from `research/fbs/phase3/game_features_c.csv`, fills missing C fields at the registered zero-difference prior, then **filters all rows with null `epa_diff`**. It asserts 3,523 rows overall and 2,397 scored games in 2023–2025. `epa_diff` is not a model input for C2 or G2h, but the filter *changes the fitting population*.
3. The production `fbs_model_service.build_frame()` and parity `fbs_model_runner.check_parity()` do not apply this same `epa_diff`-availability filter. Even if the 2,397 evaluation IDs match, compare training game IDs **for every date block**. The difference may begin in 2022 warmup and carry through all later predictions. This is a hypothesis, not yet a measured root cause.
4. Research `fbs_phase3_increment.walk_forward()` standardizes each C2 training feature with its block-specific training mean and sample SD, then applies that same transform to the scoring block. Research `fit_offset_logistic()` penalizes coefficients as `ridge * sum(beta[1:] ** 2)` and its gradient adds `2 * ridge * beta[1:]`.
5. Production `fbs_model_service.fit()` feeds C2 unstandardized columns to its independent `_fit_offset_logistic()`, which uses `0.5 * ridge * sum(beta[1:] ** 2)`, gradient `ridge * beta[1:]`, and different optimization convergence conditions. Both **C2's scaling and penalty objective** are different. Fixing only z-scores will not reproduce research C2.
6. Research **G2h already standardizes internally** in `fbs_phase3_hierarchical.HierarchicalLogistic.fit()`; this same class is used in production. Raw-versus-standardized C2 fitting does not explain G2h differences. Prove input training cohort and feature values, plus model-object diagnostics, before modifying G2h.
7. The source writer imports its Phase 1 baseline module from `/root/lp-fbs-audit/backend`; production uses `backend/fbs_game_winner_baseline.py`. Existing G2 parity is reported exact. Preserve the copied research implementations and compare immutable SHAs for all modules rather than changing baseline behavior.
8. The stored parity gate and T-90 lock safeguard are the right behavior for now. The recent push to `dev` did not validate C2/G2h; do not portray it as a production promotion.

## Experiments to run in this order, without changing the model or gate

### A. Recover the full original research lineage

Confirm the following *existing* files and record their hashes and sizes. Never invent a missing file:

- `/root/lp-fbs-archive/backend/fbs_phase3_increment_g.py`
- `/root/lp-fbs-archive/backend/fbs_phase3_increment.py`
- `/root/lp-fbs-archive/backend/fbs_phase3_hierarchical.py`
- `/root/lp-fbs-archive/research/fbs/phase3/game_features.csv`
- `/root/lp-fbs-archive/research/fbs/phase3/game_features_c.csv`
- `/root/lp-fbs-archive/research/fbs/phase3-g/forecasts_walk_forward.csv`
- `/root/fbs-data/frame.parquet` and `/root/fbs-data/parity/wf_research.csv` if they still exist.

Run `scripts/prior_art.py` and read `AGENTS.md` plus the matching rules for measurements, falsification and data provenance. Prefer an **unmodified research worktree** for the first replay.

Record whether the working tree files match their frozen commit SHAs. Clarify whether `/root/fbs-data/parity/wf_research.csv` is a byte-identical copy of the research `phase3-g/forecasts_walk_forward.csv`, a subset, or an independently created reference. Compare columns, row IDs and prediction fields.

### B. Prove the *training* cohort, not only the test cohort

Starting from the full Phase 1 event frame, reconstruct the research frame exactly as the source writer does, including the `epa_diff` filter. Make an ID-only diff to the current `service.build_frame()` output, by season and by exact UTC date-block cutoff. At minimum record:

- count of all rows by season **before** and **after** `epa_diff` eligibility;
- IDs of excluded rows (and their season/date);
- first 2023 scoring date's **train-set** IDs and count in research vs production;
- per-block sorted `(game_id, y, p_g2)` SHA-256 and `FEATURE_NAMES_C` value hashes;
- whether changed training-row membership explains the first date-block forecast differences.

Do not infer equivalence from identical aggregate Brier, 2,397 test IDs, or a 28-game feature discrepancy.

### C. Reproduce research C2 using the **same writer and estimator**

Run the committed `fbs_phase3_increment_g.py` against the pinned archive and cached phase3 features in an isolated scratch output directory. Verify its per-game C2 (and G2h) probabilities against the originally committed `phase3-g/forecasts_walk_forward.csv`, with max absolute row difference and counts above 1e-6.

Only after that, compare production's current C2 predictor. Test the exact research transformation and penalty (including solver tolerances) **as a candidate repair on a separate branch**, not as a live replacement. Freeze and reuse each training block's `mu`, `sd`, coefficients and G2 offset. Avoid leakage from test-block data when computing scaler parameters.

### D. Reproduce G2h separately

G2h is already internally standardized. If it still diverges after the research cohort is reconstructed, compare at the **first diverging date block**:

- exact `HierarchicalLogistic` source SHA and constants `LAM_TEAM=9`, `LAM_CONF=156`, `RIDGE=1`;
- `n_train`, sorted team-season keys, conference keys, `feature_cols` order, each `mu`/`sd`, `p_g2` and `y`;
- optimizer objective, initial state, convergence and max gradient; the resulting coefficient and per-team/conference effects;
- the test block's `home_team_id`, `away_team_id`, `home_conference`, `away_conference`.

If the original source and frozen data still cannot reproduce the ledger, report **evidence invalidated or provenance missing**, not an invented passing certificate. Do not recalibrate to match the ledger.

### E. Outcome and next action

| Evidence | Decision |
|---|---|
| Original research run reproduces per-game C2 and G2h, including 2025 holdout | Implement the exact same frozen research estimators/preprocessing in production; validate forthcoming fixtures and retest parity |
| Research reproduces but production doesn't | Repair production only; keep the adopted research verdict unchanged |
| Research itself fails from exact pinned inputs or provenance is irrecoverable | Keep locks blocked, invalidate claims dependent on missing reproducibility, and run a **new preregistered** chronological benchmark on the complete, correct population |
| Parity passes, but prospective schedule / lock / grading / QA fails | Keep locks blocked until operational acceptance is complete |

## Separate operational blockers

- `dev` has received `f465af89`; the local server is not necessarily running that commit. Do not restart a server or touch `:3096` without explicit owner approval under `AGENTS.md`.
- Do not schedule T-90 jobs without explicit owner approval. Only after parity and verification, request a documented cadence and record missed windows.
- Historical midnight-UTC rows remain **legacy**, including the three potentially genuine pre-kickoff rows. Do not retroactively promote to official performance. A separate forensic label may state `pre-kickoff-creation-verified, historical-time-unverified` without changing their eligibility.
- Grading still needs an official-final-status guard, neutral-site test fixtures, and season-aware navigation.

**Deliverable:** a short `RESULT-ncaaf-parity-forensics.md` with first divergence, game IDs and training-row hashes, exact module hashes, independent research reproduction, max per-row differences for all three models, and a PASS/FAIL verdict. Keep all locks blocked on failure.
