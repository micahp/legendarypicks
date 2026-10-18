# NFL discrete-prop evaluation recovery — 2026-10-18

**Status: partial recovery; research-only.** B0 has been regenerated and passed exact regression checks
on both seasons. v1–v4 candidate distributions are excluded from the new comparison because their exact
reproduction could not be established from the frozen artifacts. No candidate is adopted and no revised
gate is decided here.

Related records: [initial evaluation audit](DISCRETE-PROP-EVAL-20261018.md), [reusable artifact
contract](../../docs/EVAL-CONTRACT-discrete-props.md), [append-only learnings](LEARNINGS.md).

## 1. Frozen reproduction and recovery status

The rerun used a consistent SQLite backup of the live development database, opened read-only by the
recovery scripts. Snapshot SHA-256 is
`6fd3d9ab55751108ab279f91aa7130d71c52c1352f7c83de798aef7d47395b45` (3,035,688,960 bytes). It was
captured on 2026-10-18 at 17:35:57 CDT. The historical reports did not record an input-database
fingerprint or observation ledger, so the original run's exact DB snapshot and exact original row IDs
cannot be independently proven. The reconstructed populations and full-precision B0 metrics below match
the frozen summaries.

The population builder uses the frozen source code, 2025/2026 regular-season candidate rules, weeks 3–18,
and the frozen support. Reconstructed counts are 2,500 player-games across 240 games in 2025 and 489
player-games across 48 games in 2026. Dates are 2025-09-18–2026-01-04 and 2026-09-24–2026-10-15,
respectively. No fitting occurred in the B0 replay. The PMF code is analytic and deterministic; its
integer support is 0–160 with the frozen implementation's renormalization on that finite support.
The population builder was separately run from each frozen v1–v4 source commit. Every version produced
the same counts with unique `(game_id, player_id)` keys: 2,500/240 for 2025 and 489/48 for 2026.

The strict tolerance was absolute error `≤ 1e-10` for CRPS, MAE, and each central coverage statistic.
PMFs have no random step. The new PIT and bootstrap procedures are stochastic and their exact seeds are
recorded in the external manifest.

| Model / season | Population | CRPS: computed vs saved (difference) | MAE: computed vs saved (difference) | Central coverage 50 / 80 / 90 | Step 1 result |
|---|---:|---|---|---|---|
| B0 (v2–v4 reference), 2025 | 2,500 / 240 games | 2.0604865850045293 vs 2.060486585004534 (−4.88e−15) | 2.9401204678298565 vs 2.9401204678298574 (−8.88e−16) | Exact | **Recovered** |
| B0 (v2–v4 reference), 2026 | 489 / 48 games | 2.0889281365340806 vs 2.0889281365340815 (−8.88e−16) | 2.9972400182007015 vs 2.9972400182006997 (+1.78e−15) | Exact | **Recovered** |
| v1 B2, 2025 | 2,500 / 240 games | Not rerun: the committed v1 parameter file has the 2024–25 fit used for 2026, not the 2024-only fit used for 2025 | — | — | **Excluded: required fit unavailable** |
| v1 B2, 2026 | 489 / 48 games | 1.9764293719178376 vs report rounded to 1.9764 | 2.9330332185811883 vs report rounded to 2.9330 | 0.6850716 / 0.9120654 / 0.9631902; report rounds to 0.685 / 0.912 / 0.963 | **Excluded: source report lacks precision for the 1e−10 check** |
| v2 Zf, 2025 | 2,500 / 240 games | 1.8784964782186184 vs 1.8785009859351514 (−4.5077165e−6) | 2.939852187867374 vs 2.939852050429253 (+1.3743812e−7) | Exact | **Mismatch; stopped** |
| v2 Zf, 2026 | 489 / 48 games | 1.8668120622687707 vs 1.8668146076917196 (−2.5454229e−6) | 2.9959369187211826 vs 2.995937051810347 (−1.3308916e−7) | Exact | **Mismatch; stopped** |
| v3 V3, 2025 and 2026 | 2,500 / 489 | Not computed | — | — | **Excluded: saved fit omits `p_cross`, required by V3** |
| v4 V4, 2025 and 2026 | 2,500 / 489 | Not computed | — | — | **Excluded: saved fit omits `p_cross`; interpolation centers are rounded to 3 decimals** |

