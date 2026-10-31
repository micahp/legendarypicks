# Model D full-game replay — 2025 holdout

**Status:** Research diagnostic. Model D remains opt-in; SLC defaults are unchanged.

## Data and run

- Fit the event clock on 2022–2024 regular-season Weeks 1–18. Of 815 source games, six development games were excluded; 809 games and 103,072 plays were fitted.
- Evaluate against 2025 regular-season Weeks 1–18. The observed volume reference covers 272 games and 46,452 selected PBP rows. The ordered selected-row SHA-256 is `efd84722c3e6d1369f7f2076571f828727bd8312e914bb40e27a977a63f2eec9`.
- Run seeds 1–300 through both E2 and D using the same frozen reference and seed IDs. Each arm retains all per-seed statuses. The database file SHA-256 recorded for this run is `030843a336b0361c81e10f908b3313b35ac66cd1260c17418dea35096d06fe15`; the E2 reference hash is `1fc86a336edd03930ac86d299fef84f8e149520f3cba4026d7ae6affc1a936d8`.
- Rebuild with:

```sh
python scripts/nfl_sequence/clock_d_games.py \
  --seeds 300 \
  --out-dir docs/research/e3/clock-d-games-2025-holdout-train-2022-2024-v2
```

## Coverage and denominators

| Arm | Seeds | Reached regulation end | Legally complete, including OT | Blocked | Reached but `regulation_end_guarded` |
|---|---:|---:|---:|---:|---:|
| E2 | 300 | 296 | 140 | 4 | 156 |
| D | 300 | 298 | 136 | 2 | 162 |

The play-volume comparison uses games that reached the end of regulation, including `regulation_end_guarded` cases, because they contain regulation play-volume observations. These are **not** counted as legally completed games. Complete-game distributions have the smaller legal-completion denominators above. No blocked seed was dropped from the per-seed artifact.

## Full-game volume

The 2025 reference averages 123.36 classifiable plays, 20.11 regulation drives, and 6.22 plays per drive per game. Results below use all regulation-reached runs.

| Measure | 2025 observed | E2 | E2 difference | D | D difference |
|---|---:|---:|---:|---:|---:|
| Plays per game | 123.36 | 148.21 | +24.85 (+20.1%) | 147.12 | +23.76 (+19.3%) |
| Regulation drives per game | 20.11 | 23.08 | +2.97 (+14.8%) | 22.95 | +2.84 (+14.1%) |
| Mean game-level plays per drive | 6.22 | 6.50 | +0.28 (+4.5%) | 6.49 | +0.27 (+4.3%) |

On 296 seed IDs where both arms reached regulation, the paired D-minus-E2 difference was **−1.13 plays** (normal-approximation 95% interval −2.20 to −0.06), **−0.13 drives** (−0.37 to +0.10), and **−0.008 plays per drive** (−0.047 to +0.031). D shifts the quarter distribution: Q1 and Q3 each have about 2.8–3.0 fewer plays than E2, while Q2 has 1.58 more and Q4 has 3.06 more. This is a small total-volume reduction with a clear timing redistribution; it does not correct the high game volume.

| Plays per game by quarter | 2025 observed | E2 | D |
|---|---:|---:|---:|
| Q1 | 27.99 | 37.09 | 34.27 |
| Q2 | 33.74 | 37.29 | 38.92 |
| Q3 | 28.13 | 36.77 | 33.81 |
| Q4 | 33.50 | 37.06 | 40.12 |

## Event and runoff diagnostics

Event shares are broadly similar to the 2025 reference, but absolute event counts are elevated with the extra plays and drives. Punts are an additional composition issue: D averages 8.44 punts/game (5.63 observed), and its punt share is 5.74% (4.57% observed). D also averages 54.69 runs/game (46.80 observed) and 47.21 completed passes/game (40.19 observed).

| Event | Observed/game | D/game | Observed mean runoff | D mean runoff |
|---|---:|---:|---:|---:|
| Field-goal attempt | 3.95 | 4.60 | 3.48 sec | 3.81 sec |
| Lost fumble | 0.56 | 0.74 | 8.27 sec | 8.03 sec |
| Interception | 1.01 | 1.29 | 8.28 sec | 8.25 sec |
| Completed pass | 40.19 | 47.21 | 30.56 sec | 30.50 sec |
| Incomplete pass | 20.81 | 25.06 | 4.71 sec | 4.78 sec |
| Punt | 5.63 | 8.44 | 9.38 sec | 9.18 sec |
| Run | 46.80 | 54.69 | 33.96 sec | 31.88 sec |
| Sack | 4.40 | 5.08 | 33.30 sec | 32.98 sec |

The per-event mean runoffs are close, with the largest gap on runs (D is 2.08 seconds shorter). The full-game excess is larger in drive count than in mean plays per drive. These comparisons identify where to investigate next, but do not establish a causal decomposition: the event stream and game state can diverge after the clocks first differ, and no one-factor full-game ablation is included here.

## Conclusion

Model D changes when plays occur, but has little effect on total 2025 holdout volume: it removes 1.09 of E2's 24.85 excess plays/game and still simulates 2.84 excess drives/game. Do not treat this result as evidence that the event clock is calibrated. Diagnose possession/drive frequency and the remaining quarter-end behavior before tuning player efficiency. The fixed-outcome v6 replay separately shows quarter-end classification remains poor.

The machine-readable source is `clock-d-games-summary.json`; all 600 arm/seed rows are in `clock-d-games-per-seed.csv`. The initial run directory without `-v2` is retained as an earlier iteration; this corrected-denominator v2 review is authoritative for the full-game comparison.
