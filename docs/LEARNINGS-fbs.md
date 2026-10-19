# FBS model learnings

The single record of gate testing, experiment results and go/no-go calls for the FBS track.
Append-only. A result that fails is still a result; do not delete it, supersede it.

**Ladder:** G0 base rate · G1 Elo · G2 Elo + tuned prior · G3 margin-aware · B2/C2 features ·
G2h corrected hyperparameters.

## Decision register

| Item | Result | Verdict |
| --- | --- | --- |
| Warm-up depth beyond 5 seasons | 0.2133 → 0.2103, closes 18.9% of gap to Basic Elo | **NO-GO** — stop adding archive history |
| G3 margin-aware rating | 0.2155 vs G2 0.2133, Δ +0.0023 [−0.0023, +0.0065] | **NO-GO** |
| Phase 4 score-based adoption | G-CAL failed, total-PIT p=0.0016 | **NOT_ADOPTED** |
| Phase 4b conditional-mean (H0b) | G-CAL failed on 50% coverage 0.5561 vs ±0.05 | **NOT_ADOPTED** |
| Phase 5 play-by-play simulator | not started | awaiting owner decision |

## Entries

### 2026-10-18 — Elo warm-up depth is not what separates us from published Basic Elo
**Learned:** holding G2 fixed and varying only the warm-up start (2022 → 2004) moves Brier
0.2133 → 0.2103, Δ −0.0030 [−0.0041, −0.0018] on the same 2,398 games. It flattens at 13
seasons and closes only 18.9% of the gap to published Basic Elo (0.1976), leaving 0.01271.
**Evidence:** `RESULT-FBS-WARMUP-ABLATION-20261018.md`, commit `4f20e1fa`; arm A reproduces
G2 at 0.213269 exactly.
**Consequence:** five warm-up seasons is right. Do not spend more effort on archive history as
a route to the baseline; the remaining gap is model, features or population.

### 2026-10-18 — A margin-aware rating does not beat plain Elo
**Learned:** G3 scored 0.2155 against G2's 0.2133. Paired Δ +0.0023, interval
[−0.0023, +0.0065] spans zero.
**Evidence:** `RESULT-FBS-GAME-WINNERS-20261018.md`, commit `4a59cb6e`.
**Consequence:** keep G0–G2 as references. Do not re-run G3 as untested, and do not add team
stats on the assumption that margin information must help.

### 2026-10-18 — Phase 4 refused adoption despite the largest CRPS gain
**Learned:** G-SAMPLE, G-DIST (−2.3257 [−2.6051, −2.0475]), G-SPREAD and G-TOTAL passed, but
G-CAL failed on a total-PIT KS p of 0.0016.
**Evidence:** `RESULT-FBS-PHASE4-SCORES-20261018.md`.
**Consequence:** a model that wins on proper score but fails calibration is not shipped. The
gate order is the product decision, not a formality.

### 2026-10-19 — The total-PIT failure was conditional mean bias, not shape
**Learned:** observed-on-predicted slope 0.5032 ± 0.0691 walk-forward, 0.5173 on holdout; the
predicted total is roughly twice as variable as the data supports. Conditional mean PIT runs
0.648 (under 40 predicted) to 0.404 (over 70), same ordering every season. Marginal PIT looked
near-uniform only because the two ends cancel. Secondary high-μ over-dispersion (RMSE/SD 0.91);
tail above 110 was 1.11% (26.6 games) against 0.08% observed.
**Evidence:** total-PIT diagnosis at `0bc000ba`; n=2,397, bias −0.041, pred 53.0787 / obs 53.1197.
**Consequence:** the defect is conditional mean, so the correction is an OLS slope fitted on
prior seasons only — not a distribution reshape and not a refit.

### 2026-10-19 — Phase 4b: the correction worked but still fails one gate clause
**Learned:** H0b moved total-PIT from 0.0016 to 0.0869 and recovered slope to 0.9043
[0.7800, 1.0285], which contains 1.0. It still fails G-CAL on one clause: walk-forward 50%
central coverage 0.5561 against a ±0.05 tolerance. CRPS improved 9.4611 → 9.13713.
**Evidence:** `feat/fbs-archive` `4a725a1e`, close-out `5397c0dc`; reproduction gate rebuilt
2023 predictions from frozen block parameters to max |diff| 6.963e-13 against a 1e-6 gate.
**Consequence:** NOT_ADOPTED stands. Shortest-50 coverage (0.4977) and central-50 (0.5561)
disagree, so "coverage at 50%" must always name which interval is meant.

### 2026-10-19 — A paired interval cannot be reproduced from a description
**Learned:** the F3 paired interval is −0.323993 [−0.433123, −0.213093], 65 blocks, n=2,397.
A competing figure (−0.4590, −0.1994) came from a differently-keyed block bootstrap and does
not reproduce.
**Evidence:** recomputed with the harness's own `block_bootstrap`, game-weighted UTC-week
blocks, 2,000 reps, seed 20261017; stable across seeds.
**Consequence:** a brief that requests a bootstrap must name the code path, block key and
seed. "Block bootstrap" alone is not a specification.
