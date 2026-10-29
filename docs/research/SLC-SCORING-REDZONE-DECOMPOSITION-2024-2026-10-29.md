# SLC 2024 red-zone decomposition, corrected

Status: exploratory retrospective replay. This report supersedes the red-zone trip and conversion claims in the earlier exact-yardline analysis. No 2026 outcome was used.

## Result

The score-clock replay did **not** produce too few red-zone trips. On the 228 matched games, the simulated trip rate was 3.294 per team-game versus 3.311 actual. Its red-zone offensive touchdown conversion was low, while it produced more plays inside the 20.

| Metric | SLC replay | Actual, same games | SLC minus actual, 95% game-cluster interval |
|---|---:|---:|---:|
| Red-zone trips per team-game | 3.294 | 3.311 | -0.018 [-0.172, +0.139] |
| Offensive touchdowns per red-zone trip | 0.495 | 0.583 | -0.088 [-0.120, -0.058] |
| Run/pass plays inside the 20 per team-game | 10.350 | 9.669 | +0.681 [+0.143, +1.224] |
| Offensive touchdowns per red-zone run/pass play | 0.157 | 0.193 | -0.036 [-0.048, -0.024] |
| Run share of red-zone run/pass plays | 0.490 | 0.492 | -0.002 [-0.023, +0.019] |
| Goal-to-go share of red-zone run/pass plays | 0.435 | 0.386 | +0.049 [+0.025, +0.072] |

Positive differences mean the simulator is higher. The intervals resample the 228 matched games 10,000 times, preserving each game as one cluster. They reflect variation across games; with only two requested seeds per game, they do not include a separate Monte Carlo seed uncertainty component.

The simulated replay averaged about 3.14 red-zone plays per trip versus 2.92 actual. Its trip endings also show fewer offensive touchdowns and more field-goal attempts and turnovers on downs. Per-play breakdowns are descriptive: simulated touchdown rates were 0.161 per run and 0.153 per pass, versus 0.170 and 0.215 actual. The pass-rate gap is larger, but these descriptive splits do not by themselves identify a causal engine mechanism.

The full 2024 Weeks 2–18 population has 1,695 run/pass-defined red-zone trips across 512 team-games (3.311 per team-game), and 1,001 terminal `Touchdown` results (0.591 per trip). The matched cohort's actual values are close to those full-population rates.

## Definition correction

The earlier report described a red-zone trip as a drive reaching the 20 on a scrimmage play, but its actual-side code counted any row with `yardline_100 <= 20`. That gave 2,016 trips instead of 1,695. It also treated both `Touchdown` and `Opp touchdown` text as touchdown conversions and compared against a replay that included incomplete game seeds. Those definitions did not match the stated measure.

This replay uses a run/pass scrimmage play at or inside the 20 to define both actual and simulated trips. Actual offensive trip conversion uses `series_result == 'Touchdown'`, excluding `Opp touchdown`; the simulated equivalent requires a touchdown terminal scored by the offense. Play-level scoring uses the engine's resolved `outcome.touchdown` and the publisher's `pass_touchdown` or `rush_touchdown` fields, not the sampled source row's `sampled_touchdown_flag`. The official [nflverse PBP dictionary](https://github.com/nflverse/nflreadr/blob/main/vignettes/dictionary_pbp.Rmd) defines the relevant scoring fields and lists `Touchdown` and `Opp touchdown` as separate series results.

Therefore the prior actual rate of 3.94 trips/team-game and 0.623 touchdowns/trip is superseded. The previous claim that exact-yardline sampling closed 30% of a trip-conversion gap is also not supported by a matched, definition-consistent comparison and should not be used as calibration evidence.

## Cohort and reproducibility

- Schedule: 256 regular-season games, Weeks 2–18. Pregame snapshots built for 229 games; 27 failed historical depth-chart eligibility. The matched simulation cohort contains 228 games with at least one complete seed.
- Replay: two seeds requested per valid snapshot; 442 complete game-seeds, 16 incomplete, zero engine exceptions. The point estimates average available seeds within each game, then weight each game equally.
- Training cutoff: reference rows eligible before 2024 Week 1; play-call artifact fit through 2023. Historical schedule availability is unverified, so this remains retrospective/exploratory rather than a prospective forecast score.
- Bootstrap: 10,000 paired game-cluster resamples, seed 81029. Raw per-game counters and exact matched game IDs are in [the machine-readable result](SLC-SCORING-REDZONE-DECOMPOSITION-2024-CORRECTED-2026-10-29.json).
- Artifact SHA-256: `f79400a9f3a6fe2180bc4717cc828022f16cd2371b2170cbaff0c47e86b7081f`.
- PBP-row digest: `ff4f42477b082bf03d6837faf456e68b2d544ccaa3e45d4f2cc8ddd08ab1d72a`.
- Decomposition source SHA-256: `7113f069bc3b1ee5d7aae6064c670cddf83b325da802de35a3b7a000b26423b8`.

The next red-zone experiment should compare default and exact-yardline draws on the same seeds and matched games, reporting trip terminals, touchdowns by run/pass, yards-to-go, turnover-on-downs and field-goal attempt rates. The current result locates the observed gap in conversion and red-zone play volume, but does not validate a fix.
