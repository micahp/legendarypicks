# Player projection v2 backtest (Spec B section 5 gate), 2026-10-12

Engine `backend/nfl_player_projection_v2.py`, harness `backend/backtest_nfl_player_projection_v2.py`. Both
were committed with their rules (`27d8efe`) before any 2025 number was computed. Constants were fitted on
2024 only, frozen in a separate commit, then the 2025 run was made once.

## Fitted on 2024 (3,298 player-games, weeks 3 to 18)

| Constant | Value | Grid | Note |
|---|---|---|---|
| H (recency half-life, weeks) | 8 | 2, 4, 8 | top edge of the grid |
| K_S (share prior, pseudo-games) | 1 | 1 to 8 | bottom edge |
| K_T (team volume, pseudo-games) | 8 | 2, 4, 8 | top edge |
| K_CR (catch rate) | 80 | 10 to 160 | interior |
| K_YPT (yards per target) | 160 | 10 to 160 | top edge |
| K_TDT (TD per target) | 160 | 20 to 320 | interior |
| K_YPC (yards per carry) | 160 | 10 to 160 | top edge |
| K_TDC (TD per carry) | 320 | 20 to 320 | top edge |
| OTHER (targets to players outside the candidate set) | 0.0424 | | 480 team-weeks |

Seven of nine sit on a grid edge, so the true optimum may be beyond it. The grids were pre-registered and
were not widened.

## 2025, weeks 3 to 18, RB/WR/TE who played and had 3+ earlier games (n = 3,945)

MAE of v2, Marcel-lite on the same season (exactly the live route, `m1`) and Marcel-lite over 2024+2025 (`m2`).
Last column is the paired player-game bootstrap 95% interval of MAE(v2) - MAE(m1).

| Stat | MAE v2 | MAE m1 | MAE m2 | Bias v2 | v2 - m1 [95% CI] |
|---|---|---|---|---|---|
| targets | 1.578 | 1.589 | 1.591 | -0.493 | -0.010 [-0.039, +0.018] |
| receptions | 1.216 | 1.237 | 1.241 | -0.300 | -0.021 [-0.041, +0.000] |
| receiving yards | 15.910 | 16.431 | 16.411 | -3.645 | -0.521 [-0.813, -0.220] |
| receiving TDs | 0.232 | 0.239 | 0.243 | -0.027 | -0.007 [-0.012, -0.002] |
| carries | 1.182 | 1.108 | 1.140 | -0.452 | +0.074 [+0.037, +0.109] |
| rushing yards | 6.602 | 6.536 | 6.669 | -1.985 | +0.066 [-0.137, +0.256] |
| rushing TDs | 0.112 | 0.112 | 0.114 | -0.014 | -0.000 [-0.004, +0.003] |

**Gate (receiving yards and receptions both lower than Marcel-lite): PASS by the rule as written.** Read it
for what it is:
- Receiving yards is a clear improvement (interval excludes zero). Receptions is a small one whose interval
  touches zero (upper end +0.000). Targets are a tie.
- By position, receiving yards: RB 9.47 vs 9.95, WR 20.29 vs 21.08, TE 15.64 vs 15.68 (a tie).
- **Rushing is not better.** Carries are worse than Marcel-lite (+0.074, interval excludes zero); rushing
  yards and TDs tie. v2 should not replace Marcel-lite for rushing.
- **v2 under-projects every stat** (targets -0.49, receiving yards -3.6 per player-game). A mean error of
  this size on a conditional-on-playing projection suggests team volume or the candidate normalisation is
  low. Not investigated yet.
- Ignoring the injury report the same games cost 1.624 target MAE against 1.595 with it (n = 3,570, Marcel
  1.601). The count is every game where any teammate was Out or Doubtful, defenders included, so it is not a
  clean measure of the redistribution rule; rule counts: proportional 6,994, observed blend 146, none out 750.
- Not done: next-man-up weighting (Spec B 4.3), game-script adjustment (needs SPEC A margin), quarterback
  passing, ESPN's weekly projections as a benchmark.
