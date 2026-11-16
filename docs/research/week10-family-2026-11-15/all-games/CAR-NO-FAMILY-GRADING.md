# Week 10: CAR at NO, SLC model family

**Final:** NO 17, CAR 20 (home win = 0).

Inputs: the prospective snapshots built 2026-11-14 18:54:46Z, week-10 kicker table
(LA = McManus), week-9 streaks and snap counts. Each arm is its own git ref.

## Game level

| Arm | Valid seeds | P(NO) | P(CAR) | P(tie) | Home Brier | NO mean (P10-P90) | CAR mean (P10-P90) | Total | Combined score error |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|
| v1 | 1000 | 74.2% | 25.8% | 0.0% | 0.551 | 24.99 (14-36) | 17.49 (7-28) | 42.48 | 10.50 |
| v1.5 | 1000 | 76.2% | 23.7% | 0.1% | 0.581 | 25.61 (16-37) | 17.31 (7-28) | 42.92 | 11.30 |
| v1.6 | 1000 | 75.3% | 24.6% | 0.1% | 0.567 | 26.45 (16-38) | 18.59 (7-30) | 45.04 | 10.86 |
| v1.7 | 1000 | 73.9% | 26.0% | 0.1% | 0.546 | 23.94 (13-35) | 16.71 (6-27) | 40.65 | 10.23 |
| v1.7-pr43 | 100 | 69.0% | 31.0% | 0.0% | 0.476 | 23.39 (13-35) | 16.80 (6-27) | 40.19 | 9.59 |
| v2 | 1000 | 67.6% | 32.0% | 0.4% | 0.457 | 21.10 (10-31) | 15.80 (6-27) | 36.90 | 8.29 |

## Player stat accuracy (MAE over graded player-markets)

| Arm | Graded player-markets | MAE |
|---|---:|---:|
| v1 | 61 | 11.844 |
| v1.5 | 61 | 11.984 |
| v1.6 | 61 | 11.999 |
| v1.7 | 61 | 10.863 |
| v1.7-pr43 | 61 | 10.888 |
| v2 | 61 | 9.743 |

## Market grading

Not possible yet: `picks.dev.db` has no `prop_games` row for 2026-11-15
(newest NFL prop game is 2026-11-08), so there are no pre-kickoff lines for
this game. Prop Brier versus the de-vigged market runs once those lines land.

## Graded player-markets (model mean vs actual)

