# SLC 2025 realism results: V1, V1.5 and V2

> Post-audit interpretation correction: the historical simulated target total is assigned pass volume (throwaways/spikes are absent), and modeled lineup counts are skill-position appearances rather than full player snaps. Any interpretation of these quantities as independent receiver-volume skill or complete snap realism is withdrawn. The raw historical figures below are preserved; they are not reruns of the repaired engine. See [SLC audit remediation](slc-code-audit-2026-11-08/README.md).

Date: 2026-11-05
Status: **development-exposed retrospective result.** The 2025 season was used while the play-call layer was being developed (the penalty settings in the playcall artifact were chosen in an evaluation that looked at 2025). These numbers are not a clean holdout and are not a forecast. The 2026 prospective results are kept separate.

Scope: 272 scheduled 2025 regular-season games, 3 arms, 30 seeds per game. 271 games (542 team-games) are scored. Game `2025_07_GB_ARI` is excluded because all 30 seeds errored in all three arms.

Scripts: `scripts/nfl_sequence/realism_2025/`. Aggregate outputs: this folder. Raw batches and per-seed tables stay on the fast host, unchanged.

## Bottom line

1. **Run integrity is clean, but no simulated seed is valid by the engine's own definition.** `valid_full_game` is 0 for every seed in every arm, by construction: the 2025 inputs are an `exploratory_replay`, so the snapshot is not verified. The seeds that completed a game are 7,778 (V1), 7,803 (V1.5) and 7,863 (V2) of 8,160 each.
2. **None of the arms is realistic on play volume, yardage, sacks or turnovers.** The simulated team-game has about 7.6 more scrimmage plays than observed (68.1 vs 60.6), about 57 more scrimmage yards (385 vs 328), roughly half the observed sack rate, and about 28 percent fewer turnovers (0.79 vs 1.10). Drives, points and touchdowns match closely.
3. **Game-level accuracy is at or below a no-model baseline** for plays, yards, drives, turnovers, three-and-outs and run share. Each simulated team-game is compared with the leave-one-game-out league mean as a naive predictor. Points (7.7 to 7.8 vs 8.0) and touchdowns are the only metrics where any arm is closer.
4. **V1.5's advantage over V2 does not survive on the aggregate drive, half and total distributions.** The paired difference is −0.005 in normalized error (95% CI −0.012 to +0.003): no distinguishable difference. V2 is better on drive-termination structure (three-and-outs, punts, drive count). **V1.5 keeps an advantage on named-player workload allocation**: against an observed RB1 carry share of 0.588, V1.5 gives 0.615 and V2 gives 0.532. V2 also moves the WR1 target share further from the observed value (0.344 vs 0.315; observed 0.295).
5. **The arms are close on almost everything.** The largest V2-vs-V1.5 differences are in the RB1 share, the WR1 share, three-and-outs and the drive-count distribution. The remaining metrics differ by less than their interval.

## 1. Run integrity and seed validity

### 1a. Batch verification (`verify_batches.py`, run on the fast host)

| Check | Result |
|---|---|
| Manifest rows / files hashed / mismatches (size or SHA-256) | 816 / 816 / 0 |
| Games with all three arms | 272 of 272 |
| Games with identical seed sets across arms | 272 of 272 |
| Games with identical schedule, rosters, replay, roster snapshot id, as-of time, teams | 272 of 272 |

The manifest covers only the 816 `.json.gz` batch files. Each game also has a `.boxscores.jsonl.gz`, a `.seeds.jsonl.gz` and a `.log` file (272 of each per arm). The box-score files were read for the cross-check, and the others were not used. None of the three is in the manifest, so the manifest does not cover the full per-arm output. This is a gap in the committed manifest, not in the run.

### 1b. Seed outcomes per model (8,160 seeds per arm)

