# Week 10: KC at ATL, SLC model family

**Final:** ATL 13, KC 35 (home win = 0).

Inputs: the prospective snapshots built 2026-11-14 18:54:46Z, week-10 kicker table
(LA = McManus), week-9 streaks and snap counts. Each arm is its own git ref.

## Game level

| Arm | Valid seeds | P(ATL) | P(KC) | P(tie) | Home Brier | ATL mean (P10-P90) | KC mean (P10-P90) | Total | Combined score error |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|
| v1 | 1000 | 23.8% | 76.0% | 0.2% | 0.057 | 19.64 (9-31) | 27.93 (17-38) | 47.57 | 13.71 |
| v1.5 | 100 | 21.0% | 79.0% | 0.0% | 0.044 | 18.77 (9-28) | 28.11 (17-38) | 46.88 | 12.66 |
| v1.6 | 100 | 28.0% | 72.0% | 0.0% | 0.078 | 20.53 (10-31) | 28.81 (17-40) | 49.34 | 13.72 |
| v1.7 | 100 | 17.0% | 83.0% | 0.0% | 0.029 | 16.97 (8-28) | 27.38 (16-38) | 44.35 | 11.59 |
| v1.7-pr43 | 100 | 21.0% | 79.0% | 0.0% | 0.044 | 18.56 (9-30) | 28.21 (17-41) | 46.77 | 12.35 |
| v2 | 100 | 23.0% | 77.0% | 0.0% | 0.053 | 16.65 (9-26) | 25.31 (13-37) | 41.96 | 13.34 |

## Player stat accuracy (MAE over graded player-markets)

| Arm | Graded player-markets | MAE |
|---|---:|---:|
| v1 | 67 | 11.921 |
| v1.5 | 67 | 12.017 |
| v1.6 | 67 | 11.901 |
| v1.7 | 67 | 12.377 |
| v1.7-pr43 | 67 | 12.217 |
| v2 | 67 | 12.787 |

## Market grading

Not possible yet: `picks.dev.db` has no `prop_games` row for 2026-11-15
(newest NFL prop game is 2026-11-08), so there are no pre-kickoff lines for
this game. Prop Brier versus the de-vigged market runs once those lines land.

## Graded player-markets (model mean vs actual)

