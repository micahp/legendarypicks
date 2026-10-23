# nfl_sequence v0.1: drive-level evaluation, 2022–2023 held-out seasons

Status: research diagnostic. **Not a prediction of real games and not a claim of realistic game simulation.** Every script
the engine writes is labelled HYPOTHETICAL MODEL SIMULATION. Results are measured against the 2022–2023 seasons; the
simulator was trained on 2010–2021 only.

Companion documents: [RESULTS-nfl-sequence-v0.1-2026-10-22.md](RESULTS-nfl-sequence-v0.1-2026-10-22.md) (game-level),
[NFL-SEQUENCE-INTEGRATION-v0.1.md](NFL-SEQUENCE-INTEGRATION-v0.1.md) (contract), and representative sequences in
[results/drive-examples-2022-2023.txt](results/drive-examples-2022-2023.txt).

## Question

Do the simulated individual plays combine into realistic drives? Real drives were rebuilt from nflverse and the same
drive definitions were applied to every simulated game. Each drive gets exactly one ending.

## Definitions and conventions

- **Drive.** Every snap a possession team runs from the kickoff or change of possession that gives it the ball, until the ball
  changes hands. Real drives use nflverse's `drive` number (contiguous within each game; one kickoff per drive). Simulated
  drives use `state_before.drive_index`.
- **Kickoffs and points after touchdown** sit on the drive but are not offensive snaps. Two-point tries are kept separate, as
  points, not snaps.
- **Penalties.** Penalty-flagged snaps that happened are kept (the snap occurred). `no_play` rows (penalty-nullified, no snap) are
  excluded. The simulator generates no penalties, so it is not compared on them.
- **Aborted-flagged snaps** that happened (for example, a lost fumble nflverse also marks aborted) are kept.
- **Points** come from the score change across each play. For real plays this uses the next usable row's pre-play score, not
  nflverse's post-play totals, which are unreliable on penalty rows; points reconcile to the published final score in all 543 games.
- **Outcome,** decided from the last offensive snap and the points it produced, in priority order: defensive touchdown, field goal
  (made or missed), punt, turnover (interception or lost fumble), offensive touchdown, safety against the offense, clock expiration
  (period ended with the offense on the field), kneel (last snap a kneel), turnover on downs, kickoff-return touchdown,
  no offensive snap (kickoff with no snap before the period ended), other (should be empty; reported).
- **Intervals.** Real: 95% game-clustered bootstrap, 2,000 reps, seed 20261023. Simulated: 2.5th to 97.5th percentile across the 100
  trials; this measures the simulator's own variability, not uncertainty about real games. Baseline: 2010–2021 real drives, a point estimate.

Source: `backend/nfl_sequence/drive_eval.py`; tests `backend/nfl_sequence/test_drive_eval.py`. Round-2 counts in
`docs/results/drive-report-2022-2023.json` (copied from the run). Same simulator seeds as the 100-trial evaluation (`derive_seed`,
snapshot hash from pregame identity), so simulated games are the same games.

Commands (run from `backend/`; simulation shards in parallel, memory permitting):

```
python -m nfl_sequence.drive_eval sim --source-dir <nflverse dir> --model-dir nfl_sequence/models --test-seasons 2022-2023 --trials 100 --shard i --shards 3 --out sim_shard_i.jsonl.gz
python -m nfl_sequence.drive_eval report --source-dir <nflverse dir> --real-seasons 2022-2023 --baseline-seasons 2010-2021 --sim-glob 'sim_shard_*.jsonl.gz' --reps 2000 --seed 20261023 --out drive_report.json
python -m nfl_sequence.drive_eval examples --source-dir <nflverse dir> --model-dir nfl_sequence/models --real-season 2023 --out drive-examples.txt
```

## 1. Drive endings: real counts against the simulation

Real: 543 games, 11,984 drives (22.07 per game). Simulated: 543 games per trial, 100 trials. Per-game values are totals divided by games.

