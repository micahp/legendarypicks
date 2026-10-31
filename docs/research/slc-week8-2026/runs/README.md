# Week 8 SLC run catalog

Use [run-index.json](run-index.json) as the single inventory for all 14 Week 8 matchups. It distinguishes completed 10K batches on the current player-workload branch from older 10K batches and incomplete attempts.

## Standard location for new runs

Save new run records under:

```text
docs/research/slc-week8-2026/runs/<GAME_ID>/<RUN_ID>/
  run-header.json
  report.md
  summary.json
  outputs/
```

Keep raw worker archives on the fast host under `/root/slc-week8-player-workload-10k-2026-10-30/artifacts/<GAME_ID>/<RUN_ID>/`, and put their exact artifact path and hashes in `run-index.json`. Do not put another run version beside a different matchup's files or reuse a run ID.

The older raw artifacts remain at their recorded locations. The catalog points to them without moving or rewriting the frozen files. Create a matchup folder only when there is an actual run; the index explicitly marks the remaining games.

## Status meanings

- `completed_10k_latest_player_workload`: all 10,000 seed attempts are accounted for on the newer player-workload run line. Blocked seeds remain part of that denominator.
- `completed_10k_earlier_source`: a 10K batch exists for an earlier source revision; it is not a substitute for a run on the newer player-workload branch.
- `no_completed_10k`: no complete 10K batch was found. A pilot, smoke, empty output directory, or interrupted ledger does not count.

The index was checked against the frozen snapshots, the Oct. 27 run report, the local IND–JAX archive, and the fast-host artifact roots on 2026-10-31. No Week 8 simulator process was running at that check.
