# Week 10: MIN at GB, SLC model family

**Final:** GB 10, MIN 30 (home win = 0).

Inputs: the prospective snapshots built 2026-11-14 18:54:46Z, week-10 kicker table
(LA = McManus), week-9 streaks and snap counts. Each arm is its own git ref.

## Game level

| Arm | Valid seeds | P(GB) | P(MIN) | P(tie) | Home Brier | GB mean (P10-P90) | MIN mean (P10-P90) | Total | Combined score error |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|
| v1 | 100 | 55.0% | 45.0% | 0.0% | 0.303 | 23.97 (13-34) | 21.70 (10-31) | 45.67 | 22.27 |
| v1.5 | 100 | 60.0% | 40.0% | 0.0% | 0.360 | 25.71 (16-37) | 21.81 (10-33) | 47.52 | 23.90 |
| v1.6 | 100 | 69.0% | 31.0% | 0.0% | 0.476 | 28.16 (19-38) | 22.35 (13-33) | 50.51 | 25.81 |
| v1.7 | 100 | 57.0% | 43.0% | 0.0% | 0.325 | 24.58 (13-37) | 21.09 (10-30) | 45.67 | 23.49 |
| v1.7-pr43 | 100 | 65.0% | 35.0% | 0.0% | 0.423 | 24.16 (16-34) | 18.92 (7-29) | 43.08 | 25.24 |
| v2 | 100 | 73.0% | 26.0% | 1.0% | 0.533 | 22.75 (13-36) | 16.82 (7-30) | 39.57 | 25.93 |

## Player stat accuracy (MAE over graded player-markets)

| Arm | Graded player-markets | MAE |
|---|---:|---:|
| v1 | 68 | 8.812 |
| v1.5 | 68 | 8.939 |
| v1.6 | 68 | 8.831 |
| v1.7 | 68 | 7.696 |
| v1.7-pr43 | 68 | 7.941 |
| v2 | 68 | 7.972 |

## Market grading

Not possible yet: `picks.dev.db` has no `prop_games` row for 2026-11-15
(newest NFL prop game is 2026-11-08), so there are no pre-kickoff lines for
this game. Prop Brier versus the de-vigged market runs once those lines land.

## Graded player-markets (model mean vs actual)

