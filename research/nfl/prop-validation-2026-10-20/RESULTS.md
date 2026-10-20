# NFL player-market distribution validation — 2026-10-20

Research only. Per-market verdicts on whether a market's predictive distribution is good enough
to show next to a sportsbook line. **One market does not approve another.** No serving code, model
math, gate, threshold or production database was changed.

Reproduce every number with:

```bash
cd /root/lp-nfl-props
python3 research/nfl/prop-validation-2026-10-20/run_validation.py
```

The 2025 walk-forward pass is deterministic and takes about 17 minutes; it is cached in
`walk_forward_2025.json` so a re-run of the 2026 analysis is under a minute. Recompute it with
`--force-2025`. `--skip-2025` runs only the 2026 capture artifact.

Outputs in this directory: `metrics_2026.json`, `walk_forward_2025.json`,
`reproducibility_2026.json`, `per_market_coverage.csv`, `frozen_predictions_2026.csv`,
`manifest.json`.

## Splits, stated explicitly

| Window | Population | Fit / tune | Scored | Purpose |
|---|---|---|---|---|
| **A. 2026 capture backfill** | frozen 2026 weeks 4–5 sportsbook lines, 12,783 gradeable paired line-items, 359 player-games, 6 markets | v2 constants frozen on 2024; the forward Platt map is fit on the weeks *before* the served week (week 4 map on weeks 2–3; week 5 map on weeks 2–4) | 2026 weeks 4–5 | market comparison, distribution integrity, reproducibility |
| **B. 2025 walk-forward** | RB/WR/TE weeks 3–18 (3,945 player-games) and quarterbacks (403 player-games), every market | v2 constants and `K_T_ATT=4.0` frozen on 2024 | 2025 weeks 3–18 | distribution integrity and baselines for the markets that have no 2026 sportsbook lines |

Nothing is retuned on a scored window. Window A is the only one with prices.

## 1. Reproducibility — the finding comes first

The frozen 2026 capture artifact was re-derived from the frozen **input snapshot** (177,371
database rows) plus the committed engine. The four engine source files are byte-identical to the
hashes recorded in the capture manifest:

```
backend/nfl_player_projection_v2.py      3286521b…  match
backend/nfl_player_projections_job.py    d5f52ac7…  match
backend/nfl_prop_calibration.py          e70d6c8d…  match
backend/routers/players/nfl_projections.py d2e98bee…  match
```

**Result: 870 of 870 frozen player-game-market PMFs reproduce byte-for-byte** (integer PMF and the
continuous-draw P(over), tolerance 1e-12), across **389 player-games**. Zero mismatches.

| Market | Re-derived / tested |
|---|---:|
| receiving yards | 338 / 338 |
| receptions | 332 / 332 |
| pass attempts | 50 / 50 |
| pass completions | 50 / 50 |
| passing yards | 50 / 50 |
| passing touchdowns | 50 / 50 |

The artifact SHA-256 is `5804a506…` and the input snapshot `6c9395b8…`, both matching the manifest.
This is the first market family in the NFL track where the frozen distribution, not just a point
mean, has been reproduced exactly.

## 2. Verdict table

Verdict order: reproducibility, then distribution integrity, then the market comparison.

