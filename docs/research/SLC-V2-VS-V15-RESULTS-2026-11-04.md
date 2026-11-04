# SLC v2 against V1.5, and the V1 / V1.5 baseline, over 2026 weeks 1 to 8: results, 2026-11-04

Scored after M5 freeze amendment 8 (one team-code interface, `PLAYCALL-M5-FREEZE-AMENDMENT-8-2026-11-04.md`). Label:
`retrospective-exposure` (2026 is sealed for development; these reads were directed by the owner and are logged in the
holdout exposure record, rows 23 to 25).

## Verdict

- **v2 does not advance over V1.5.** Winner log loss and Brier are level within noise; points CRPS is equal.
- **v2 does not fix the workload problem.** It is worse than V1.5 on carries, targets, receptions, receiving yards and
  rushing yards for players who recorded the stat, every 95% interval above zero. Of V1.5's gain over V1 it keeps 66%
  on carries, 43% on targets and 34% on receiving yards.
- **V1.5 is the baseline.** It is level with V1 on winners and points and clearly better on every workload stat.

## Run

- Games: the 121 regular-season games of weeks 1 to 8 with a final score. v2 has 120: `2026_08_MIA_*` has no v2 run
  (the week 8 kicker table has no MIA row; open).
- The 15 Rams and Washington games were rerun for V1, V1.5 and v2 on `5edb8b49` (fast host, `/root/repro/arms-fix`),
  seeds 1 to 20, box scores on, flags as before (V1.5: `--playcall-season-adapt --season-adapt-n0 4.0`; v2: `--slc-v2`
  with the week 1 to 7 snap counts). Before the amendment their streak input missed (V1, V1.5) or the kicker lookup
  raised (v2). The other games are the earlier runs: V1 and V1.5 on `ffe7e0ef`, v2 on `ffea8f0e`.
- Scored with `score_season_batches.py --seed-rule complete_game --weeks 1-8` (results from the dev database) and
  `slc-v2-eval-2026-11-04/score_player_workloads.py` (players: nflverse `stats_player_week_2026`, weeks 1 to 8; snaps:
  2026 snap counts through week 7). V1.5 against v2 is paired on the same 120 games.
- Outputs: `slc-v2-eval-2026-11-04/SEASON-V1-VS-V15-AMENDMENT8.json`, `SEASON-V15-VS-V2-AMENDMENT8.json`,
  `PLAYERS-V1-V15-V2-AMENDMENT8.json`.

### Why mixing commits is valid here (measured)

V1 and V1.5 seed their random streams from a reference fingerprint that includes the source-file hashes and the git
commit, so any commit reshuffles every game's draws. To show the new code changes nothing else outside the Rams and
Washington games, two control games (`2026_01_ARI_LAC`, `2026_08_KC_DEN`) were run on `5edb8b49` with the fingerprint
fed the old file bytes and commit id, once for `ffea8f0e` and once for `ffe7e0ef`. All 8 batches (2 games, V1 and
V1.5, 2 commits) match the earlier batches in every seed record and every box-score line except `configuration_hash`.
v2 needs no such step: its streams are keyed on the layer tables, and its two control games on `5edb8b49` match the
earlier v2 run the same way.

## Winners and points

| | V1 | V1.5 | v2 |
|---|---|---|---|
| Winner log loss (121 games; v2 120) | 0.6945 | 0.6980 | 0.6970 |
| Winner Brier | 0.2484 | 0.2489 | 0.2480 |
| Points CRPS, home / away | 5.33 / 6.11 | 5.38 / 6.03 | 5.49 / 5.96 |

On v2's 120 games V1.5 scores log loss 0.6997, Brier 0.2497, points CRPS 5.40 / 6.07.

Paired log-loss difference, game-clustered bootstrap, 95% interval: V1.5 minus V1 +0.0035 [-0.0630, +0.0726];
v2 minus V1.5 -0.0027 [-0.0691, +0.0673]. Both fail the advance rule.

Before the amendment (Rams and Washington streak input missing) V1 led V1.5 0.6888 to 0.6948; most of that gap closed.

## Workload: players who recorded the stat

Mean absolute error per player-game; 80% interval coverage in brackets (0.80 is calibrated).

| Stat | Player-games | V1 | V1.5 | v2 |
|---|---|---|---|---|
| Carries | 924 | 4.41 (0.56) | 3.53 (0.65) | 3.82 (0.61) |
| Targets | 1,864 | 2.57 (0.70) | 2.21 (0.76) | 2.41 (0.70) |
| Receptions | 1,660 | 1.89 (0.71) | 1.65 (0.77) | 1.78 (0.70) |
| Rushing yards | 859 | 23.08 (0.53) | 20.07 (0.62) | 20.96 (0.60) |
| Receiving yards | 1,617 | 23.20 (0.60) | 21.06 (0.68) | 22.47 (0.64) |

Paired difference in MAE, 95% interval:

| Stat | V1.5 minus V1 | v2 minus V1.5 |
|---|---|---|
| Carries | -0.88 [-1.11, -0.66] | +0.30 [+0.08, +0.50] |
| Targets | -0.35 [-0.44, -0.28] | +0.20 [+0.13, +0.26] |
| Receptions | -0.24 [-0.29, -0.19] | +0.14 [+0.09, +0.19] |
| Rushing yards | -3.01 [-3.91, -2.06] | +0.89 [+0.10, +1.68] |
| Receiving yards | -2.14 [-2.76, -1.52] | +1.41 [+0.91, +1.93] |
| Pass attempts, passing yards, touchdowns | intervals span zero | intervals span zero |

Top target share and top carry share (CRPS): V1.5 better than V1 (-0.017, -0.017, intervals below zero); v2 against
V1.5 +0.003 and +0.005, intervals span zero.

## Personnel and snaps (v2 only)

Snap-share MAE 0.161 over 3,124 player-games (0.171 for players who played). By role, mean absolute error:
WR1 0.075, WR2 0.110, WR3 0.122, RB1 0.110, RB2 0.096, TE1 0.107, TE2 0.129.

## Open

- MIA week 8 has no v2 run (kicker table gap).
- Week 8 snap shares are scored against snap counts through week 7 only.
