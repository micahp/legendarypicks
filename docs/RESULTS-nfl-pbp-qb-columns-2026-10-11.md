# Results: qb_hit, qb_scramble, qb_dropback and no_huddle in nfl_pbp

Date: 2026-10-11. Why: [RESEARCH-nfl-model-inputs-2026-10-11.md](RESEARCH-nfl-model-inputs-2026-10-11.md).

## What was added

Four nflverse play-by-play flags, appended last to `_PLAY_COLS` in `backend/ingest_nfl_pbp_logs.py`:
`qb_hit`, `qb_scramble`, `qb_dropback`, `no_huddle`. They were never in the curated column list before
this change. Nobody removed them; they were never selected.

Code commit: `fe9dfa2` (on `feat/nfl-model-foundation`).

## Method

- UPDATE only, on stored rows, matched on `(game_id, play_id)`.
- No other column is written. No row is inserted or deleted.
- A full `--year` re-ingest was not used, because nflverse rewrites old files in place and the 2024/2025
  results are pinned to the stored values.
- 2026 games: only games already stored were filled (`--allow-new-games`, 2026 only).
- Every season was dry-run first. Each apply ran in one transaction that refuses unless every stored
  play of the season is in the file, and checks the stored counts and the alignment of each flag to its
  play types.

## Sources

- 2010 to 2023: files already on disk in `/root/nfl-v1-rehearsal.d0IcMW/nflverse_2010_2023`, checksums
  verified against the profiled set before use.
- 2024 to 2026: downloaded from the nflverse-data `pbp` release. Download time (UTC):
  `2026-10-12T00:36:14Z`.

```
d2ef9c407319719910ad8de8c4c1b88f0ea945ffb3f78f48ef32fa3ed3a7573b  play_by_play_2010.parquet
c54753b8137b88dab260489b1462cbf1309c3d11741eb8d10e5f1b0a9b8795b1  play_by_play_2011.parquet
447b90789104aac70427ec9d3b51df7247234029d0ecabd269279369b1cc6278  play_by_play_2012.parquet
f454605a1983b3946baf0ffadf3a0b9f5e04735c4b84732e0483f2049a780d00  play_by_play_2013.parquet
54c01408d8f0ff9e013a4ea51428b91d610101f72545d082e932f5710e2fb4f7  play_by_play_2014.parquet
01b5ae7d06633a2e66b418404461a3d4ff055ad2f3a87d453cebcc8d3fda7ed9  play_by_play_2015.parquet
95eba04e2145e3c1c8ca502f2a3a76cfb0a5990680c3fb480f02a74a45f54a3b  play_by_play_2016.parquet
84eacd963c1fdd45965f6222c62e9329a7f3412f029d92c1ac5e34a1bb4d3710  play_by_play_2017.parquet
2e6f2dce7c7ebd46e985cabe0c17eb72b39a77f98cb4478409294f50b5820150  play_by_play_2018.parquet
60c3067017db2d28a78f66a79b657268be8578d9a5288e6a827efdcd7fe42540  play_by_play_2019.parquet
8889f5d8782b5c5dce3c3644acdc0322b228a7e9cb13fa36cbac250e260e9f60  play_by_play_2020.parquet
333ad34378e5339d5172717cc83378e908daf02c8699416ab3e17c2ec10f78d8  play_by_play_2021.parquet
931121d8897779d7944e2a293e92ed8799c8e5cceef84096ac42339003fedc09  play_by_play_2022.parquet
bd3484731408def6b0ec93225bba2bd7b2c65769ca707a2b9444d891abdc6776  play_by_play_2023.parquet
```

```
3fd2896bc0b911b615142d2f1fabae54a4bbba5ab7b73b28187b118ef8af6a3b  play_by_play_2024.parquet
c6ecedd6d678cc37ed316b23ef84ee1ec6abb69c514bb11868a7ebd5a367df29  play_by_play_2025.parquet
24235d333336e2861d83e198d7374fa59adc750f658b85f482f779d64980e852  play_by_play_2026.parquet
```

## Per-season results

Generated from the apply log by `results_table.py`. Shares are the alignment of each flag to its play
types, measured on the stored rows after the write.