| Player | Team | Market | Actual | v1 | v1.5 | v1.6 | v1.7 | v1.7-pr43 | v2 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| Austin Hooper | ATL | receiving_yards | 8 | 1.90 | 1.66 | 2.14 | 0.76 | 2.20 | 3.94 |
| Austin Hooper | ATL | receptions | 1 | 0.18 | 0.24 | 0.22 | 0.13 | 0.19 | 0.46 |
| Austin Hooper | ATL | targets | 1 | 0.29 | 0.41 | 0.29 | 0.27 | 0.37 | 0.64 |
| Beaux Collins | ATL | targets | 2 | 0.87 | 0.93 | 1.14 | 0.78 | 1.00 | 0.13 |
| Bijan Robinson | ATL | receiving_yards | 6 | 31.85 | 27.52 | 33.85 | 35.74 | 34.76 | 31.49 |
| Bijan Robinson | ATL | receptions | 4 | 4.24 | 3.87 | 4.29 | 4.14 | 4.16 | 3.74 |
| Bijan Robinson | ATL | rush_tds | 1 | 0.74 | 0.64 | 0.60 | 0.48 | 0.66 | 0.58 |
| Bijan Robinson | ATL | rush_yards | 71 | 99.01 | 89.77 | 100.36 | 87.26 | 100.04 | 91.88 |
| Bijan Robinson | ATL | targets | 5 | 6.21 | 5.97 | 6.12 | 6.05 | 5.96 | 5.08 |
| Chris Blair | ATL | receiving_yards | 26 | 6.69 | 5.35 | 6.23 | 5.47 | 6.17 | 4.73 |
| Chris Blair | ATL | receptions | 1 | 0.57 | 0.44 | 0.48 | 0.47 | 0.63 | 0.45 |
| Chris Blair | ATL | targets | 4 | 0.90 | 0.76 | 0.85 | 0.73 | 1.19 | 0.75 |
| Drake London | ATL | receiving_yards | 109 | 133.47 | 148.06 | 134.95 | 123.54 | 118.94 | 79.44 |
| Drake London | ATL | receptions | 6 | 11.33 | 11.70 | 10.89 | 10.33 | 10.04 | 7.73 |
| Drake London | ATL | targets | 12 | 19.43 | 20.11 | 18.88 | 18.75 | 17.85 | 13.04 |
| Jahan Dotson | ATL | receiving_yards | 63 | 5.58 | 3.01 | 4.52 | 5.12 | 9.32 | 11.93 |
| Jahan Dotson | ATL | receptions | 3 | 0.49 | 0.30 | 0.49 | 0.38 | 0.64 | 1.17 |
| Jahan Dotson | ATL | targets | 6 | 0.87 | 0.59 | 0.88 | 0.78 | 0.97 | 2.16 |
| Khalil Herbert | ATL | receiving_yards | 7 | 1.46 | 1.27 | 1.40 | 1.63 | 1.97 | 1.06 |
| Khalil Herbert | ATL | receptions | 2 | 0.21 | 0.18 | 0.13 | 0.22 | 0.20 | 0.11 |
| Khalil Herbert | ATL | targets | 3 | 0.32 | 0.30 | 0.23 | 0.34 | 0.27 | 0.18 |
| Kyle Pitts Sr. | ATL | receiving_yards | 50 | 39.99 | 41.29 | 39.11 | 38.27 | 33.07 | 25.70 |
| Kyle Pitts Sr. | ATL | receptions | 4 | 4.34 | 4.50 | 4.30 | 4.24 | 3.83 | 2.71 |
| Kyle Pitts Sr. | ATL | targets | 5 | 7.17 | 7.75 | 7.71 | 7.10 | 6.45 | 4.31 |
| Michael Penix Jr. | ATL | interceptions | 1 | 0.67 | 0.66 | 0.69 | 0.63 | 0.77 | 0.66 |
| Michael Penix Jr. | ATL | pass_attempts | 43 | 38.27 | 39.15 | 38.26 | 36.78 | 36.07 | 31.34 |
| Michael Penix Jr. | ATL | pass_completions | 23 | 23.27 | 23.25 | 22.75 | 21.55 | 21.59 | 19.24 |
| Michael Penix Jr. | ATL | pass_yards | 286 | 241.00 | 248.46 | 243.44 | 228.30 | 225.80 | 186.09 |
| Michael Penix Jr. | ATL | rush_yards | 29 | 14.28 | 13.05 | 15.79 | 10.30 | 12.28 | 16.26 |
| Olamide Zaccheaus | ATL | receiving_yards | 17 | 6.27 | 8.86 | 7.14 | 4.12 | 4.26 | 10.07 |
| Olamide Zaccheaus | ATL | receptions | 2 | 0.52 | 0.69 | 0.59 | 0.43 | 0.39 | 0.93 |
| Olamide Zaccheaus | ATL | targets | 4 | 0.87 | 1.15 | 0.94 | 0.78 | 0.70 | 1.93 |
| Andrew Armstrong | KC | receiving_tds | 1 | 0.02 | 0.03 | 0.02 | 0.02 | 0.02 | 0.02 |
| Andrew Armstrong | KC | receiving_yards | 43 | 3.63 | 3.46 | 5.82 | 4.68 | 3.17 | 1.78 |
| Andrew Armstrong | KC | receptions | 1 | 0.28 | 0.33 | 0.37 | 0.46 | 0.26 | 0.19 |
| Andrew Armstrong | KC | targets | 1 | 0.46 | 0.58 | 0.63 | 0.66 | 0.42 | 0.33 |
| Cyrus Allen | KC | receiving_tds | 1 | 0.03 | 0.01 | 0.04 | 0.02 | 0.05 | 0.03 |
| Cyrus Allen | KC | receiving_yards | 44 | 4.26 | 4.46 | 4.77 | 1.91 | 5.18 | 2.73 |
| Cyrus Allen | KC | receptions | 2 | 0.35 | 0.46 | 0.41 | 0.23 | 0.45 | 0.28 |
| Cyrus Allen | KC | targets | 4 | 0.54 | 0.66 | 0.70 | 0.40 | 0.81 | 0.38 |
| Emmett Johnson | KC | receiving_tds | 2 | 0.03 | 0.04 | 0.03 | 0.03 | 0.01 | 0.12 |
| Emmett Johnson | KC | receiving_yards | 70 | 3.28 | 2.88 | 3.16 | 3.53 | 3.48 | 11.47 |
| Emmett Johnson | KC | receptions | 6 | 0.48 | 0.40 | 0.47 | 0.53 | 0.55 | 1.89 |
| Emmett Johnson | KC | rush_yards | 101 | 8.74 | 8.84 | 8.05 | 8.16 | 13.38 | 38.47 |
| Emmett Johnson | KC | targets | 7 | 0.71 | 0.58 | 0.66 | 0.77 | 0.74 | 2.43 |
| Jake Briningstool | KC | receiving_yards | 20 | 2.47 | 3.68 | 2.01 | 1.74 | 3.66 | 2.30 |
| Jake Briningstool | KC | receptions | 1 | 0.26 | 0.27 | 0.26 | 0.22 | 0.33 | 0.20 |
| Jake Briningstool | KC | targets | 2 | 0.40 | 0.32 | 0.36 | 0.28 | 0.43 | 0.27 |
| Josh Downs | KC | receiving_tds | 1 | 0.03 | 0.01 | 0.02 | 0.03 | 0.03 | 0.00 |
| Josh Downs | KC | receiving_yards | 53 | 4.20 | 2.66 | 2.81 | 4.85 | 3.04 | 0.00 |
| Josh Downs | KC | receptions | 4 | 0.35 | 0.28 | 0.28 | 0.37 | 0.28 | 0.00 |
| Josh Downs | KC | targets | 5 | 0.53 | 0.45 | 0.48 | 0.59 | 0.48 | 0.00 |
| Nate Carter | KC | rush_yards | 6 | - | - | - | - | - | - |
| Noah Gray | KC | receiving_yards | 6 | 19.84 | 24.48 | 19.22 | 18.60 | 18.83 | 15.92 |
| Noah Gray | KC | receptions | 1 | 1.88 | 2.10 | 1.86 | 1.84 | 1.77 | 1.49 |
| Noah Gray | KC | targets | 3 | 2.69 | 3.17 | 2.64 | 2.43 | 2.66 | 2.02 |
| Patrick Mahomes | KC | pass_attempts | 35 | 39.69 | 38.66 | 38.50 | 38.83 | 39.24 | 39.01 |
| Patrick Mahomes | KC | pass_completions | 22 | 26.49 | 25.42 | 25.58 | 26.26 | 26.34 | 26.83 |
| Patrick Mahomes | KC | pass_tds | 5 | 1.88 | 1.86 | 2.23 | 1.89 | 1.96 | 1.55 |
| Patrick Mahomes | KC | pass_yards | 348 | 286.41 | 281.15 | 285.45 | 268.49 | 266.14 | 262.36 |
| Patrick Mahomes | KC | rush_yards | 15 | 30.45 | 31.10 | 29.79 | 26.75 | 28.50 | 26.24 |
| Rashee Rice | KC | receiving_yards | 82 | 61.98 | 54.43 | 62.52 | 51.75 | 54.58 | 44.24 |
| Rashee Rice | KC | receptions | 5 | 5.24 | 4.52 | 4.71 | 4.71 | 4.88 | 4.04 |
| Rashee Rice | KC | targets | 6 | 7.62 | 6.86 | 7.05 | 6.71 | 7.06 | 5.92 |
| Travis Kelce | KC | receiving_yards | 30 | 58.63 | 53.68 | 60.48 | 59.35 | 51.24 | 60.02 |
| Travis Kelce | KC | receptions | 2 | 5.56 | 5.11 | 5.39 | 5.61 | 5.06 | 5.89 |
| Travis Kelce | KC | targets | 2 | 7.98 | 7.43 | 7.73 | 7.86 | 7.21 | 8.51 |
| Xavier Worthy | KC | targets | 3 | 6.95 | 7.15 | 6.63 | 6.79 | 7.63 | 10.32 |