| Market | Verdict | Load-bearing numbers |
|---|---|---|
| **Passing attempts** | **INCONCLUSIVE** | reproducible 50/50; 2026 coverage 58/84/88% (nominal 50/80/90), variance ratio 0.93; v2-Platt vs market Brier 0.2499 vs 0.2495, delta +0.0003 [−0.0071, +0.0077] (spans zero) |
| **Pass completions** | **INCONCLUSIVE** | reproducible 50/50; 2026 coverage 62/86/90%, variance ratio 0.93; Brier 0.2512 vs 0.2493, delta +0.0019 [−0.0082, +0.0118] (spans zero) |
| **Passing yards** | **INCONCLUSIVE** | reproducible 50/50; 2026 coverage 52/86/90%, variance ratio 0.87; Brier 0.2522 vs 0.2449, delta +0.0073 [−0.0014, +0.0157] (spans zero, point estimate worse) |
| **Receptions** | **INCONCLUSIVE** | reproducible 332/332; 2026 coverage 63.3/86.9/92.1%, variance ratio 1.31; Brier 0.2475 vs 0.2445, delta +0.0030 [−0.0024, +0.0081] (spans zero) |
| **Receiving yards** | **INCONCLUSIVE** | reproducible 338/338; 2026 coverage 51.1/80.3/87.4%, variance ratio 1.40; Brier 0.2487 vs 0.2480, delta +0.0006 [−0.0020, +0.0033] (spans zero) |
| **Passing touchdowns** | **NOT_ADOPTED** | reproducible 50/50 but the distribution fails: 2026 coverage **98% at nominal 80%**, **100% at nominal 90%**, variance ratio **0.58** (underdispersed). The Brier tie (0.2433 vs 0.2436) does not rescue a distribution that is too wide |
| **Receiving touchdowns** | **NOT_ADOPTED** | no 2026 lines; 2025 walk-forward coverage **95.6% at nominal 80%** on 3,936 player-games |
| **Targets** | **NO_PRICE_ARCHIVE** | distribution is in the engine and reproducible in principle; the capture artifact has **no targets rows**. 2025 coverage 71.6/91.3/95.6%, variance ratio 1.51 |
| **Rushing yards** | **NOT_ADOPTED** | **no predictive distribution exists in the committed v2 engine** (point means only). 2025 point MAE 6.512 on 3,945 player-games |
| **Carries** | **NOT_ADOPTED** | no predictive distribution; 2025 point MAE 1.153 on 3,945 player-games. The reported v1–v4 rushing-carries candidates are not reproducible on this branch |
| **Rushing touchdowns** | **NOT_ADOPTED** | no predictive distribution; 2025 point MAE 0.112 on 3,945 player-games |

No market is `ADOPT_CANDIDATE`. No market is `NOT_REPRODUCIBLE`; every market whose distribution
exists in the committed engine re-derived exactly.

## 3. Distribution integrity

`cov50/80/90` is the share of actuals inside the central 50/80/90% interval; nominal is 50/80/90.
The variance ratio is observed variance divided by the mean predictive variance (a pooled measure:
it also carries between-player-game heterogeneity, so the PIT and the coverage are the primary
evidence). A well-calibrated distribution has coverage near nominal and a PIT histogram flat near
10% per decile.

### Window A — 2026 weeks 4–5 (frozen PMFs)

| Market (stat) | n | cov50 | cov80 | cov90 | var ratio | PIT mean | log score | CRPS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| pass attempts | 50 | 58.0 | 84.0 | 88.0 | 0.93 | 0.578 | 3.703 | 5.552 |
| pass completions | 50 | 62.0 | 86.0 | 90.0 | 0.93 | 0.553 | 3.371 | 3.890 |
| passing yards | 50 | 52.0 | 86.0 | 90.0 | 0.87 | 0.549 | 5.999 | 48.953 |
| receiving yards | 309 | 51.1 | 80.3 | 87.4 | 1.40 | 0.621 | 4.951 | 17.924 |
| receptions | 305 | 63.3 | 86.9 | 92.1 | 1.31 | 0.624 | 2.218 | 1.300 |
| **passing TDs** | 50 | **84.0** | **98.0** | **100.0** | **0.58** | 0.505 | 1.416 | 0.523 |

### Window B — 2025 weeks 3–18 (walk-forward, constants frozen on 2024)

| Market (stat) | n | cov50 | cov80 | cov90 | var ratio | log score | CRPS |
|---|---:|---:|---:|---:|---:|---:|---:|
| pass attempts | 403 | 62.0 | 86.4 | 92.8 | 0.74 | 3.832 | 4.906 |
| pass completions | 403 | 60.8 | 88.1 | 93.5 | 0.72 | 3.383 | 3.423 |
| passing yards | 403 | 57.6 | 87.1 | 93.8 | 0.71 | 6.352 | 42.940 |
| passing TDs | 403 | 71.5 | 94.8 | 98.3 | 0.89 | 1.583 | 0.657 |
| targets | 3,936 | 71.6 | 91.3 | 95.6 | 1.51 | 1.984 | 1.130 |
| receptions | 3,936 | 75.2 | 91.9 | 96.2 | 1.38 | 1.710 | 0.856 |
| receiving yards | 3,936 | 64.0 | 87.1 | 92.8 | 1.41 | 3.965 | 11.341 |
| receiving TDs | 3,936 | 88.7 | 95.6 | 98.0 | 1.21 | 0.423 | 0.129 |
| carries | 3,945 | — | — | — | — | — | — |
| rushing yards | 3,945 | — | — | — | — | — | — |
| rushing TDs | 3,945 | — | — | — | — | — | — |