| Category | V1 | V1.5 | V2 | Definition |
|---|---|---|---|---|
| valid (`valid_full_game` true) | 0 | 0 | 0 | Engine gate: snapshot verified AND complete AND no blocker AND no guarded transition AND no unsupported rule. The snapshot is `exploratory_replay`, so `verified` is false for every game. |
| completed, untied (regulation or overtime) | 7,766 | 7,794 | 7,855 | `complete_regulation` or `complete_overtime`, no tie |
| tied at the end of overtime | 12 | 9 | 8 | `complete_game` true, `final_tie` true. Overtime ties are legal in regular season, so they count as completed. |
| **completed total** | **7,778** | **7,803** | **7,863** | untied plus tied; used for every comparison |
| blocked | 352 | 327 | 267 | `status` blocked (a blocker recorded) |
| incomplete (simulation_error) | 30 | 30 | 30 | all in `2025_07_GB_ARI`: "QB 00-0035228 has no eligible target roles on team ARI" |

The `valid` column is zero by construction, so "valid" in the request is answered as "completed". Any claim that a seed produced a valid full game would need a verified input snapshot first.

### 1c. Pairing and what it does and does not establish

- Seed numbers 1 to 30 are the same in all three arms for every game, and the shared pregame inputs match (see table above). The `snapshot_sha256` differs by arm because each arm records its own model reference; the shared components do not.
- **The random streams are not shared across arms.** V2 keys its streams by `stream_root_sha256`. V1 and V1.5 key theirs by their own `snapshot_sha256`, which differs between arms. "Paired seed IDs" therefore means the same seed index, not the same random draws. All comparisons here are paired by game and use game-clustered intervals, which do not depend on RNG sharing.

### 1d. Export inconsistencies found and how they were handled

- **Boxscore record status.** Every completed seed carries `status: "incomplete"` in its boxscore record, while the batch summary says `complete_regulation` or `complete_overtime`. The cause is not yet known: `quarter_by_quarter.complete` is true in 27 of 29 non-blocked records of one checked game, so it does not explain the label. The batch summary is used as authoritative for completion. The mismatch is reported in `boxscore_vs_outcome_status.csv`, and the exporter's status field should be fixed before anyone reads it.
- **Snap counts exist for V2 only.** The V1 and V1.5 realism exports have `lineup: null`, so their player snap counts are absent, not zero. Snap metrics are reported as "not exported" for those arms.
- **Touchdowns by half.** These were not in the first extraction and were added. In 98.3% of observed team-games, every touchdown falls in a regulation half. The rest include an overtime touchdown.

### 1e. Observed data: a crosswalk bug, found and fixed

The first observed extraction mapped PFR snap-count ids to GSIS ids with `dict(zip(pfr_id.dropna(), gsis_id.dropna()))`. Dropping nulls from each column separately shifted the pairs, so for example `ConnJa00` mapped to the wrong player and every observed rusher showed zero snaps. The fix drops incomplete rows before zipping and fails on duplicate PFR ids. All observed outputs in this folder come from the corrected extraction.

## 2. Method

- **Unit.** A team-game. The simulated value is the mean over the arm's completed seeds, with the same definitions applied to each seed as to the observed game (`seed_metrics.py` and `observed_2025_metrics.py` document them field by field).
- **Game-level accuracy.** Mean absolute error between each simulated team-game mean and the observed team-game, averaged over games. A naive baseline predicts each team-game as the mean of all other 2025 team-games (leave-one-game-out).
- **Season-level realism.** Bias, standardized bias (bias divided by the observed SD), pooled distributions (KS distance, quantiles), extreme-event shares, and yardage bucket shares.
- **Natural variability.** Observed leave-one-game-out baselines, league-wide and within team. Each simulated seed set is scored with the probability integral transform (PIT) of the observed value and with the coverage of its 10th to 90th percentile interval (target 0.80).
- **Uncertainty.** Resampling of games (2,000 draws, seed 2026). Arm differences are paired by game.
- **What is not scored.** No winner, no margin and no single-game result sign.
- **Yards after catch.** Not compared. The simulator records no air yards or YAC, so there is no event-level comparison to make.
- **Scrambles.** nflverse `run` includes quarterback scrambles. The simulator's `decision_type run` is its own label. This is a definitional difference, not tuned away.

## 3. Side-by-side tables

Standardized bias is the season-mean bias divided by the observed SD across team-games. "ΔMAE V2 minus V1.5" is the paired game-level difference in mean absolute error (negative means V2 is closer), with its 95% game-clustered interval.

