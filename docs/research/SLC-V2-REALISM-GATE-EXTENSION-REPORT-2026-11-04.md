# SLC v2 realism-gate extension: observed-threshold report

**Date:** 2026-11-04
**Status:** Observed-only threshold results, prepared before any 2025 SLC simulation.
**Scope:** Metrics 8-11 extend the existing whole-game realism-gate draft. Metrics 1-7 and their thresholds remain unchanged.

## Run and data scope

No SLC simulation was run. No 2025 or 2026 data values were read or used. The extension materializer checked the existing hash-pinned 2022-2024 inputs and reused the original materializer’s ACT roster rows, zero-filled player-game lines, metric-7 statistic definitions, and role mapping. It accepts no season selection and records `simulation_outputs_read: false` in its JSON output.

Active-roster player-game counts are 2022: 26,016; 2023: 26,112; 2024: 26,121. RB and FB use the same combined role as metric 7.

## New thresholds

### Metric 8: central 50% and 95% interval coverage

For 2023, position-role intervals train on 2022. For 2024, they train on pooled 2022-2023. Each envelope is the min/max of the two held-out coverage rates. The table gives held-out line counts and the resulting coverage envelopes. Full fold endpoints, training counts, coverage numerators, and game-cluster counts are in the JSON artifact.

| Line / role | n 2023 | n 2024 | Central 50% envelope | Central 95% envelope |
|---|---:|---:|---:|---:|
| Offensive snap share / OL | 4366 | 4372 | [0.756176, 0.761338] | [1.000000, 1.000000] |
| Offensive snap share / OTHER | 14238 | 14241 | [0.996349, 0.997261] | [0.996349, 0.997261] |
| Offensive snap share / QB | 1112 | 1098 | [1.000000, 1.000000] | [1.000000, 1.000000] |
| Offensive snap share / RB | 1850 | 1846 | [0.494041, 0.537297] | [0.972914, 0.974595] |
| Offensive snap share / TE | 1669 | 1730 | [0.503895, 0.518497] | [0.980228, 0.984393] |
| Offensive snap share / WR | 2877 | 2834 | [0.517290, 0.547445] | [0.982004, 0.983664] |
| Offensive touchdowns / QB | 1112 | 1098 | [0.909173, 0.915301] | [0.986339, 0.986511] |
| Offensive touchdowns / RB | 1850 | 1846 | [0.793608, 0.812973] | [0.994583, 0.995135] |
| Offensive touchdowns / TE | 1669 | 1730 | [0.902890, 0.907130] | [0.990751, 0.991013] |
| Offensive touchdowns / WR | 2877 | 2834 | [0.833804, 0.844282] | [0.973183, 0.981230] |
| Passing attempts / QB | 1112 | 1098 | [0.750000, 0.760474] | [0.975410, 0.987410] |
| Receiving yards / RB | 1850 | 1846 | [0.727568, 0.742145] | [0.950270, 0.959913] |
| Receiving yards / TE | 1669 | 1730 | [0.744757, 0.749711] | [0.970520, 0.971240] |
| Receiving yards / WR | 2877 | 2834 | [0.749471, 0.768161] | [0.965242, 0.976359] |
| Receptions / RB | 1850 | 1846 | [0.782703, 0.802275] | [0.984865, 0.985915] |
| Receptions / TE | 1669 | 1730 | [0.753745, 0.758382] | [0.972254, 0.980228] |
| Receptions / WR | 2877 | 2834 | [0.811927, 0.822037] | [0.985180, 0.985749] |
| Rushing attempts / QB | 1112 | 1098 | [0.748634, 0.770683] | [0.982914, 0.985428] |
| Rushing attempts / RB | 1850 | 1846 | [0.735135, 0.766522] | [0.965872, 0.981081] |
| Rushing attempts / TE | 1669 | 1730 | [0.982081, 0.985620] | [0.982081, 0.985620] |
| Rushing attempts / WR | 2877 | 2834 | [0.882517, 0.887791] | [0.990615, 0.991531] |
| Rushing yards / QB | 1112 | 1098 | [0.654676, 0.663934] | [0.954463, 0.967626] |
| Rushing yards / RB | 1850 | 1846 | [0.728649, 0.731853] | [0.955580, 0.964324] |
| Rushing yards / TE | 1669 | 1730 | [0.983815, 0.989814] | [0.983815, 0.989814] |
| Rushing yards / WR | 2877 | 2834 | [0.888425, 0.893790] | [0.962113, 0.970360] |
| Targets / RB | 1850 | 1846 | [0.820000, 0.832069] | [0.987541, 0.988649] |
| Targets / TE | 1669 | 1730 | [0.752546, 0.758960] | [0.966474, 0.977831] |
| Targets / WR | 2877 | 2834 | [0.534227, 0.549878] | [0.983063, 0.985749] |

