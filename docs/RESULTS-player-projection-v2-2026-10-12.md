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

## Simulated distribution (Spec B 4.5), same 3,945 player-games

Targets are negative binomial, receptions binomial, yards a gamma sum per reception, TDs binomial. Dispersion
fitted on 2024 by method of moments (targets R = 3.41, gamma shape G = 1.23 with a fixed 11 yard mean), frozen,
graded once on 2025. Nominal 80% inside p10 to p90, 10% in each tail.

| Stat | Inside | Below p10 | Above p90 |
|---|---|---|---|
| receiving yards | 86.9% | 1.8% | 11.3% |
| receptions | 91.8% | 0.3% | 7.9% |

The band is conservative (too wide), the low tail is nearly empty because p10 is often 0 and an outcome cannot
fall below it, and the upper tail is a little heavy, consistent with the negative bias above. Treat p10 as a
floor of zero for low-volume players and do not read the band as calibrated. Not yet built: the questionable
player scenarios (Spec B 4.4); the fitted P(plays | Questionable) from 2025 is 801 of 1,147 = 0.70 and
Doubtful 0 of 98, measured on `player_game_availability`.

## Against ESPN's published weekly projections (2025, pre-registered, no gate)

`capture_espn_weekly_projections.py` pulled ESPN's weekly projection for the 400 most-owned RB/WR/TE in 8
requests (3 second spacing, under the host budget): 14,604 rows, 344 players, weeks 3 to 18, 0 players unmatched
to ours. Same player-games for all three columns (n = 2,427, the intersection of the v2 sample and ESPN's
players), MAE:

| Stat | v2 | Marcel-lite | ESPN | v2 - ESPN [95% CI] |
|---|---|---|---|---|
| receptions | 1.394 | 1.439 | 1.377 | +0.017 [-0.015, +0.048] |
| receiving yards | 18.285 | 19.088 | 18.360 | -0.076 [-0.447, +0.294] |
| targets | 1.809 | 1.835 | 1.732 | +0.077 [+0.031, +0.123] |
| receiving TDs | 0.275 | 0.289 | 0.289 | -0.014 [-0.017, -0.011] |

v2 is level with ESPN on receptions and receiving yards, worse on targets, better on receiving TDs, and both beat
Marcel-lite. It does not beat ESPN. Three caveats, none corrected for: the sample is ESPN's most-owned players;
ESPN's number is an expectation that includes the chance the player sits while ours is conditional on playing and
scored only on games played (this favours us); and ESPN returns its current stored value for a past week, so
whether it equals the number shown before kickoff is unverified (the values look smooth across weeks, which
fits a rest-of-season model more than a weekly matchup one). The real comparison is the 2026 one: ESPN's
projection captured before kickoff, graded by `grade_nfl_player_projections.py`.
