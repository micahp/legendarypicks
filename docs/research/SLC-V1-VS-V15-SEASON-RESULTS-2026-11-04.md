# SLC V1 against V1.5 over 2026 weeks 1 to 8: results, 2026-11-04

Verdict: **V1.5 does not advance.** The owner's advance rule (2026-11-03) needs lower mean log loss and lower mean Brier
than V1 and a 95% interval for the log-loss difference below zero. V1.5 is worse on both means and the interval spans zero.
Per the owner (2026-11-04), V1.5 work stops here; research continues on pbv1 / SLC v2.

## Run

- Code: one commit, `ffe7e0ef` (branch `slc-v1.5`), on the fast host (`/root/repro/arms-season.sh`), seeds 1 to 20 per
  game and arm, `v1_full_stack` profile, `--slc-fg-ordinary-cutoff 60.0`. V1.5 adds `--playcall-season-adapt
  --season-adapt-n0 4.0` (the current-season shrink). Nothing else differs between arms.
- Games: 121 (all of weeks 1 to 8 with a final score). Weeks 1 to 7 (107 games) run in archive-reconstruction mode from
  the committed snapshots (`docs/research/slc-week1-7-snapshots-2026-11-03`, primary 28 and secondary 79 games); week 8
  (14 games) from its prospective snapshots (`docs/research/slc-week8-2026`).
- All 242 batches exited 0. Scored with `score_season_batches.py --seed-rule complete_game --weeks 1-8` against the dev
  database results. Archive reconstructions are never `valid_full_game` (their capture time is not established), so
  complete, unblocked games are scored and the report is labelled `retrospective-exposure`. Scored seeds per game: 18 to
  20, so a game's win probability moves in steps of about 0.05.
- Report: `SLC-V1-VS-V15-SEASON-REPORT-2026-11-04.json`.

## Results

| | V1 | V1.5 |
|---|---|---|
| Winner log loss | 0.6888 | 0.6948 |
| Winner Brier | 0.2458 | 0.2480 |
| Points CRPS, home | 5.28 | 5.41 |
| Points CRPS, away | 6.16 | 6.06 |

Paired difference, V1.5 minus V1, game-clustered bootstrap (10,000 draws): log loss +0.0060 [-0.0544, +0.0702]; Brier
+0.0023 [-0.0242, +0.0288].

By week (log loss, V1 / V1.5): 1 0.643 / 0.623; 2 0.757 / 0.752; 3 0.696 / 0.671; 4 0.677 / 0.771; 5 0.646 / 0.547;
6 0.691 / 0.686; 7 0.748 / 0.878; 8 0.655 / 0.637. V1.5 is better in six of eight weeks and much worse in weeks 4 and 7.

By snapshot tier (one tied game left out, log loss and Brier, V1 / V1.5): primary 28 games 0.721 / 0.710, 0.261 / 0.255;
secondary 78 games 0.684 / 0.702, 0.243 / 0.251; week 8, 14 games 0.655 / 0.637, 0.234 / 0.224.

## Player projections, week 8 (added 2026-11-04, not part of the verdict)

The advance rule is on winners only, so this does not change the verdict. Only week 8 (14 games) can be scored: the
weeks 1 to 7 archive reconstructions carry no player projections. Each arm's mean projection per player is scored
against the nflverse weekly player stats (`stats_player_week_2026.parquet`, SHA-256 prefix `0df020e779067149`, regular
season). Paired difference V1.5 minus V1, game-clustered bootstrap (4,000 draws), negative means V1.5 is better.

All 520 projected players (218 not in the published file are scored as 0; 679 published players were not projected,
5 of them with yards):

| Stat | MAE V1 | MAE V1.5 | MSE difference, 95% interval |
|---|---|---|---|
| Carries | 1.42 | 1.16 | -5.87 [-9.88, -1.88] |
| Rushing yards | 7.27 | 6.21 | -124.3 [-208.4, -49.2] |
| Targets | 1.55 | 1.30 | -2.64 [-3.64, -1.71] |
| Receptions | 1.12 | 0.95 | -1.15 [-1.59, -0.75] |
| Receiving yards | 13.06 | 11.38 | -156.5 [-214.9, -101.3] |
| Pass attempts, completions, passing yards, all touchdowns, interceptions | | | intervals span zero |

Only players who recorded the stat (observed value above 0), mean absolute error:

| Stat | Players | V1 | V1.5 | Difference, 95% interval |
|---|---|---|---|---|
| Carries | 104 | 4.92 | 3.87 | -1.05 [-1.76, -0.29] |
| Rushing yards | 100 | 27.28 | 23.54 | -3.74 [-5.94, -1.25] |
| Targets | 202 | 2.55 | 2.04 | -0.52 [-0.72, -0.34] |
| Receptions | 179 | 1.95 | 1.57 | -0.37 [-0.52, -0.23] |
| Receiving yards | 178 | 23.94 | 20.32 | -3.62 [-5.46, -2.08] |

The earlier week 8-only run of the same two arms, scored the same way, gives the same picture: V1.5 better
on carries, rushing yards, targets, receptions and receiving yards, with intervals below zero.

V1.5 is better on player workload in week 8, and not better on winners over weeks 1 to 8. Fourteen games of one week
are a small sample, and week 8 was already exposed (see `HOLDOUT-EXPOSURE-RECORD-2026.md`).

## Context

- Neither arm is clearly better than a coin flip on winners: log loss of 0.5 is 0.6931 and Brier 0.25; the season's home
  win rate (0.517, in sample) gives 0.6926. Both arms are within the noise of those references over 121 games.
- With 20 seeds per game, sampling noise in each game's probability is about 0.11 (sd at p = 0.5), which is large next
  to the differences being tested.

## Limits

- 107 of 121 games are archive reconstructions, not verified pregame snapshots.
- 2026 weeks 1 to 8 were already exposed to development (see `HOLDOUT-EXPOSURE-RECORD-2026.md`); this is not a holdout.
- Player projections are scored only for week 8 (archive games carry no player contributions, by the valid_full_game
  gate); they are not part of the verdict. Results in the section above.