For v2, the replay used the four-decimal recent-form cells exactly as stored; no refit or replacement
parameter was introduced. The resulting CRPS and MAE misses exceed the tolerance, so Zf was not exported
or scored in Step 2. For v3 and v4, supplying a missing `p_cross` would require recovering an unstored
parameter or refitting; neither was done.

The v1 frozen 2026 CLI run also reproduced its **printed** B2 values, but those results document only
four-decimal CRPS/MAE and three-decimal coverage, so a strict regression check is impossible. It also
reveals why the earlier B0 figures differed across reports: v1's 2026 B0 replay uses its saved `R =
3.656999027807565` (CRPS 2.088744092896997), while the common v2–v4 B0 uses `R0 = 3.7053745466736103`
(CRPS 2.0889281365340815). The difference is the stored baseline parameter, not a changed evaluation
population. The v1 2025 B0 fit remains unavailable.

### Reproduction commands

The B0 command archives the exact v2 source commit and checks all frozen statistics before it writes any
PMF rows:

```bash
python3 research/nfl/discrete-prop-eval-2026-10-18/recover_b0_diagnostics.py \
  --db /root/lp-discrete-eval-artifacts/picks-dev-eval-recovery-20261018.sqlite3 \
  --output-dir /root/lp-discrete-eval-artifacts/recovered-b0-complete \
  --bootstrap-reps 1000 --pit-draws 100 --seed 20261018
```

The population-only check rebuilds both seasons through each v1–v4 source revision and asserts the counts
and unique player-game keys without fitting:

```bash
python3 research/nfl/discrete-prop-eval-2026-10-18/check_frozen_population.py \
  --db /root/lp-discrete-eval-artifacts/picks-dev-eval-recovery-20261018.sqlite3
```

The v2 candidate's strict replay check is:

```bash
python3 research/nfl/discrete-prop-eval-2026-10-18/check_v2_candidate_reproduction.py \
  --db /root/lp-discrete-eval-artifacts/picks-dev-eval-recovery-20261018.sqlite3 \
  --tolerance 1e-10