### 3a. Drive level

| Metric | Observed | V1 | V1.5 | V2 | Std bias V1 / V1.5 / V2 | ΔMAE V2 − V1.5 (95% CI) |
|---|---:|---:|---:|---:|---|---|
| Drives per team-game | 10.48 | 10.57 | 10.52 | 10.51 | 0.06 / 0.03 / 0.02 | −0.03 (−0.07, 0.01) |
| Scrimmage plays per drive | 5.87 | 6.56 | 6.57 | 6.59 | 0.63 / 0.65 / 0.66 | +0.01 (−0.02, 0.03) |
| Scrimmage yards per drive | 31.9 | 37.1 | 37.1 | 37.3 | 0.57 / 0.56 / 0.58 | +0.06 (−0.12, 0.24) |
| Points per drive | 2.23 | 2.20 | 2.20 | 2.20 | −0.03 / −0.03 / −0.03 | −0.02 (−0.03, 0.00) |
| Scoring-drive rate | 0.404 | 0.415 | 0.416 | 0.418 | 0.07 / 0.07 / 0.08 | 0.00 (−0.00, 0.00) |
| Three-and-outs per team-game | 2.08 | 1.83 | 1.84 | 1.94 | −0.18 / −0.17 / −0.10 | 0.00 (−0.03, 0.03) |
| Punts per team-game | 3.56 | 3.24 | 3.26 | 3.33 | −0.18 / −0.17 / −0.13 | −0.00 (−0.04, 0.03) |
| Turnovers (plays) per team-game | 1.10 | 0.82 | 0.78 | 0.79 | −0.25 / −0.29 / −0.28 | −0.00 (−0.02, 0.02) |
| Turnovers on downs per team-game | 0.67 | 0.82 | 0.83 | 0.82 | 0.17 / 0.18 / 0.17 | −0.02 (−0.03, 0.00) |
| Touchdowns per team-game | 2.52 | 2.48 | 2.46 | 2.45 | −0.03 / −0.04 / −0.04 | −0.03 (−0.05, 0.00) |
| Field-goal attempts per team-game | 2.00 | 2.18 | 2.18 | 2.09 | 0.14 / 0.13 / 0.07 | −0.01 (−0.03, 0.01) |
| Field goals made per team-game | 1.71 | 1.83 | 1.83 | 1.85 | 0.10 / 0.10 / 0.11 | −0.00 (−0.03, 0.02) |

### 3b. Half level

| Metric | Observed | V1 | V1.5 | V2 | Std bias V1 / V1.5 / V2 |
|---|---:|---:|---:|---:|---|
| Scrimmage plays, first half | 29.8 | 34.2 | 34.1 | 34.1 | 0.76 / 0.74 / 0.75 |
| Scrimmage plays, second half | 30.4 | 34.1 | 34.0 | 34.0 | 0.57 / 0.55 / 0.55 |
| Drives, first half | 5.17 | 5.29 | 5.25 | 5.26 | 0.11 / 0.07 / 0.08 |
| Drives, second half | 5.31 | 5.28 | 5.27 | 5.25 | −0.02 / −0.03 / −0.05 |
| Points, first half | 11.55 | 11.41 | 11.36 | 11.42 | −0.02 / −0.03 / −0.02 |
| Points, second half (incl. OT) | 11.46 | 11.51 | 11.41 | 11.37 | 0.01 / −0.01 / −0.01 |
| Touchdowns, first half | 1.22 | 1.24 | 1.24 | 1.24 | 0.02 / 0.01 / 0.02 |
| Touchdowns, second half | 1.28 | 1.24 | 1.22 | 1.21 | −0.04 / −0.05 / −0.07 |
| Run share, first half | 0.429 | 0.444 | 0.442 | 0.443 | 0.15 / 0.13 / 0.14 |
| Run share, second half | 0.439 | 0.449 | 0.451 | 0.448 | 0.07 / 0.08 / 0.06 |

### 3c. Season totals and game-level accuracy against the naive baseline

