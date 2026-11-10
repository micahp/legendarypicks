# SLC-v2 three-arm comparison: output and grading

Run date: 2026-11-10. This archive records the completed paired comparison of Default V2, C, and D1.

## Run and output summary

- All three arms completed 1,000 requested seeds over ARI–SEA (334), DAL–IND (333), and DEN–CAR (333).
- The run used `--slc-profile v1_full_stack --slc-v2` with RNG-v2. The manifest pins each snapshot and model input hash.
- The output renderer produced one report and its CSV/JSON summaries for each of the nine arm/matchup combinations under `worker-reports/`.
- The compressed worker JSON, seed ledgers, box-score exports, and logs are archived under `worker-artifacts/`. Their gzip hashes match the run manifest.

| Arm | ARI–SEA | DAL–IND | DEN–CAR | Total |
| --- | --- | --- | --- | ---: |
| Default V2 | 334 success, 0 error | 333 success, 0 error | 332 success, 1 error | 1,000 |
| C | 334 success, 0 error | 333 success, 0 error | 332 success, 1 error | 1,000 |
| D1 | 334 success, 0 error | 333 success, 0 error | 332 success, 1 error | 1,000 |

Each arm has one simulation error at seed 300786 in DEN–CAR. The full arm-specific failure records are in `failure-records/`. All three have the same blocked-kick `ILLEGAL_STATE` assertion; the Default V2 record is also included in the earlier failure-evidence archive.

## Outcome grading

`score_season_batches.py` was run for Week 9 with `valid_full_game` seeds, comparing Default V2 against C and D1. The grader returned **NOT SCORED** for both comparisons: the local grading database has no final scores for any Week 9 game in `nfl_schedule` (`results_in_weeks: 0`). It excluded all three matchups. This is missing observed-score input, not a model pass or fail.

- `default-v2-vs-C.json`
- `default-v2-vs-D1.json`

## Reproduction and provenance

- The exact run manifest and launcher are in `provenance/runner-manifest.json` and `provenance/run_three_way.py`.
- The run source commit was `8a5d809ffaec720b3d7b8ddb487f33c55e5d0d0e`. The original run tree had local edits to the batch runner and its test; the exact patch is retained in `provenance/source-local-diff.patch`.
- The renderer and grader were `scripts/nfl_sequence/render_slc_run_report.py` and `scripts/nfl_sequence/score_season_batches.py` from that source checkout. The Week 9 grading command used `--weeks 9-9 --season 2026`; the scorer defaulted to `valid_full_game`.
- `SHA256SUMS` covers all files in this archive except itself.