```

The v1 2026 check used source commit `24d793c6fc10b0a0fee53b651aa1c8771eeca6db`,
`--eval-season 2026 --fit-seasons 2024 2025 --weeks 3 18 --frozen frozen-v1.json`, and the captured
SQLite snapshot. Its exact output is in `/tmp/lp-discrete-v1-replay-2026.json`; only printed-precision
agreement is verifiable.

### Recovered B0 artifacts

The complete per-observation ledgers are outside Git, in
`/root/lp-discrete-eval-artifacts/recovered-b0-complete/`. Each gzip JSONL row carries the actual,
game/player identifiers, date, week, team/opponent, position, `m` tier, full 0–160 PMF and CDF, model
version/commit, frozen parameter-file checksum, and input snapshot checksum. The manifest records the
exact command, season counts and date ranges, source commit and engine hash, support, deterministic
reproduction statistics, bootstrap/PIT seeds, full aggregate and per-tier diagnostics, reliability bins,
and paired interval-family comparisons.

| Artifact | Rows | SHA-256 |
|---|---:|---|
| `B0-2025.jsonl.gz` | 2,500 | `2f99c2e0c0faf7be90dea8c837c6a58494f9a8783b5a18c3cb339b898c574bff` |
| `B0-2026.jsonl.gz` | 489 | `a384e7b0ec64b91534f8606a42370194ddc3870f5d7cb74219271cf816f58228` |
| `manifest-and-diagnostics.json` | — | `22fa89ee030d786442e310216c417ab71f33efc0040a22c8a9dd57b646a9cc08` |

The manifest also fingerprints the recovery script (`7744588cbfc325c4fe57ef4c59e29dc72ba5ee30ed20a90388b63b4ecb710878`)
and records the runtime (Python 3.8.10, SQLite 3.31.1).

Frozen parameter checksums: v1 `12fde4c8182b948df7305e5ecbf14bff81034d89cb108fc21dc654c136b5843b`; v2
`6c32fbaf16d6a393acbb2b03c25c8ac68ef1b713ac0af082a7f1709c6ee56917`; v3
`42b3f20ae4135986c4027a6ff62effae1ee4bf40e940d89f9accc5841c0f3960`; v4
`d4a1fdfe3c6c57f167c7be4f69d6a56087e7f3c263d429b9f6e2904f53016603`.

## 2. Diagnostic bundle for recovered B0

All uncertainty intervals below are 95% percentile intervals from game-cluster bootstrap resampling;
all player rows within a selected game remain together. There are 1,000 replicates. The manifest records
the exact seed used for each season/stratum and paired contrast. Randomized PIT uses 100 draws per
group; its randomization range is reported separately from its game-cluster bootstrap interval.

CRPS is the mean discrete ranked probability score. MAE is the mean absolute error of the PMF expectation.
The confidence intervals describe sampling variation across games, conditional on the frozen model and
parameters; they are not parameter-fit uncertainty.

| Season | CRPS [95% CI] | MAE [95% CI] |
|---|---|---|
| 2025 | 2.06049 [1.97566, 2.14120] | 2.94012 [2.81978, 3.06016] |
| 2026 | 2.08893 [1.90815, 2.28562] | 2.99724 [2.75204, 3.26665] |

### Interval families, coverage and atom decomposition

The shortest contiguous interval minimizes integer set size; ties choose the lower endpoint. HPD sets add
outcomes in descending PMF order, breaking ties toward the lower outcome. Boundary atom mass sums the PMF
at the two interval endpoints; for HPD it sums endpoints of each contiguous component. Set size counts
integer outcomes; width is maximum minus minimum. The last two columns decompose coverage exactly:

```text
observed coverage = nominal level + (forecast set mass − nominal level)
                    + (observed coverage − forecast set mass)
