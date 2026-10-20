# NCAAF C2 / G2h parity forensics: result (2026-10-20)

**Status.** Research diagnosis, committed on `research/ncaaf-parity-forensics-2026-10-20`. Locks stay blocked. No parity certificate was written, and nothing was started, scheduled, merged to `dev`, or changed in production. The candidate repair lives on `candidate/ncaaf-parity-repair-2026-10-20` (`54800dad`), which is not merged or enabled.

Reproduce everything with `research/fbs/forensics/run_all.sh`. Its manifest is `research/fbs/forensics/out/MANIFEST.tsv`.

## Verdict

| Model | Frozen research reproduces the committed artifact | Production as written: parity gate, 2023–25 | First divergent block | Max per-game difference, 2023–25 | Candidate repair |
|---|---|---|---|---|---|
| G2 | exact (0) | PASS (0) | none | 0 | not changed |
| C2 | PASS, 4.4e-16 | **FAIL**: 2,397 of 2,397 rows, max 0.19563 | 2022-09-25 (cutoff), n_train 201 | 0.196 gate; 0.227 forecasting path | PASS: gate 0.0; path 3.3e-16 |
| G2h | PASS, 1.7e-8 | **FAIL**: 2,397 of 2,397 rows, max 0.18841 | 2022-09-25 (cutoff), n_train 201 | 0.188 gate and path | PASS: gate 1.5e-8; path 1.5e-8 |

**Final parity verdict, production as written: FAIL for C2 and G2h.** The research reproduction itself passes, to 1.7e-8 at worst, against the 1e-6 threshold, which was not changed. Locks stay blocked.

The gate and the forecasting path give different C2 numbers, because the gate calls the research walk-forward and the forecasts come from `service.fit`/`predict` (see §5).

## 1. Lineage