**The underdispersion is real and consistent, not a small-sample artifact.** Receiving markets
carry variance ratios of 1.2–1.5 across both windows; passing markets are over-dispersed on the
variance-ratio measure (0.7–0.9) yet still over-cover at 80% (86–95%), which is what the PIT
histogram shows: pass attempts in 2026, for example, has only 6% of mass in the lowest PIT decile
and 16% in the fifth. Passing TDs at 2026 weeks 4–5 (n=50) is the extreme case; the 2025 window
confirms the direction at coverage 94.8% at nominal 80%.

No fix (mixture, negative binomial, quantile mapping, conformal widening) is adopted here. The
task accepts a fix only if it improves log score / CRPS **and** coverage together on held-out
weeks; that is a separate pre-registered experiment.

## 4. Score against real baselines (identical player-games)

Both baselines are built from only the games before the target week, so they respect the same
walk-forward split. `t5` is the trailing-5-game empirical distribution; `league` is the
position-level league distribution.

### Window B (2025), log score — lower is better

| Market | model | trailing-5 | position-league |
|---|---:|---:|---:|
| pass attempts | **3.832** | 7.447 | 3.664 |
| pass completions | 3.383 | 7.150 | **3.308** |
| passing yards | 6.352 | 8.958 | **6.104** |
| passing TDs | 1.583 | 4.292 | **1.551** |
| targets | **1.984** | 4.690 | 2.250 |
| receptions | **1.710** | 4.202 | 2.093 |
| receiving yards | **3.965** | 6.859 | 4.154 |
| receiving TDs | **0.423** | 1.406 | 0.464 |

The model beats the trailing-5 mean everywhere on log score. Against the position-level league
distribution it is essentially level: it wins targets, receptions, receiving yards and receiving
TDs, and loses attempts, completions, passing yards and passing TDs by a small margin.

### Window A (2026), CRPS — lower is better

| Market | model | trailing-5 | position-league |
|---|---:|---:|---:|
| pass attempts | 5.552 | **4.767** | 6.408 |
| pass completions | 3.890 | **3.203** | 4.344 |
| passing yards | **48.953** | 49.300 | 54.564 |
| passing TDs | **0.523** | 0.583 | 0.572 |
| receptions | 1.300 | **1.078** | 1.372 |
| receiving yards | 17.924 | **12.809** | 17.933 |

**This is the tension the log score hides.** On 2026, the trailing-5 empirical spread beats the
model on CRPS for attempts, completions, receptions and receiving yards — exactly the markets whose
variance ratio says the model is underdispersed. The model still wins on log score because the
trailing-5 empirical PMF assigns zero (clipped) probability to outcomes it has not seen. So a wider
distribution is the plausible direction of a fix, but the log-score/CRPS split means widening alone
is not automatically an improvement; it has to be tested on held-out weeks.

## 5. Market comparison where prices exist (Window A only)

De-vigged from the frozen two-sided American odds (proportional de-vig), scored on the identical
12,783 gradeable paired line-items, paired and clustered by player-game.

| Market | items | player-games | v2 raw Brier | v2-Platt Brier | market Brier | Platt − market [95% CI] |
|---|---:|---:|---:|---:|---:|---|
| pass attempts | 356 | 50 | 0.2577 | 0.2499 | 0.2495 | +0.0003 [−0.0071, +0.0077] |
| pass completions | 304 | 50 | 0.2755 | 0.2512 | 0.2493 | +0.0019 [−0.0082, +0.0118] |
| passing TDs | 313 | 50 | 0.2308 | 0.2433 | 0.2436 | −0.0003 [−0.0212, +0.0202] |
| passing yards | 2,576 | 50 | 0.2804 | 0.2522 | 0.2449 | +0.0073 [−0.0014, +0.0157] |
| receiving yards | 7,232 | 309 | 0.2650 | 0.2487 | 0.2480 | +0.0006 [−0.0020, +0.0033] |
| receptions | 2,002 | 305 | 0.2745 | 0.2475 | 0.2445 | +0.0030 [−0.0024, +0.0081] |
| **overall** | **12,783** | **359** | **0.2688** | **0.2492** | **0.2468** | **+0.0024 [−0.0006, +0.0051]** |

Raw v2 is worse than the de-vigged market overall with an interval that excludes zero
(+0.0220 [+0.0060, +0.0374]). Platt removes most of that and lands level with the market on this
population: the overall interval spans zero, as do all six per-market intervals. **This is a
null result for a market edge, not evidence of one**, and it does not reproduce the significance of
the earlier 24,558-item aggregate (which reported +0.00227 ± 0.00222) because the capture
population is smaller and different. The point estimates still favour the market on receiving
yards, receptions, passing yards and completions.