```

| Season | Family | Level | Realized coverage [95% CI] | Mean width | Mean set size | Forecast set mass | Boundary atom mass | Set-mass excess | Coverage residual | Disconnected share |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2025 | Central | 50% | 0.5428 [0.5221, 0.5633] | 4.338 | 5.338 | 0.6578 | 0.3302 | +0.1578 | −0.1150 | 0.000 |
| 2025 | Central | 80% | 0.8176 [0.8013, 0.8337] | 8.282 | 9.282 | 0.8863 | 0.2522 | +0.0863 | −0.0687 | 0.000 |
| 2025 | Central | 90% | 0.9092 [0.8966, 0.9221] | 10.682 | 11.682 | 0.9496 | 0.2147 | +0.0496 | −0.0404 | 0.000 |
| 2025 | Shortest | 50% | 0.5472 [0.5299, 0.5641] | 3.471 | 4.471 | 0.5756 | 0.3444 | +0.0756 | −0.0284 | 0.000 |
| 2025 | Shortest | 80% | 0.8084 [0.7943, 0.8218] | 7.070 | 8.070 | 0.8380 | 0.2712 | +0.0380 | −0.0296 | 0.000 |
| 2025 | Shortest | 90% | 0.8948 [0.8838, 0.9053] | 9.303 | 10.303 | 0.9213 | 0.2298 | +0.0213 | −0.0265 | 0.000 |
| 2025 | HPD set | 50% | 0.5176 [0.4968, 0.5372] | 3.471 | 4.471 | 0.5871 | 0.3529 | +0.0871 | −0.0695 | 0.000 |
| 2025 | HPD set | 80% | 0.7992 [0.7832, 0.8142] | 7.070 | 8.070 | 0.8402 | 0.2748 | +0.0402 | −0.0410 | 0.000 |
| 2025 | HPD set | 90% | 0.8916 [0.8800, 0.9029] | 9.303 | 10.303 | 0.9219 | 0.2313 | +0.0219 | −0.0303 | 0.000 |
| 2026 | Central | 50% | 0.4908 [0.4368, 0.5487] | 4.303 | 5.303 | 0.6506 | 0.3269 | +0.1506 | −0.1598 | 0.000 |
| 2026 | Central | 80% | 0.8119 [0.7755, 0.8495] | 8.292 | 9.292 | 0.8849 | 0.2447 | +0.0849 | −0.0730 | 0.000 |
| 2026 | Central | 90% | 0.8957 [0.8679, 0.9220] | 10.671 | 11.671 | 0.9492 | 0.2087 | +0.0492 | −0.0535 | 0.000 |
| 2026 | Shortest | 50% | 0.4928 [0.4560, 0.5325] | 3.530 | 4.530 | 0.5771 | 0.3337 | +0.0771 | −0.0842 | 0.000 |
| 2026 | Shortest | 80% | 0.7996 [0.7654, 0.8340] | 7.178 | 8.178 | 0.8401 | 0.2573 | +0.0401 | −0.0405 | 0.000 |
| 2026 | Shortest | 90% | 0.9141 [0.8876, 0.9411] | 9.387 | 10.387 | 0.9215 | 0.2199 | +0.0215 | −0.0074 | 0.000 |
| 2026 | HPD set | 50% | 0.4744 [0.4366, 0.5223] | 3.530 | 4.530 | 0.5912 | 0.3439 | +0.0912 | −0.1167 | 0.000 |
| 2026 | HPD set | 80% | 0.7853 [0.7495, 0.8188] | 7.178 | 8.178 | 0.8430 | 0.2616 | +0.0430 | −0.0577 | 0.000 |
| 2026 | HPD set | 90% | 0.8957 [0.8652, 0.9271] | 9.387 | 10.387 | 0.9223 | 0.2215 | +0.0223 | −0.0265 | 0.000 |

The 2025 central-50 result is the requested exhibit: coverage is 0.5428, while mean forecast set mass is
0.6578. The `+0.1578` discrete set-mass excess is partly cancelled by a `−0.1150` empirical coverage
residual. Endpoint mass by itself is not a calibration verdict. Shortest and HPD sets shorten the
average envelope relative to central intervals, but their coverage and residuals differ; all three
families are reported separately in the machine-readable bundle.

Game-clustered paired contrasts between interval families are also in the manifest. For example, on 2025
the central-minus-HPD realized 50% coverage difference is `+0.0252` [0.0087, 0.0404]; in 2026 it is
`+0.0164` [−0.0287, 0.0674]. These are same-observation paired comparisons. Candidate-versus-B0 paired
intervals are not available because no candidate passed Step 1.

### Randomized PIT and zero/tail event reliability

| Season | Randomized PIT mean KS D | Game-cluster bootstrap 95% CI | Randomization 2.5–97.5% range | Mean KS asymptotic p-value |
|---|---:|---:|---:|---:|
| 2025 | 0.1335 | [0.1198, 0.1486] | [0.1259, 0.1414] | 3.89e−36 |
| 2026 | 0.1627 | [0.1288, 0.1997] | [0.1440, 0.1813] | 2.10e−10 |

The KS p-values are conventional unclustered asymptotic references, not decision gates. The first PIT
decile contains 21.7% of 2025 randomized values and 24.9% in 2026, against 10% under Uniform(0,1). The
cluster-bootstrap intervals for D and the full decile frequencies are in the manifest.

| Season | Event | Mean predicted probability | Observed rate | Predicted − observed [95% game-cluster CI] | Brier |
|---|---|---:|---:|---:|---:|
| 2025 | Y = 0 | 0.1726 | 0.3788 | −0.2062 [−0.2205, −0.1928] | 0.2380 |
| 2025 | Y ≥ 1 | 0.8274 | 0.6212 | +0.2062 [+0.1928, +0.2205] | 0.2380 |
| 2025 | Y ≥ 2 | 0.6683 | 0.5420 | +0.1263 [+0.1134, +0.1403] | 0.1915 |
| 2025 | Y ≥ 5 | 0.3598 | 0.3616 | −0.0018 [−0.0120, +0.0093] | 0.1243 |
| 2025 | Y ≥ 10 | 0.1535 | 0.2044 | −0.0509 [−0.0590, −0.0425] | 0.0869 |
| 2025 | Y ≥ 20 | 0.0347 | 0.0356 | −0.0009 [−0.0076, +0.0052] | 0.0292 |
| 2026 | Y = 0 | 0.1672 | 0.3845 | −0.2172 [−0.2501, −0.1804] | 0.2498 |
| 2026 | Y ≥ 1 | 0.8328 | 0.6155 | +0.2172 [+0.1804, +0.2501] | 0.2498 |
| 2026 | Y ≥ 2 | 0.6884 | 0.5521 | +0.1362 [+0.1054, +0.1652] | 0.2082 |
| 2026 | Y ≥ 5 | 0.3756 | 0.3579 | +0.0177 [−0.0089, +0.0452] | 0.1354 |
| 2026 | Y ≥ 10 | 0.1591 | 0.1963 | −0.0372 [−0.0540, −0.0200] | 0.0727 |
| 2026 | Y ≥ 20 | 0.0370 | 0.0470 | −0.0101 [−0.0230, +0.0021] | 0.0341 |

Reliability tables by forecast-probability decile, with counts, mean prediction and observed rate, are in
the manifest for zero and each shown tail event.

### Per-tier view

| Season | Tier | n | CRPS | MAE | Mean P(0) | P(0) − observed zero [95% CI] | PIT KS D [game-cluster 95% CI] | Central coverage 50 / 80 / 90 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 2025 | m < 3 | 1,140 | 1.0443 | 1.6311 | 0.3309 | −0.2753 [−0.3026, −0.2467] | 0.2406 [0.2153, 0.2696] | 0.6123 / 0.9149 / 0.9456 |
| 2025 | 3 ≤ m < 8 | 837 | 2.3480 | 3.3564 | 0.0602 | −0.1931 [−0.2191, −0.1679] | 0.1773 [0.1503, 0.2025] | 0.4361 / 0.6810 / 0.8722 |
| 2025 | m ≥ 8 | 523 | 3.8153 | 5.1273 | 0.0076 | −0.0766 [−0.1009, −0.0536] | 0.1716 [0.1376, 0.2107] | 0.5621 / 0.8241 / 0.8891 |
| 2026 | m < 3 | 214 | 0.9821 | 1.5374 | 0.3339 | −0.2549 [−0.3115, −0.1904] | 0.2334 [0.1689, 0.2959] | 0.5421 / 0.9486 / 0.9486 |
| 2026 | 3 ≤ m < 8 | 172 | 2.3165 | 3.3215 | 0.0567 | −0.2515 [−0.3140, −0.1892] | 0.2349 [0.1791, 0.2916] | 0.4244 / 0.6453 / 0.8430 |
| 2026 | m ≥ 8 | 103 | 4.0085 | 5.4887 | 0.0055 | −0.0819 [−0.1384, −0.0322] | 0.2272 [0.1545, 0.3188] | 0.4951 / 0.8058 / 0.8738 |

The full tier-by-family-by-level matrix, including mean widths, set sizes, set mass, boundary atoms,
coverage decomposition, disconnected share, paired interval-family differences, and tail reliability,
is in `manifest-and-diagnostics.json`.

### Original central-interval gate, preserved as historical evidence

The previous reports compared each candidate's absolute central-coverage error with B0's at all three
levels and both seasons, with the registered MAE criterion. Those results remain as originally reported;
they are not rerun candidate results from this recovery.

| Season | Model | Central coverage 50 / 80 / 90 |
|---|---|---|
| 2025 | B0 (v2–v4 source) | 0.543 / 0.818 / 0.909 |
| 2025 | v1 B2 | 0.713 / 0.914 / 0.955 |
| 2025 | v2 Zf | 0.738 / 0.910 / 0.960 |
| 2025 | v3 V3 | 0.750 / 0.919 / 0.965 |
| 2025 | v4 V4 | 0.744 / 0.938 / 0.970 |
| 2026 | B0 (v2–v4 source) | 0.491 / 0.812 / 0.896 |
| 2026 | v1 B2 | 0.685 / 0.912 / 0.963 |
| 2026 | v2 Zf | 0.740 / 0.926 / 0.965 |
| 2026 | v3 V3 | 0.748 / 0.930 / 0.973 |
| 2026 | v4 V4 | 0.718 / 0.928 / 0.978 |

The stored v1 result says its CRPS and MAE criteria passed while coverage closeness failed in both seasons.
The v2, v3 and v4 JSONs each record zero of six central-coverage comparisons passing and retain their
original `NOT_ADOPTED` verdicts. The earlier audit records a source inconsistency in v3's prose versus its
printed tier table; the displayed table values were used there. These historical decisions are preserved,
not reinterpreted as approval or a new gate.

## 3. Adoption protocol proposal — not a decision

This structure is offered for Micah to accept or reject. It does not select a candidate or set replacement
cut-offs.

- **Probabilistic accuracy:** compare CRPS on the identical frozen observations using paired game-cluster
  uncertainty. Report MAE of the predictive mean separately as a point-error summary; it does not measure
  the quality or calibration of the entire distribution.
- **Calibration:** report randomized PIT and its distributional diagnostics, plus event reliability and
  Brier scores for zero and predeclared positive-count thresholds. Show central-interval coverage with the
  forecast set-mass excess and empirical coverage residual, overall and by useful strata.
- **Sharpness:** report interval widths and prediction-set sizes at each nominal level, together with
  disconnected share for HPD sets. Interpret sharpness alongside calibration, since narrow sets alone do
  not establish useful forecasts.
- **Comparison procedure:** freeze the population, forecast artifacts, event definitions and paired
  uncertainty method before looking at candidate results. Require a written interpretation across the
  three dimensions and a separate approval of any future decision rule.

The original central-interval gate and its results above remain preserved. Micah has approved this
diagnostic framework, not a revised adoption gate. No numeric replacement cut-offs are proposed here.

## 4. Reusable contract

The league- and market-agnostic minimum artifact requirements are in
[`docs/EVAL-CONTRACT-discrete-props.md`](../../docs/EVAL-CONTRACT-discrete-props.md). The same contract is
referenced from the append-only [research learnings log](LEARNINGS.md).

## 5. Remaining unknowns and integrity

- The historical evaluations did not fingerprint their database snapshot or retain original keyed
  observation ledgers. The current snapshot reproduces B0 exactly, but cannot prove byte identity with the
  original run's database or row IDs.
- v1's 2025-only fit parameters and full-precision reported scores are unavailable. The v1 2026 result
  matches only the precision printed in its report.
- v2's recent-form cross cells are stored at four decimals, which produces the measured CRPS/MAE mismatch.
  v3 omits the required `p_cross` table. v4 omits it too and stores interpolation centers at three
  decimals.
- No new v1–v4 candidate PMF/CDFs were exported. Therefore candidate shortest/HPD sets, endpoint mass,
  randomized PIT, threshold reliability, and new paired candidate-versus-B0 intervals remain unverified.
- The frozen PMF implementation renormalizes support 0–160. This replay reproduces the code's defined
  distribution; any probability originally intended above that cap is not separately represented.
- The old v3 report's prose/table tier-calibration contradiction remains unresolved at source level.

No model was refit, no threshold was applied or newly selected, v4 was not adopted, the prospective v1
2026 weeks 7–18 test was not touched, `/root/lp-rushing-carries` was not touched, and nothing was merged
to `dev` or changed in production.