| Metric | Observed | V1 | V1.5 | V2 | MAE V1 / V1.5 / V2 | Naive MAE |
|---|---:|---:|---:|---:|---|---:|
| Scrimmage plays | 60.6 | 68.3 | 68.1 | 68.1 | 9.68 / 9.54 / 9.57 | 6.84 |
| Scrimmage yards | 327.8 | 385.6 | 383.4 | 384.6 | 81.8 / 79.6 / 79.7 | 67.3 |
| Points | 23.0 | 22.9 | 22.8 | 22.8 | 7.81 / 7.84 / 7.71 | 7.96 |
| Run plays | 26.1 | 30.9 | 30.8 | 30.7 | 7.29 / 7.45 / 7.29 | n/a |
| Pass plays | 34.4 | 37.4 | 37.3 | 37.4 | 7.37 / 7.38 / 7.42 | n/a |
| Run share of plays | 0.432 | 0.447 | 0.447 | 0.446 | 0.088 / 0.089 / 0.087 | 0.083 |

Drives, touchdowns, turnovers and three-and-outs have naive MAEs of 1.24, 1.18, 0.86 and 1.13. Each arm's MAE for these is at or above the naive value except touchdowns (1.13 to 1.16 for the arms).

### 3d. Named-player allocation (team-game shares, V2 snap metrics only where exported)

| Metric | Observed | V1 | V1.5 | V2 | Std bias V1 / V1.5 / V2 |
|---|---:|---:|---:|---:|---|
| Team carries | 26.1 | 30.9 | 30.8 | 30.7 | 0.67 / 0.66 / 0.65 |
| Team targets | 30.7 | 36.5 | 36.4 | 36.5 | 0.76 / 0.75 / 0.76 |
| Team receptions | 20.6 | 23.7 | 23.7 | 23.8 | 0.56 / 0.56 / 0.57 |
| Team pass attempts (by passer) | 32.1 | 36.5 | 36.4 | 36.5 | 0.56 / 0.55 / 0.56 |
| **RB1 share of carries** | 0.588 | 0.652 | 0.615 | 0.532 | **0.47 / 0.20 / −0.41** |
| RB2 share of carries | 0.249 | 0.205 | 0.218 | 0.228 | −0.45 / −0.32 / −0.22 |
| **WR1 share of targets** | 0.295 | 0.347 | 0.315 | 0.344 | **0.77 / 0.31 / 0.73** |
| WR2 share of targets | 0.205 | 0.204 | 0.199 | 0.206 | −0.01 / −0.15 / 0.03 |
| Top carrier is the observed top carrier (share of seeds) | n/a | 0.489 | 0.578 | 0.587 | n/a |
| Top target is the observed top target (share of seeds) | n/a | 0.278 | 0.315 | 0.328 | n/a |
| Top passer is the observed top passer (share of seeds) | n/a | 0.893 | 0.893 | 0.893 | n/a |
| Team offensive snaps (V2 only) | 64.2 | not exported | not exported | 68.1 | n/a / n/a / 0.43 |
| RB1 snap share (V2 only) | 0.636 | not exported | not exported | 0.613 | n/a / n/a / −0.15 |

The like-for-like allocation family (the eight metrics every arm has: team carries, targets, receptions, pass attempts, RB1 and RB2 carry shares, WR1 and WR2 target shares) has mean absolute standardized bias 0.532 for V1, **0.436 for V1.5** and 0.492 for V2.

Team snaps are a definitional caveat: the simulator's team snap count is about equal to its scrimmage plays, while the observed snap-count file also includes punts and other non-scrimmage snaps. Read the V2 snap rows as directional only.

### 3e. Yardage distribution (pooled shares of plays)

