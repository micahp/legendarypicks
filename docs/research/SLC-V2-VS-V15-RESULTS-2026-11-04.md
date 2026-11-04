# SLC v2 against V1.5, and the V1 / V1.5 baseline, over 2026 weeks 1 to 8: results, 2026-11-04

Scored after M5 freeze amendments 8 (one team-code interface) and 9 (the MIA week 8 kicker). Label:
`retrospective-exposure` (2026 is sealed for development; these reads were directed by the owner and are logged in the
holdout exposure record, rows 23 to 26). All three arms on the same 121 games.

## Verdict

- **v2 does not advance over V1.5.** Winner log loss and Brier are level within noise; points CRPS is level.
- **v2 does not fix the workload problem.** It is worse than V1.5 on carries, targets, receptions, receiving yards and
  rushing yards for players who recorded the stat, every 95% interval above zero. Of V1.5's gain over V1 it keeps 67%
  on carries, 44% on targets and 36% on receiving yards.
- **V1.5 is the baseline.** It is level with V1 on winners and points and clearly better on every workload stat.
- **One signal for v2:** in week 8, the only week run from prospective snapshots, v2 beats V1.5 on carries and rushing
  yards (small samples, below). The rushing side of the lineup model may help when its inputs are current.

## Run

- Games: the 121 regular-season games of weeks 1 to 8 with a final score, all three arms.
- The 15 Rams and Washington games were rerun for V1, V1.5 and v2 on `5edb8b49`, and `2026_08_NE_MIA` for v2 on
  `c6bd9b44` (fast host), seeds 1 to 20, box scores on, flags as before (V1.5: `--playcall-season-adapt
  --season-adapt-n0 4.0`; v2: `--slc-v2` with the week 1 to 7 snap counts). The other games are the earlier runs: V1
  and V1.5 on `ffe7e0ef`, v2 on `ffea8f0e`. Completed seeds per game: 15 to 20.
- Scored with `score_season_batches.py --seed-rule complete_game --weeks 1-8` (results from the dev database) and
  `slc-v2-eval-2026-11-04/score_player_workloads.py` (players: nflverse `stats_player_week_2026`, weeks 1 to 8; snaps:
  2026 snap counts through week 7).
- Outputs in `slc-v2-eval-2026-11-04/`: `SEASON-V1-VS-V15-AMENDMENT8.json`, `SEASON-V15-VS-V2-AMENDMENT9.json`,
  `PLAYERS-V1-V15-V2-AMENDMENT9.json`.

### Why mixing commits is valid here (measured)

V1 and V1.5 seed their random streams from a reference fingerprint that includes the source-file hashes and the git
commit, so any commit reshuffles every game's draws. To show the new code changes nothing else outside the Rams and
Washington games, two control games (`2026_01_ARI_LAC`, `2026_08_KC_DEN`) were run on `5edb8b49` with the fingerprint
fed the old file bytes and commit id, once for `ffea8f0e` and once for `ffe7e0ef`. All 8 batches match the earlier
batches in every seed record and every box-score line except `configuration_hash`. v2's streams are keyed on the
layer tables; its control games on `5edb8b49` and on `c6bd9b44` (`2026_08_KC_DEN`, with the new kicker table) match
the earlier v2 run except provenance fields.

### Player coverage

Players who recorded a stat but are on no arm's simulated roster (67 player-games with offense) are scored as a
projection of 0 for every arm; earlier scoring left them out, which understated every arm's error equally. 8 published
player-games carry no player id and cannot be scored. 28 v2 team-games have no published snap counts (week 8 snaps are
published through week 7 only).

## Winners and points

| | V1 | V1.5 | v2 |
|---|---|---|---|
| Winner log loss | 0.6945 | 0.6980 | 0.6966 |
| Winner Brier | 0.2484 | 0.2489 | 0.2478 |
| Points CRPS, home / away | 5.33 / 6.11 | 5.38 / 6.03 | 5.47 / 5.94 |