| ending | real drives | real per game | real share [95% CI] | sim per game [2.5–97.5%] | sim share [2.5–97.5%] | baseline share 2010–2021 |
|---|---|---|---|---|---|---|
| `touchdown` | 2,466 | 4.541 | 0.206 [0.198, 0.214] | 3.731 [3.610, 3.845] | 0.163 [0.158, 0.168] | 0.206 |
| `field_goal_made` | 1,813 | 3.339 | 0.151 [0.145, 0.158] | 3.542 [3.396, 3.683] | 0.155 [0.148, 0.161] | 0.140 |
| `field_goal_missed` | 305 | 0.562 | 0.025 [0.023, 0.028] | 0.631 [0.567, 0.689] | 0.028 [0.025, 0.030] | 0.026 |
| `punt` | 4,444 | 8.184 | 0.371 [0.360, 0.381] | 9.496 [9.256, 9.798] | 0.415 [0.406, 0.424] | 0.388 |
| `turnover` | 1,242 | 2.287 | 0.104 [0.098, 0.109] | 2.353 [2.253, 2.462] | 0.103 [0.099, 0.107] | 0.107 |
| `turnover_on_downs` | 648 | 1.193 | 0.054 [0.050, 0.058] | 1.157 [1.074, 1.236] | 0.051 [0.047, 0.054] | 0.038 |
| `defensive_touchdown` | 140 | 0.258 | 0.012 [0.010, 0.014] | 0.026 [0.014, 0.039] | 0.001 [0.001, 0.002] | 0.015 |
| `safety_against_offense` | 26 | 0.048 | 0.002 [0.001, 0.003] | 0.107 [0.080, 0.139] | 0.005 [0.004, 0.006] | 0.002 |
| `clock_expiration` | 322 | 0.593 | 0.027 [0.024, 0.029] | 1.766 [1.722, 1.802] | 0.077 [0.075, 0.079] | 0.027 |
| `kneel_end_game` | 525 | 0.967 | 0.044 [0.041, 0.046] | 0.065 [0.045, 0.084] | 0.003 [0.002, 0.004] | 0.040 |
| `kickoff_return_touchdown` | 10 | 0.018 | 0.001 [0.000, 0.001] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.002 |
| `no_offensive_snap` | 35 | 0.064 | 0.003 [0.002, 0.004] | 0.014 [0.005, 0.026] | 0.001 [0.000, 0.001] | 0.005 |
| `other` | 8 | 0.015 | 0.001 [0.000, 0.001] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.003 |
| all drives | 11,984 | 22.07 | – | 22.89 | – | – |

Keys: `totals.real_2022_2023.outcome:<ending>`, `stats.share:<ending>`, `stats.per_game:<ending>`.

### Field goals

Real: **2,122 field-goal attempts** on drives: **1,814 made**, **308 missed** (missed = attempts − made). Of the 308 not made, 305 drives are labelled
`field_goal_missed`. The other 3 are drives whose last snap was a missed kick returned for a touchdown (labelled `defensive_touchdown`) or a drive labelled `other`; the per-drive check is listed under Limitations.

| measure | real | real per game | sim per game [2.5–97.5%] | baseline 2010–2021 |
|---|---|---|---|---|
| field-goal attempts | 2,122 | 3.91 | 4.17 | – |
| made | 1,814 | 3.34 | 3.54 | – |
| missed | 308 | 0.57 | 0.63 | – |

| per drive / rate | real [95% CI] | sim [2.5–97.5%] | baseline |
|---|---|---|---|
| attempts per drive | 0.177 [0.170, 0.184] | 0.182 [0.176, 0.189] | 0.167 |
| make rate | 0.855 [0.840, 0.870] | 0.849 [0.836, 0.861] | 0.841 |
| mean attempt distance (yards) | 39.2 [38.7, 39.7] | 36.6 [36.2, 37.0] | 37.9 |

