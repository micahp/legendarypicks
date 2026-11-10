# Corrected workload evaluation, 2026-11-08

Research only. These results use the local read-only `picks.dev.db` at approximately 12:26–12:28 p.m. Central on 2026-11-08, with code `596ce748`. The mutable database was not frozen or hashed, so this is not an independently reproducible run identity. Player positions come from the current `players` table, not a cutoff-frozen position source; pregame eligibility is unknown. Historical observed play opportunities are used, and absence of an opportunity is not proof of inactivity. Original reports in the parent directory remain unchanged.

The original group interval used a beta share times the observed total. The corrected interval samples beta-binomial counts (3,000 draws, seed 0). Group coverage uses one observation per team-game and does not measure individual allocation. C and D still use the old C concentration for these coverage numbers.

| Position / role | team-games | old C / D coverage | corrected C / D coverage | conditional player NLL C / D |
|---|---:|---:|---:|---:|
| RB carry | 242 | 0.746 / 0.783 | 0.897 / 0.921 | 11.694 / 8.918 |
| QB carry | 242 | 0.832 / 0.852 | 0.967 / 0.992 | 2.468 / 1.949 |
| WR target | 242 | 0.705 / 0.734 | 0.917 / 0.934 | 18.640 / 14.701 |
| TE target | 242 | 0.807 / 0.799 | 0.930 / 0.938 | 6.734 / 5.710 |
| RB target | 242 | 0.783 / 0.770 | 0.942 / 0.950 | 6.668 / 5.772 |

Conditional NLL scores player counts given the observed group total, with unseen same-position players pooled into OTHER at 2% prior mass. It does not evaluate the simulator's position-group chooser. The higher coverage does not establish calibration: the roster, position mapping and conditional count population are not independently verified, the prior concentration is not D-fitted, and 3,000 Monte Carlo draws introduce small sampling variation.

The D concentration fitter separately minimizes within-group NLL on rolling 2025 team-games and evaluates the fitted values on weeks 1–8 of 2026. It reports RB carry phi 1.413, QB carry 1.0 (lower grid boundary), WR target 3.528, TE target 2.065 and RB target 1.514. Each group has 544 training and 242 test team-games. This fitting exercise uses the same 2% OTHER convention and current position lookup; the grid-boundary QB fit is unresolved. The 2025/2026 datasets have been used in prior model development, so the test is temporally separated but not an untouched research holdout. These fits have not been applied to the simulator, and no C-versus-D paired simulation or claim of player-level predictive calibration follows from them.