Paired log-loss difference, game-clustered bootstrap, 95% interval: V1.5 minus V1 +0.0035 [-0.0630, +0.0726];
v2 minus V1.5 -0.0014 [-0.0670, +0.0667]. Both fail the advance rule.

Before amendment 8 (Rams and Washington streak input missing) V1 led V1.5 0.6888 to 0.6948; most of that gap closed.

## Workload: players who recorded the stat

Mean absolute error per player-game; 80% interval coverage in brackets (0.80 is calibrated).

| Stat | Player-games | V1 | V1.5 | v2 |
|---|---|---|---|---|
| Carries | 958 | 4.39 (0.54) | 3.53 (0.63) | 3.82 (0.59) |
| Targets | 1,932 | 2.56 (0.68) | 2.21 (0.74) | 2.41 (0.68) |
| Receptions | 1,714 | 1.89 (0.69) | 1.65 (0.75) | 1.78 (0.68) |
| Rushing yards | 888 | 23.00 (0.52) | 20.07 (0.60) | 20.91 (0.58) |
| Receiving yards | 1,669 | 23.14 (0.58) | 21.01 (0.66) | 22.37 (0.62) |

Paired difference in MAE, 95% interval:

| Stat | V1.5 minus V1 | v2 minus V1.5 |
|---|---|---|
| Carries | -0.86 [-1.08, -0.65] | +0.28 [+0.08, +0.48] |
| Targets | -0.34 [-0.42, -0.27] | +0.19 [+0.13, +0.26] |
| Receptions | -0.24 [-0.29, -0.19] | +0.13 [+0.08, +0.18] |
| Rushing yards | -2.93 [-3.81, -2.05] | +0.84 [+0.07, +1.60] |
| Receiving yards | -2.12 [-2.72, -1.53] | +1.36 [+0.87, +1.84] |
| Pass attempts, passing yards, touchdowns | intervals span zero | intervals span zero |

Every player, including those projected but without the stat: the ordering is the same (carries 1.65 / 1.37 / 1.53,
targets 2.10 / 1.84 / 1.95 for V1 / V1.5 / v2).

Week 8 only (prospective snapshots), players who recorded the stat, MAE V1.5 / v2: carries 3.89 / 3.76 (107),
rushing yards 23.56 / 22.13 (103), targets 2.02 / 2.41 (206), receptions 1.56 / 1.82 (182), receiving yards
20.44 / 22.53 (181).

## Team workload shape

Mean share of the team's carries or targets taken by the leading players (observed / V1 / V1.5 / v2):

| Role | Observed | V1 | V1.5 | v2 |
|---|---|---|---|---|
| Leading ball carrier | 0.602 | 0.697 | 0.660 | 0.588 |
| Second ball carrier | 0.235 | 0.185 | 0.201 | 0.231 |
| Leading targeted receiver | 0.297 | 0.368 | 0.337 | 0.347 |

v2 splits the backfield closer to the observed shape than V1.5, while its named-player carry errors are larger: it gets
the share structure nearer and assigns it to the wrong backs more often. Ranked-role shares cannot see this, because
roles are ranked by each arm's own simulated workload. On targets v2 concentrates more on the leading receiver than
V1.5, away from the observed share. Top target and top carry share CRPS: V1.5 better than V1 (both intervals below
zero); v2 against V1.5, intervals span zero.

## Personnel and snaps (v2 only)

Snap-share MAE 0.161 over 3,124 player-games (0.171 for players who played). By role: WR1 0.075, WR2 0.110, WR3 0.122,
RB1 0.110, RB2 0.096, TE1 0.107, TE2 0.129. V1 and V1.5 produce no lineups, so this has no comparison arm.

## Limits

- Retrospective and development-exposed: these results can direct debugging; a change made because of them cannot be
  validated on the same 2026 games.
- 15 to 20 completed seeds per game: enough for means, thin for 80% intervals and tails.
- Week 8 snap shares are scored against snap counts through week 7.
