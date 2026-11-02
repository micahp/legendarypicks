# SLC Week 8 CLE–PIT: 10,000-run result

- **Matchup:** Cleveland at Pittsburgh (`2026_08_CLE_PIT`)
- **Report date:** 2026-10-30
- **Profile:** `v1_full_stack` (`SLC_v1_full_stack`)
- **Run scope:** one matchup, 10,000 seeds split across six workers

## Outcome coverage

| Outcome | Games | Share |
| --- | ---: | ---: |
| Complete in regulation | 9,494 | 94.94% |
| Complete in overtime | 400 | 4.00% |
| **Complete** | **9,894** | **98.94%** |
| Blocked | 106 | 1.06% |
| Simulation errors | 0 | 0.00% |

The six workers are seed shards of the **same CLE–PIT matchup**, not six different games. Their ranges are contiguous and non-overlapping:

| Worker | Seeds | Attempts |
| --- | ---: | ---: |
| 01 | 1–1,667 | 1,667 |
| 02 | 1,668–3,334 | 1,667 |
| 03 | 3,335–5,001 | 1,667 |
| 04 | 5,002–6,668 | 1,667 |
| 05 | 6,669–8,334 | 1,666 |
| 06 | 8,335–10,000 | 1,666 |

All 10,000 seed IDs are unique. The exported boxscore stream has 10,000 game records. Its configured reconciliation passed for all 10,000 records (`strict=false` in the records).

## Scores and team output

Score summaries use the 9,894 completed games, including ties. The seven tied games are excluded from the win-rate denominator. Percentiles use linear interpolation.

| Measure | PIT | CLE | Total / PIT margin |
| --- | ---: | ---: | ---: |
| Mean points | 22.668 | 18.278 | 40.946 / +4.390 |
| Median | 23 | 17 | 41 / +4 |
| 10th–90th percentile | 13–34 | 9–29 | 27–55 / −11 to +20 |

PIT won 6,367 of 9,887 decisive games (64.40%); CLE won 3,520 (35.60%). Seven completed games ended tied.

Mean team output per completed game:

| Team | Plays | Drives | Pass att. | Completions | Rush att. | Pass yds | Rush yds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| PIT | 69.713 | 10.668 | 33.597 | 20.390 | 35.170 | 211.903 | 158.630 |
| CLE | 66.411 | 10.599 | 38.595 | 21.373 | 26.551 | 226.856 | 119.865 |

The boxscores contain player-level passing, rushing, receiving, and fumble-lost totals. These are simulated allocations from the frozen participant inputs, not observed player results.

| Player | Team | Pass att. / yds / TD / INT | Targets / receptions / rec. yds | Rush att. / yds / TD |
| --- | --- | ---: | ---: | ---: |
| Deshaun Watson | CLE | 38.52 / 226.43 / 0.99 / 0.76 | — | 2.99 / 23.00 / 0.08 |
| Aaron Rodgers | PIT | 33.54 / 211.50 / 1.03 / 0.38 | — | 2.39 / 14.57 / 0.19 |
| Jerry Jeudy | CLE | — | 13.37 / 7.10 / 84.46 | 0.10 / 0.44 / 0.00 |
| DK Metcalf | PIT | — | 11.77 / 6.56 / 74.56 | 0.11 / 0.57 / 0.01 |
| Jaylen Warren | PIT | — | 5.22 / 3.63 / 32.24 | 28.47 / 125.56 / 1.10 |
| Quinshon Judkins | CLE | — | 2.70 / 1.63 / 13.63 | 14.14 / 58.62 / 0.43 |

Player averages are per completed game and include zero-stat games for each eligible listed player.

## Blocked outcomes

| Blocker | Games |
| --- | ---: |
| `blocked_kick_period_end_not_reached:field_goal` | 60 |
| `blocked_kick_period_expired_next_possession_unresolved:field_goal:Q1` | 20 |
| `blocked_kick_period_expired_next_possession_unresolved:field_goal:Q3` | 21 |
| `blocked_kick_no_legal_geometry:punt:next_snap:receiving_team:blocked_kick_next_snap_outside_field:receiving_team` | 2 |
| `blocked_kick_no_legal_geometry:field_goal:next_snap:kicking_team:next-snap blocked kick needs an observed start spot, down and distance` | 1 |
| `timeout_limit_exceeded` | 2 |
| **Total** | **106** |

The recorded blocker-fix set was `run_scramble_backoff`, `long_field_goal_feasibility`, `blocked_kick_source_audit`, `blocked_kick_geometry`, and `safety_free_kick_boundaries`. The remaining blockers are retained as incomplete outcomes; they were not converted into ordinary game results.

## Model configuration and provenance

- The run used 16 of 17 configured playcalling layers. `fixed_player_target_carry_shares` was disabled; the other recorded layers were enabled.
- All shards report configuration hash `8e5067cda217f5db22b45e74e353f7b69e38497eab5abd1ce0cd791f9822b1a8`, the same layer settings, and consistent producer-file hashes.
- The recorded information cutoff is `2026-10-29T00:02:21Z`; historical playcalling sources are eligible only before 2026 Week 1. The profile labels the run `prospective_forecast` with verified snapshot inputs.
- Producer commit recorded in the run headers: `ea4d13095c5642519db025a8a458528e37082c7a`. The producer checkout was dirty when inspected after the run. The headers preserve per-file producer hashes, but that commit alone is not a clean reproduction pin.
- `snapshot_sha256`: `e90036489fbdf2663b610746b90c1179a66d3e6c096a1a6070be423fcbf91beb`
- `source_snapshot_sha256`: `01173abf541861cb5dd7a350469a8c95bff5f5a123d8b6976991ec6a46a36681`
- `reference_sha256`: `9eb5a02ae7be4b016eb3c1220cffd9ce820336247ad8a2213dfdbc2bbb8cbef4`
- `playcall_artifact_sha256`: `27c02afd6d9f6f80a38b3bc7ae278b1efebcc7caa5664688c64c55bc0c698ac7`

The raw worker summaries, seed ledgers, boxscores, logs, and `SHA256SUMS.txt` are in [`outputs/parallel-6-offensive-td-classified-fixed-2026-10-30/`](outputs/parallel-6-offensive-td-classified-fixed-2026-10-30/). All 26 listed artifact files passed checksum verification after the local pull.

## Interpretation

This is a descriptive 10,000-seed distribution for one frozen matchup. It does not measure calibration or establish improvement over a baseline. In particular, do not compare it as a paired run with the earlier CAR–GB batch: the matchup, code state, and run configuration differ.
