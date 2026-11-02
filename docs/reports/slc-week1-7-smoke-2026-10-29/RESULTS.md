# Week 1-7 comparison smoke results (interim)

**Status:** The smoke run was still active when this snapshot was captured. The latest completed progress checkpoint was 2026-10-29 23:20:00 UTC: 15 of 56 command slots complete. The SEA-DEN SLC_v1_full_stack arm was running; it is not counted as a success or failure here.

## Results so far

- The S0 baseline has successful output files for eight matchups.
- SLC_v1_full_stack has no successful matchup yet. Eight failed attempts are recorded across seven matchups; CHI-GB was retried.
- Each completed full-stack failure in the ledger ends with FileNotFoundError for the missing host snapshot file /root/lp-snapshots/nfl-backfill-2026-10-27/raw/players/players.parquet.
- The data below is an interim snapshot. The active batch may produce more results after this report was captured.

## Successful baseline outputs

| Matchup | Simulation result | Boxscores | Seeds |
| --- | --- | --- | --- |
| 2026_05_CHI_GB | [S0 JSON](outputs/2026_05_CHI_GB/S0.json) | [boxscores](outputs/2026_05_CHI_GB/S0.boxscores.jsonl) | [seeds](outputs/2026_05_CHI_GB/S0.seeds.jsonl) |
| 2026_05_CIN_MIA | [S0 JSON](outputs/2026_05_CIN_MIA/S0.json) | [boxscores](outputs/2026_05_CIN_MIA/S0.boxscores.jsonl) | [seeds](outputs/2026_05_CIN_MIA/S0.seeds.jsonl) |
| 2026_05_CLE_NYJ | [S0 JSON](outputs/2026_05_CLE_NYJ/S0.json) | [boxscores](outputs/2026_05_CLE_NYJ/S0.boxscores.jsonl) | [seeds](outputs/2026_05_CLE_NYJ/S0.seeds.jsonl) |
| 2026_05_HOU_TEN | [S0 JSON](outputs/2026_05_HOU_TEN/S0.json) | [boxscores](outputs/2026_05_HOU_TEN/S0.boxscores.jsonl) | [seeds](outputs/2026_05_HOU_TEN/S0.seeds.jsonl) |
| 2026_05_IND_PIT | [S0 JSON](outputs/2026_05_IND_PIT/S0.json) | [boxscores](outputs/2026_05_IND_PIT/S0.boxscores.jsonl) | [seeds](outputs/2026_05_IND_PIT/S0.seeds.jsonl) |
| 2026_05_MIN_NO | [S0 JSON](outputs/2026_05_MIN_NO/S0.json) | [boxscores](outputs/2026_05_MIN_NO/S0.boxscores.jsonl) | [seeds](outputs/2026_05_MIN_NO/S0.seeds.jsonl) |
| 2026_05_BAL_ATL | [S0 JSON](outputs/2026_05_BAL_ATL/S0.json) | [boxscores](outputs/2026_05_BAL_ATL/S0.boxscores.jsonl) | [seeds](outputs/2026_05_BAL_ATL/S0.seeds.jsonl) |
| 2026_06_SEA_DEN | [S0 JSON](outputs/2026_06_SEA_DEN/S0.json) | [boxscores](outputs/2026_06_SEA_DEN/S0.boxscores.jsonl) | [seeds](outputs/2026_06_SEA_DEN/S0.seeds.jsonl) |

## Full-stack failures

| Matchup | Failed attempts | Captured error log |
| --- | ---: | --- |
| 2026_05_CHI_GB | 2 | [full-stack log](outputs/logs/2026_05_CHI_GB/SLC_v1_full_stack.log); [earlier interrupted trace](outputs/logs/2026_05_CHI_GB/SLC_v1_full_stack.interrupted-210s.log) |
| 2026_05_CIN_MIA | 1 | [full-stack log](outputs/logs/2026_05_CIN_MIA/SLC_v1_full_stack.log); [additional trace](outputs/logs/2026_05_CIN_MIA/SLC_v1_full_stack.missing-pyarrow.log) |
| 2026_05_CLE_NYJ | 1 | [full-stack log](outputs/logs/2026_05_CLE_NYJ/SLC_v1_full_stack.log) |
| 2026_05_HOU_TEN | 1 | [full-stack log](outputs/logs/2026_05_HOU_TEN/SLC_v1_full_stack.log) |
| 2026_05_IND_PIT | 1 | [full-stack log](outputs/logs/2026_05_IND_PIT/SLC_v1_full_stack.log) |
| 2026_05_MIN_NO | 1 | [full-stack log](outputs/logs/2026_05_MIN_NO/SLC_v1_full_stack.log) |
| 2026_05_BAL_ATL | 1 | [full-stack log](outputs/logs/2026_05_BAL_ATL/SLC_v1_full_stack.log) |

The SEA-DEN full-stack arm was active in this snapshot; its [log](outputs/logs/2026_06_SEA_DEN/SLC_v1_full_stack.log) contains only the in-progress trace.

## Run records

- [Run manifest](outputs/run_manifest.json)
- [Commands](outputs/commands.jsonl)
- [Progress events](outputs/progress.jsonl)
- [Failure ledger](outputs/failure_ledger.jsonl)
