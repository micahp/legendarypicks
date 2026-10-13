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

## 2026-10-13 slices (same harness, dev DB copied 2026-10-13 02:04 CDT)

The dev DB was re-ingested on 2026-10-13 (2024 logs now dated), so the baseline engine was re-run on the
same copy before any slice. Baseline v2.0 on 2025 weeks 3 to 18 (n = 3,945): targets MAE 1.567 (bias
-0.477), receptions 1.209 (-0.289), receiving yards 15.832 (-3.527), carries 1.157, rushing yards 6.503.
Gate PASS (receiving yards -0.599 [-0.888, -0.313], receptions -0.028 [-0.049, -0.008] vs Marcel-lite).
Every slice below is compared to this baseline on the same 3,945 player-games.

### Slice 4.3: observed and next-man-up redistribution (built, not the default)

Rule pre-registered in `History.team_shares` (commit 580a056) before the fit. Fitted on 2024 starter
absences (the top-share player of a position group removed by the report, 2+ group mates played):

| Metric | Cases | Next man up's fraction of the group's gain | Plain proportional would give |
|---|---|---|---|
| targets, 2024 (frozen) | 68 | 0.590 | 0.525 |
| carries, 2024 (frozen) | 58 | 0.519 | 0.571 |
| targets, 2025 (check only) | 67 | 0.475 | 0.570 |
| carries, 2025 (check only) | 57 | 0.726 | 0.722 |

The fitted rule is "next man up takes about 0.59 of the freed targets and 0.52 of the freed carries",
which is close to proportional and does not hold up on 2025, so at this sample size there is no stable
next-man-up premium. The next man up is the remaining group player with the highest base share, not the
depth chart: weekly depth charts on this box stop at 2024 (`nfl_hist_depth_charts`), so 2025 has none.

2025 run with `--redist 4.3`: gate PASS against Marcel-lite, but worse than the baseline on every
receiving stat (targets 1.590 vs 1.567, receptions 1.225 vs 1.209, receiving yards 15.910 vs 15.832,
carries 1.178 vs 1.157). The keep criterion written in the pre-registration compared target MAE on
"games where the redistribution fired", but the two rules fire on different sets (1,049 vs 3,570
player-games), so it was not a valid comparison and is not used. The paired same-sample comparison
decides: `REDIST` stays `v2.0` by default and the 4.3 rule is available behind the switch. Rule counts
under 4.3: none_out 4,134, proportional 2,047, group 759, observed 556, next_man_up 394.

### Slice 4.4: P(plays) by designation (built, in the weekly job)

Pre-registered in `nfl_player_projections_job.py` (commit before the fit), measured on
`player_game_availability`, REG games, offensive skill positions, played known from snap counts:

| Designation | 2024+2025 (frozen) | 2024 | 2025 | Unknown (no complete snap file) |
|---|---|---|---|---|
| Questionable | 493 of 723 = 0.682 | 257 of 383 = 0.671 | 236 of 340 = 0.694 | 57 |
| Doubtful | 0 of 84 | 0 of 63 | 0 of 21 | 18 |
| Out | 0 of 602 | 0 of 241 | 0 of 361 | 138 |

The 0.70 used until now came from all positions in 2025 (801 of 1,147); skill positions alone give 0.682.
Out-of-sample check: the 2024 rate (0.671) scored on the 340 Questionable skill player-games of 2025 has
Brier 0.2129 against 0.2124 for the flat 0.70, so the fitted rate is no better or worse at this sample;
it is used because it is the measured rate for the population the job projects. Doubtful and Out stay
removed (0 played in 686 known cases). The rate does not vary by anything else in this version
(position, practice status and team were not fitted).

### The under-projection bias (one defect fixed, one rule measured and not adopted)

