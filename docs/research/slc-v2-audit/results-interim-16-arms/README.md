# V2 mechanism ablation: interim results, 16 of 39 arms (2026-11-25)

Preliminary. 13 week 11 games, 20 matched seeds per game (300001-300020), many comparisons at once: read effects with
intervals below or above zero as signals to confirm, not as findings. The full report follows when all 39 arms are done.

Control A00 (full V2) reproduces the frozen V2 exactly on all 13 games (260/260 seeds, scores and player box scores).
Graded with the week 11 grader (`grading/`: build_report.py, props_compare.py, grade.py, the same inputs as the frozen
grading: games.csv f3a6752c, stats 0be2a210, props from picks.dev.db) plus `grading/compare_arms.py` (arm minus control,
95% game-bootstrap interval). 1,037 graded props per arm.

| arm (mechanism removed) | home-win Brier vs control | prop Brier vs control | prop log loss vs control |
|---|---|---|---|
| S1 participation lineup | +0.030 (n.s.) | **-0.022 (-0.045 to -0.003)** | **-0.114 (-0.192 to -0.049)** |
| K3 streak context | +0.015 (n.s.) | **-0.017 (-0.028 to -0.007)** | **-0.049 (-0.078 to -0.019)** |
| P1 score-clock play-calling | +0.014 (n.s.) | **-0.009 (-0.017 to -0.002)** | **-0.032 (-0.052 to -0.012)** |
| D1 Dirichlet player shares | **-0.046 (-0.078 to -0.019)** | +0.012 (n.s.) | **+0.055 (+0.017 to +0.094)** |
| F1 formation choice | **+0.064 (+0.022 to +0.109)** | -0.004 (n.s.) | -0.008 (n.s.) |
| G1 no multipliers, G2 no filters, G3 both, T1 team weights, U3 player outcome strength, Q4 QB model, L1 labels, L6 label modifiers, C1 coverage | no detected effect | no detected effect | no detected effect |

Control: home-win Brier 0.211, prop Brier 0.316, valid games 100%. G4 (league-wide outcomes) equals G3 exactly, as
expected. The SD of team mean points falls from 3.5 (control) to 1.9 without multipliers and filters (G3).
The D1 home-win result is probably noise: player allocation should barely move game winners.