| Bucket | Obs run | V1 run | V1.5 run | V2 run | Obs pass | V1 pass | V1.5 pass | V2 pass |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Negative | 0.084 | 0.103 | 0.100 | 0.100 | 0.080 | 0.037 | 0.037 | 0.037 |
| Zero | 0.080 | 0.075 | 0.074 | 0.074 | 0.333 | 0.346 | 0.345 | 0.344 |
| 1 to 3 | 0.370 | 0.350 | 0.355 | 0.355 | 0.068 | 0.078 | 0.079 | 0.079 |
| 4 to 9 | 0.354 | 0.348 | 0.350 | 0.351 | 0.252 | 0.271 | 0.272 | 0.271 |
| 10 to 19 | 0.089 | 0.097 | 0.096 | 0.096 | 0.181 | 0.182 | 0.181 | 0.182 |
| 20 to 39 | 0.018 | 0.022 | 0.021 | 0.021 | 0.073 | 0.075 | 0.074 | 0.074 |
| 40 or more | 0.005 | 0.004 | 0.003 | 0.003 | 0.012 | 0.012 | 0.012 | 0.012 |

The "pass" negative bucket is sacks. The arms have 3.7 percent sacks against 8.0 percent observed.

Yardage total-variation distance (run and pass, lower is closer): V1 0.038, V1.5 0.035, V2 0.034. The difference between arms is inside the bootstrap noise.

Team-game extremes (share of team-games):

| Event | Observed | V1 | V1.5 | V2 |
|---|---:|---:|---:|---:|
| 35 or more points | 12.2% | 9.1% | 9.0% | 9.3% |
| 6 or fewer points | 4.6% | 2.6% | 3.0% | 3.0% |
| 500 or more scrimmage yards | 2.2% | 6.5% | 6.7% | 6.9% |
| 200 or fewer scrimmage yards | 7.0% | 0.7% | 1.0% | 1.0% |

### 3f. Season distributions and calibration against natural variability

| Metric | KS V1 / V1.5 / V2 | PIT mean (0.5 is calibrated) V1 / V1.5 / V2 | 80% coverage (target 0.80) V1 / V1.5 / V2 | Sim SD ÷ league LOO SD V1 / V1.5 / V2 |
|---|---|---|---|---|
| Points | 0.047 / 0.039 / 0.040 | 0.507 / 0.506 / 0.509 | 0.70 / 0.70 / 0.69 | 0.83 / 0.83 / 0.82 |
| Scrimmage yards | 0.294 / 0.278 / 0.284 | 0.298 / 0.304 / 0.300 | 0.59 / 0.60 / 0.60 | 0.84 / 0.84 / 0.84 |
| Scrimmage plays | 0.362 / 0.349 / 0.355 | 0.264 / 0.270 / 0.270 | 0.62 / 0.64 / 0.63 | 1.00 / 1.02 / 1.02 |
| Turnovers | 0.107 / 0.125 / 0.122 | 0.568 / 0.583 / 0.578 | 0.83 / 0.83 / 0.82 | 0.80 / 0.78 / 0.78 |
| Touchdowns | 0.034 / 0.031 / 0.032 | 0.507 / 0.509 / 0.511 | 0.82 / 0.83 / 0.83 | 0.88 / 0.87 / 0.87 |
| Drives | 0.039 / 0.026 / 0.018 | 0.482 / 0.492 / 0.494 | 0.82 / 0.80 / 0.83 | 0.94 / 0.94 / 0.94 |
| Three-and-outs | 0.074 / 0.073 / 0.045 | 0.548 / 0.549 / 0.527 | 0.83 / 0.82 / 0.82 | 0.90 / 0.90 / 0.92 |
| Run share of plays | 0.093 / 0.091 / 0.087 | 0.460 / 0.461 / 0.461 | 0.78 / 0.75 / 0.76 | 1.07 / 1.05 / 1.05 |

The points distribution is calibrated in location (PIT about 0.51), but too narrow: the simulated spread is about 0.82 of the observed game-to-game spread, and 80% intervals cover only 0.69 to 0.70 of observed values. Yards are off in location (PIT about 0.30). Plays are too high in location (PIT about 0.27). Turnovers are too low (PIT about 0.58).

Family summary (`table_family_summary.csv`):

