# Temporal-window ablation: results (exploratory)

Status: exploratory development evidence. Not a gate. 2024 and 2025 were both test seasons in the play-call gate, so nothing here is untouched. 2026 has not been read.

Scripts: `temporal_window.py` (run or pass, 2023 to 2025 targets) and `temporal_joint.py` (full play call, 2024 and 2025 targets). Each writes its JSON next to itself. Run from anywhere: `python3 temporal_window.py`, then `python3 temporal_joint.py`. Pre-declaration for the blend alternatives: `temporal_predeclaration.md`.

## Models

- A: league prior seasons, situation cell, backoff chain.
- B: same team, previous season.
- C: same team, current season, games before the target week.
- D3, D5: same team, last 3 or 5 games before the target game.
- E: previous season weighted by N0 / (N0 + games played), plus current season. N0 = 4 in the first run.

Team models smooth their own finest-context counts toward model A with K = 20. The target game is never in its window.

## Run or pass (`temporal_window.py`, targets 2023 to 2025)

Log loss per play. Lower is better.

| Model | 1-3 | 4-8 | 9-13 | 14-18 |
|---|---|---|---|---|
| A | 0.61798 | 0.61930 | 0.61994 | 0.62070 |
| B | 0.61782 | 0.61899 | 0.62026 | 0.62140 |
| C | 0.61787 | 0.61889 | 0.61892 | 0.61988 |
| E | 0.61756 | 0.61843 | 0.61872 | 0.61978 |

C minus B: weeks 9-13 -0.0013 [-0.0022, -0.0006]; weeks 14-18 -0.0015 [-0.0024, -0.0007]. Intervals are game-clustered 95%.

## Full play call (`temporal_joint.py`, targets 2024 and 2025)

Joint loss is personnel + formation + run or pass + concept, per play.

| Model | 1-3 | 4-8 | 9-13 | 14-18 |
|---|---|---|---|---|
| A | 4.1812 | 4.2381 | 4.3224 | 4.3618 |
| B | 4.1770 | 4.2334 | 4.3208 | 4.3617 |
| C | 4.1786 | 4.2268 | 4.2980 | 4.3316 |
| D5 | 4.1786 | 4.2279 | 4.3039 | 4.3454 |
| E | 4.1739 | 4.2226 | 4.2960 | 4.3304 |

Minus B, with game-clustered 95% intervals:
- C: 1-3 +0.0016 [-0.0030, +0.0064]; 4-8 -0.0066 [-0.0109, -0.0022]; 9-13 -0.0227 [-0.0299, -0.0157]; 14-18 -0.0300 [-0.0371, -0.0230].
- E: 1-3 -0.0030 [-0.0045, -0.0017]; 4-8 -0.0108 [-0.0140, -0.0079]; 9-13 -0.0248 [-0.0313, -0.0191]; 14-18 -0.0313 [-0.0384, -0.0250].

Step-level loss, weeks 9 to 18: personnel B 1.427 at 14-18 vs C 1.404 and E 1.403. Formation B 0.759 vs C 0.754 and E 0.753 at 9-13. Run or pass and concept show no meaningful difference between windows.

## Limits

- The team models use only the finest situation context for each step. This is not the gate table. All models share it, so the window comparison is fair.
- 2023 is not a target for the full play call because 2022 formation labels are unreliable.
- Bins are coarse. Week-level crossover, calibration and Brier are not yet reported.
- Workload realism is not tested. It needs the lineup layer.
- The N0 alternatives in `temporal_predeclaration.md` were not run yet.