Simulated attempt distance is `yardline_100 + 17` (the engine has no kick distance). Real distance is nflverse `kick_distance`.

Make rate by distance (real vs sim vs baseline):

| distance | real [95% CI] | sim [2.5–97.5%] | baseline |
|---|---|---|---|
| <=29 | 0.979 [0.966, 0.991] | 0.973 [0.962, 0.982] | 0.974 |
| 30-34 | 0.959 [0.935, 0.979] | 0.935 [0.909, 0.968] | 0.934 |
| 35-39 | 0.909 [0.877, 0.941] | 0.879 [0.832, 0.915] | 0.880 |
| 40-44 | 0.842 [0.801, 0.883] | 0.822 [0.775, 0.863] | 0.819 |
| 45-49 | 0.758 [0.706, 0.807] | 0.734 [0.686, 0.784] | 0.730 |
| 50-54 | 0.736 [0.679, 0.789] | 0.669 [0.614, 0.727] | 0.669 |
| 55+ | 0.594 [0.515, 0.669] | 0.497 [0.412, 0.561] | 0.494 |

## 2. Per-drive measures

| measure | real [95% CI] | sim [2.5–97.5%] | baseline 2010–2021 |
|---|---|---|---|
| snaps per drive (incl. punts, FG) | 6.26 [6.20, 6.32] | 6.20 [6.14, 6.26] | 6.09 |
| run and pass snaps per drive | 5.56 [5.50, 5.63] | 5.45 [5.39, 5.52] | 5.38 |
| net offensive yards per drive | 30.4 [29.9, 31.0] | 30.1 [29.6, 30.6] | 30.1 |
| first downs per drive | 1.485 [1.455, 1.517] | 1.447 [1.422, 1.483] | 1.451 |
| elapsed minutes per drive | 2.73 [2.70, 2.76] | 2.61 [2.58, 2.65] | 2.63 |
| offensive points per drive (excl. PAT) | 1.692 [1.646, 1.739] | 1.449 [1.411, 1.487] | 1.672 |
| turnovers per drive | 0.119 [0.113, 0.124] | 0.103 [0.099, 0.107] | 0.123 |
| drives per game (both teams) | 22.07 [21.81, 22.36] | 22.89 [22.55, 23.12] | 23.06 |

## 3. Third downs, fourth downs and the red zone

| measure | real [95% CI] | sim [2.5–97.5%] | baseline |
|---|---|---|---|
| third-down snaps per drive | 1.152 [1.137, 1.166] | 1.142 [1.131, 1.156] | 1.106 |
| third-down conversion (first down or TD) | 0.404 [0.396, 0.413] | 0.387 [0.380, 0.396] | 0.404 |
| fourth downs: share of 4th-down snaps that go (vs punt or FG) | 0.188 [0.178, 0.197] | 0.144 [0.137, 0.150] | 0.136 |
| fourth-down go conversion | 0.515 [0.488, 0.541] | 0.463 [0.439, 0.490] | 0.505 |
| red-zone entries per drive (snap at or inside the 20) | 0.290 [0.282, 0.299] | 0.278 [0.270, 0.285] | 0.284 |
| red-zone entries that score a TD | 0.549 [0.532, 0.566] | 0.482 [0.467, 0.495] | 0.551 |

Third-down conversion by distance:

| distance | real [95% CI] | sim [2.5–97.5%] | baseline |
|---|---|---|---|
| 1-2 | 0.643 [0.625, 0.661] | 0.599 [0.580, 0.618] | 0.623 |
| 3-4 | 0.501 [0.479, 0.523] | 0.486 [0.465, 0.503] | 0.498 |
| 5-7 | 0.404 [0.385, 0.422] | 0.384 [0.372, 0.396] | 0.418 |
| 8-9 | 0.325 [0.303, 0.348] | 0.285 [0.265, 0.305] | 0.335 |
| 10 | 0.269 [0.244, 0.296] | 0.231 [0.214, 0.251] | 0.303 |
| 11+ | 0.159 [0.146, 0.174] | 0.169 [0.154, 0.182] | 0.176 |

