# SLC scoring review bundle, 2026-11-07

Raw evidence for the team scoring-distribution review. This folder is a partial export. Read the "Missing" section before using it.

## Included here

- `manifest.json`: runs, scripts, status and timestamps, snapshot identity, and where each raw file lives.
- `seed-outcomes/JAX-BAL-corrected-{v1,v15,v2}.csv`: one row per seed (1 to 1000) for the corrected rerun. Columns: status, complete_game, valid_full_game, regulation_end_reached, final_tie, blocker, home_points, away_points, error.
- `actual/2026_09_JAX_BAL.json`: Thursday's actual result (JAX 33, BAL 10) from `nfl_schedule`, plus the play count in `nfl_pbp` (156).

## Missing

1. **Original V1, V1.5, V2 runs (Thursday, first pass).** The run logs say `game.json` was written, but the output folders on the fast host hold only `run.log` and `status.txt`. The raw files are not on disk. I can't export them.
2. **Full play-level records for the corrected rerun.** Each arm has `game.json`, `game.seeds.jsonl` and `game.boxscores.jsonl`, about 2.2 GB per arm in total. They are on the fast host at `/root/repro/jax-bal-w09/out-cutoff/{v1,v15,v2}/`. I haven't pushed them, because that's roughly 2.2 GB for git, the host disk is 98% full, and a push is hard to undo. Say the word if you want them compressed and pushed in chunks, or stored somewhere else.
3. **Thursday's box scores, snap counts and drive summaries.** Not exported. The database has the schedule and play-by-play; I haven't checked which tables hold the rest.
4. **Week 8 and other matchup seed ledgers.** They exist in `docs/research/slc-week8-2026/`, `slc-week8-recoveries-2026-10-31/` and `slc-week8-player-workload-10k-2026-10-30/`, plus other review folders. I haven't re-exported them into this bundle yet.

## Status of the inputs

- The snapshot was built as `exploratory_replay` with `verified: false`. Every run in this bundle used an unverified input, so `valid_full_game` is false for all 1000 seeds in every arm. The manifest lists the three unverified inputs.
- The frozen cutoff folder `docs/research/frozen-2026_09_JAX_BAL/` is untracked and was not staged. Its manifest hash is in `manifest.json`.

## Notes

- The corrected rerun was run with the five registered blocker fixes; the originals were run without them.
- Per the manifest, the seed-outcome CSVs have no drive, possession, or play-level data. Those come from the raw files on the host.

## Added 2026-11-07

- `team-drive-tables/team-stats-{v1,v15,v2}.csv`: one row per team per seed, from the corrected rerun box scores. Includes drives, plays, possession seconds, points, red-zone counts, turnovers and sacks.
- `team-drive-tables/player-usage-{v1,v15,v2}.csv.gz`: one row per roster player per seed, zeros included. Snaps exist only for V2; V1 and V1.5 have no lineup record.
- `actual/`: Thursday's play-by-play (156 plays, all four quarters), player game logs, team totals and results, and player usage shares from the database.

## Corrections to the provenance

- The three "corrected rerun" arms were produced from `9b5a1e43` (Nov 5, 15:01 CST), before the identity fix `2b13edac` (23:28 CST). They are the five-blocker rerun only.
- The identity-fixed rerun exists for V2 alone, at `out-identity/v2` on the fast host, from `2b13edac`. It is not in this bundle.
- Explosive plays, starting field position and per-drive duration and outcome are not in the box scores, and the raw files don't keep per-play records (`game.json` `replay_examples` is empty). Those need a run that retains per-play records.