| Family | V1 | V1.5 | V2 | Paired difference V2 minus V1.5 (95% CI) |
|---|---:|---:|---:|---|
| Drive, half and total metrics: mean normalized game-level MAE (28 metrics) | 0.865 | 0.866 | 0.861 | −0.005 (−0.012, +0.003) |
| Variability: mean KS distance (8 metrics) | 0.131 | 0.127 | 0.123 | not computed as a paired interval |
| Yardage: total variation distance | 0.038 | 0.035 | 0.034 | not computed as a paired interval |
| Extremes: mean absolute share error | 0.039 | 0.038 | 0.038 | not computed as a paired interval |
| Player allocation, like-for-like (8 metrics): mean absolute standardized bias | 0.532 | 0.436 | 0.492 | not computed as a paired interval |

## 4. Does V1.5's advantage over V2 survive a distributional, workload-level comparison?

Partly. Under the drive, half and total distributions, there is no difference that the data can separate: the paired gap is −0.005, with a CI that includes zero. V2 is nominally better on the drive-count and three-and-out distributions (KS 0.018 vs 0.026 and 0.045 vs 0.073) and on punts and turnovers on downs. V1.5 is nominally better on the scrimmage-play and scrimmage-yard distributions (KS 0.349 vs 0.355 and 0.278 vs 0.284).

The workload is where V1.5 keeps its advantage. The RB1 carry share is 0.615 under V1.5 and 0.532 under V2 against an observed 0.588; the V2 deviation is about twice the V1.5 deviation in the opposite direction. The WR1 target share is overstated by all arms, and V2 overstates it more (0.344 vs 0.315, observed 0.295). The like-for-like allocation family favors V1.5 (0.436 vs 0.492). The bootstrap intervals for the RB1 and WR1 shares do not overlap between V1.5 and V2.

So the V1.5 advantage is real for who gets the touches, and absent for the aggregate drive and total distributions.

## 5. The five largest realism deficiencies

Ranked by the size of the standardized bias for V2 and by how far game-level error sits from the naive baseline. "Likely component" names the engine layer a targeted ablation should test; it is a hypothesis from these tables, not a verified attribution.

| # | Deficiency | Evidence (V1 / V1.5 / V2) | Likely component (hypothesis) | V2 vs V1.5 |
|---|---|---|---|---|
| 1 | **Too many scrimmage plays per drive and per game.** Drives match, so the excess is inside drives. | Plays per team-game +7.6 (std 0.89 / 0.87 / 0.88). Run plays +4.6 to +4.8, pass plays +3.0. Plays per drive 6.6 vs 5.9. Game MAE 9.6 vs naive 6.8. | Play-call layer (run/pass decision and drive continuation). Yards per play is also high (5.65 vs 5.41), so the play-count excess is not explained by short plays. | Unchanged (std 0.88 vs 0.87). |
| 2 | **Yardage is too high on average and wrong in the tails.** | Yards per drive +5.2 to +5.4 (std 0.57 / 0.56 / 0.58). Team-game yards about +57 (std 0.68 / 0.65 / 0.67). PIT 0.30. Team-games of 200 yards or fewer: 1% vs 7% observed. 500 or more: 6.9% vs 2.2%. | Play-outcome yardage sampler: its location and its spread. | Unchanged (KS 0.284 vs 0.278). |
| 3 | **Sacks and negative pass plays are about half the observed rate.** Negative run plays are too common, which may be where that loss-of-yards mass ends up. | Pass negative share 3.7% vs 8.0% observed, identical in all arms. Run negative share 10.0% vs 8.4%. | Pass-outcome sampler (sack and loss-of-yards outcomes). | Unchanged. |
| 4 | **Turnovers are too rare, and turnovers on downs too common.** Punts and three-and-outs are short. This looks like a single fourth-down and turnover balance. | Turnovers 0.79 vs 1.10 (std −0.28, PIT 0.58). Turnovers on downs 0.82 vs 0.67 (std +0.17). Punts 3.33 vs 3.56. | Fourth-down decision (go vs punt) and interception and fumble generation. | V2 improves this family slightly: punts −0.13 vs −0.17, three-and-outs KS 0.045 vs 0.073, turnovers on downs +0.17 vs +0.18. |
| 5 | **Named-player workload allocation, especially the RB1 carry share and the WR1 target share.** | RB1 carry share 0.652 / 0.615 / 0.532 vs observed 0.588. WR1 target share 0.347 / 0.315 / 0.344 vs observed 0.295. RB2 share under by 0.02 to 0.04 in all arms. | Target-role and carry-share priors in the player-allocation layer (the playbook and target-role components that V2 changed). | **Worse in V2**: RB1 std −0.41 vs +0.20; WR1 std +0.73 vs +0.31. |