### Metrics 9-11: mean bias, variance ratio, and tail frequency

Metric 9 T is `abs(mean_2024 - mean_2023)`. Metric 10 T is `abs(ln(var_2024 / var_2023))` using population variance (`ddof=0`) of single player-game lines. All 28 line-role variance thresholds are evaluable. Metric 11 fixes p95 and p99 cutoffs from 2022 and sets T to `abs(freq_2024 - freq_2023)` for the share strictly above each cutoff. The simulation-side variance and tail checks use one hash-selected seed result per matchup, not seed means.

| Line / role | n 2022 | n 2023 | n 2024 | T9 mean | T10 logvar | T11 p95 | T11 p99 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Offensive snap share / OL | 4343 | 4366 | 4372 | 0.002035488 | 0.008606297 | 0.000000000 | 0.000000000 |
| Offensive snap share / OTHER | 14141 | 14238 | 14241 | 0.000011215 | 0.142156673 | 0.000912280 | 0.000912280 |
| Offensive snap share / QB | 1102 | 1112 | 1098 | 0.002046641 | 0.026406738 | 0.000000000 | 0.000000000 |
| Offensive snap share / RB | 1969 | 1850 | 1846 | 0.002255506 | 0.043506405 | 0.005543615 | 0.002186759 |
| Offensive snap share / TE | 1693 | 1669 | 1730 | 0.000318394 | 0.001065296 | 0.003229929 | 0.000211265 |
| Offensive snap share / WR | 2768 | 2877 | 2834 | 0.001362943 | 0.018689729 | 0.000136139 | 0.000000000 |
| Offensive touchdowns / QB | 1102 | 1112 | 1098 | 0.004134397 | 0.035416637 | 0.000171994 | 0.000171994 |
| Offensive touchdowns / RB | 1969 | 1850 | 1846 | 0.023252028 | 0.064366638 | 0.003872800 | 0.000552253 |
| Offensive touchdowns / TE | 1693 | 1669 | 1730 | 0.003880694 | 0.009562385 | 0.000261137 | 0.000620288 |
| Offensive touchdowns / WR | 2768 | 2877 | 2834 | 0.017852022 | 0.121116495 | 0.008047668 | 0.000674073 |
| Passing attempts / QB | 1102 | 1112 | 1098 | 0.300726632 | 0.028980285 | 0.004925568 | 0.002823970 |
| Receiving yards / RB | 1969 | 1850 | 1846 | 0.185216831 | 0.055974921 | 0.000965125 | 0.003231531 |
| Receiving yards / TE | 1693 | 1669 | 1730 | 0.185843865 | 0.033382772 | 0.002955285 | 0.002552150 |
| Receiving yards / WR | 2768 | 2877 | 2834 | 0.115377011 | 0.076971642 | 0.004833556 | 0.007899509 |
| Receptions / RB | 1969 | 1850 | 1846 | 0.094545987 | 0.100616698 | 0.003182337 | 0.002701531 |
| Receptions / TE | 1693 | 1669 | 1730 | 0.007514105 | 0.093610691 | 0.009200414 | 0.004180621 |
| Receptions / WR | 2768 | 2877 | 2834 | 0.006820943 | 0.000169272 | 0.000683640 | 0.002311791 |
| Rushing attempts / QB | 1102 | 1112 | 1098 | 0.008186893 | 0.012569229 | 0.003923091 | 0.002801038 |
| Rushing attempts / RB | 1969 | 1850 | 1846 | 0.066865392 | 0.048544941 | 0.014168838 | 0.003265497 |
| Rushing attempts / TE | 1693 | 1669 | 1730 | 0.020859121 | 2.083909960 | 0.003539207 | 0.004025116 |
| Rushing attempts / WR | 2768 | 2877 | 2834 | 0.010603406 | 0.040136908 | 0.005181631 | 0.000310667 |
| Rushing yards / QB | 1102 | 1112 | 1098 | 1.173074655 | 0.218337863 | 0.020495079 | 0.000864882 |
| Rushing yards / RB | 1969 | 1850 | 1846 | 1.665910808 | 0.161886592 | 0.013623613 | 0.004353606 |
| Rushing yards / TE | 1693 | 1669 | 1730 | 0.159975341 | 5.086926907 | 0.003130184 | 0.005780347 |
| Rushing yards / WR | 2768 | 2877 | 2834 | 0.210082937 | 0.518255974 | 0.005634202 | 0.004465857 |
| Targets / RB | 1969 | 1850 | 1846 | 0.157603584 | 0.152321360 | 0.008047202 | 0.003777927 |
| Targets / TE | 1693 | 1669 | 1730 | 0.029428857 | 0.076044036 | 0.004964033 | 0.006965162 |
| Targets / WR | 2768 | 2877 | 2834 | 0.017381790 | 0.007061840 | 0.002900992 | 0.000236833 |

