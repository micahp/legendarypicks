# Thanksgiving 2026 SLC run results

Status at 2026-11-27 10:25 CT. These are retrospective runs for the completed Nov 26 games. The latest completed six-model run has 100 requested seeds and 100 valid full games per model for CHI–DET and PHI–DAL. Frozen CEG separately completed 100/100 for PHI–DAL. V1 Complete 100-seed runs are active for all three Thanksgiving games; the three-game sequence has started with CHI–DET and its completed results will be added here after it finishes.

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

The 100-seed V1 Complete sequence is running one game at a time with four workers: CHI–DET, PHI–DAL, then KC–BUF. At report preparation, CHI–DET had 84 seed records written; this is progress, not a completed/graded result. Each game uses the frozen game snapshot, the same V1 Complete package and its pinned game-specific rating input. Seed failures are retained in the attempts output. Final counts, stack traces for failed seeds, and player boxes will be appended when the sequence completes.

## Coverage and storage

The latest completed six-model results cover CHI–DET and PHI–DAL only; no completed 100-seed six-model KC–BUF batch was found. V1 Complete is the only current 100-seed sequence covering all three Thanksgiving games. CEG results are identified above. Raw run archives are kept under `/root/runs/week-12/games/<game>/raw`; the two completed six-model archives passed `gzip -t` and each contains 20 files. Raw host outputs have not been deleted.

These retrospective runs use frozen Nov 26 game inputs and must not be presented as prospective forecasts. No model was tuned or promoted from these results.