| Player | Team | Market | Actual | v1 | v1.5 | v1.6 | v1.7 | v1.7-pr43 | v2 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| Bryce Young | CAR | pass_attempts | 30 | 36.77 | 37.16 | 36.80 | 34.70 | 34.56 | 34.33 |
| Bryce Young | CAR | pass_completions | 17 | 21.51 | 21.60 | 21.52 | 20.10 | 19.75 | 21.37 |
| Bryce Young | CAR | pass_yards | 200 | 216.29 | 218.49 | 219.07 | 196.34 | 193.80 | 208.49 |
| Bryce Young | CAR | rush_yards | 1 | 22.47 | 22.66 | 23.16 | 21.85 | 23.21 | 11.90 |
| Chuba Hubbard | CAR | receiving_yards | 80 | 27.76 | 28.40 | 27.75 | 26.27 | 30.03 | 28.73 |
| Chuba Hubbard | CAR | receptions | 5 | 3.25 | 3.33 | 3.21 | 3.21 | 3.18 | 3.46 |
| Chuba Hubbard | CAR | rush_tds | 2 | 0.49 | 0.49 | 0.49 | 0.45 | 0.42 | 0.48 |
| Chuba Hubbard | CAR | rush_yards | 92 | 77.48 | 77.25 | 79.40 | 81.75 | 82.14 | 91.88 |
| Chuba Hubbard | CAR | targets | 5 | 4.93 | 5.04 | 4.89 | 4.69 | 4.55 | 4.78 |
| Darren Waller | CAR | receiving_yards | 24 | 1.75 | 1.78 | 1.74 | 1.84 | 1.89 | 5.21 |
| Darren Waller | CAR | receptions | 2 | 0.18 | 0.17 | 0.18 | 0.20 | 0.18 | 0.58 |
| Darren Waller | CAR | targets | 4 | 0.31 | 0.29 | 0.31 | 0.34 | 0.31 | 0.91 |
| Jalen Coker | CAR | rush_yards | 3 | 0.27 | 0.30 | 0.27 | 0.27 | 0.42 | 0.17 |
| Jalen Coker | CAR | targets | 4 | 4.00 | 3.90 | 4.08 | 3.83 | 3.42 | 5.18 |
| John Metchie III | CAR | receiving_yards | 4 | 2.40 | 2.74 | 2.42 | 2.20 | 2.26 | 3.72 |
| John Metchie III | CAR | receptions | 1 | 0.23 | 0.25 | 0.22 | 0.22 | 0.26 | 0.36 |
| John Metchie III | CAR | targets | 1 | 0.40 | 0.44 | 0.38 | 0.38 | 0.43 | 0.67 |
| Mitchell Evans | CAR | targets | 1 | 1.72 | 1.71 | 1.71 | 1.54 | 1.58 | 1.92 |
| Tetairoa McMillan | CAR | receiving_yards | 35 | 63.79 | 66.09 | 65.37 | 56.61 | 54.92 | 71.00 |
| Tetairoa McMillan | CAR | receptions | 3 | 5.88 | 6.04 | 5.94 | 5.40 | 5.39 | 6.68 |
| Tetairoa McMillan | CAR | targets | 7 | 10.87 | 11.19 | 10.84 | 10.16 | 10.53 | 11.40 |
| Tommy Tremble | CAR | receiving_yards | 48 | 13.88 | 13.72 | 14.00 | 12.73 | 12.66 | 26.81 |
| Tommy Tremble | CAR | receptions | 4 | 1.48 | 1.50 | 1.47 | 1.42 | 1.34 | 2.96 |
| Tommy Tremble | CAR | targets | 5 | 2.45 | 2.56 | 2.47 | 2.32 | 2.35 | 4.56 |
| Trevor Etienne | CAR | receiving_yards | 9 | 2.91 | 2.80 | 2.95 | 3.14 | 3.51 | 2.26 |
| Trevor Etienne | CAR | receptions | 2 | 0.36 | 0.33 | 0.35 | 0.35 | 0.45 | 0.28 |
| Trevor Etienne | CAR | rush_yards | 1 | 12.12 | 11.95 | 12.41 | 11.38 | 9.24 | 8.31 |
| Trevor Etienne | CAR | targets | 2 | 0.56 | 0.54 | 0.56 | 0.55 | 0.62 | 0.40 |
| Alvin Kamara | NO | receiving_tds | 1 | 0.09 | 0.10 | 0.15 | 0.16 | 0.14 | 0.07 |
| Alvin Kamara | NO | receiving_yards | 10 | 19.52 | 20.45 | 21.02 | 20.63 | 19.65 | 19.20 |
| Alvin Kamara | NO | receptions | 3 | 2.73 | 2.76 | 2.79 | 2.65 | 2.56 | 2.71 |
| Alvin Kamara | NO | rush_tds | 1 | 0.66 | 0.65 | 0.66 | 0.60 | 0.59 | 0.50 |
| Alvin Kamara | NO | rush_yards | 4 | 78.59 | 80.56 | 80.16 | 79.27 | 80.79 | 69.92 |
| Alvin Kamara | NO | targets | 4 | 3.63 | 3.69 | 3.67 | 3.43 | 3.18 | 3.54 |
| Audric Estime | NO | receiving_yards | 5 | 6.06 | 6.45 | 6.77 | 6.44 | 7.76 | 9.16 |
| Audric Estime | NO | receptions | 1 | 0.87 | 0.89 | 0.91 | 0.86 | 0.97 | 1.27 |
| Audric Estime | NO | rush_yards | 6 | 28.88 | 29.23 | 27.79 | 29.40 | 25.19 | 33.96 |
| Audric Estime | NO | targets | 1 | 1.16 | 1.21 | 1.18 | 1.15 | 1.27 | 1.69 |
| Chris Olave | NO | receiving_yards | 30 | 109.76 | 111.25 | 108.18 | 99.31 | 98.13 | 83.70 |
| Chris Olave | NO | receptions | 3 | 9.16 | 9.24 | 9.05 | 8.72 | 8.64 | 7.58 |
| Chris Olave | NO | targets | 4 | 13.90 | 13.97 | 13.68 | 13.50 | 13.57 | 11.98 |
| Devaughn Vele | NO | receiving_yards | 14 | 29.31 | 28.13 | 30.96 | 25.10 | 33.43 | 43.30 |
| Devaughn Vele | NO | receptions | 2 | 2.40 | 2.38 | 2.55 | 2.18 | 2.84 | 3.87 |
| Devaughn Vele | NO | targets | 2 | 3.52 | 3.48 | 3.73 | 3.34 | 4.11 | 6.17 |
| Jordyn Tyson | NO | receiving_yards | 80 | 4.63 | 3.88 | 3.96 | 3.32 | 4.77 | 0.34 |
| Jordyn Tyson | NO | receptions | 11 | 0.39 | 0.32 | 0.31 | 0.30 | 0.44 | 0.04 |
| Jordyn Tyson | NO | targets | 13 | 0.58 | 0.49 | 0.46 | 0.44 | 0.72 | 0.06 |
| Juwan Johnson | NO | receiving_yards | 28 | 55.81 | 55.76 | 57.23 | 52.86 | 52.26 | 39.32 |
| Juwan Johnson | NO | receptions | 2 | 5.23 | 5.30 | 5.30 | 5.01 | 4.98 | 4.28 |
| Juwan Johnson | NO | targets | 3 | 7.44 | 7.61 | 7.48 | 7.09 | 7.07 | 6.35 |
| Noah Fant | NO | targets | 1 | 0.43 | 0.44 | 0.40 | 0.38 | 0.46 | 0.67 |
| Travis Etienne Jr. | NO | receiving_yards | 20 | 2.84 | 3.10 | 3.08 | 2.85 | 2.51 | 4.05 |
| Travis Etienne Jr. | NO | receptions | 3 | 0.38 | 0.39 | 0.41 | 0.39 | 0.46 | 0.56 |
| Travis Etienne Jr. | NO | rush_yards | 14 | 2.57 | 2.41 | 3.02 | 2.07 | 3.52 | 18.40 |
| Travis Etienne Jr. | NO | targets | 5 | 0.53 | 0.51 | 0.55 | 0.50 | 0.58 | 0.72 |
| Tyler Shough | NO | interceptions | 1 | 0.44 | 0.42 | 0.41 | 0.48 | 0.45 | 0.41 |
| Tyler Shough | NO | pass_attempts | 35 | 35.04 | 35.00 | 34.86 | 33.61 | 33.95 | 33.03 |
| Tyler Shough | NO | pass_completions | 25 | 24.09 | 24.09 | 24.18 | 22.89 | 23.38 | 21.90 |
| Tyler Shough | NO | pass_tds | 1 | 1.44 | 1.48 | 1.79 | 1.53 | 1.53 | 1.12 |
| Tyler Shough | NO | pass_yards | 187 | 261.21 | 260.40 | 262.86 | 239.78 | 244.19 | 215.47 |
| Tyler Shough | NO | rush_yards | 25 | 20.40 | 20.86 | 20.88 | 20.03 | 20.53 | 21.17 |
