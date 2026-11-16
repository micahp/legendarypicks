# Week 10: PIT at CIN, SLC model family

**Final:** CIN 38, PIT 18 (home win = 1).

Inputs: the prospective snapshots built 2026-11-14 18:54:46Z, week-10 kicker table
(LA = McManus), week-9 streaks and snap counts. Each arm is its own git ref.

## Game level

| Arm | Valid seeds | P(CIN) | P(PIT) | P(tie) | Home Brier | CIN mean (P10-P90) | PIT mean (P10-P90) | Total | Combined score error |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|
| v1 | 100 | 68.0% | 32.0% | 0.0% | 0.102 | 25.00 (13-38) | 19.73 (9-32) | 44.73 | 14.73 |
| v1.5 | 100 | 64.0% | 35.0% | 1.0% | 0.130 | 24.73 (13-38) | 20.53 (7-31) | 45.26 | 15.80 |
| v1.6 | 100 | 68.0% | 32.0% | 0.0% | 0.102 | 28.33 (18-38) | 22.18 (10-34) | 50.51 | 13.85 |
| v1.7 | 100 | 65.0% | 35.0% | 0.0% | 0.122 | 24.05 (13-35) | 19.21 (9-31) | 43.26 | 15.16 |
| v1.7-pr43 | 100 | 58.0% | 42.0% | 0.0% | 0.176 | 23.14 (10-34) | 20.18 (10-31) | 43.32 | 17.04 |
| v2 | 100 | 65.0% | 33.0% | 2.0% | 0.122 | 21.59 (10-34) | 17.05 (9-26) | 38.64 | 17.36 |

## Player stat accuracy (MAE over graded player-markets)

| Arm | Graded player-markets | MAE |
|---|---:|---:|
| v1 | 76 | 10.571 |
| v1.5 | 76 | 10.557 |
| v1.6 | 76 | 10.333 |
| v1.7 | 76 | 10.462 |
| v1.7-pr43 | 76 | 10.856 |
| v2 | 76 | 11.240 |

## Market grading

Not possible yet: `picks.dev.db` has no `prop_games` row for 2026-11-15
(newest NFL prop game is 2026-11-08), so there are no pre-kickoff lines for
this game. Prop Brier versus the de-vigged market runs once those lines land.

## Graded player-markets (model mean vs actual)