- The writer is `backend/fbs_phase3_increment_g.py`, committed at `88573876` (2026-10-18) on `feat/fbs-archive`. Nothing has changed it since. Its frozen inputs and outputs are at that commit too (hashes in `out/MANIFEST.tsv`).
- `/root/fbs-data/parity/wf_research.csv` is **byte-identical** to `research/fbs/phase3-g/forecasts_walk_forward.csv` at `88573876` (sha256 `8ec54a98…`). It is the writer's output, not an independent reference.
- Replayed unchanged from a detached worktree at `88573876`, the writer reproduces every committed artifact. Both replays are numerically identical (`asis` uses the writer's default `lp-fbs-audit` baseline, `pinned` uses the frozen baseline).
  - Walk-forward: C2 4.4e-16, G2h 1.7e-8, G1 8.9e-9, G2 0.
  - 2025 holdout: G2h 1.1e-13, C2 4.4e-16.
  - Metrics and paired comparisons: max numeric difference 3.8e-10.
  - Not reproduced: `gates.csv`. The writer writes it only with `--primary`, which I did not run.
- The frozen research modules are byte-identical in production. The exception is `fbs_model_service.py`, which is the production forecaster. The two baseline copies differ (`lp-fbs-audit` `08e9f364…`, frozen `b52c1d16…`), but G2 and every other output are identical under either. The writer's import path, which picks up the audit worktree first, is an environmental dependency I left alone.

**Corrections to earlier statements.**
1. I said no ledger writer existed in any worktree. That was wrong. I searched for the output filename, not the writer. The writer is `fbs_phase3_increment_g.py` at `88573876`.
2. I said production features were identical to the research features. I compared against `/root/fbs-data/frame.parquet`, which is a production-built frame. Against the committed `game_features_c.csv`, production differs on every scored row with drive data (3,474 of 3,474).
3. The handoff attributed the 28 discrepant rows to a drive-feature rebuild on 50 games. The 28 come from the epa population rule (§2). The feature divergence is much larger (§3).

## 2. Population and the epa filter

- Pre-filter: 3,524 rows (2022: 776, 2023: 792, 2024: 798, 2025: 808, 2026: 350).
- Only one row has a null adopted `epa_diff`: game `401778314`, 2025-12-26, Minnesota v New Mexico, with no drive data. The writer filters it out after the Elo forecast, leaving 3,523 games and 2,397 scored in 2023–25.
- Game IDs, dates, outcomes, G2 probabilities and conferences are identical between research and production, with zero mismatches.
- The excluded game feeds the Elo history but is not in the frame. Adding it back changes **28 scored 2025 predictions** for C2 (max 2.75e-4) and **28 for G2h** (max 5.04e-4), all dated 2025-12-27 to 2026-01-20. Those 28 rows are the handoff's number.
- Training membership is identical in all 376 blocks when the frame is restricted to the writer's population.

## 3. Drive features: the root cause

- The committed `game_features_c.csv` equals the frozen `build_features_c` run over **2014–2026**: exact, max difference 0 across 10,804 games.
- Production's `build_frame` loads only the scored seasons, **2022–2026**. Rebuilt that way, the frozen code matches production to about 4e-15, so production's features are exactly "same code, shorter history".
- The features are as-of team ratings, so earlier seasons change them. Max differences for 2022–2026 only: points per drive 2.96, turnovers 0.126, start field position 37.7, red zone TD rate 0.606, third-down rate 0.088, explosive drives 0.312, penalties per play 0.060.
- Not a play-by-play change. The PBP files were written 2026-10-18 11:53, before the feature CSV (13:32).

## 4. First divergent block, and parameters

There are 376 date blocks. Training membership and `n_train` are identical in every block. The feature values differ in every non-empty training block, starting in 2022-08-28 (n_train 4). Those early differences have no effect until a model is fitted.

**First fitted block: 2022-09-25** (cutoff 2022-09-25, n_train 201, 9 test games, first game `401403997`). Both models diverge there. Divergent rows: 3,322 of 3,523, covering every season from 2022.

| Model | research prob | production prob | Δ at first game | max Δ in block |
|---|---|---|---|---|
| C2 | 0.257713 | 0.332728 | 0.0750 | 0.1670 |
| G2h | 0.249132 | 0.322911 | 0.0738 | 0.1651 |

**C2 decomposition at 2022-09-25.** Each row changes one factor relative to the reference (research estimator on research features, which matches the committed output to 5.6e-17).

| Case | max Δp vs reference |
|---|---|
| Research estimator, production features | 0.1670 |
| Research objective, raw features (no standardization), research features | 0.0853 |
| Production estimator as written, research features | 0.0766 |
| Production estimator as written, production features | 0.1619 |

Parameters for the reference (research estimator, research features). Coefficients are intercept then seven standardized features, in the order `points_per_drive_diff`, `turnovers_per_drive_diff`, `start_field_position_diff`, `rz_td_rate_diff`, `third_down_rate_diff`, `explosive_drive_rate_diff`, `penalties_per_play_diff`:

- β = [0.413201, 0.571142, 0.078721, −0.148308, 0.053008, 0.220983, 0.232878, 0.078414]
- Training mean for `start_field_position_diff` = −0.356; sd = 9.601.

With production features: mean = 0.851, sd = 13.916. The production estimator on raw features gives β = [0.309115, 0.940059, 0.063449, −0.002815, 0.236895, 0.303359, −0.187074, 0.222565]. Full values are in `out/decompose_2022-2022-09-25.json`.

**G2h at 2022-09-25.** The same class is used on both sides, so the difference comes only from the inputs. The research fit reproduces the committed output (4.2e-9). The production fit reproduces its own block file (1.1e-16). Converged in both cases (45 and 43 iterations; grad norms 4.8e-7 and 3.9e-7). Team effects `u` differ by up to 0.067, conference effects `m` by up to 0.0027. Feature means and sds differ as in §3.

## 5. Estimators, and a gap in the gate

**C2, research estimator** (`fbs_phase3_increment.walk_forward`). Each feature is standardized by the block's training mean and sample sd. The fit is a ridge logistic with the G2 logit as a fixed offset: penalty `ridge·Σβ²` (gradient `2·ridge·β`), eps 1e-9, scipy L-BFGS-B defaults.

**C2, production forecasting path** (`fbs_model_service.fit`, as written before the candidate). Raw features with no standardization, penalty `0.5·ridge·Σβ²` (gradient `ridge·β`), eps 1e-12, and L-BFGS-B with `maxiter=500` and `gtol=1e-6`. This is a different estimator, not the adopted C2.

**The gate does not test that path.** `runner.check_parity` calls the research `walk_forward` and `hierarchical_walk_forward`, not `service.fit`/`predict`. So the gate never exercised production's C2 forecasting estimator, even though it reports C2 as the model under test. This is a gap in the gate itself, separate from the data.

**2×2 through the forecasting path** (`service.fit` and `service.predict` at every block cutoff, population 3,523, 2023–25 rows):

| Inputs | C2 as written | C2 research-standardized candidate | G2h as written |
|---|---|---|---|
| Research (committed) | 0.0889, 2,397 of 2,397 rows over 1e-6 | 3.3e-16 | 1.7e-8, 0 rows |
| Production, before the fix | 0.227, 2,397 of 2,397 | 0.196 | 0.188, 2,397 of 2,397 |
| Production, after the candidate | 3.3e-16 | 3.3e-16 | 1.5e-8, 0 rows |

So G2h's forecasting code is correct; its gap is entirely the feature inputs. C2's forecasting code is wrong on its own, and the research estimator fixes it.

## 6. Candidate repair (`candidate/ncaaf-parity-repair-2026-10-20`, `54800dad`)

Three changes to `backend/fbs_model_service.py`, plus one regression test:

1. Drive features over seasons 2014 onward, failing loudly if any play-by-play file is missing. Matches the committed features exactly.
2. The writer's population, enforced by pinning game `401778314`, applied after the Elo forecast as the writer does.
3. C2 in the forecasting path uses the research estimator (`fit_c2`/`predict_c2`), and the old raw-feature objective is removed.

The new test checks `fit_c2`/`predict_c2` against the research `walk_forward` on a synthetic block: 23 of 23 FBS tests pass.

With the rebuilt production frame, the production gate reports `ok: true`, with G2 0, C2 0.0 and G2h 1.5e-8 on 2,397 games. As noted in §5, that gate runs the research harness. The forecasting path is verified separately by the 2×2 in §5.

The candidate changes production C2 and G2h forecasts. It is not merged, enabled or certified. Adopting it is the owner's decision.

## 7. What remains unresolved

1. **Decision: adopt the candidate.** It fixes the features and the C2 estimator, and it matches the adopted research on every test I ran. Adopting it changes production forecasts, so it needs an explicit owner decision.
2. **Epa population rule.** The exclusion is pinned by game ID. A production implementation of the rule requires the phase-(b) EP pipeline (`fbs_phase3_features.py`), which I did not port.
3. **The gate.** `check_parity` should exercise `service.fit`/`predict`, not the research harness. I did not change gate semantics or the threshold.
4. **`gates.csv`** is not reproduced. It needs the writer's `--primary` run.
5. **Floating point.** The replay matches to 1.7e-8, not byte for byte. The gate threshold of 1e-6 is unchanged.
6. **Writer import path.** The writer's default `sys.path` picks up `lp-fbs-audit`. The outputs are unaffected, but the dependency is environmental.
7. **Not done:** a dry run of the candidate against the live ESPN slate, visual QA, the neutral-site path (none in the current window), grading guards, a T-90 scheduler, and the handling of legacy rows.
8. **Legacy rows.** The three late, midnight-UTC rows (games 401871055, 401871069, 401871092) were created at 21:26Z, before their real 23:00Z and 23:30Z kickoffs. That is evidence for "created before kickoff", and not evidence of a valid historical lock. They stay legacy and excluded.

## 8. Operational status

- Locks blocked. The gate was run only in scratch (`out/gate_fix.json`, `out/gate_candidate.json`), with no certificate written.
- Nothing started or restarted, no scheduler, no merge to `dev`, nothing touched in production.
- Branches: the research branch was committed locally and not pushed. The candidate branch was committed locally and not pushed.
