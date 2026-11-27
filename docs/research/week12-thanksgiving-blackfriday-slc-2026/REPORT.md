# Thanksgiving 2026 SLC run results

Status at 2026-11-27 11:38 CT. These are retrospective runs for the completed Nov 26 games. The six statistical SLC arms and frozen CEG results were already published for CHI–DET and PHI–DAL. V1 Complete has now finished 100 attempts for all three Thanksgiving games; failed seeds remain in the evidence and were not replaced.

## Actual results and forecast summary

Actual scores were read from the Legendary Picks scoreboard API. Player box scores were graded against `nflverse_weekly` game logs. Per-seed outcomes, player prop lines and grading rows are in [`grades.json`](grades.json).

### 2026_12_CHI_DET

Kickoff: 2026-11-26T18:00:00+00:00 UTC. Actual: CHI 39, DET 35 (total 74).

| Model | Valid | P(home wins) | Mean away | Mean home | Mean total | Prop lines graded | Prop Brier |
|---|---:|---:|---:|---:|---:|---:|---:|
| v1 | 100/100 | 0.660 | 21.9 | 26.9 | 48.8 | 87 | 0.280 |
| v1.6 | 100/100 | 0.580 | 24.2 | 25.7 | 49.9 | 87 | 0.252 |
| v2_frozen | 100/100 | 0.640 | 22.6 | 26.6 | 49.2 | 87 | 0.222 |
| v2_simplified | 100/100 | 0.540 | 23.5 | 25.2 | 48.7 | 87 | 0.244 |
| v2_support_aware | 100/100 | 0.590 | 20.0 | 22.2 | 42.2 | 87 | 0.267 |
| v2_soft_conditioning | 100/100 | 0.670 | 21.7 | 26.2 | 47.9 | 87 | 0.237 |
| v1_complete | 89/100 valid | 0.551 | 16.4 | 18.8 | 35.3 | 87 | 0.472 |

Actual total error is model mean total minus actual total (74); actual home-margin error is model mean margin minus actual home margin (-4). The detailed values are included per model in `grades.json`. Each run requested seeds 300001–300100. Latest pregame prop over lines were aggregated as the median across sources, using each source's latest quote captured before the scheduled kickoff; empirical P(over) comes from the simulated player box scores. Brier excludes pushes. Supported prop coverage is 87 graded player-market rows from 130 unique pregame quote lines for CHI–DET; this is a limited single-game retrospective grade, not evidence of model selection.

### 2026_12_PHI_DAL

Kickoff: 2026-11-26T21:30:00+00:00 UTC. Actual: PHI 39, DAL 38 (total 77).

| Model | Valid | P(home wins) | Mean away | Mean home | Mean total | Prop lines graded | Prop Brier |
|---|---:|---:|---:|---:|---:|---:|---:|
| v1 | 100/100 | 0.380 | 26.3 | 23.4 | 49.7 | 86 | 0.308 |
| v1.6 | 100/100 | 0.490 | 21.0 | 21.6 | 42.6 | 86 | 0.290 |
| v2_frozen | 100/100 | 0.560 | 21.4 | 22.1 | 43.5 | 86 | 0.335 |
| v2_simplified | 100/100 | 0.600 | 19.3 | 23.0 | 42.3 | 86 | 0.331 |
| v2_support_aware | 100/100 | 0.640 | 18.4 | 21.1 | 39.5 | 86 | 0.348 |
| v2_soft_conditioning | 100/100 | 0.600 | 20.7 | 22.6 | 43.3 | 86 | 0.333 |

Actual total error is model mean total minus actual total (77); actual home-margin error is model mean margin minus actual home margin (-1). The detailed values are included per model in `grades.json`. Each run requested seeds 300001–300100. Latest pregame prop over lines were aggregated as the median across sources, using each source's latest quote captured before the scheduled kickoff; empirical P(over) comes from the simulated player box scores. Brier excludes pushes. Supported prop coverage is 86 graded player-market rows from 132 unique pregame quote lines for PHI–DAL; this is a limited single-game retrospective grade, not evidence of model selection.

## Frozen CEG

