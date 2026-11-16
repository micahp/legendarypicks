# Week 10: LA at ARI, SLC model family

**Final:** ARI 6, LA 34 (home win = 0).

Inputs: the prospective snapshots built 2026-11-14 18:54:46Z, week-10 kicker table
(LA = McManus), week-9 streaks and snap counts. Each arm is its own git ref.

## Game level

| Arm | Valid seeds | P(ARI) | P(LA) | P(tie) | Home Brier | ARI mean (P10-P90) | LA mean (P10-P90) | Total | Combined score error |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|
| v1 | 100 | 29.0% | 71.0% | 0.0% | 0.084 | 22.36 (12-34) | 27.17 (17-38) | 49.53 | 23.19 |
| v1.5 | 100 | 40.0% | 60.0% | 0.0% | 0.160 | 21.43 (13-31) | 25.13 (16-35) | 46.56 | 24.30 |
| v1.6 | 100 | 46.0% | 54.0% | 0.0% | 0.212 | 24.84 (13-37) | 26.22 (15-36) | 51.06 | 26.62 |
| v1.7 | 100 | 37.0% | 63.0% | 0.0% | 0.137 | 22.40 (13-34) | 25.42 (14-38) | 47.82 | 24.98 |
| v1.7-pr43 | 100 | 36.0% | 64.0% | 0.0% | 0.130 | 20.74 (11-30) | 25.41 (15-38) | 46.15 | 23.33 |
| v2 | 100 | 29.0% | 71.0% | 0.0% | 0.084 | 19.98 (10-30) | 24.91 (13-35) | 44.89 | 23.07 |

## Player stat accuracy (MAE over graded player-markets)

| Arm | Graded player-markets | MAE |
|---|---:|---:|
| v1 | 64 | 10.545 |
| v1.5 | 64 | 10.146 |
| v1.6 | 64 | 10.549 |
| v1.7 | 64 | 9.961 |
| v1.7-pr43 | 64 | 10.025 |
| v2 | 64 | 11.097 |

## Market grading

Not possible yet: `picks.dev.db` has no `prop_games` row for 2026-11-15
(newest NFL prop game is 2026-11-08), so there are no pre-kickoff lines for
this game. Prop Brier versus the de-vigged market runs once those lines land.

## Graded player-markets (model mean vs actual)

