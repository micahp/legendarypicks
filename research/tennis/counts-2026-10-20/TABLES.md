# Generated tables

Produced by `run_counts_eval.py` from `summary.json`. Differences are candidate minus reference.
CI is the 95% cluster bootstrap (tournament clusters; match clusters in the JSON as sensitivity).

## ATP aces

n = 23546 player-match targets (11773 matches); years {'2023': 6894, '2024': 7140, '2025': 6380, '2026': 3132}; lines [4.5, 5.5, 6.5].

| model | CRPS | dCRPS vs ref [95% CI] | log score | dlog [95% CI] | cov 50/80/90 | PIT KS | PIT <0.05 / >0.95 | >p95 / >p99 | calibrated |
|---|---:|---|---:|---|---|---:|---|---|---|
| C0 | 2.37552 | (ref) | 3.14010 | (ref) | 41.2/63.9/72.3 | 0.1554 | 17.6 / 15.7 | 14.3 / 7.64 | no |
| p0_poisson | 2.09232 | -0.28320 [-0.32596, -0.23651] | 2.84838 | -0.29172 [-0.33176, -0.25047] | 43.3/67.4/78.0 | 0.1323 | 15.0 / 13.4 | 11.5 / 5.89 | no |
| p0_gamma_poisson | 2.08776 | -0.28776 [-0.33021, -0.24093] | 2.82893 | -0.31117 [-0.35096, -0.26991] | 43.7/68.1/78.4 | 0.1287 | 14.6 / 13.1 | 11.3 / 5.67 | no |
| p1_poisson | 2.08967 | -0.28585 [-0.32732, -0.23889] | 2.84601 | -0.29409 [-0.33412, -0.25232] | 43.5/67.4/78.1 | 0.1298 | 14.8 / 13.3 | 11.6 / 5.89 | no |
| p1_gamma_poisson | 2.03281 | -0.34271 [-0.38197, -0.29946] | 2.64633 | -0.49377 [-0.53293, -0.45141] | 49.8/75.6/86.5 | 0.0769 | 10.0 / 9.5 | 8.0 / 3.06 | no |

Threshold reliability at the book-style lines (predicted vs observed P(over), Brier):

| model | over 4.5 | over 5.5 | over 6.5 |
|---|---|---|---|
| C0 | 60.3 vs 51.7, B 0.2457 | 45.4 vs 42.1, B 0.2352 | 31.9 vs 34.2, B 0.2151 |
| p0_poisson | 58.2 vs 51.7, B 0.2112 | 44.6 vs 42.1, B 0.2033 | 32.7 vs 34.2, B 0.1879 |
| p0_gamma_poisson | 58.1 vs 51.7, B 0.2107 | 44.6 vs 42.1, B 0.2031 | 32.8 vs 34.2, B 0.1878 |
| p1_poisson | 57.9 vs 51.7, B 0.2110 | 44.4 vs 42.1, B 0.2035 | 32.6 vs 34.2, B 0.1882 |
| p1_gamma_poisson | 54.8 vs 51.7, B 0.2063 | 42.8 vs 42.1, B 0.2006 | 32.6 vs 34.2, B 0.1858 |

CRPS by year: C0 2023 2.3192, 2024 2.4085, 2025 2.3906, 2026 2.3936; p0_poisson 2023 2.0134, 2024 2.1008, 2025 2.1138, 2026 2.2029; p0_gamma_poisson 2023 2.0087, 2024 2.0964, 2025 2.1093, 2026 2.1982; p1_poisson 2023 2.0105, 2024 2.0971, 2025 2.1134, 2026 2.1988; p1_gamma_poisson 2023 1.9573, 2024 2.0429, 2025 2.0559, 2026 2.1289

**Decision:** INCONCLUSIVE; winner (clear over reference, lowest CRPS) p1_gamma_poisson; runner-up p0_gamma_poisson; calibrated False; lowest pooled CRPS overall p1_gamma_poisson.

## ATP double_faults

n = 23546 player-match targets (11773 matches); years {'2023': 6894, '2024': 7140, '2025': 6380, '2026': 3132}; lines [1.5, 2.5, 3.5].