Fourth-down go share by starting field (yardline_100 bin):

| field | real [95% CI] | sim [2.5–97.5%] | baseline |
|---|---|---|---|
| 1-20 | 0.276 [0.250, 0.301] | 0.240 [0.220, 0.259] | 0.217 |
| 21-40 | 0.304 [0.280, 0.327] | 0.217 [0.199, 0.237] | 0.249 |
| 41-60 | 0.228 [0.208, 0.248] | 0.173 [0.155, 0.192] | 0.152 |
| 61-80 | 0.093 [0.082, 0.105] | 0.068 [0.059, 0.077] | 0.060 |
| 81-99 | 0.047 [0.032, 0.062] | 0.041 [0.028, 0.056] | 0.033 |

## 4. Outcomes conditioned on starting field and game state

Starting field is the drive's first snap, as yards from the opponent's goal (bin `1-20` is inside the red zone).

| start | share of drives: real / sim / base | TD share: real [CI] | TD share: sim [CI] | TD share: base | punt share: real / sim | FG made share: real / sim |
|---|---|---|---|---|---|---|
| 1-20 | 0.018 / 0.015 / 0.021 | 0.512 [0.441, 0.580] | 0.487 [0.422, 0.566] | 0.522 | 0.000 / 0.004 | 0.323 / 0.341 |
| 21-40 | 0.042 / 0.051 / 0.046 | 0.341 [0.299, 0.381] | 0.330 [0.303, 0.364] | 0.364 | 0.053 / 0.051 | 0.312 / 0.372 |
| 41-60 | 0.116 / 0.115 / 0.122 | 0.259 [0.235, 0.283] | 0.222 [0.202, 0.238] | 0.260 | 0.237 / 0.271 | 0.197 / 0.225 |
| 61-80 | 0.613 / 0.579 / 0.569 | 0.200 [0.190, 0.209] | 0.151 [0.143, 0.160] | 0.197 | 0.393 / 0.443 | 0.146 / 0.141 |
| 81-99 | 0.207 / 0.239 / 0.236 | 0.144 [0.130, 0.157] | 0.108 [0.098, 0.123] | 0.150 | 0.485 / 0.518 | 0.097 / 0.098 |

By quarter where the drive started (TD / FG made / punt / turnover share, real vs sim):

| quarter | TD real | TD sim | FG made real | FG made sim | punt real | punt sim | turnover real | turnover sim |
|---|---|---|---|---|---|---|---|---|
| Q1 | 0.227 | 0.187 | 0.166 | 0.175 | 0.445 | 0.453 | 0.085 | 0.101 |
| Q2 | 0.193 | 0.145 | 0.162 | 0.139 | 0.347 | 0.377 | 0.101 | 0.099 |
| Q3 | 0.234 | 0.184 | 0.163 | 0.174 | 0.417 | 0.437 | 0.103 | 0.109 |
| Q4_OT | 0.174 | 0.134 | 0.117 | 0.130 | 0.287 | 0.390 | 0.123 | 0.103 |

By score before the drive (offense minus defense):

| score | TD real | TD sim | punt real | punt sim | turnover real | turnover sim |
|---|---|---|---|---|---|---|
| trail_9+ | 0.228 | 0.165 | 0.291 | 0.351 | 0.139 | 0.137 |
| trail_1-8 | 0.210 | 0.163 | 0.355 | 0.410 | 0.127 | 0.114 |
| tied | 0.198 | 0.180 | 0.441 | 0.454 | 0.084 | 0.095 |
| lead_1-8 | 0.198 | 0.156 | 0.393 | 0.434 | 0.087 | 0.088 |
| lead_9+ | 0.191 | 0.147 | 0.371 | 0.415 | 0.066 | 0.073 |

