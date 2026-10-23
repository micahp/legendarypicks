# nfl_sequence v0.2 (pre-registered): late-clock context in the call table, D1 only

Status: **pre-registered before any v0.2 result was computed.** Results are appended in section 6 and were not
used to choose any choice made in sections 1–5. Base commit `51db9868`. Frozen v0.1 record, not edited:
[RESULTS-nfl-sequence-v0.1-2026-10-22.md](RESULTS-nfl-sequence-v0.1-2026-10-22.md),
[DRIVE-EVAL-nfl-sequence-v0.1-2026-10-22.md](DRIVE-EVAL-nfl-sequence-v0.1-2026-10-22.md),
[results/eval-2022-2023-t100-v2.json](results/eval-2022-2023-t100-v2.json),
[results/drive-report-2022-2023.json](results/drive-report-2022-2023.json).

Not a prediction of real games. Every script is labelled HYPOTHETICAL MODEL SIMULATION.

## 1. What is added, exactly

One binary context, **`late`**, added to the **call table only**. The table that chooses the call (run, pass,
punt, field goal, kneel, spike) gains the key, and its backoff levels all carry it.

- **Definition.** `late` = the snap is in the last 120 seconds of the second half (period 2), the fourth quarter
  (period 4), or overtime (period 5), using the period clock at the start of the snap. Otherwise `early`. This is
  the same window the v0.1 drive diagnostics used (`call_timing`), so the variant is tested against the
  definition it was diagnosed with.
- **New call-table levels** (the v0.1 `main` levels had no time key):
  1. `(down, dist, field, score, qtr, late)`
  2. `(down, dist, field, score, late)`
  3. `(down, dist, field, late)`
  4. `(down, dist, late)`
  5. `(down, late)`
  6. `(late,)`
  7. `()`
  The minimum cell size is 200, as in v0.1. Backoff goes from the first level to the last.
- **Unchanged.** Pass class and all yardage tables (`pass_class`, `run_yards`, `pass_yards`, sack, scramble),
  physical tables (field goals, punts, kickoffs, clock run-off, fumbles, extra points), the playbook seam, the
  seeds (`derive_seed` with the same snapshot hash and `MODEL_VERSION = nfl-seq-v0.1`), the 100 trials, the training
  window 2010–2021, the 543-game test set 2022–2023, and the bootstrap settings.
- **Bootstrap seeds.** Drive-level intervals use seed 20261023, 2,000 reps (as in v0.1). Game-level intervals use
  seed 20261022, 2,000 reps, as the frozen v0.1 game-level document did. Changing it would move the comparison
  off the frozen record.