| model | CRPS | dCRPS vs ref [95% CI] | log score | dlog [95% CI] | cov 50/80/90 | PIT KS | PIT <0.05 / >0.95 | >p95 / >p99 | calibrated |
|---|---:|---|---:|---|---|---:|---|---|---|
| C0 | 1.15316 | (ref) | 2.11434 | (ref) | 64.1/76.4/92.1 | 0.0888 | 9.8 / 9.0 | 7.2 / 2.89 | no |
| p0_poisson | 1.06913 | -0.08403 [-0.09170, -0.07559] | 2.00782 | -0.10652 [-0.11651, -0.09587] | 59.7/83.8/92.3 | 0.0677 | 8.4 / 7.9 | 5.8 / 2.18 | no |
| p0_gamma_poisson | 1.06786 | -0.08530 [-0.09299, -0.07684] | 2.00158 | -0.11275 [-0.12283, -0.10204] | 60.3/84.3/92.6 | 0.0640 | 8.2 / 7.6 | 5.7 / 2.04 | no |
| p1_poisson | 1.06902 | -0.08415 [-0.09155, -0.07571] | 2.00775 | -0.10659 [-0.11661, -0.09593] | 59.9/83.7/92.3 | 0.0676 | 8.3 / 7.8 | 5.8 / 2.19 | no |
| p1_gamma_poisson | 1.05849 | -0.09467 [-0.10208, -0.08635] | 1.96644 | -0.14790 [-0.15966, -0.13529] | 64.0/88.7/95.5 | 0.0289 | 6.0 / 5.6 | 4.2 / 1.13 | no |

Threshold reliability at the book-style lines (predicted vs observed P(over), Brier):

| model | over 1.5 | over 2.5 | over 3.5 |
|---|---|---|---|
| C0 | 74.0 vs 65.0, B 0.2355 | 49.2 vs 43.3, B 0.2490 | 27.4 vs 27.0, B 0.1971 |
| p0_poisson | 71.5 vs 65.0, B 0.2188 | 47.7 vs 43.3, B 0.2297 | 27.7 vs 27.0, B 0.1816 |
| p0_gamma_poisson | 71.1 vs 65.0, B 0.2184 | 47.5 vs 43.3, B 0.2295 | 27.7 vs 27.0, B 0.1816 |
| p1_poisson | 71.4 vs 65.0, B 0.2187 | 47.6 vs 43.3, B 0.2297 | 27.6 vs 27.0, B 0.1816 |
| p1_gamma_poisson | 67.6 vs 65.0, B 0.2152 | 45.6 vs 43.3, B 0.2280 | 28.0 vs 27.0, B 0.1813 |

CRPS by year: C0 2023 1.1651, 2024 1.1534, 2025 1.1839, 2026 1.0639; p0_poisson 2023 1.0764, 2024 1.0603, 2025 1.1114, 2026 0.9870; p0_gamma_poisson 2023 1.0750, 2024 1.0591, 2025 1.1103, 2026 0.9857; p1_poisson 2023 1.0759, 2024 1.0610, 2025 1.1117, 2026 0.9853; p1_gamma_poisson 2023 1.0658, 2024 1.0501, 2025 1.1010, 2026 0.9747

**Decision:** INCONCLUSIVE; winner (clear over reference, lowest CRPS) p1_gamma_poisson; runner-up p0_gamma_poisson; calibrated False; lowest pooled CRPS overall p1_gamma_poisson.

## ATP games

n = 11766 matches (11766 matches); years {'2023': 3448, '2024': 3561, '2025': 3191, '2026': 1566}; lines [21.5, 22.5, 23.5].

