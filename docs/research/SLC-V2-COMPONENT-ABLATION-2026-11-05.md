# SLC v2 component ablation, 2026 weeks 1 to 8 (2026-11-05)

## Question

Does each v2 component, added to the V1.5 control, improve the pregame winner probability on the 121 games of 2026 weeks 1 to 8?

## Arms

Launch script on the fast host: `/root/repro/arms-abl.sh`. Code: `final-fix` at `c6bd9b44`. Every arm uses the same snapshots, the same streaks, the same seed IDs and the same rng protocol (v2).

- **A** (control): V1.5, `v1_full_stack`, `--playcall-season-adapt --season-adapt-n0 4.0`.
- **B**: A plus lineups and substitutions (`--participation-field`, `field_v4_decay075_2020_2025.json`).
- **C**: B plus the snap-count update (`--participation-snap-counts`, snap counts through week 7).
- **D**: A plus field goals by the team kicker (`--playcall-fg-kicker`, with `--slc-blocker-fix long_field_goal_feasibility`).

Scored with `scripts/nfl_sequence/score_season_batches.py` (slc-v2 `8e911fa4`), `--weeks 1-8`, `--seed-rule complete_game`. All 484 arm-games finished with exit 0. 0 games were excluded.

## Result

| Comparison | Brier (baseline to candidate) | Mean log-loss difference | 95% interval | Advance |
|---|---|---|---|---|
| B vs A (lineups and substitutions) | 0.2495 to 0.2566 | +0.014 | [-0.038, +0.068] | no |
| C vs B (snap counts) | 0.2566 to 0.2372 | -0.042 | [-0.089, +0.004] | no |
| D vs A (kicker field goals) | 0.2495 to 0.2626 | +0.028 | [-0.036, +0.093] | no |

Advance rule (the scorer's owner rule, 2026-11-03): advance only if mean log loss and mean Brier are both lower than the baseline and the 95% game-clustered interval for the log-loss difference is below zero. No arm advances.

## Reading

- C vs B has the lowest Brier and log loss of the three comparisons, but its interval reaches +0.004. The gain is not established.
- B vs A and D vs A are slightly worse on both metrics, and both intervals include zero.
- An earlier partial scoring on 73 of the 121 games (B vs A and D vs A slightly better) did not hold on the full set. That partial result is superseded.

## Caveats

- **Exposure.** These games were already scored for V1, V1.5 and v2 in rows 23 to 26 of the holdout record. This run adds arms on the same games, not new games. It is logged as row 27 on `slc-v1.5`.
- **Kicker table.** `kicker_table_through_2025_assign_2026.json` contains 2026 kicker assignments. Whether each assignment was known before its game has not been checked. Treat D as unvalidated until that is verified.
- **Sample.** One season, 8 weeks, 121 games. The intervals are wide.

## Not in this writeup

- The 2025 realism run is running on the fast host with injury-excluded inputs. Its results are not here.
- Timestamped injury reconstruction has not started.

## Files

`docs/research/slc-v2-ablation-2026-11-05/`: the three scorer outputs (`season_B_vs_A.json`, `season_C_vs_B.json`, `season_D_vs_A.json`) and their score logs.