**Defect fixed (56ddd26).** The engine took a player's opponent by comparing his log team (LAR, WSH, the
codes `player_game_logs` and `nfl_schedule` use) to the codes inside the nflverse game id (LA, WAS). On 2,882
of 43,786 NFL logs (2024 to 2026) the Rams or Commanders came out as their own opponent, and every team that
played them got a 0-target game in its "allowed" volume. The opponent now comes from the schedule row and a
log whose team is not in its game raises. Effect on 2025 (n = 3,945): targets MAE 1.567 to 1.562 (bias -0.477
to -0.433), receptions 1.209 to 1.207, receiving yards 15.832 to 15.849 (bias -3.527 to -3.197). Gate PASS.
This fixed engine is the baseline below.

**Where the rest of the bias is (`--diagnose-bias`, 2025 weeks 3 to 18, 480 team-games).** Team volume is
not low: projected minus actual team targets +0.76 per team-game, carries -0.59. The loss is in shares: 13.3%
of the projected targets (11.8% of carries) is held by candidates who were not removed by the report and do
not appear in the box score, so the players who did log were given 0.827 of the team's targets against an
actual 0.968. This supports the status doc's hypothesis.

**Rule tested (P_LOG, pre-registered c5233f3, frozen aa69707).** Weight every other candidate by his fitted
chance of logging, by how many of the team's last 3 games he logged and whether he logged the last one:

| Recent form (games of last 3, logged last) | 2024 (frozen) | 2025 (check) |
|---|---|---|
| 1, no | 271 of 790 = 0.343 | 0.329 |
| 1, yes | 326 of 547 = 0.596 | 0.621 |
| 2, no | 222 of 440 = 0.505 | 0.539 |
| 2, yes | 877 of 1,095 = 0.801 | 0.798 |
| 3, yes | 3,161 of 3,447 = 0.917 | 0.919 |

2025 result (n = 3,945): bias nearly gone (targets +0.085, receptions +0.098, receiving yards +0.660), share of
players who logged 0.984 against 0.968 actual. But MAE rose on every gated stat: targets 1.582 vs 1.562,
receptions 1.229 vs 1.207, receiving yards 16.308 vs 15.849. The pre-registered rule required no rise, so
**P_LOG is not adopted** (`P_LOG_2024` and `backtest --run --plog` keep it reproducible).

Why, measured but not pre-registered (information only): root mean squared error, which rewards the mean,
goes the other way. With P_LOG: targets 2.141 vs 2.202, receptions 1.659 vs 1.686, receiving yards 23.23 vs
23.61. The median of actual minus projection is -0.05 targets without P_LOG and -0.36 with it. The current
engine behaves like a median projection, and MAE rewards a median for right-skewed stats; the "bias" is
largely that. Which one to publish is a product decision: the mean (P_LOG) is what P(over) and the team
consistency check need; the gate as written (MAE) prefers the median. Not decided here.

### Slice 4.1: game script from SPEC A's projected margin (built, not adopted)

Rule pre-registered in `nfl_game_script.py` (22002fa): projected team targets and carries scaled by
clamp(1 + B x margin, 0.75, 1.25), margin from SPEC A version 1 (the adopted model the weekly lock publishes,
half_life 6, cap 14) walk-forward from earlier weeks only. The engine has no separate pass rate; targets and
carries are its pass and rush volumes. Fitted on 2024 weeks 3 to 18 (480 team-games): B_tgt -0.00259 and
B_car +0.00812 per point of margin (a 7-point favourite: targets -1.8%, carries +5.7%). On 2025 alone the
slopes are +0.00130 and +0.00387, so the targets effect does not even keep its sign.

2025 (`--run --script`): team MAE of targets 5.790 with the factor vs 5.784 without, carries 5.957 vs 5.939
(480 team-games); player MAE targets 1.563 vs 1.562, receptions 1.209 vs 1.207, receiving yards 15.880 vs
15.849 (n = 3,945). Gate against Marcel-lite still PASS, but parts (a) and (b) of the pre-registered rule
fail, so it is **not adopted** (`SCRIPT_2024`, `--run --script` reproduce it). The live job does not attach
margins. The 2026 SPEC A lock exists for week 5 only on the dev DB, so a live margin would also be missing for
most weeks today.

### Slice 4.5: quarterback passing (built, gate passed, in the weekly job)