| model | CRPS | dCRPS vs ref [95% CI] | log score | dlog [95% CI] | cov 50/80/90 | PIT KS | PIT <0.05 / >0.95 | >p95 / >p99 | calibrated |
|---|---:|---|---:|---|---|---:|---|---|---|
| direct_format | 3.36637 | (ref) | 3.05601 | (ref) | 59.1/86.3/93.3 | 0.0212 | 4.0 / 5.3 | 4.7 / 0.96 | no |
| direct_surface | 3.36563 | -0.00074 [-0.00471, +0.00315] | 3.05949 | +0.00348 [-0.00090, +0.00876] | 57.9/85.7/93.0 | 0.0224 | 3.9 / 5.5 | 4.9 / 0.95 | no |
| direct_surface_competitive | 3.35956 | -0.00681 [-0.01267, -0.00054] | 3.06563 | +0.00962 [+0.00176, +0.01942] | 56.1/84.7/92.8 | 0.0232 | 4.0 / 5.5 | 4.6 / 0.88 | no |
| simulator | 3.53266 | +0.16628 [+0.13622, +0.19650] | 3.10589 | +0.04988 [+0.03792, +0.06164] | 51.7/79.0/89.1 | 0.1358 | 11.9 / 3.2 | 2.2 / 0.38 | no |

Threshold reliability at the book-style lines (predicted vs observed P(over), Brier):

| model | over 21.5 | over 22.5 | over 23.5 |
|---|---|---|---|
| direct_format | 52.1 vs 54.0, B 0.2488 | 44.6 vs 45.8, B 0.2485 | 38.9 vs 40.1, B 0.2404 |
| direct_surface | 52.0 vs 54.0, B 0.2487 | 44.5 vs 45.8, B 0.2486 | 38.8 vs 40.1, B 0.2406 |
| direct_surface_competitive | 52.0 vs 54.0, B 0.2478 | 44.5 vs 45.8, B 0.2479 | 38.9 vs 40.1, B 0.2400 |
| simulator | 67.3 vs 54.0, B 0.2632 | 59.2 vs 45.8, B 0.2643 | 52.7 vs 40.1, B 0.2552 |

CRPS by year: direct_format 2023 3.3912, 2024 3.3250, 2025 3.3562, 2026 3.4265; direct_surface 2023 3.3946, 2024 3.3241, 2025 3.3517, 2026 3.4245; direct_surface_competitive 2023 3.3872, 2024 3.3157, 2025 3.3441, 2026 3.4297; simulator 2023 3.5354, 2024 3.5126, 2025 3.5171, 2026 3.6037

**Decision:** INCONCLUSIVE; winner (clear over reference, lowest CRPS) direct_surface_competitive; runner-up direct_surface; calibrated False; lowest pooled CRPS overall direct_surface_competitive.

## WTA aces

n = 25802 player-match targets (12901 matches); years {'2023': 7558, '2024': 7762, '2025': 7262, '2026': 3220}; lines [1.5, 2.5, 3.5].

| model | CRPS | dCRPS vs ref [95% CI] | log score | dlog [95% CI] | cov 50/80/90 | PIT KS | PIT <0.05 / >0.95 | >p95 / >p99 | calibrated |
|---|---:|---|---:|---|---|---:|---|---|---|
| C0 | 1.45075 | (ref) | 2.42899 | (ref) | 42.3/71.3/87.6 | 0.1553 | 14.7 / 13.0 | 10.6 / 6.17 | no |
| p0_poisson | 1.22969 | -0.22106 [-0.24413, -0.19689] | 2.13225 | -0.29674 [-0.32520, -0.26948] | 56.3/80.0/89.2 | 0.1140 | 10.8 / 10.0 | 8.0 / 3.74 | no |
| p0_gamma_poisson | 1.22703 | -0.22372 [-0.24662, -0.19977] | 2.12019 | -0.30880 [-0.33732, -0.28143] | 56.7/80.7/89.4 | 0.1108 | 10.4 / 9.8 | 7.8 / 3.65 | no |
| p1_poisson | 1.22856 | -0.22220 [-0.24574, -0.19771] | 2.13100 | -0.29799 [-0.32643, -0.27034] | 56.5/80.0/89.1 | 0.1118 | 10.7 / 10.1 | 8.0 / 3.74 | no |
| p1_gamma_poisson | 1.20510 | -0.24565 [-0.26767, -0.22294] | 2.03449 | -0.39451 [-0.42351, -0.36671] | 60.9/85.9/92.6 | 0.0733 | 7.8 / 7.8 | 6.2 / 2.25 | no |

Threshold reliability at the book-style lines (predicted vs observed P(over), Brier):