- **Not changed.** Elapsed time per play (the run-off model). D1's second half is therefore not addressed by this
  variant and stays documented as open. D2 (pass yardage pooled across downs), D3 (fourth-down decisions), D4
  (kickoff-era touchbacks; open pending Micah's decision on the boundary) and D5 (defensive returns) are not touched.

Artifacts: the variant is trained into `backend/nfl_sequence/models-v0.2/` with its own `manifest.json`. The
frozen `models/` directory is not regenerated. Its variant tag is `clock`.

## 1a. Amendment A1 (recorded before any v0.2 measure was computed)

Section 1's level list lets a thin late-window cell back off to `(down, dist, late)`, `(down, late)` and `(late,)`.
Those levels pool all field positions. A 30-game integrity check (300 seeded trials, 42,472 calls) found **9
field-goal calls from the opponent's 20 or further**, the deepest at 114 yards (kick distance is yardline + 17).
The v0.1 `main` table made **0** such calls on the same games and seeds. A field goal from the own 14 is not a
real play. The check counted calls only; it computed none of the section 2 measures. The first full drive
simulation with the unamended levels also stopped at the first deep kick (a 103-yard distance was outside the
distance bins), before any drive measure was produced.

The amended call-table levels keep the window on the three finest levels and then fall back to the v0.1
structure, which conditions on field position:

1. `(down, dist, field, score, qtr, late)`
2. `(down, dist, field, score, late)`
3. `(down, dist, field, late)`
4. `(down, dist, field)` (v0.1's third level)
5. `(down, dist)`
6. `(down,)`
7. `()`

The window therefore applies only where a cell with the same field position has at least 200 observations.
Section 2's expectations, section 3's verdict rule, the seeds, the training window and the test set are unchanged.
Section 5's test is updated to require the window on the first three levels and the v0.1 structure after them.

## 1b. Amendment A2: withdrawn (recorded before any v0.2 measure was computed)

A2 proposed a minimum of 50 for the late-keyed levels. It was based on a probe that used field labels which do
not exist in the model (`1-20`, `21-40`), so the probe fell back to the coarse levels and showed no effect. The probe
is withdrawn. Re-run with the real bins (`G10`, `11-19`, `20-34`, `35-49`, `50-64`, `65-79`, `80+`), the amended
model with the section 1 minimum of 200 everywhere **already changes the call mix in 87 of 112 leading states**
(score bins W, W9, T and L; down-and-distance states 1&10, 2&8–9, 3&5–7, 4&1–2; all seven fields), with late kneel
probability up to 0.78 and early kneel probability at most 0.006. The training counts that favoured 50 (41 finest
late cells at 200, 207 at 50) are real, but they do not show that the window is inert at 200. So the threshold stays
at the pre-registered 200, and A2 is not applied. The model in `models-v0.2/` is trained with A1 only.

## 2. Expectations, written before the run

Reference values are v0.1 (`main`) from the frozen records. "Real" is 2022–2023 with its 95% interval.

| measure | real [95% CI] | v0.1 sim | v0.1 training baseline | expected v0.2 sim | expected direction |
|---|---|---|---|---|---|
| snaps in the late window, leading | 0.145 [0.140, 0.152] | 0.080 | 0.131 | 0.06–0.10 | stays put, below real CI |
| kneel share of late snaps, leading | 0.187 [0.172, 0.203] | 0.040 | 0.196 | 0.15–0.23 | moves toward real, inside CI |
| kneel share of early snaps, leading | 0.000 [0.000, 0.000] | 0.025 | 0.000 | 0.000–0.005 | moves toward real |
| kneel-ended drives per game | 0.967 [0.910, 1.022] | 0.065 | 0.931 | 0.3–0.9 | rises toward real; likely still below its CI |
| clock-expiration drives per game | 0.593 [0.538, 0.646] | 1.766 | 0.628 | 0.9–1.5 | falls toward real; likely still above its CI |
| elapsed minutes per drive | 2.732 [2.699, 2.764] | 2.610 | 2.632 | 2.61–2.70 | little change; kneels add time |
| touchdown share per drive | 0.206 [0.198, 0.214] | 0.163 | 0.206 | 0.155–0.170 | stays put |
| red-zone entries that score a TD | 0.549 [0.532, 0.566] | 0.482 | 0.551 | 0.46–0.50 | stays put |
| game Brier (541 decisive games) | 0.2466 base-rate forecast | 0.2543 [0.2499, 0.2588] | — | 0.2530–0.2600 | stays worse than the base rate |
| Brier minus base-rate Brier (paired, game-clustered) | — | +0.0077 [0.0012, 0.0143] | — | 0.000 to +0.015 | does not turn clearly negative |
| log loss minus base-rate log loss (paired) | — | +0.0154 [0.0025, 0.0287] | — | 0.000 to +0.030 | does not turn clearly negative |
| winner accuracy (541 decisive games) | — | 0.4935 [0.4529, 0.5323] | coin flip 0.5; home share 0.5582 | 0.47–0.53 | no clear change |

Why these expectations. The training data already has a late-lead kneel share of 0.196, so a table that conditions on
the window should reproduce that share. That is the main prediction. The table does not change run-off, so late
snap counts should stay low. Kneels consume about 40 seconds, so they may slightly lower late snap counts and
lengthen drives. Touchdown share and the red-zone rate depend on yardage and fourth-down decisions, which this
variant does not change, so they should stay put. Game-level results should move little. A kneel changes the clock,
not the score, so a clear Brier improvement is not expected from this change alone.

## 3. Verdict rule (pre-registered)

For each drive measure with real estimate R, v0.1 mean A and v0.2 mean B:

- **stayed put**: |B − A| ≤ 10% of |A − R|, or the change is smaller than 0.001 for rates.
- **moved toward**: otherwise, |B − R| < |A − R|, and B has not crossed R.
- **overshot**: B has crossed R (B and A are on opposite sides of R).
- **moved away**: otherwise.

Inside or outside the real CI: "inside" if the v0.2 simulated mean lies within the real 95% interval, otherwise "outside".

For game-level measures, a degradation is any move of the v0.2 paired Brier or log-loss difference from the base-rate
forecast that is larger than its own sign-change threshold, in the wrong direction. The result is reported
as it is. The variant is **not** tuned if game-level measures degrade, and the drive measures are not used to justify
a tuned version.

## 4. Stopping rules

- One variant. No second clock definition, no second window length, and no tuning after the result is seen.
- If a v0.2 measure moves away from real, or the game-level measures degrade, report that as the result.
- D2, D3 and D4 stay documented as open.

## 5. Tests that must fail if time context is removed

- A call table without a `late` key fails the clock-variant structure test.
- The `main` (v0.1) call table must still ignore `late`. A test checks it, so v0.1 stays frozen.

## 6. Results

Computed from the frozen v0.1 records and the v0.2 run, with the rule in section 3 applied as written.

### 6.1 Drive measures (2022–2023, 543 games, 100 seeded trials per game)

| measure | real [95% CI] | v0.1 sim [2.5–97.5%] | v0.2 sim [2.5–97.5%] | v0.2 inside real CI? | v0.2 vs real | pre-registered expectation | result vs expectation |
|---|---|---|---|---|---|---|---|
| snaps in the late window, leading | 0.1454 [0.1398, 0.1517] | 0.0796 [0.0765, 0.0840] | 0.0852 [0.0814, 0.0885] | outside | gap 0.0659 → 0.0603 | 0.06–0.10 | stayed put; within expectation |
| kneel share of late snaps, leading | 0.1871 [0.1717, 0.2029] | 0.0398 [0.0320, 0.0494] | 0.1374 [0.1221, 0.1517] | outside | gap 0.1473 → 0.0497 | 0.15–0.23 | moved toward; outside expectation |
| kneel share of early snaps, leading | 0.0000 [0.0000, 0.0001] | 0.0248 [0.0232, 0.0266] | 0.0001 [0.0000, 0.0002] | inside | gap 0.0247 → 0.0000 | 0.000–0.005 | moved toward; within expectation |
| kneel-ended drives per game | 0.9669 [0.9098, 1.0221] | 0.0650 [0.0451, 0.0838] | 0.2595 [0.2173, 0.3012] | outside | gap 0.9019 → 0.7073 | 0.3–0.9 | moved toward; outside expectation |
| clock-expiration drives per game | 0.5930 [0.5378, 0.6464] | 1.7657 [1.7219, 1.8021] | 1.5446 [1.4822, 1.5997] | outside | gap 1.1727 → 0.9516 | 0.9–1.5 | moved toward; outside expectation |
| elapsed minutes per drive | 2.7318 [2.6987, 2.7643] | 2.6095 [2.5822, 2.6491] | 2.6449 [2.6207, 2.6733] | outside | gap 0.1223 → 0.0868 | 2.61–2.70 | moved toward; within expectation |
| touchdown share per drive | 0.2058 [0.1979, 0.2136] | 0.1630 [0.1577, 0.1681] | 0.1680 [0.1631, 0.1741] | outside | gap 0.0428 → 0.0378 | 0.155–0.170 | moved toward; within expectation |
| red-zone entries that score a TD | 0.5487 [0.5317, 0.5658] | 0.4820 [0.4667, 0.4951] | 0.4907 [0.4742, 0.5092] | outside | gap 0.0667 → 0.0580 | 0.46–0.50 | moved toward; within expectation |

Keys: `stats.<name>.real`, `stats.<name>.sim` in `drive-report-2022-2023.json` (v0.1, frozen) and the v0.2 report. Rates use the 0.001 tolerance of section 3.

### 6.2 Game level (541 decisive games; game-clustered paired bootstrap, 2,000 reps, seed 20261022)

The base rate is the 2010–2021 training home-win share, 1,714/3,078 = 0.5569.

| measure | v0.1 `main` (frozen) [95% CI] | v0.2 clock [95% CI] | v0.2 − v0.1 |
|---|---|---|---|
| Brier, home win | 0.2543 [0.2499, 0.2588] | 0.2517 [0.2474, 0.2561] | -0.0026 |
| log loss, home win | 0.7018 [0.6931, 0.7108] | 0.6966 [0.6879, 0.7055] | -0.0052 |
| winner accuracy (coin flip 0.5) | 0.4935 [0.4529, 0.5323] | 0.5009 [0.4584, 0.5434] | 0.0074 |
| Brier minus base-rate Brier (paired) | 0.0077 [0.0012, 0.0143] | 0.0051 [-0.0013, 0.0118] | -0.0026 |
| log loss minus base-rate log loss (paired) | 0.0154 [0.0025, 0.0287] | 0.0102 [-0.0026, 0.0237] | -0.0052 |

Pre-registered game-level expectations and whether they held: Brier outside range (expected 0.2530–0.2600); Brier minus base in range (expected 0.000 to +0.015); log loss minus base in range (expected 0.000 to +0.030); winner accuracy in range (expected 0.47–0.53).

### 6.3 Supplementary paired comparison (not pre-registered)

The brief asks whether the clock context cost or bought anything. The paired difference between v0.2 and v0.1 on the same
541 decisive games, same seed and 2,000 game-clustered reps, is:

| paired difference (v0.2 − v0.1) | estimate | 95% CI |
|---|---|---|
| Brier, home win | −0.0026 | [−0.0078, +0.0025] |
| log loss, home win | −0.0052 | [−0.0157, +0.0052] |
| winner correct (indicator) | +0.0074 | [−0.0425, +0.0610] |

No difference is distinguishable from zero. Computed from the per-game records in both JSON files
(`variants.clock.games`, `variants.main.games`).

### 6.4 Reading the result

- **The window did what the call table was built to do, but only in part.** Kneels in late leading snaps went from 0.040
  to 0.137 (real 0.187, expectation 0.15–0.23). Early leading kneels went from 0.025 to 0.0001. Kneel-ended drives per game
  went from 0.065 to 0.260 (real 0.967). Clock-expiration drives went from 1.766 to 1.545 (real 0.593).
- **Every drive measure that the variant could move moved toward the real value, and none is inside its real interval
  except early kneels.** The pre-registered verdict rule classes each of the eight measures as "moved toward", "stayed put" or
  "overshot"; none overshot. The late-window snap share stayed put, as predicted, because the call table does not change
  run-off.
- **Two expectations were missed on the low side**: late-leading kneel share and kneel-ended drives per game. Clock-expiration
  drives per game were slightly above their expected range (1.545 against 0.9–1.5).
- **The touchdown share moved 0.005.** It falls inside the expected range (0.155–0.170). The rule classes a change of 12%
  of the gap to real as "moved toward", not "stayed put", and that classification is reported as written.
- **Game level:** Brier moved below the expected range. The paired difference from the base-rate forecast is 0.0051
  [−0.0013, +0.0118] (v0.1: 0.0077 [0.0012, 0.0143]), so v0.2 is no longer clearly worse than the base rate, and it is not
  clearly better either (6.3). Winner accuracy is inside its expected range.
- **Remaining gaps.** Run-off per play is still context-free (elapsed 2.645 against 2.732), so clock management is only
  partly modelled. D2 (pass yardage pooled across downs), D3 (fourth-down decisions), D4 (kickoff-era touchbacks; open pending
  Micah's decision on the boundary) and D5 (defensive returns) are untouched, and the touchdown share is still 0.168 against 0.206.

### 6.5 Deviations and process notes (all recorded before the result they affect)

- **Amendment A1** (section 1a): the window was removed from the coarse backoff levels after 9 field goals from the
  opponent's 20 or further were found in the first 300 trials (deepest 114 yards, kick distance = yardline + 17). Applied
  before any drive measure was computed. Across all 54,300 trials, field-goal calls from the 80-yard line or beyond: 0 for
  v0.2 (220,558 field-goal calls in total) and 0 for v0.1 (226,585); no kick exceeds 99 yards in either.
- **Amendment A2** (section 1b): proposed and **withdrawn**. Its probe used field labels that do not exist (`1-20`, `21-40`),
  so the probe was invalid. The correct probe showed the window active at the pre-registered minimum of 200.
- **Shared-variable bug**: `run_evaluation` shadowed its `variants` argument with its output dictionary, so the first clock
  run simulated nothing (13.6 seconds). Renamed to `variant_names` before the real run. The frozen v0.1 run predates the
  argument and is unaffected.
- **First clock shards crashed** on the 103-yard kick before any tally was written. The fix is A1. No output from those shards
  was used.
- **Seeds.** The drive measures use `derive_seed` with the frozen model-version string, and the same 100 trials per game. The
  v0.1 drive report re-run from its shards reproduces the frozen `drive-report-2022-2023.json` exactly. Game-level intervals
  use seed 20261022, as in the frozen v0.1 game document.
- **Frozen record untouched.** `docs/RESULTS-nfl-sequence-v0.1-2026-10-22.md`, `docs/DRIVE-EVAL-nfl-sequence-v0.1-2026-10-22.md`,
  `docs/results/eval-2022-2023-t100-v2.json`, `docs/results/drive-report-2022-2023.json` and `backend/nfl_sequence/models/` have no
  diff. Re-training the three frozen variants reproduces their artifacts byte for byte.

## 7. Reproducibility

```
cd backend
python -m nfl_sequence.train --source-dir <parquet dir> --train-seasons 2010-2021 --variants clock --out-dir nfl_sequence/models-v0.2
python -m nfl_sequence.drive_eval sim --source-dir <parquet dir> --model-dir nfl_sequence/models-v0.2 --variant clock --test-seasons 2022-2023 --trials 100 --shard i --shards 3 --out sim_shard_i.jsonl.gz
python -m nfl_sequence.drive_eval report --source-dir <parquet dir> --real-seasons 2022-2023 --baseline-seasons 2010-2021 --sim-glob 'sim_shard_*.jsonl.gz' --reps 2000 --seed 20261023 --out drive_report_v02.json
python -m nfl_sequence.evaluate --source-dir <parquet dir> --model-dir nfl_sequence/models-v0.2 --variants clock --test-seasons 2022-2023 --trials 100 --schedule-db <sqlite> --out eval_v02_clock.json
```

Outputs committed: [results/eval-2022-2023-t100-v0.2-clock.json](results/eval-2022-2023-t100-v0.2-clock.json) and
[results/drive-report-v0.2-clock-2022-2023.json](results/drive-report-v0.2-clock-2022-2023.json).