## 4a. Where the touchdown-share gap comes from

Touchdowns per drive, real 0.206 vs sim 0.163: a gap of 0.043. Drives that entered the red zone and scored, real 0.159 vs sim 0.134, account for 0.025 of the gap (59%); touchdowns from outside the red zone account for the rest. Keys: `totals.*.rz_td`, `totals.*.outcome:touchdown`, `totals.*.drives`.

## 5. Clock, kneels and possession transitions

Late = last 120 seconds of the second half, or of overtime, of any period-2, period-4 or overtime snap. Lead, tied and trail are the
offense's score before the snap.

| measure | real [95% CI] | sim [2.5–97.5%] | baseline |
|---|---|---|---|
| snaps in the late window, leading | 0.145 [0.140, 0.152] | 0.080 [0.076, 0.084] | 0.131 |
| kneel share of late snaps, leading | 0.187 [0.172, 0.203] | 0.040 [0.032, 0.049] | 0.196 |
| kneel share of early snaps, leading | 0.000 [0.000, 0.000] | 0.025 [0.023, 0.027] | 0.000 |
| run share of late snaps, leading | 0.247 [0.229, 0.265] | 0.408 [0.384, 0.432] | 0.248 |
| kneel share of late snaps, trailing | 0.024 [0.020, 0.029] | 0.004 [0.002, 0.007] | 0.018 |
| kneel share of late snaps, tied | 0.037 [0.025, 0.052] | 0.007 [0.000, 0.016] | 0.038 |
| kneel-ended drives per game | 0.967 | 0.065 [0.045, 0.084] | – |
| clock-expiration drives per game | 0.593 | 1.766 [1.722, 1.802] | – |
| elapsed minutes per drive | 2.73 [2.70, 2.76] | 2.61 [2.58, 2.65] | 2.63 |

Keys: `stats.late_*`, `stats.per_game:*`, `stats.duration_min_per_drive`.

## 6. Yardage by down and distance

Yards per attempt, passes and runs, for selected down-and-distance cells (real [95% CI], sim, baseline):

| cell | real [95% CI] | sim [2.5–97.5%] | baseline |
|---|---|---|---|
| pass, 1st and 5–7 | 4.30 [3.53, 5.15] | 2.66 [2.25, 3.02] | 4.27 |
| pass, 2nd and 8–9 | 6.75 [6.38, 7.13] | 7.89 [7.50, 8.25] | 7.34 |
| pass, 2nd and 5–7 | 6.81 [6.49, 7.15] | 7.44 [7.07, 7.71] | 7.01 |
| pass, 3rd and 5–7 | 7.29 [6.89, 7.69] | 6.65 [6.36, 7.00] | 7.13 |
| pass, 3rd and 10 | 7.73 [7.04, 8.46] | 6.65 [6.23, 7.29] | 7.68 |
| run, 3rd and 5–7 | 4.59 [3.94, 5.22] | 4.83 [4.08, 5.60] | 4.73 |
| run, 1st and 5–7 | 2.73 [2.41, 3.06] | 2.46 [2.15, 2.69] | 3.05 |

## 7. Consecutive drives and team scoring

| measure | real [95% CI] | sim [2.5–97.5%] | baseline |
|---|---|---|---|
| next drive is a TD, after a scoring drive | 0.196 [0.184, 0.208] | 0.147 [0.136, 0.159] | 0.188 |
| next drive scores, after a scoring drive | 0.330 [0.316, 0.345] | 0.281 [0.266, 0.295] | 0.305 |
| next drive is a TD, after a non-scoring drive | 0.210 [0.200, 0.220] | 0.170 [0.163, 0.176] | 0.217 |
| next drive scores, after a non-scoring drive | 0.371 [0.359, 0.383] | 0.334 [0.324, 0.343] | 0.370 |
| kickoff touchbacks per kickoff | 0.664 [0.644, 0.683] | 0.513 [0.498, 0.526] | 0.513 |
| points per team-game | 21.825 [21.259, 22.400] | 18.588 [18.168, 19.004] | 22.853 |