| Player | Team | Market | Actual | v1 | v1.5 | v1.6 | v1.7 | v1.7-pr43 | v2 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| Bam Knight | ARI | rush_yards | 19 | 48.96 | 45.79 | 59.02 | 41.75 | 44.69 | 20.33 |
| Bam Knight | ARI | targets | 2 | 2.84 | 2.28 | 2.45 | 2.56 | 2.52 | 1.04 |
| Carson Beck | ARI | interceptions | 2 | 0.60 | 0.58 | 0.43 | 0.44 | 0.54 | 0.47 |
| Carson Beck | ARI | pass_attempts | 18 | 37.61 | 36.50 | 35.38 | 34.96 | 35.82 | 34.06 |
| Carson Beck | ARI | pass_completions | 11 | 24.92 | 24.54 | 23.52 | 23.25 | 23.66 | 21.90 |
| Carson Beck | ARI | pass_yards | 108 | 263.50 | 251.52 | 257.35 | 243.65 | 244.73 | 220.89 |
| Carson Beck | ARI | rush_yards | 1 | 22.94 | 21.99 | 23.25 | 21.61 | 22.17 | 18.17 |
| Devin Duvernay | ARI | receiving_yards | 35 | 8.03 | 6.21 | 5.65 | 5.16 | 2.51 | 0.52 |
| Devin Duvernay | ARI | receptions | 2 | 0.74 | 0.59 | 0.45 | 0.47 | 0.24 | 0.08 |
| Devin Duvernay | ARI | targets | 3 | 1.04 | 0.98 | 0.67 | 0.64 | 0.54 | 0.11 |
| Elijah Wilkinson | ARI | receiving_yards | -1 | - | - | - | - | - | - |
| Elijah Wilkinson | ARI | receptions | 1 | - | - | - | - | - | - |
| Elijah Wilkinson | ARI | targets | 1 | - | - | - | - | - | - |
| Harrison Wallace III | ARI | receiving_yards | 9 | 5.02 | 4.14 | 6.39 | 3.14 | 5.50 | 0.33 |
| Harrison Wallace III | ARI | receptions | 1 | 0.50 | 0.42 | 0.47 | 0.34 | 0.51 | 0.05 |
| Harrison Wallace III | ARI | targets | 1 | 0.73 | 0.60 | 0.73 | 0.50 | 0.78 | 0.07 |
| Hunter Long | ARI | receiving_yards | 7 | 2.32 | 1.26 | 1.16 | 4.09 | 2.01 | 0.93 |
| Hunter Long | ARI | receptions | 1 | 0.21 | 0.14 | 0.14 | 0.29 | 0.24 | 0.12 |
| Hunter Long | ARI | targets | 2 | 0.31 | 0.21 | 0.25 | 0.34 | 0.30 | 0.18 |
| Simi Fehoko | ARI | receiving_yards | 21 | 6.84 | 6.05 | 5.87 | 5.16 | 6.69 | 2.81 |
| Simi Fehoko | ARI | receptions | 1 | 0.60 | 0.49 | 0.51 | 0.42 | 0.50 | 0.26 |
| Simi Fehoko | ARI | targets | 2 | 0.96 | 0.80 | 0.83 | 0.82 | 0.81 | 0.46 |
| Trey McBride | ARI | receiving_yards | 37 | 56.92 | 54.60 | 58.94 | 52.51 | 52.67 | 59.78 |
| Trey McBride | ARI | receptions | 5 | 5.32 | 5.51 | 5.23 | 5.24 | 5.22 | 6.03 |
| Trey McBride | ARI | targets | 5 | 7.75 | 7.95 | 7.45 | 7.62 | 7.53 | 8.75 |
| Tyler Allgeier | ARI | rush_yards | 14 | 2.38 | 1.42 | 1.26 | 3.86 | 1.72 | 12.90 |
| Tyler Allgeier | ARI | targets | 1 | 0.69 | 0.51 | 0.47 | 0.49 | 0.49 | 0.45 |
| Zay Jones | ARI | targets | 1 | - | - | - | - | - | - |
| Blake Corum | LA | receiving_yards | 19 | 8.89 | 8.50 | 10.01 | 9.24 | 9.82 | 7.01 |
| Blake Corum | LA | receptions | 3 | 1.01 | 1.09 | 1.10 | 1.19 | 1.03 | 0.98 |
| Blake Corum | LA | rush_tds | 1 | 0.30 | 0.26 | 0.16 | 0.19 | 0.19 | 0.40 |
| Blake Corum | LA | rush_yards | 100 | 31.63 | 24.42 | 25.28 | 29.91 | 24.82 | 32.63 |
| Blake Corum | LA | targets | 4 | 1.40 | 1.76 | 1.63 | 1.49 | 1.38 | 1.33 |
| CJ Daniels | LA | receiving_yards | 22 | 21.29 | 20.18 | 19.86 | 21.98 | 23.03 | 4.36 |
| CJ Daniels | LA | receptions | 1 | 1.62 | 1.76 | 1.73 | 1.86 | 1.81 | 0.40 |
| CJ Daniels | LA | targets | 2 | 2.40 | 2.73 | 2.59 | 2.83 | 2.78 | 0.64 |
| Colby Parkinson | LA | receiving_yards | 11 | 19.12 | 15.41 | 17.10 | 17.48 | 14.72 | 19.86 |
| Colby Parkinson | LA | receptions | 2 | 1.75 | 1.49 | 1.57 | 1.63 | 1.40 | 2.06 |
| Colby Parkinson | LA | targets | 2 | 2.39 | 2.16 | 2.24 | 2.05 | 2.03 | 2.85 |
| Davis Allen | LA | receiving_tds | 1 | 0.10 | 0.13 | 0.11 | 0.12 | 0.13 | 0.06 |
| Davis Allen | LA | receiving_yards | 19 | 14.32 | 15.93 | 14.01 | 13.34 | 13.44 | 9.65 |
| Davis Allen | LA | receptions | 1 | 1.35 | 1.40 | 1.21 | 1.32 | 1.31 | 1.13 |
| Davis Allen | LA | targets | 1 | 1.97 | 2.16 | 1.86 | 1.86 | 1.91 | 1.74 |
| Konata Mumpfield | LA | receiving_yards | 81 | 18.27 | 21.38 | 22.53 | 20.42 | 20.52 | 21.70 |
| Konata Mumpfield | LA | receptions | 3 | 1.62 | 1.64 | 1.79 | 1.82 | 1.74 | 2.17 |
| Konata Mumpfield | LA | targets | 4 | 2.33 | 2.60 | 2.85 | 3.04 | 2.68 | 3.39 |
| Kyren Williams | LA | receiving_yards | 9 | 11.80 | 11.24 | 10.99 | 9.91 | 11.09 | 30.37 |
| Kyren Williams | LA | receptions | 2 | 1.24 | 1.20 | 1.26 | 1.07 | 1.36 | 3.76 |
| Kyren Williams | LA | rush_yards | 23 | 31.64 | 26.37 | 32.23 | 30.59 | 34.79 | 81.78 |
| Kyren Williams | LA | targets | 5 | 1.63 | 1.69 | 1.72 | 1.46 | 1.69 | 5.03 |
| Matthew Stafford | LA | interceptions | 1 | 0.38 | 0.34 | 0.57 | 0.45 | 0.34 | 0.40 |
| Matthew Stafford | LA | pass_attempts | 26 | 35.30 | 36.58 | 36.90 | 35.71 | 34.92 | 37.48 |
| Matthew Stafford | LA | pass_completions | 18 | 24.51 | 25.01 | 24.91 | 24.79 | 24.30 | 25.53 |
| Matthew Stafford | LA | pass_tds | 3 | 1.61 | 1.60 | 1.73 | 1.82 | 1.85 | 1.23 |
| Matthew Stafford | LA | pass_yards | 249 | 277.41 | 279.38 | 284.95 | 266.98 | 267.05 | 251.06 |
| Matthew Stafford | LA | rush_yards | -2 | 15.72 | 15.97 | 15.99 | 17.51 | 16.46 | 21.14 |
| Ronnie Rivers | LA | rush_yards | 81 | 27.63 | 31.78 | 34.33 | 27.79 | 27.65 | 5.49 |
| Tutu Atwell | LA | receiving_yards | 31 | 21.05 | 17.38 | 26.49 | 16.72 | 17.48 | 15.18 |
| Tutu Atwell | LA | receptions | 1 | 1.79 | 1.48 | 2.11 | 1.57 | 1.56 | 1.45 |
| Tutu Atwell | LA | targets | 2 | 2.78 | 2.25 | 3.16 | 2.38 | 2.36 | 2.25 |
| Tyler Higbee | LA | receiving_tds | 1 | 0.13 | 0.06 | 0.13 | 0.15 | 0.16 | 0.08 |
| Tyler Higbee | LA | receiving_yards | 17 | 14.95 | 17.43 | 12.63 | 13.26 | 14.42 | 23.35 |
| Tyler Higbee | LA | receptions | 3 | 1.23 | 1.53 | 1.13 | 1.29 | 1.34 | 2.27 |
| Tyler Higbee | LA | targets | 4 | 1.85 | 2.21 | 1.71 | 1.95 | 1.92 | 3.23 |
| Xavier Smith | LA | receiving_tds | 1 | 0.14 | 0.19 | 0.18 | 0.08 | 0.16 | 0.07 |
| Xavier Smith | LA | receiving_yards | 40 | 20.63 | 28.33 | 28.52 | 16.65 | 26.06 | 15.88 |
| Xavier Smith | LA | receptions | 2 | 1.86 | 2.29 | 2.12 | 1.40 | 2.25 | 1.36 |
| Xavier Smith | LA | targets | 2 | 2.50 | 3.12 | 3.05 | 2.15 | 3.15 | 2.12 |
