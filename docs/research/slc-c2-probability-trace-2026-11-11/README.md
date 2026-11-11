# SLC C2 probability trace — 2026-11-11

## Result

A fresh-input ARI–SEA SLC-v2 + D1 diagnostic completed for seeds 1–3. All 3 games passed full-game validation and strict box-score reconciliation. This is not a reproduction of the archived replay: its original database is unavailable, and this run uses the database and PBP hashes recorded in [run-manifest.json](run-manifest.json).

The 211 traced dropbacks all used the exact-cell path. No sparse-backoff dropbacks occurred.

| Probability stage | Mean sack probability | Change at stage | Mean completion probability | Change at stage |
| --- | ---: | ---: | ---: | ---: |
| Exact-cell historical rows | 6.49% | — | 59.68% | — |
| Formation | 6.35% | −0.14 pp | 59.83% | +0.15 pp |
| Coverage | 4.84% | −1.51 pp | 61.21% | +1.38 pp |
| League streak | 4.82% | −0.02 pp | 61.27% | +0.06 pp |
| Decision labels | 2.08% | −2.74 pp | 63.38% | +2.12 pp |
| Team event weights | 2.17% | +0.09 pp | 63.89% | +0.51 pp |
| Player event weights / final draw | 2.25% | +0.08 pp | 64.42% | +0.54 pp |

The base and final sack means use the 210 dropbacks with sack support; completion means use all 211. The sampled outcomes were 7 sacks (3.32%), 139 completions (65.88%), 63 incompletions, and 2 interceptions. The sample is small and comes from one matchup, so it identifies likely mechanisms to investigate; it does not estimate league-wide calibration.

Coverage and decision-label weighting account for nearly all of the observed reduction in sack probability in this sample. Team and player weighting slightly increase it after those stages. `restore_sack_mass` was off. No production model settings were changed.

## Trace parity

The same three seeds were rerun with tracing disabled. Per-seed RNG roots, scores, box scores, and all non-trace outcome fields matched exactly. The trace-on and trace-off box-score sidecars have the same SHA-256. See [trace-parity.json](trace-parity.json). The raw seed ledgers are retained as compressed JSONL in [trace-on-seeds.jsonl.gz](trace-on-seeds.jsonl.gz) and [trace-off-seeds.jsonl.gz](trace-off-seeds.jsonl.gz); the former contains all stage traces.

## Inputs and scope

- Snapshot: `2026_09_ARI_SEA`, as of `2026-11-07T22:16:59Z`, marked valid before roster finalization. Its pre-finalization timing does not invalidate the completed games.
- Cutoff-safe season evidence: 122 games and 21,347 PBP rows; 14,960 rows entered the play-call frame. All modeled plays had matching score fields. The 255 rows with missing score values were non-play, unknown, or special-team records excluded from the frame. `2026_09_JAX_BAL` was present in the newer PBP source; its five missing-score records were header, quarter-end, or timeout/no-play rows.
- PBP source: [nflverse 2026 PBP release](https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_2026.parquet), SHA-256 `5030e8fc1739ea8f93ce67b461f76d3ae89b2f952d430ddbfa5b7f7f07d44b18`.
- Simulation database SHA-256: `5d75378aa7fd35948a8dc73d7f22eae1f6837cc0dbe97e4c46747bd982ed14dd`. The database is not included in this report.
- D1 workload, snap-count, participation, play-call and streak input hashes are in [run-manifest.json](run-manifest.json). The snap-count file was acquired after the snapshot; it is recorded as input provenance and does not change the snapshot's valid pre-finalization status.
- Tracing code: `scripts/nfl_sequence/slc_playcall.py`, committed in `97c33596`. The trace-on run used the identical file contents immediately before that commit; the trace-off parity run used the commit.

The persisted trace records do not include down, distance, field position, score state, or source play ID. This result therefore cannot break the layer deltas down by situation. Add those fields before using traces for situation-level calibration. Sparse-backoff probability changes also remain unmeasured in a full game.

## Reproduce

Download the PBP asset above and verify its SHA-256. Use the same database hash and committed input files. Set `SLC_PBP_RELEASE_2026` to the downloaded parquet path; the wrapper pins it for `season_layers` without replacing the historical snapshot. The exact three seed IDs, flags, output hashes, stage aggregates, and parity details are in the adjacent manifest and JSON artifacts.