Frozen CEG completed 100/100 valid full games for both matchups (seeds 300001–300100). It emitted no player lines, so CEG player props are unavailable.

| Game | P(home wins) | Mean away | Mean home | Mean total | Actual |
|---|---:|---:|---:|---:|---|
| CHI–DET | 0.500 | 22.8 | 22.1 | 44.9 | CHI 39, DET 35 |
| PHI–DAL | 0.450 | 22.1 | 22.0 | 44.1 | PHI 39, DAL 38 |

Per-seed scores and artifact/source hashes are in each `ceg_frozen/summary.json` and `manifest.json`. The umbrella runs also contain failures for other models; this section reports only the individually completed CEG arms.

## V1 Complete

Each Thanksgiving game used 100 attempts (seeds 300001–300100), four workers, pinned code `41680940cb61749dd91c4e04ba374a9df8952600` and package `1b5a4369aa69f7fb739463d17fbc19c6ed7c307265e1368639fc812d795593a1`. No failed seed was replaced. Completed legal game counts are CHI–DET 89/100, PHI–DAL 91/100, and KC–BUF 85/100. These are execution and grading results, not evidence of forecast readiness.

| Game | Valid games | P(home wins) | Mean away | Mean home | Mean total | Prop rows | Prop Brier |
|---|---:|---:|---:|---:|---:|---:|---:|
| CHI–DET | 89/100 | 0.551 | 16.44 | 18.83 | 35.27 | 87 | 0.472 |
| PHI–DAL | 91/100 | 0.692 | 13.62 | 20.55 | 34.16 | 86 | 0.455 |
| KC–BUF | 85/100 | 0.824 | 10.51 | 23.29 | 33.80 | 86 | 0.225 |

Failure seeds, named blockers and exception stack traces are in each game's `failures.json`. Full play diagnostics and all attempts remain in the raw archives listed in `raw-archive-checksums.json`. Player prop lines and per-seed scores are in `grades.json` and each V1 Complete `summary.json`. Prop Brier excludes pushes and uses valid games only.
## Coverage and storage

The latest completed six-model results cover CHI–DET and PHI–DAL only; no completed 100-seed six-model KC–BUF batch was found. V1 Complete is the only current 100-seed sequence covering all three Thanksgiving games. CEG results are identified above. Raw run archives are kept under `/root/runs/week-12/games/<game>/raw`; the two completed six-model archives passed `gzip -t` and each contains 20 files. Raw host outputs have not been deleted.

These retrospective runs use frozen Nov 26 game inputs and must not be presented as prospective forecasts. No model was tuned or promoted from these results.

## Black Friday: DEN–PIT

The DEN–PIT pregame snapshot is frozen at SHA-256 `af7d7ad6b18bf2e2c528848655620b2eb9b817e5f1724cb03f054849db383293`. A 500-seed batch was started for V1, V1.6, Frozen V2, Simplified V2, Support-Aware V2, Soft Conditioning V2 and Frozen CEG (seeds 300001–300500); V1 Complete is intentionally excluded. The first single-process launch was stopped before it wrote a result file. The replacement run uses four concurrent 125-seed shards per model, with model variants run sequentially. At publication, the four V1 shards were running; this is an in-progress status, not a completed forecast or grade. Live manifest, shard outputs and run log are on the fast host under `/root/runs/week-12/games/2026_12_DEN_PIT/family-500-no-v1complete-20261127/`.

The separate 1,000-seed V1 Complete DEN–PIT run was paused after 541 emitted seed records. A direct audit recovered **532 valid completed games** (509 regulation and 23 overtime) and **9 blocked attempts**: 2 `fractional_penalty_state_not_supported_by_integer_game_state`, 4 `goal_line_gain_needs_offensive_touchdown_fact`, and 3 `play_yardage_crosses_end_line`. The compressed attempt stream lacks its final gzip trailer, but all 541 JSONL records were recovered before the truncation error. This remains a partial run, not a completed 1,000-game batch. Its manifest, stream and stack trace are preserved at `/root/runs/week-12/games/2026_12_DEN_PIT/family-1000-early-capture-20261127T172208Z/2026_12_DEN_PIT-20261127T191433Z-af7d7ad6b18b/`.
