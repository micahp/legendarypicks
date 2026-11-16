# Week 10: JAX at TEN, SLC model family

**Final:** TEN 23, JAX 40 (home win = 0).

Inputs: the prospective snapshots built 2026-11-14 18:54:46Z, week-10 kicker table
(LA = McManus), week-9 streaks and snap counts. Each arm is its own git ref.

## Game level

| Arm | Valid seeds | P(TEN) | P(JAX) | P(tie) | Home Brier | TEN mean (P10-P90) | JAX mean (P10-P90) | Total | Combined score error |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|
| v1 | 1000 | 25.8% | 74.2% | 0.0% | 0.067 | 17.83 (7-29) | 25.31 (14-37) | 43.14 | 19.86 |
| v1.5 | 1000 | 26.8% | 73.1% | 0.1% | 0.072 | 18.07 (8-28) | 25.37 (14-37) | 43.44 | 19.56 |
| v1.6 | 1000 | 24.3% | 75.5% | 0.2% | 0.059 | 19.57 (9-31) | 27.12 (17-38) | 46.70 | 16.30 |
| v1.7 | 100 | 20.0% | 80.0% | 0.0% | 0.040 | 16.70 (6-29) | 25.96 (16-36) | 42.66 | 20.34 |
| v1.7-pr43 | 99 | 20.2% | 79.8% | 0.0% | 0.041 | 17.23 (7-26) | 26.78 (16-38) | 44.01 | 18.99 |
| v2 | 1000 | 29.9% | 69.2% | 0.9% | 0.089 | 17.19 (7-27) | 23.50 (13-34) | 40.69 | 22.31 |

## Player stat accuracy (MAE over graded player-markets)

| Arm | Graded player-markets | MAE |
|---|---:|---:|
| v1 | 71 | 9.536 |
| v1.5 | 71 | 9.489 |
| v1.6 | 71 | 9.336 |
| v1.7 | 71 | 9.688 |
| v1.7-pr43 | 71 | 9.945 |
| v2 | 71 | 9.608 |

## Market grading

Not possible yet: `picks.dev.db` has no `prop_games` row for 2026-11-15
(newest NFL prop game is 2026-11-08), so there are no pre-kickoff lines for
this game. Prop Brier versus the de-vigged market runs once those lines land.

## Graded player-markets (model mean vs actual)