Starting field of the drive after a scoring drive (kickoff spot):

| start | real | sim | baseline |
|---|---|---|---|
| 21-40 | 0.004 | 0.006 | 0.008 |
| 41-60 | 0.042 | 0.047 | 0.053 |
| 61-80 | 0.865 | 0.803 | 0.770 |
| 81-99 | 0.080 | 0.141 | 0.150 |

Points per team-game, pooled distribution (real 1,086 team-games; sim 108,600 across 100 trials):

| source | mean | SD | p10 | median | p90 |
|---|---|---|---|---|---|
| real 2022–2023 | 21.83 | 9.66 | 10 | 21 | 34 |
| sim, pooled over trials | 18.59 | 8.30 | 9 | 18 | 30 |
| baseline 2010–2021 | 22.85 | 10.18 | 10 | 23 | 36 |

## 8. Representative sequences

The file [results/drive-examples-2022-2023.txt](results/drive-examples-2022-2023.txt) prints up to two real drives (2023 season, in game order)
and up to two simulated drives (trial 0 of the first 60 test games, in season order) for each ending that the sample contains,
snap by snap: down and distance, yard line as yards from the goal, yards, elapsed seconds, quarter and clock, and points for the
offense and defense. Two real and two simulated `kneel_end_game` drives are shown. The sample contains two real `no_offensive_snap`
drives and no simulated one.

## 9. Prioritized failure diagnoses

Each diagnosis names the stage that produces it. No model parameter was changed; each entry says what the next, parameter-free check would be.

**D1. Play selection and the clock: the simulator does not condition play calls on time remaining.** (Stage: play selection and clock transitions.)
- Late in a half or game while leading, real teams kneel on 0.187 of snaps; the simulator on 0.040. Early in a quarter while leading, the simulator kneels on 0.025 of snaps; real teams on 0.000.
- Kneel-ended drives per game: real 0.967, sim 0.065. Clock-expiration drives per game: real 0.593, sim 1.766.
- Late-lead run share: real 0.247, sim 0.408. Elapsed minutes per drive: real 2.73, sim 2.61.
- Mechanism: the call table conditions on down, distance, field, score and a quarter bin in which every fourth quarter and overtime snap falls together (`4+`). Nothing knows the time remaining, so kneels are spread across the quarter rather than concentrated in the final two minutes. Run-off per play is also context-free.
- Next check (no parameter change): add a last-two-minutes context to the call table and compare the late-window and kneel-ended measures above.

**D2. Pass yardage is pooled across downs.** (Stage: yardage outcomes, which feed first-down and third-down conversion.)
- Yards per pass attempt, third and fifth to seventh to go: real 7.29, sim 6.65 (baseline 7.13). Third-down conversion, real 0.404 vs sim 0.387, is below the real rate at every distance except 11+ to go (section 3).
- Completion rates are close to the training rates and do not explain the gap: five to seven to go, second down 0.68 real against 0.65 in training; third down 0.59 against 0.58.
- Yards per completion differ by down at the same distance in the real data (five to seven to go: about 6.9 on first down, 10.0 on second, 12.3 on third, 2022–2023). The table `pass_yards` is keyed on distance and field only, so it cannot represent this. Its pooled mean for five to seven to go is about 10.5 yards, which is too long for first down and too short for third down.
- Scope of attribution: the third-down shortfall is consistent with the pooled table. The first-down cell (real 4.30, sim 2.66) is larger than the pooled table alone predicts, so part of it comes from the field-position mix of simulated first-down states. This report does not decompose that part.