The `p_over_served_4dp` field is a hazard: it equals rounded raw v2 on 26,638/26,638 rows but the
rows are labelled `v2-platt`. A consumer must read `p_over_v2_platt` explicitly for this version.

## 6. Capture-harness assessment (separate result)

Source: `/root/lp-nfl-capture/research/nfl/prospective-capture` at `5202d247`.

**Can it run before kickoff today? No.** `capture_nfl_props.py --mode live` is implemented and
fail-closed: it aborts rather than writing a forecast if capture, cutoff and serialization do not
all finish before the earliest kickoff. But **no scheduler job or service is installed**, no live
run has been executed, and no live file exists. Live readiness is **NOT READY**.

**Does it freeze the exact PMF, parameters and inputs? Yes.** The backfill artifact stores, per
side row, the integer-support PMF with mass/tail/truncation metadata, the explicit
`p_over_raw` and `p_over_v2_platt`, the quote, the outcome and settlement states separately, and
source/input/parameter SHA-256 hashes. Route parity was verified at 1e-9 for six representative
market inputs, and the four engine source hashes still match the manifest on this branch. Its
provenance says 4,000 seeded draws (`seed=7`) and the `nfl_player_projections_job.project_week`
means.

**Does it carry settlement rules? Yes.** `outcome_state` (resolved / true_zero / dnp / missing /
unresolved / void) and `settlement_state` (win / loss / push / void / dnp / missing / unresolved)
are distinct; the grade script rejects unpaired sides, non-complementary win/loss settlements,
in-play quotes, and mismatched de-vig, and cross-checks the book's own result.

**What is missing for live use:**

1. A pre-kickoff scheduler and service, plus one prospective run that proves cutoff/lock ordering.
2. Durable append-only forecast storage (the artifacts are local worktree files).
3. An authorized production source and storage target (only the dev DB was read, read-only).
4. An unambiguous live model-version → probability-field mapping (`p_over_served_4dp` is raw v2
   while every row is labelled `v2-platt`).
5. A continuous CDF representation alongside the integerised PMF; the integer PMF and the
   continuous route probability differ by +0.00386 on average on yardage markets.

Every one of the 26,638 backfill side rows is `capture_mode=backfill` and
`cp4_evidence_eligible=false`; the pre-kickoff assertion is explicitly negative. **Backfill is not
prospective evidence and cannot pass CP4.** No scheduler was installed and no production system was
touched by this task.

## 7. What could not be measured

- **No 2026 sportsbook lines for targets, carries, rushing yards, rushing TDs or receiving TDs.**
  The capture artifact has 6 markets; the task names 8 families. The market comparison for those
  families is impossible from this artifact, so their verdicts come from the distribution-integrity
  and 2025 walk-forward evidence.
- **No rushing predictive distribution exists in the committed v2 engine.** `eng.project` returns
  rushing means, but `simulate`/`simulate_qb` cover only receiving and passing. The v1–v4
  rushing-carries candidates are not on this branch and cannot be reproduced here. That is the
  finding for carries, rushing yards and rushing TDs, not a score.
- **No prospective (CP4) evidence exists.** The live harness has never run before kickoff.
- **The variance ratio is a pooled statistic** and carries between-player-game heterogeneity; it
  is reported because the task asks for it, beside the PIT and coverage which are per-observation.
- **The 2025 baselines lean on the live dev database** (read-only) because the frozen input snapshot
  carries only 2025–2026 logs; the engine hashes match the manifest, so the 2025 pass is
  reproducible with `run_validation.py` against that database.

## 8. Bottom line per the independent gates

- Every market whose distribution exists in the engine is **reproducible**, and the 2026 capture
  artifact is contract-quality research evidence (frozen PMF, inputs, parameters and settlement).
- **Passing touchdowns and receiving touchdowns fail distribution integrity**; **carries, rushing
  yards and rushing TDs have no distribution at all**. These are `NOT_ADOPTED` and must not be
  shown next to a line.
- **Passing attempts, completions, passing yards, receptions and receiving yards** are
  `INCONCLUSIVE`: reproducible, roughly calibrated on coverage, but no established market edge, a
  consistent underdispersion on the receiving side, and no prospective evidence. They are not
  approved. CP3 remains unmet and CP4 remains unmet.