The JSON also records the 2023 and 2024 means and variances, 2022 tail cutoffs, each fold’s exceedance counts and frequencies, all line-role sample counts, and input hashes. The executable selection rule for the one-seed metrics and the full PASS definitions are in the [gate draft](SLC-V2-REALISM-GATES-DRAFT-2026-11-04.md).

## Reports to produce when 2025 simulations are run

- **Metric 12, season envelope:** For 1,000 sampled seasons, draw one valid seed result per 2025 matchup. Report the observed 2025 midrank percentile and simulated 2.5th-97.5th percentile range for league game means of points, scrimmage plays, pass-call rate, and drives. Also report observed percentiles for p10, p50, and p90 of the team-game top-receiver and top-carrier share distributions. This metric is report-only.
- **Metric 13, as-of baseline:** Score the 30-seed SLC ensemble beside the rolling player-mean baseline on identical 2025 ACT player-game lines, by metric-7 line and role. Report MAE and CRPS, sample counts, and cold-start fallback counts. The baseline uses prior 2025 weeks, then the same player’s 2024 line-role mean, then the 2024 league line-role mean. The deterministic baseline CRPS equals its absolute error. This revision assigns no pass threshold.

## Reproduction artifacts

Run `python3 docs/research/slc-v2-realism-gate-2026-11-04/materialize_extended_thresholds.py` from the repository root. The script prints all input hashes, refuses source seasons outside 2022-2024, verifies the original materializer hash before importing its metric-7 population logic, and writes `extended_observed_thresholds.json`.

| Artifact | SHA-256 |
|---|---|
| `materialize_extended_thresholds.py` | `f4a60f8eb315332c5b9be1137fccc69483cd3de5679e7e47745f81e6bb60c650` |
| `extended_observed_thresholds.json` | `857104b4ed3c2c674e8f6e04001cb0fb1fb546cd1f65b93f35c19809bc8d43d1` |

The original `materialize_thresholds.py` and `observed_thresholds.json` remain byte-identical to their pinned hashes in the gate draft.

## Question for Micah

**Should metric 13 affect advancement?** This revision treats it as a comparative report because no baseline-improvement acceptance rule was specified. Metrics 12-13 do not change the advancement decision unless Micah sets an explicit metric-13 rule.