| model | over 1.5 | over 2.5 | over 3.5 |
|---|---|---|---|
| C0 | 72.3 vs 57.4, B 0.2634 | 48.0 vs 41.0, B 0.2434 | 27.1 vs 28.6, B 0.2013 |
| p0_poisson | 67.8 vs 57.4, B 0.2132 | 46.3 vs 41.0, B 0.2023 | 28.9 vs 28.6, B 0.1689 |
| p0_gamma_poisson | 67.5 vs 57.4, B 0.2121 | 46.2 vs 41.0, B 0.2020 | 29.0 vs 28.6, B 0.1690 |
| p1_poisson | 67.5 vs 57.4, B 0.2127 | 46.1 vs 41.0, B 0.2025 | 28.9 vs 28.6, B 0.1692 |
| p1_gamma_poisson | 64.1 vs 57.4, B 0.2060 | 44.1 vs 41.0, B 0.1992 | 28.6 vs 28.6, B 0.1679 |

CRPS by year: C0 2023 1.4480, 2024 1.4419, 2025 1.4648, 2026 1.4469; p0_poisson 2023 1.1968, 2024 1.2131, 2025 1.2733, 2026 1.2487; p0_gamma_poisson 2023 1.1939, 2024 1.2106, 2025 1.2706, 2026 1.2462; p1_poisson 2023 1.1952, 2024 1.2118, 2025 1.2725, 2026 1.2481; p1_gamma_poisson 2023 1.1700, 2024 1.1906, 2025 1.2487, 2026 1.2243

**Decision:** INCONCLUSIVE; winner (clear over reference, lowest CRPS) p1_gamma_poisson; runner-up p0_gamma_poisson; calibrated False; lowest pooled CRPS overall p1_gamma_poisson.

## WTA double_faults

n = 25802 player-match targets (12901 matches); years {'2023': 7558, '2024': 7762, '2025': 7262, '2026': 3220}; lines [2.5, 3.5, 4.5].

| model | CRPS | dCRPS vs ref [95% CI] | log score | dlog [95% CI] | cov 50/80/90 | PIT KS | PIT <0.05 / >0.95 | >p95 / >p99 | calibrated |
|---|---:|---|---:|---|---|---:|---|---|---|
| C0 | 1.48092 | (ref) | 2.41592 | (ref) | 57.6/78.0/83.9 | 0.1023 | 11.3 / 10.5 | 9.0 / 3.72 | no |
| p0_poisson | 1.33162 | -0.14930 [-0.15884, -0.13951] | 2.25551 | -0.16041 [-0.17053, -0.15038] | 56.6/79.4/88.8 | 0.0718 | 9.2 / 8.9 | 6.9 / 2.59 | no |
| p0_gamma_poisson | 1.32996 | -0.15096 [-0.16042, -0.14123] | 2.24895 | -0.16697 [-0.17721, -0.15733] | 57.0/79.8/89.2 | 0.0684 | 9.0 / 8.6 | 6.6 / 2.47 | no |
| p1_poisson | 1.33469 | -0.14624 [-0.15531, -0.13681] | 2.25837 | -0.15754 [-0.16746, -0.14765] | 56.5/79.2/88.7 | 0.0727 | 9.2 / 8.9 | 6.9 / 2.61 | no |
| p1_gamma_poisson | 1.31752 | -0.16340 [-0.17198, -0.15473] | 2.19704 | -0.21888 [-0.23153, -0.20615] | 63.2/86.7/94.4 | 0.0147 | 5.5 / 5.4 | 4.0 / 0.87 | yes |

Threshold reliability at the book-style lines (predicted vs observed P(over), Brier):

| model | over 2.5 | over 3.5 | over 4.5 |
|---|---|---|---|
| C0 | 71.7 vs 61.7, B 0.2465 | 50.9 vs 45.2, B 0.2517 | 31.6 vs 31.2, B 0.2152 |
| p0_poisson | 68.3 vs 61.7, B 0.2167 | 49.1 vs 45.2, B 0.2211 | 32.1 vs 31.2, B 0.1913 |
| p0_gamma_poisson | 68.0 vs 61.7, B 0.2163 | 49.0 vs 45.2, B 0.2209 | 32.1 vs 31.2, B 0.1913 |
| p1_poisson | 68.2 vs 61.7, B 0.2172 | 49.1 vs 45.2, B 0.2218 | 32.0 vs 31.2, B 0.1920 |
| p1_gamma_poisson | 63.0 vs 61.7, B 0.2133 | 46.1 vs 45.2, B 0.2201 | 32.0 vs 31.2, B 0.1913 |