Items 1 and 2 are the largest. Both are the same in every arm, so neither V2 nor V1.5 has been fixed. Item 5 is the only one where V2 is clearly worse than V1.5.

## 6. Limitations and what this does not establish

- **Development exposure.** The 2025 season was used while the play-call layer was tuned. These are retrospective numbers, and the comparison among arms is not an independent test.
- **Two dropped team-games.** `2025_07_GB_ARI` is excluded because all 30 seeds errored in all arms. The error is `ILLEGAL_STATE: QB has no eligible target roles on team ARI`, and it should be fixed before that game is scored in any future run.
- **Definitional differences.** Scrambles (run versus dropback), punts and kickoffs in snap counts, and penalty plays (excluded in both) are not perfectly aligned. These are reported as definitional, not as model deficiencies.
- **Team snaps.** The simulator's team snap count tracks scrimmage plays, the observed snap-count file tracks slightly more. The V2 snap rows are directional.
- **Random streams are not shared across arms.** Same seed index, different draws, so seed-level pairing carries no information beyond the game pairing.
- **Naive baseline.** The naive comparison is the leave-one-game-out league mean. It is a point baseline and does not say anything about variability. The clustered interval for sim-minus-naive is not computed here.
- **Touchdowns by half.** The observed half split uses the scoring play's quarter. In about 1.7% of observed team-games a touchdown falls in overtime, outside both halves.
- **Sample.** One season, 271 games, 30 seeds each. Between-seed variance is not counted as uncertainty about the game; game-clustered intervals are.
- **Halftime and end-of-regulation drives.** Both sides count them as drives; the simulator's drive summaries include halftime-terminated drives.

## 7. Reproduce

Fast host (standard library only; reads raw batches, writes only under `/root/repro/analysis-2026-11-05/`):

```
python3 verify_batches.py --root /root/repro/arms-2025 --manifest manifest.csv --out verify
python3 seed_metrics.py --root /root/repro/arms-2025 --out metrics
```

Local (pandas; `/root/legendarypicks/backend/venv/bin/python`):

```
python3 observed_2025_metrics.py --out docs/research/SLC-2025-REALISM-RESULTS-2026-11-05/observed
python3 score_realism.py --metrics <dir with team_seed.csv.gz and player_seed.csv.gz> \
  --observed docs/research/SLC-2025-REALISM-RESULTS-2026-11-05/observed \
  --verify <dir with seed_status.csv> --out docs/research/SLC-2025-REALISM-RESULTS-2026-11-05
```

Script hashes as run (first 16 hex characters of SHA-256; the host copies of `verify_batches.py` and `seed_metrics.py` were checked against these):

- `verify_batches.py` `e0b18479ab7df344`
- `seed_metrics.py` `798092cb4c3bed17`
- `observed_2025_metrics.py` `0bfa491d1a74b723`
- `score_realism.py` `7c1d492f0cc41cca`

The per-seed derived tables (`team_seed.csv.gz`, 1.8 MB; `player_seed.csv.gz`, 6.7 MB) are not committed. They are on the fast host at `/root/repro/analysis-2026-11-05/metrics/`, next to the raw batches.

## Files in this folder

- `summary.json`: counts of completed, blocked, tied and error seeds; dropped team-games; snap export flags.
- `verification.json`, `game_pairing.csv`, `boxscore_vs_outcome_status.csv`, `simulation_errors.csv`, `seed_status.csv.gz`: batch verification and per-seed status.
- `table_drive_half_totals.csv`, `table_players.csv`, `table_yardage.csv`, `table_extremes.csv`, `table_variability.csv`, `table_calibration.csv`: the tables above, machine-readable.
- `table_family_summary.csv`, `table_paired_family_differences.csv`: family aggregates and paired intervals.
- `observed/observed_team_game.csv`, `observed/observed_player_game.csv`: observed 2025 team-game and player-game metrics.
