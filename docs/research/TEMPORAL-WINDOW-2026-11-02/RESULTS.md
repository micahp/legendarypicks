# Temporal-window ablation: results (exploratory)

Status: exploratory development evidence. Not a gate. 2024 and 2025 were both test seasons in the play-call gate, so nothing here is untouched. 2026 has not been read.

Scripts: `temporal_window.py` (run or pass, 2023 to 2025 targets) and `temporal_joint.py` (full play call, 2024 and 2025 targets). Each writes its JSON next to itself. Run from anywhere: `python3 temporal_window.py`, then `python3 temporal_joint.py`. Pre-declaration for the blend alternatives: `temporal_predeclaration.md`. `temporal_blend_fast.py` runs the N0 alternatives in about two minutes.

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

## Blend alternatives (`temporal_blend_fast.py`, targets 2024 and 2025)

Post-hoc. N0 = 2 and N0 = 8 were added after the first run, so this is development evidence, not a confirmation. The selection rule from `temporal_predeclaration.md` is the lowest pooled 2024 to 2025 joint loss over weeks 1 to 18. Output: `temporal_blend_fast.json`.

Joint loss per play. Lower is better.

| Model | 1-3 | 4-8 | 9-13 | 14-18 |
|---|---|---|---|---|
| B | 4.17696 | 4.23343 | 4.32077 | 4.36168 |
| C | 4.17859 | 4.22682 | 4.29803 | 4.33165 |
| E2 (N0 = 2) | 4.17379 | 4.22328 | 4.29647 | 4.33069 |
| E4 (N0 = 4) | 4.17395 | 4.22265 | 4.29601 | 4.33035 |
| E8 (N0 = 8) | 4.17419 | 4.22254 | 4.29591 | 4.33026 |

Minus B, with game-clustered 95% intervals:
- E2: 1-3 -0.0032 [-0.0049, -0.0016]; 4-8 -0.0102 [-0.0136, -0.0071]; 9-13 -0.0243 [-0.0309, -0.0184]; 14-18 -0.0310 [-0.0384, -0.0245].
- E4: 1-3 -0.0030 [-0.0044, -0.0016]; 4-8 -0.0108 [-0.0136, -0.0080]; 9-13 -0.0248 [-0.0317, -0.0187]; 14-18 -0.0313 [-0.0382, -0.0246].
- E8: 1-3 -0.0028 [-0.0040, -0.0016]; 4-8 -0.0109 [-0.0137, -0.0082]; 9-13 -0.0249 [-0.0315, -0.0191]; 14-18 -0.0314 [-0.0388, -0.0253].

Pooled joint loss, weeks 1 to 18: B 4.28356, C 4.26739, D3 4.27633, D5 4.27319, E2 4.26490, E4 4.26453, E8 4.26449.

Selection: E8 is lowest, but only by 0.00004 over E4. E2 to E8 differ by under 0.0005 pooled, so the N0 choice within this range matters little. Every E variant beats C in every bin, and C beats B in weeks 4 to 18.

## Limits

- The team models use only the finest situation context for each step. This is not the gate table. All models share it, so the window comparison is fair.
- 2023 is not a target for the full play call because 2022 formation labels are unreliable.
- Bins are coarse. Week-level crossover, calibration and Brier are not yet reported.
- Workload realism is not tested. It needs the lineup layer.
- The N0 alternatives in `temporal_predeclaration.md` were run after the first run, so they are post-hoc (see the blend section).