| Player | Team | Market | Actual | v1 | v1.5 | v1.6 | v1.7 | v1.7-pr43 | v2 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| Chase Brown | CIN | receiving_tds | 2 | 0.18 | 0.20 | 0.33 | 0.21 | 0.27 | 0.13 |
| Chase Brown | CIN | receiving_yards | 39 | 35.71 | 31.56 | 36.61 | 36.65 | 35.52 | 26.36 |
| Chase Brown | CIN | receptions | 8 | 4.45 | 4.33 | 4.50 | 4.53 | 4.25 | 3.08 |
| Chase Brown | CIN | rush_yards | 44 | 68.13 | 71.72 | 70.82 | 66.34 | 52.50 | 61.32 |
| Chase Brown | CIN | targets | 9 | 5.86 | 6.06 | 5.90 | 5.65 | 5.83 | 3.83 |
| Dohnte Meyers | CIN | receiving_tds | 1 | 0.06 | 0.00 | 0.04 | 0.02 | 0.01 | 0.21 |
| Dohnte Meyers | CIN | receiving_yards | 20 | 2.72 | 5.23 | 6.01 | 3.10 | 2.61 | 51.54 |
| Dohnte Meyers | CIN | receptions | 2 | 0.25 | 0.45 | 0.53 | 0.22 | 0.22 | 4.71 |
| Dohnte Meyers | CIN | targets | 2 | 0.37 | 0.60 | 0.62 | 0.36 | 0.32 | 6.72 |
| Drew Sample | CIN | receiving_tds | 1 | 0.03 | 0.06 | 0.02 | 0.06 | 0.06 | 0.10 |
| Drew Sample | CIN | receiving_yards | 15 | 11.54 | 10.07 | 12.67 | 12.01 | 12.63 | 10.38 |
| Drew Sample | CIN | receptions | 3 | 1.18 | 1.04 | 1.27 | 1.38 | 1.20 | 1.17 |
| Drew Sample | CIN | targets | 3 | 1.45 | 1.58 | 1.73 | 1.85 | 1.69 | 1.47 |
| Ja'Marr Chase | CIN | receiving_yards | 231 | 117.89 | 114.26 | 126.30 | 108.11 | 110.71 | 55.48 |
| Ja'Marr Chase | CIN | receptions | 11 | 10.41 | 10.18 | 10.51 | 9.87 | 9.73 | 5.21 |
| Ja'Marr Chase | CIN | targets | 14 | 15.09 | 15.38 | 15.46 | 14.30 | 14.65 | 7.10 |
| Jack Endries | CIN | receiving_yards | 4 | 3.09 | 2.73 | 4.54 | 2.66 | 3.19 | 4.43 |
| Jack Endries | CIN | receptions | 1 | 0.32 | 0.30 | 0.43 | 0.27 | 0.27 | 0.53 |
| Jack Endries | CIN | targets | 2 | 0.45 | 0.44 | 0.60 | 0.38 | 0.40 | 0.85 |
| Joe Burrow | CIN | pass_attempts | 44 | 42.10 | 41.85 | 42.31 | 40.70 | 41.05 | 36.82 |
| Joe Burrow | CIN | pass_completions | 35 | 29.26 | 28.43 | 29.45 | 28.44 | 27.97 | 26.76 |
| Joe Burrow | CIN | pass_tds | 4 | 1.59 | 1.47 | 2.32 | 1.72 | 1.68 | 1.30 |
| Joe Burrow | CIN | pass_yards | 409 | 297.99 | 294.76 | 318.17 | 288.72 | 290.69 | 263.40 |
| Joe Burrow | CIN | rush_yards | 8 | 19.87 | 16.57 | 17.97 | 18.69 | 15.71 | 17.07 |
| Mike Gesicki | CIN | receiving_yards | 9 | 22.04 | 22.14 | 20.97 | 22.47 | 21.63 | 8.83 |
| Mike Gesicki | CIN | receptions | 1 | 2.41 | 2.31 | 2.09 | 2.41 | 2.27 | 0.99 |
| Mike Gesicki | CIN | targets | 2 | 3.67 | 3.48 | 3.12 | 3.34 | 3.28 | 1.38 |
| Samaje Perine | CIN | receiving_yards | 25 | 8.27 | 10.69 | 7.72 | 8.80 | 8.99 | 20.41 |
| Samaje Perine | CIN | receptions | 4 | 1.12 | 1.12 | 0.92 | 1.07 | 0.98 | 2.29 |
| Samaje Perine | CIN | rush_tds | 1 | 0.30 | 0.28 | 0.17 | 0.26 | 0.23 | 0.21 |
| Samaje Perine | CIN | rush_yards | 14 | 25.01 | 23.90 | 21.68 | 27.24 | 28.40 | 37.36 |
| Samaje Perine | CIN | targets | 4 | 1.34 | 1.50 | 1.26 | 1.47 | 1.30 | 2.84 |
| Tahj Brooks | CIN | rush_yards | 12 | 6.43 | 5.83 | 5.52 | 4.89 | 4.49 | 8.33 |
| Tee Higgins | CIN | receiving_yards | 66 | 61.30 | 55.07 | 61.56 | 58.34 | 56.41 | 44.13 |
| Tee Higgins | CIN | receptions | 5 | 5.76 | 4.70 | 5.23 | 5.08 | 5.22 | 4.25 |
| Tee Higgins | CIN | targets | 6 | 8.88 | 6.89 | 7.66 | 7.94 | 7.90 | 6.23 |
| Aaron Rodgers | PIT | pass_attempts | 29 | 39.39 | 39.63 | 40.76 | 36.46 | 38.79 | 35.12 |
| Aaron Rodgers | PIT | pass_completions | 15 | 25.13 | 25.31 | 26.02 | 23.11 | 24.95 | 22.00 |
| Aaron Rodgers | PIT | pass_tds | 2 | 1.07 | 1.15 | 1.57 | 1.27 | 1.18 | 0.81 |
| Aaron Rodgers | PIT | pass_yards | 143 | 251.83 | 248.56 | 266.97 | 228.44 | 249.05 | 219.91 |
| Aaron Rodgers | PIT | rush_yards | -1 | 13.25 | 12.11 | 13.43 | 12.31 | 17.38 | 9.48 |
| Ben Skowronek | PIT | receptions | 1 | 0.54 | 0.70 | 0.92 | 0.36 | 0.29 | 0.22 |
| Ben Skowronek | PIT | targets | 1 | 0.80 | 1.10 | 1.27 | 0.66 | 0.40 | 0.39 |
| Brandon Smith | PIT | receiving_yards | 15 | 5.50 | 6.02 | 3.32 | 2.35 | 4.11 | 1.65 |
| Brandon Smith | PIT | receptions | 2 | 0.49 | 0.49 | 0.35 | 0.22 | 0.34 | 0.15 |
| Brandon Smith | PIT | targets | 3 | 0.84 | 0.74 | 0.55 | 0.48 | 0.60 | 0.32 |
| DK Metcalf | PIT | receiving_tds | 1 | 0.44 | 0.45 | 0.36 | 0.37 | 0.35 | 0.25 |
| DK Metcalf | PIT | receiving_yards | 54 | 88.21 | 77.89 | 83.75 | 79.22 | 91.17 | 75.50 |
| DK Metcalf | PIT | receptions | 2 | 7.92 | 7.36 | 7.48 | 7.21 | 8.22 | 6.80 |
| DK Metcalf | PIT | targets | 6 | 13.36 | 12.95 | 12.95 | 12.64 | 13.91 | 12.08 |
| Darnell Washington | PIT | receiving_yards | 5 | 26.68 | 27.82 | 32.34 | 28.46 | 27.00 | 16.54 |
| Darnell Washington | PIT | receptions | 1 | 2.67 | 2.80 | 3.29 | 2.98 | 2.63 | 1.69 |
| Darnell Washington | PIT | targets | 3 | 4.32 | 4.21 | 5.03 | 4.43 | 4.03 | 2.49 |
| Germie Bernard | PIT | rush_yards | 10 | 0.11 | 0.35 | 0.11 | 0.00 | 0.41 | 0.38 |
| Germie Bernard | PIT | targets | 3 | 0.74 | 0.61 | 0.99 | 0.68 | 1.04 | 2.00 |
| Jaylen Warren | PIT | receiving_yards | 26 | 33.95 | 35.84 | 36.38 | 32.21 | 37.03 | 36.33 |
| Jaylen Warren | PIT | receptions | 5 | 4.37 | 4.56 | 4.28 | 3.98 | 4.36 | 4.43 |
| Jaylen Warren | PIT | rush_yards | 15 | 90.01 | 91.44 | 84.33 | 87.84 | 98.74 | 84.64 |
| Jaylen Warren | PIT | targets | 6 | 5.96 | 6.27 | 5.97 | 5.22 | 5.85 | 6.31 |
| Lew Nichols | PIT | receiving_yards | 1 | 3.60 | 4.20 | 5.41 | 5.23 | 2.63 | 1.12 |
| Lew Nichols | PIT | receptions | 1 | 0.54 | 0.44 | 0.54 | 0.57 | 0.36 | 0.08 |
| Lew Nichols | PIT | rush_yards | 43 | 2.31 | 1.74 | 0.39 | 0.99 | 2.15 | 1.22 |
| Lew Nichols | PIT | targets | 1 | 0.88 | 0.63 | 0.81 | 0.79 | 0.57 | 0.11 |
| Mason Rudolph | PIT | pass_attempts | 3 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Mason Rudolph | PIT | pass_completions | 1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Mason Rudolph | PIT | pass_yards | 1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Mason Rudolph | PIT | rush_yards | 9 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Pat Freiermuth | PIT | receiving_tds | 1 | 0.17 | 0.12 | 0.25 | 0.23 | 0.22 | 0.19 |
| Pat Freiermuth | PIT | receiving_yards | 35 | 35.22 | 36.51 | 34.26 | 31.30 | 37.29 | 38.08 |
| Pat Freiermuth | PIT | receptions | 2 | 3.71 | 3.82 | 3.48 | 3.29 | 3.92 | 3.88 |
| Pat Freiermuth | PIT | targets | 3 | 5.48 | 5.56 | 5.33 | 4.91 | 5.67 | 5.79 |
| Rico Dowdle | PIT | receiving_yards | 8 | 2.39 | 7.07 | 2.00 | 2.21 | 4.40 | 6.01 |
| Rico Dowdle | PIT | receptions | 2 | 0.30 | 0.72 | 0.26 | 0.38 | 0.57 | 0.76 |
| Rico Dowdle | PIT | rush_yards | 26 | 2.03 | 1.25 | 1.04 | 0.79 | 1.86 | 13.79 |
| Rico Dowdle | PIT | targets | 2 | 0.49 | 1.02 | 0.44 | 0.52 | 0.78 | 1.08 |
| Robert Tonyan | PIT | targets | 1 | 0.57 | 0.61 | 0.59 | 0.35 | 0.40 | 0.21 |