| Season | REG plays in file | Stored | Matched | qb_hit null / 1 | qb_scramble 1 | qb_dropback null / 1 | no_huddle 1 | Hit on pass | Scramble on run/no_play | Dropback on pass/run/no_play | New games skipped |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2010 | 44991 | 44991 | 44991 | 1412 / 2271 | 677 | 1364 / 19005 | 1314 | 1.0000 | 0.9970 | 1.0000 | 0 |
| 2011 | 45455 | 45455 | 45455 | 1392 / 2436 | 753 | 1347 / 19284 | 1963 | 1.0000 | 1.0000 | 1.0000 | 0 |
| 2012 | 45829 | 45829 | 45829 | 1396 / 2387 | 715 | 1355 / 19603 | 2349 | 1.0000 | 1.0000 | 1.0000 | 0 |
| 2013 | 46255 | 46255 | 46255 | 1399 / 2583 | 801 | 1356 / 20181 | 4281 | 1.0000 | 0.9975 | 1.0000 | 0 |
| 2014 | 45673 | 45673 | 45673 | 1421 / 2565 | 746 | 1350 / 19765 | 4392 | 1.0000 | 0.9973 | 1.0000 | 0 |
| 2015 | 46141 | 46141 | 46141 | 1408 / 2804 | 780 | 1354 / 20231 | 4663 | 1.0000 | 0.9987 | 1.0000 | 0 |
| 2016 | 45707 | 45707 | 45707 | 1382 / 2730 | 696 | 1335 / 20072 | 3994 | 1.0000 | 0.9971 | 1.0000 | 0 |
| 2017 | 45268 | 45268 | 45268 | 1374 / 2764 | 771 | 1334 / 19414 | 3015 | 1.0000 | 1.0000 | 1.0000 | 0 |
| 2018 | 45120 | 45120 | 45120 | 1402 / 2817 | 843 | 1345 / 19765 | 2649 | 1.0000 | 0.9964 | 1.0000 | 0 |
| 2019 | 45339 | 45339 | 45339 | 1406 / 2783 | 842 | 1348 / 19922 | 2758 | 1.0000 | 1.0000 | 1.0000 | 0 |
| 2020 | 45406 | 45406 | 45406 | 1342 / 2793 | 897 | 1294 / 20024 | 3313 | 1.0000 | 0.9989 | 1.0000 | 0 |
| 2021 | 47651 | 47651 | 47651 | 1431 / 2868 | 976 | 1392 / 20907 | 3978 | 1.0000 | 1.0000 | 1.0000 | 0 |
| 2022 | 47157 | 47157 | 47157 | 1428 / 2908 | 968 | 1384 / 20298 | 3796 | 1.0000 | 1.0000 | 1.0000 | 0 |
| 2023 | 47399 | 47399 | 47399 | 1420 / 3021 | 1118 | 1386 / 20770 | 3381 | 1.0000 | 1.0000 | 1.0000 | 0 |
| 2024 | 47274 | 47274 | 47274 | 1450 / 2861 | 1134 | 1380 / 20215 | 4478 | 1.0000 | 1.0000 | 1.0000 | 0 |
| 2025 | 46452 | 46452 | 46452 | 1444 / 2891 | 1160 | 1378 / 19830 | 3591 | 1.0000 | 1.0000 | 1.0000 | 0 |
| 2026 | 13449 | 11327 | 11327 | 342 / 748 | 272 | 331 / 4813 | 563 | 1.0000 | 1.0000 | 1.0000 | 12 |

2026 file plays in games not yet stored (2122 plays, not written): `2026_05_CHI_GB`, `2026_05_CIN_MIA`,
`2026_05_CLE_NYJ`, `2026_05_DEN_LAC`, `2026_05_DET_ARI`, `2026_05_HOU_TEN`, `2026_05_IND_PIT`,
`2026_05_LV_NE`, `2026_05_MIN_NO`, `2026_05_NYG_WAS`, `2026_05_PHI_JAX`, `2026_05_SF_SEA`.

## Checks

- Snapshot of existing columns (season, plays, games, sums of epa, sack, yards_gained, wpa, and
  counts): identical before and after all 17 applies. The 2024 (47274) and 2025 (46452) pinned play
  counts are intact.
- Independent re-read (`spotcheck_pbp_cols.py`, reads the parquet directly, 25 random stored plays per
  season): 0 mismatches in all 17 seasons.
- Storage type, 2015 games: `null|null` 1408 and `real|real` 44733. No text values.
- Dry runs: 17 of 17 wrote nothing.
- Tests: `backend/test_ingest_nfl_pbp_logs.py`, `test_nfl_epa_model.py` and `test_nfl_lock.py`, 50 passed.

## Caveats

1. The 12 2026 games above were not stored yet, so they were skipped. They get the four columns at the
   next 2026 refresh, run from this worktree.
2. The `dev` copy of `ingest_nfl_pbp_logs.py` does not know these columns. Until this branch is merged, a
   `--year 2026` run from `/root/legendarypicks` would set them to NULL on 2026 rows (INSERT OR REPLACE).
   2026 refreshes must run from this worktree.
3. `qb_scramble=1` is on `run`/`no_play` plays at 0.9964 to 1.0000 by season (lowest 2018), not 1.0 in
   every season. The gate is 0.99. The plays that fall outside `run`/`no_play` were not examined.