Rule pre-registered in the engine (dad94e5) before the fit: team pass attempts (own and allowed, K_T 8) x the
quarterback's own regressed share of team attempts (not normalised against backups), x completion rate, yards
per attempt and TD per attempt regressed to the QB mean. Fitted on 2024 (410 QB-games, weeks 3 to 18):
K_CMP 160, K_YPA 160, K_PTD 320 pseudo-attempts (all interior to the grid 40 to 640); attempts negative
binomial R_ATT 14.62; yards a gamma sum per completion, shape G_PASS 1.15 (mean 11.07 yards per completion).

2025, weeks 3 to 18, a QB with 3+ earlier games who led his team in attempts (403 QB-games), MAE with the
paired bootstrap 95% interval of v2 minus Marcel-lite:

| Stat | v2 | Marcel-lite | Bias v2 | v2 - Marcel [95% CI] |
|---|---|---|---|---|
| attempts | 6.835 | 7.512 | -1.270 | -0.677 [-0.997, -0.363] |
| completions | 4.769 | 5.279 | -0.595 | -0.510 [-0.734, -0.286] |
| passing yards | 59.324 | 63.458 | -9.267 | -4.135 [-6.854, -1.471] |
| passing TDs | 0.971 | 1.010 | -0.106 | -0.039 [-0.076, -0.001] |

**Gate (passing yards and attempts below Marcel-lite): PASS**, every interval excludes zero. The simulated
p10 to p90 band holds 86.6% of attempts, 88.3% of completions, 87.3% of yards and 94.3% of TDs (nominal 80):
too wide, like the receiving band; do not read it as calibrated. The graded sample is "the QB who turned out to
lead his team in attempts"; the job publishes the expected passer chosen before the game (last game's
attempt leader unless Out or Doubtful), so a surprise starter is not projected.

**TD per opportunity** for receivers and rushers already existed (receiving TDs per target, K_TDT 160;
rushing TDs per carry, K_TDC 320). On the baseline 2025 run: receiving TDs MAE 0.234 vs Marcel-lite 0.239
(interval -0.011 to -0.001), rushing TDs 0.112 vs 0.112 (a tie).

**Rushing stays unpublished.** On the same baseline run carries are worse than Marcel-lite (1.153 vs 1.108,
interval +0.010 to +0.077) and rushing yards tie (6.512 vs 6.536, interval -0.213 to +0.152). No rushing rule
was changed in these slices, so there was no new rushing gate to run.

Not run: the job for 2026 (left to the coordinator). The stored week 6 rows on the dev DB predate these
changes and have no quarterbacks.

### Slice 4.6: team consistency gap (measured, nothing forced)

`backtest --consistency` (pre-registered in its docstring, committed before the run): every
2025 team-game, weeks 3 to 18 (480), every candidate not removed by the report projected by the default
engine (receiving and rushing, conditional on playing) and summed per team, beside SPEC A version 1's
walk-forward projected points. Per team-game rows: `docs/RESULTS-nfl-team-consistency-2025.csv`.

| Measure (mean per team-game) | Value |
|---|---|
| projected skill yards (receiving + rushing) | 336.2 |
| actual skill yards (same players' logs) | 342.4 |
| projected skill TDs | 2.36 |
| actual skill TDs | 2.43 |
| SPEC A projected points | 23.21 |
| actual points | 23.04 |
| gap = SPEC A points - 7 x projected TDs | 6.72 (sd 3.53, p10 2.21, p90 11.53) |

At team level the sum of player projections is close to the actual totals (yards -1.8%, TDs -0.07), which
is consistent with the bias finding above: the volume is there, it is spread over candidates who do not all
play. Across team-games, projected TDs correlate 0.532 with SPEC A's points and 0.474 for yards, but only 0.171
with actual points (SPEC A's own points: 0.331). The gap holds field goals and every other non-skill score,
so its level is expected; its spread is the inconsistency. By team, the mean gap runs from 1.48 (NO) to 9.71
(DAL) over 15 games each. Not used to adjust anything in this version.