| Player | Team | Market | Actual | v1 | v1.5 | v1.6 | v1.7 | v1.7-pr43 | v2 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| Bhayshul Tuten | JAX | receiving_yards | 25 | 10.63 | 10.38 | 9.57 | 12.72 | 9.28 | 18.45 |
| Bhayshul Tuten | JAX | receptions | 3 | 1.34 | 1.31 | 1.28 | 1.52 | 1.28 | 2.53 |
| Bhayshul Tuten | JAX | rush_tds | 1 | 0.81 | 0.80 | 0.80 | 0.82 | 0.71 | 0.58 |
| Bhayshul Tuten | JAX | rush_yards | 88 | 85.51 | 83.53 | 86.04 | 98.10 | 88.11 | 63.24 |
| Bhayshul Tuten | JAX | targets | 4 | 1.93 | 1.90 | 1.90 | 2.01 | 1.80 | 3.38 |
| Brenton Strange | JAX | receiving_tds | 1 | 0.23 | 0.21 | 0.28 | 0.19 | 0.24 | 0.26 |
| Brenton Strange | JAX | receiving_yards | 9 | 47.45 | 45.64 | 46.65 | 42.66 | 49.14 | 53.47 |
| Brenton Strange | JAX | receptions | 2 | 4.26 | 4.26 | 4.22 | 3.98 | 4.23 | 5.23 |
| Brenton Strange | JAX | targets | 3 | 6.15 | 6.11 | 5.96 | 5.64 | 5.80 | 7.16 |
| Brian Thomas Jr. | JAX | receiving_yards | 29 | 49.40 | 48.65 | 50.13 | 48.37 | 43.83 | 29.95 |
| Brian Thomas Jr. | JAX | receptions | 3 | 3.98 | 4.01 | 4.11 | 3.98 | 3.75 | 2.75 |
| Brian Thomas Jr. | JAX | targets | 4 | 6.35 | 6.43 | 6.39 | 6.51 | 6.31 | 4.70 |
| Chris Rodriguez Jr. | JAX | rush_yards | 5 | 5.50 | 5.00 | 5.29 | 5.68 | 6.56 | 16.95 |
| Jakobi Meyers | JAX | receiving_yards | 34 | 33.94 | 34.51 | 35.91 | 32.62 | 29.76 | 57.22 |
| Jakobi Meyers | JAX | receptions | 3 | 2.75 | 2.83 | 2.87 | 2.69 | 2.35 | 5.17 |
| Jakobi Meyers | JAX | targets | 6 | 4.19 | 4.27 | 4.28 | 4.02 | 3.98 | 7.85 |
| Josh Cameron | JAX | receiving_tds | 1 | 0.02 | 0.02 | 0.02 | 0.04 | 0.02 | 0.03 |
| Josh Cameron | JAX | receiving_yards | 67 | 2.75 | 2.98 | 2.34 | 3.23 | 2.00 | 6.08 |
| Josh Cameron | JAX | receptions | 3 | 0.23 | 0.25 | 0.19 | 0.30 | 0.16 | 0.56 |
| Josh Cameron | JAX | targets | 3 | 0.37 | 0.37 | 0.29 | 0.46 | 0.21 | 0.88 |
| Nate Boerkircher | JAX | receiving_yards | 12 | 4.49 | 4.05 | 3.91 | 6.81 | 3.29 | 7.00 |
| Nate Boerkircher | JAX | receptions | 1 | 0.38 | 0.34 | 0.38 | 0.49 | 0.35 | 0.68 |
| Nate Boerkircher | JAX | targets | 2 | 0.54 | 0.53 | 0.56 | 0.71 | 0.55 | 0.98 |
| Parker Washington | JAX | receiving_tds | 1 | 0.30 | 0.29 | 0.36 | 0.30 | 0.33 | 0.35 |
| Parker Washington | JAX | receiving_yards | 152 | 54.29 | 53.40 | 54.96 | 43.55 | 47.08 | 71.25 |
| Parker Washington | JAX | receptions | 7 | 4.39 | 4.33 | 4.52 | 3.77 | 3.84 | 6.48 |
| Parker Washington | JAX | targets | 9 | 6.90 | 6.83 | 7.12 | 6.10 | 6.14 | 10.78 |
| Tanner Koziol | JAX | receiving_yards | 8 | 4.66 | 4.30 | 5.06 | 3.26 | 4.80 | 1.71 |
| Tanner Koziol | JAX | receptions | 1 | 0.40 | 0.38 | 0.43 | 0.32 | 0.43 | 0.17 |
| Tanner Koziol | JAX | targets | 1 | 0.59 | 0.54 | 0.61 | 0.43 | 0.63 | 0.24 |
| Travis Hunter | JAX | receiving_yards | 16 | 24.42 | 26.74 | 25.32 | 20.00 | 28.44 | 5.00 |
| Travis Hunter | JAX | receptions | 2 | 2.01 | 2.21 | 2.02 | 1.70 | 2.37 | 0.47 |
| Travis Hunter | JAX | rush_yards | 3 | 0.42 | 0.43 | 0.46 | 0.40 | 0.27 | 0.07 |
| Travis Hunter | JAX | targets | 2 | 3.13 | 3.38 | 3.12 | 2.82 | 3.68 | 0.70 |
| Trevor Lawrence | JAX | interceptions | 1 | 0.37 | 0.40 | 0.39 | 0.42 | 0.40 | 0.50 |
| Trevor Lawrence | JAX | pass_attempts | 35 | 34.49 | 34.69 | 34.67 | 32.51 | 32.69 | 39.51 |
| Trevor Lawrence | JAX | pass_completions | 25 | 22.81 | 22.94 | 23.17 | 21.63 | 21.52 | 26.01 |
| Trevor Lawrence | JAX | pass_tds | 3 | 1.38 | 1.40 | 1.73 | 1.54 | 1.59 | 1.35 |
| Trevor Lawrence | JAX | pass_yards | 352 | 257.81 | 258.05 | 261.93 | 238.11 | 241.20 | 265.88 |
| Trevor Lawrence | JAX | rush_yards | 27 | 22.79 | 23.88 | 23.90 | 24.72 | 23.96 | 20.05 |
| Cam Ward | TEN | interceptions | 1 | 0.66 | 0.62 | 0.66 | 0.74 | 0.57 | 0.65 |
| Cam Ward | TEN | pass_attempts | 39 | 36.41 | 36.64 | 36.75 | 34.29 | 35.31 | 32.84 |
| Cam Ward | TEN | pass_completions | 28 | 21.89 | 21.91 | 22.12 | 20.76 | 21.42 | 20.05 |
| Cam Ward | TEN | pass_tds | 2 | 0.95 | 1.00 | 1.28 | 0.97 | 1.00 | 0.70 |
| Cam Ward | TEN | pass_yards | 231 | 217.77 | 217.49 | 222.95 | 204.83 | 209.71 | 188.65 |
| Cam Ward | TEN | rush_yards | 39 | 16.26 | 15.90 | 16.66 | 16.95 | 16.34 | 18.16 |
| Chimere Dike | TEN | receiving_yards | 16 | 49.26 | 47.60 | 49.37 | 36.94 | 43.24 | 26.66 |
| Chimere Dike | TEN | receptions | 2 | 4.42 | 4.40 | 4.47 | 3.63 | 3.95 | 2.60 |
| Chimere Dike | TEN | rush_yards | 5 | 1.11 | 1.16 | 1.54 | 0.85 | 1.65 | 0.46 |
| Chimere Dike | TEN | targets | 3 | 7.44 | 7.35 | 7.53 | 6.39 | 6.91 | 4.13 |
| Daniel Bellinger | TEN | receiving_tds | 1 | 0.02 | 0.02 | 0.02 | 0.03 | 0.01 | 0.03 |
| Daniel Bellinger | TEN | receiving_yards | 6 | 3.64 | 4.33 | 4.67 | 4.91 | 2.83 | 6.43 |
| Daniel Bellinger | TEN | receptions | 2 | 0.42 | 0.46 | 0.47 | 0.57 | 0.28 | 0.73 |
| Daniel Bellinger | TEN | targets | 3 | 0.66 | 0.70 | 0.70 | 0.82 | 0.45 | 1.12 |
| Elic Ayomanor | TEN | receiving_yards | 79 | 53.72 | 53.27 | 55.06 | 51.47 | 47.39 | 46.22 |
| Elic Ayomanor | TEN | receptions | 5 | 4.80 | 4.72 | 4.89 | 4.46 | 4.61 | 4.57 |
| Elic Ayomanor | TEN | targets | 10 | 9.01 | 9.05 | 9.15 | 8.44 | 8.84 | 8.44 |
| Gunnar Helm | TEN | receiving_yards | 23 | 42.94 | 43.34 | 43.79 | 35.49 | 42.96 | 31.38 |
| Gunnar Helm | TEN | receptions | 4 | 4.51 | 4.56 | 4.58 | 3.91 | 4.47 | 3.58 |
| Gunnar Helm | TEN | targets | 4 | 6.90 | 6.98 | 6.98 | 6.04 | 6.59 | 5.58 |
| Tony Pollard | TEN | receiving_tds | 1 | 0.04 | 0.04 | 0.06 | 0.09 | 0.08 | 0.05 |
| Tony Pollard | TEN | receiving_yards | 66 | 11.40 | 12.84 | 12.12 | 13.29 | 13.05 | 19.16 |
| Tony Pollard | TEN | receptions | 8 | 1.61 | 1.67 | 1.54 | 1.84 | 1.63 | 2.40 |
| Tony Pollard | TEN | rush_yards | 33 | 78.04 | 76.63 | 76.61 | 70.67 | 68.59 | 76.58 |
| Tony Pollard | TEN | targets | 9 | 2.41 | 2.47 | 2.37 | 2.44 | 2.48 | 3.42 |
| Tyjae Spears | TEN | receptions | 1 | 2.03 | 1.98 | 2.08 | 2.02 | 2.07 | 1.48 |
| Tyjae Spears | TEN | rush_yards | 28 | 22.36 | 24.50 | 21.54 | 23.38 | 24.70 | 37.32 |
| Tyjae Spears | TEN | targets | 1 | 2.94 | 2.88 | 2.98 | 2.94 | 2.85 | 1.93 |
| Wan'Dale Robinson | TEN | receiving_yards | 10 | 3.43 | 2.81 | 4.15 | 3.73 | 4.60 | 24.11 |
| Wan'Dale Robinson | TEN | receptions | 3 | 0.31 | 0.26 | 0.35 | 0.33 | 0.37 | 2.34 |
| Wan'Dale Robinson | TEN | targets | 4 | 0.52 | 0.44 | 0.58 | 0.53 | 0.56 | 3.90 |
| Xavier Restrepo | TEN | receiving_yards | 31 | - | - | - | - | - | - |
| Xavier Restrepo | TEN | receptions | 3 | - | - | - | - | - | - |
| Xavier Restrepo | TEN | targets | 3 | - | - | - | - | - | - |