**D3. Fourth-down decisions: the simulator goes for it less and punts more.** (Stage: fourth-down decisions.)
- Fourth-down go share: real 0.188, sim 0.144, baseline 2010–2021 0.136. Punts per game: real 8.18, sim 9.50.
- The simulator's go share is below the real rate in every starting-field bin (for example, 21–40: real 0.304, sim 0.217). Go conversion is lower too: real 0.515, sim 0.463.
- The 2010–2021 baseline sits between the two in several bins, so part of the gap looks like change over time (the 2022–2023 seasons are more aggressive) and part like the decision layer itself. This report does not separate them.
- Effect on drives: more punts means more possessions per game (drives per game: real 22.07, sim 22.89) and fewer scoring drives.

**D4. Kickoff touchbacks and starting field position: an era effect in the training data.** (Stage: field position.)
- Touchbacks per kickoff: real 0.664, sim 0.513 (equal to the 2010–2021 baseline). Drives starting at the opponent's 1–20: real 0.018, sim 0.015.
- The drive after a scoring drive starts deep in its own territory (yardline 81–99) more often in the simulation: real 0.080, sim 0.141. Kickoff distributions come from 2010–2021; the touchback rate of 2022–2023 is not in the training data. This is not a bug in the engine. Fixing it means retraining on newer kickoffs, which changes the evaluation boundary, so it needs a decision first.

**D5. Defensive touchdowns are not modelled.** (Stage: unsupported mechanic.)
- Real drives ending in a defensive touchdown: 0.258 per game; simulated: 0.026. Interception and fumble return yards are sampled as zero, so a pick-six or fumble return never occurs. At about six points each before extra points, the real figure is roughly 1.5 points per game (both teams).

**D6. Field-goal distances are shorter in the simulation, but make rates by distance match the history.** (Stage: kicking logic and where attempts occur.)
- Make rates by distance agree with the 2010–2021 baseline in every bin; the simulation is a few points lower in the 45–55 range (section 1). Mean attempt distance: real 39.2, sim 36.6.
- The difference therefore comes from where attempts are taken, which follows from D2 and D3, not from kicking accuracy.

**D7. Red-zone touchdown conversion is lower in the simulation, and this report does not yet attribute it.** (Stage: unresolved; likely D2 and D3.)
- Red-zone entries per drive: real 0.290, sim 0.278; entries that score a touchdown: real 0.549, sim 0.482 (baseline 0.551).
- The tallies do not record red-zone snap outcomes, so the cause within the red zone is not measured here. Next check: tabulate red-zone snaps by down, distance and outcome.

**D8. Definitions: the PAT rate is not comparable.** The real PAT rate includes two-point tries, and the simulator generates none. Compare extra-point rates only.

## 10. Limitations and what is not claimed

- Not a claim of realistic game simulation. Plausible drive counts and per-drive yards do not establish that drives combine correctly; the outcome gaps above are exactly that.
- Team strength is not an input. The engine is team-agnostic apart from playbook call weights, so no team quality is tested here.
- Real and simulated drive definitions match, but two conventions differ: the simulated attempt distance is `yardline_100 + 17`, and two-point tries are absent from the simulation.
- Per-drive check (round 2): of the four real drives with a field-goal attempt not labelled as a field-goal ending, two were missed kicks returned for a touchdown and two are nflverse ordering anomalies (a made kick followed by a same-offense snap in the drive order). The anomalies are labelled `other` (8 real drives in total, 0.015 per game).
- `no_offensive_snap` drives (kickoffs with no snap before a period ends) occur 0.064 per game in real data and 0.014 per game in simulation.
- Intervals for simulated values measure the simulator's variability across 100 seeded trials of the same 543 games, not uncertainty about real games. The baseline is a single 2010–2021 point estimate.

## Reproducibility

Round 1 and round 2 simulations use the same seeds. Their simulated outcome means agree exactly; round 2 adds counters only. Shards were run with `--shards 3`, and the report reads all three shard files.