| Player | Team | Market | Actual | v1 | v1.5 | v1.6 | v1.7 | v1.7-pr43 | v2 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| Chris Brooks | GB | receiving_yards | 2 | 19.30 | 20.66 | 18.48 | 21.49 | 20.08 | 11.79 |
| Chris Brooks | GB | receptions | 1 | 2.68 | 2.57 | 2.38 | 2.63 | 2.58 | 1.79 |
| Chris Brooks | GB | rush_yards | 1 | 67.42 | 76.83 | 77.04 | 73.60 | 78.74 | 46.88 |
| Chris Brooks | GB | targets | 1 | 3.67 | 3.51 | 3.18 | 3.47 | 3.31 | 2.46 |
| Christian Watson | GB | receiving_yards | 37 | 68.91 | 59.96 | 64.77 | 47.93 | 53.79 | 70.14 |
| Christian Watson | GB | receptions | 3 | 5.31 | 4.94 | 5.06 | 4.11 | 4.69 | 5.92 |
| Christian Watson | GB | targets | 5 | 8.14 | 7.96 | 7.70 | 6.56 | 7.90 | 9.32 |
| J. Michael Sturdivant | GB | receiving_tds | 1 | 0.02 | 0.01 | 0.04 | 0.02 | 0.03 | 0.00 |
| J. Michael Sturdivant | GB | receiving_yards | 37 | 2.86 | 3.48 | 5.17 | 4.22 | 5.05 | 0.76 |
| J. Michael Sturdivant | GB | receptions | 2 | 0.25 | 0.32 | 0.48 | 0.31 | 0.38 | 0.05 |
| J. Michael Sturdivant | GB | targets | 4 | 0.41 | 0.53 | 0.71 | 0.54 | 0.49 | 0.10 |
| Jordan Love | GB | interceptions | 1 | 0.57 | 0.58 | 0.43 | 0.66 | 0.51 | 0.49 |
| Jordan Love | GB | pass_attempts | 27 | 36.12 | 35.46 | 35.00 | 34.87 | 34.16 | 37.49 |
| Jordan Love | GB | pass_completions | 17 | 24.11 | 24.11 | 24.24 | 23.40 | 23.11 | 24.28 |
| Jordan Love | GB | pass_tds | 1 | 1.38 | 1.42 | 1.99 | 1.60 | 1.46 | 1.33 |
| Jordan Love | GB | pass_yards | 220 | 272.85 | 264.44 | 262.71 | 248.09 | 250.99 | 253.89 |
| Kaleb Johnson | GB | rush_yards | 42 | 10.46 | 12.16 | 14.25 | 14.93 | 12.44 | 14.08 |
| MarShawn Lloyd | GB | receiving_yards | 26 | 4.25 | 3.55 | 6.23 | 4.43 | 6.47 | 10.65 |
| MarShawn Lloyd | GB | receptions | 3 | 0.56 | 0.49 | 0.78 | 0.74 | 0.67 | 1.43 |
| MarShawn Lloyd | GB | rush_yards | 13 | 12.43 | 13.78 | 19.06 | 13.27 | 14.19 | 35.56 |
| MarShawn Lloyd | GB | targets | 3 | 0.90 | 0.68 | 1.07 | 0.99 | 0.83 | 1.99 |
| Mark Redman | GB | receiving_yards | 5 | 4.16 | 2.91 | 2.54 | 2.49 | 1.95 | 2.97 |
| Mark Redman | GB | receptions | 1 | 0.30 | 0.23 | 0.27 | 0.23 | 0.20 | 0.27 |
| Mark Redman | GB | targets | 1 | 0.42 | 0.28 | 0.35 | 0.33 | 0.36 | 0.30 |
| Matthew Golden | GB | receiving_yards | 70 | 58.25 | 50.41 | 49.84 | 47.51 | 47.33 | 74.15 |
| Matthew Golden | GB | receptions | 5 | 4.56 | 4.31 | 4.32 | 4.02 | 3.97 | 6.88 |
| Matthew Golden | GB | targets | 9 | 6.91 | 6.45 | 6.48 | 6.26 | 6.03 | 11.26 |
| Savion Williams | GB | receiving_yards | 27 | 11.95 | 11.63 | 11.86 | 8.91 | 9.78 | 10.92 |
| Savion Williams | GB | receptions | 2 | 0.97 | 0.88 | 0.91 | 0.82 | 0.74 | 1.16 |
| Savion Williams | GB | targets | 2 | 1.42 | 1.32 | 1.19 | 1.12 | 1.18 | 1.68 |
| Tucker Kraft | GB | receiving_yards | 19 | 26.80 | 24.74 | 25.36 | 25.72 | 25.39 | 47.41 |
| Tucker Kraft | GB | receptions | 1 | 2.50 | 2.48 | 2.52 | 2.51 | 2.29 | 4.09 |
| Tucker Kraft | GB | targets | 4 | 3.66 | 3.53 | 3.43 | 3.61 | 3.23 | 5.94 |
| Tyrod Taylor | GB | pass_attempts | 2 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Tyrod Taylor | GB | pass_completions | 1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Tyrod Taylor | GB | pass_yards | 3 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Aaron Jones Sr. | MIN | receiving_yards | 8 | 17.28 | 18.61 | 19.85 | 18.84 | 14.66 | 16.35 |
| Aaron Jones Sr. | MIN | receptions | 1 | 2.34 | 2.69 | 2.77 | 2.52 | 2.19 | 2.05 |
| Aaron Jones Sr. | MIN | rush_tds | 1 | 0.28 | 0.32 | 0.40 | 0.18 | 0.25 | 0.18 |
| Aaron Jones Sr. | MIN | rush_yards | 47 | 47.25 | 41.64 | 48.14 | 46.61 | 53.08 | 57.10 |
| Aaron Jones Sr. | MIN | targets | 1 | 3.27 | 3.77 | 3.75 | 3.29 | 3.10 | 3.02 |
| Ben Yurosek | MIN | receiving_yards | 7 | 10.21 | 7.93 | 7.12 | 7.88 | 8.19 | 21.08 |
| Ben Yurosek | MIN | receptions | 1 | 1.07 | 0.75 | 0.74 | 0.85 | 0.88 | 2.35 |
| Ben Yurosek | MIN | targets | 1 | 1.45 | 1.25 | 1.08 | 1.24 | 1.32 | 3.36 |
| Gavin Bartholomew | MIN | receiving_tds | 1 | 0.06 | 0.03 | 0.03 | 0.05 | 0.10 | 0.03 |
| Gavin Bartholomew | MIN | receiving_yards | 36 | 9.85 | 6.44 | 7.07 | 8.38 | 9.58 | 4.34 |
| Gavin Bartholomew | MIN | receptions | 3 | 0.95 | 0.66 | 0.72 | 0.91 | 0.78 | 0.53 |
| Gavin Bartholomew | MIN | targets | 4 | 1.46 | 1.11 | 1.21 | 1.27 | 1.10 | 0.81 |
| Jordan Mason | MIN | rush_yards | 59 | 66.44 | 65.98 | 56.16 | 66.15 | 53.44 | 43.30 |
| Jordan Mason | MIN | targets | 1 | 1.06 | 1.01 | 1.26 | 1.21 | 1.31 | 1.60 |
| Justin Jefferson | MIN | receiving_yards | 74 | 108.22 | 109.59 | 104.82 | 94.17 | 91.75 | 76.72 |
| Justin Jefferson | MIN | receptions | 9 | 9.25 | 9.10 | 8.86 | 8.48 | 8.76 | 7.07 |
| Justin Jefferson | MIN | targets | 13 | 13.93 | 13.91 | 13.31 | 13.18 | 13.45 | 12.58 |
| Kirk Cousins | MIN | interceptions | 1 | 0.90 | 1.02 | 0.96 | 0.89 | 0.97 | 1.13 |
| Kirk Cousins | MIN | pass_attempts | 31 | 35.81 | 35.85 | 36.48 | 34.10 | 34.85 | 35.79 |
| Kirk Cousins | MIN | pass_completions | 21 | 24.39 | 24.13 | 25.04 | 22.97 | 23.47 | 21.61 |
| Kirk Cousins | MIN | pass_tds | 2 | 1.44 | 1.24 | 1.51 | 1.46 | 1.30 | 0.96 |
| Kirk Cousins | MIN | pass_yards | 207 | 254.09 | 257.19 | 263.47 | 231.96 | 233.73 | 209.89 |
| Kirk Cousins | MIN | rush_yards | 11 | 8.36 | 11.05 | 9.23 | 9.32 | 9.36 | 12.14 |
| Max Bredeson | MIN | targets | 1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Myles Price | MIN | receiving_tds | 1 | 0.01 | 0.00 | 0.02 | 0.02 | 0.02 | 0.04 |
| Myles Price | MIN | receiving_yards | 49 | 2.25 | 2.85 | 3.83 | 3.75 | 1.74 | 2.60 |
| Myles Price | MIN | receptions | 4 | 0.28 | 0.27 | 0.30 | 0.22 | 0.21 | 0.27 |
| Myles Price | MIN | rush_yards | 12 | 0.08 | 0.20 | 0.39 | 0.48 | 0.32 | 0.34 |
| Myles Price | MIN | targets | 4 | 0.37 | 0.34 | 0.41 | 0.35 | 0.41 | 0.58 |
| Tai Felton | MIN | receiving_yards | 33 | 2.70 | 2.98 | 3.97 | 4.05 | 3.05 | 5.91 |
| Tai Felton | MIN | receptions | 3 | 0.30 | 0.21 | 0.34 | 0.43 | 0.36 | 0.45 |
| Tai Felton | MIN | targets | 5 | 0.45 | 0.30 | 0.54 | 0.61 | 0.51 | 0.82 |
