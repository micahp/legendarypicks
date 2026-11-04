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

## Context

- Neither arm is clearly better than a coin flip on winners: log loss of 0.5 is 0.6931 and Brier 0.25; the season's home
  win rate (0.517, in sample) gives 0.6926. Both arms are within the noise of those references over 121 games.
- With 20 seeds per game, sampling noise in each game's probability is about 0.11 (sd at p = 0.5), which is large next
  to the differences being tested.

## Limits

- 107 of 121 games are archive reconstructions, not verified pregame snapshots.
- 2026 weeks 1 to 8 were already exposed to development (see `HOLDOUT-EXPOSURE-RECORD-2026.md`); this is not a holdout.
- Player projections are scored only for week 8 (archive games carry no player contributions, by the valid_full_game
  gate); they are not part of the verdict.