CRPS by year: C0 2023 1.4677, 2024 1.5123, 2025 1.4848, 2026 1.4274; p0_poisson 2023 1.3118, 2024 1.3516, 2025 1.3585, 2026 1.2693; p0_gamma_poisson 2023 1.3101, 2024 1.3498, 2025 1.3570, 2026 1.2677; p1_poisson 2023 1.3141, 2024 1.3545, 2025 1.3625, 2026 1.2726; p1_gamma_poisson 2023 1.2963, 2024 1.3359, 2025 1.3477, 2026 1.2551

**Decision:** ADOPT_CANDIDATE; winner (clear over reference, lowest CRPS) p1_gamma_poisson; runner-up p0_gamma_poisson; calibrated True; lowest pooled CRPS overall p1_gamma_poisson.

## WTA games

n = 13062 matches (13062 matches); years {'2023': 3781, '2024': 3892, '2025': 3631, '2026': 1758}; lines [20.5, 21.5, 22.5].

| model | CRPS | dCRPS vs ref [95% CI] | log score | dlog [95% CI] | cov 50/80/90 | PIT KS | PIT <0.05 / >0.95 | >p95 / >p99 | calibrated |
|---|---:|---|---:|---|---|---:|---|---|---|
| direct_format | 3.24659 | (ref) | 3.03204 | (ref) | 57.2/85.1/93.6 | 0.0089 | 4.4 / 5.1 | 4.5 / 0.87 | yes |
| direct_surface | 3.24539 | -0.00120 [-0.00338, +0.00080] | 3.03743 | +0.00539 [+0.00188, +0.00891] | 56.4/84.8/93.6 | 0.0094 | 4.4 / 5.2 | 4.3 / 0.82 | yes |
| direct_surface_competitive | 3.22852 | -0.01806 [-0.02492, -0.01105] | 3.04719 | +0.01515 [+0.00686, +0.02413] | 57.1/85.1/92.8 | 0.0088 | 4.5 / 5.1 | 4.4 / 0.87 | yes |
| simulator | 3.55718 | +0.31059 [+0.28488, +0.34064] | 3.14471 | +0.11267 [+0.10282, +0.12347] | 48.6/76.8/86.9 | 0.1803 | 14.8 / 2.7 | 2.1 / 0.45 | no |

Threshold reliability at the book-style lines (predicted vs observed P(over), Brier):

| model | over 20.5 | over 21.5 | over 22.5 |
|---|---|---|---|
| direct_format | 47.5 vs 48.3, B 0.2499 | 42.8 vs 43.3, B 0.2456 | 37.5 vs 37.9, B 0.2353 |
| direct_surface | 47.6 vs 48.3, B 0.2499 | 42.8 vs 43.3, B 0.2456 | 37.5 vs 37.9, B 0.2354 |
| direct_surface_competitive | 47.6 vs 48.3, B 0.2481 | 42.8 vs 43.3, B 0.2441 | 37.5 vs 37.9, B 0.2340 |
| simulator | 65.9 vs 48.3, B 0.2789 | 60.9 vs 43.3, B 0.2748 | 54.2 vs 37.9, B 0.2611 |

CRPS by year: direct_format 2023 3.2810, 2024 3.2550, 2025 3.2408, 2026 3.1660; direct_surface 2023 3.2816, 2024 3.2537, 2025 3.2373, 2026 3.1658; direct_surface_competitive 2023 3.2633, 2024 3.2365, 2025 3.2239, 2026 3.1456; simulator 2023 3.5968, 2024 3.5768, 2025 3.5321, 2026 3.4801

**Decision:** ADOPT_CANDIDATE; winner (clear over reference, lowest CRPS) direct_surface_competitive; runner-up direct_surface; calibrated True; lowest pooled CRPS overall direct_surface_competitive.

