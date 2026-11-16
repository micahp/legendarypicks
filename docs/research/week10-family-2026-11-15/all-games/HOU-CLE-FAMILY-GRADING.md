# Week 10: HOU at CLE, SLC model family

**Final:** CLE 27, HOU 24 (home win = 1).

Inputs: the prospective snapshots built 2026-11-14 18:54:46Z, week-10 kicker table
(LA = McManus), week-9 streaks and snap counts. Each arm is its own git ref.

## Game level

| Arm | Valid seeds | P(CLE) | P(HOU) | P(tie) | Home Brier | CLE mean (P10-P90) | HOU mean (P10-P90) | Total | Combined score error |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|
| v1 | 1000 | 27.8% | 72.2% | 0.0% | 0.521 | 16.01 (6-26) | 22.60 (12-34) | 38.62 | 12.38 |
| v1.5 | 1000 | 30.6% | 69.2% | 0.2% | 0.482 | 16.34 (6-27) | 22.40 (12-34) | 38.74 | 12.26 |
| v1.6 | 1000 | 30.3% | 69.6% | 0.1% | 0.486 | 17.70 (7-28) | 24.52 (13-36) | 42.22 | 9.82 |
| v1.7 | 99 | 28.3% | 71.7% | 0.0% | 0.514 | 14.78 (6-26) | 21.54 (10-33) | 36.31 | 14.69 |
| v1.7-pr43 | 100 | 36.0% | 64.0% | 0.0% | 0.410 | 15.64 (6-24) | 21.40 (11-31) | 37.04 | 13.96 |
| v2 | 1000 | 31.5% | 67.9% | 0.6% | 0.469 | 15.60 (6-26) | 21.08 (12-31) | 36.68 | 14.32 |

## Player stat accuracy (MAE over graded player-markets)

| Arm | Graded player-markets | MAE |
|---|---:|---:|
| v1 | 66 | 9.467 |
| v1.5 | 66 | 9.408 |
| v1.6 | 66 | 9.439 |
| v1.7 | 66 | 10.120 |
| v1.7-pr43 | 66 | 10.319 |
| v2 | 66 | 9.397 |

## Market grading

Not possible yet: `picks.dev.db` has no `prop_games` row for 2026-11-15
(newest NFL prop game is 2026-11-08), so there are no pre-kickoff lines for
this game. Prop Brier versus the de-vigged market runs once those lines land.

## Graded player-markets (model mean vs actual)

| Player | Team | Market | Actual | v1 | v1.5 | v1.6 | v1.7 | v1.7-pr43 | v2 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| Blake Whiteheart | CLE | targets | 1 | 0.42 | 0.39 | 0.46 | 0.39 | 0.31 | 1.69 |
| Denzel Boston | CLE | receiving_yards | 16 | 4.21 | 3.96 | 4.27 | 2.71 | 3.74 | 22.21 |
| Denzel Boston | CLE | receptions | 1 | 0.37 | 0.37 | 0.35 | 0.24 | 0.43 | 2.15 |
| Denzel Boston | CLE | targets | 2 | 0.70 | 0.67 | 0.62 | 0.44 | 0.58 | 3.74 |
| Deshaun Watson | CLE | interceptions | 1 | 1.16 | 1.08 | 1.12 | 0.99 | 1.02 | 0.35 |
| Deshaun Watson | CLE | pass_attempts | 40 | 37.48 | 36.97 | 37.26 | 32.93 | 32.93 | 29.21 |
| Deshaun Watson | CLE | pass_completions | 25 | 20.81 | 20.54 | 20.69 | 18.37 | 18.01 | 18.32 |
| Deshaun Watson | CLE | pass_yards | 312 | 207.28 | 207.27 | 212.43 | 178.70 | 174.60 | 172.13 |
| Deshaun Watson | CLE | rush_tds | 1 | 0.15 | 0.17 | 0.14 | 0.14 | 0.13 | 0.21 |
| Deshaun Watson | CLE | rush_yards | 49 | 24.57 | 25.66 | 26.03 | 23.97 | 23.30 | 31.91 |
| Dylan Sampson | CLE | receiving_yards | 31 | 14.40 | 15.58 | 15.62 | 13.29 | 15.24 | 12.26 |
| Dylan Sampson | CLE | receptions | 4 | 1.98 | 1.97 | 2.03 | 1.74 | 1.98 | 1.44 |
| Dylan Sampson | CLE | rush_yards | 6 | 18.86 | 16.54 | 17.70 | 22.44 | 19.20 | 35.34 |
| Dylan Sampson | CLE | targets | 6 | 3.14 | 3.08 | 3.14 | 2.76 | 2.92 | 2.05 |
| Harold Fannin Jr. | CLE | receiving_yards | 91 | 43.35 | 42.81 | 42.55 | 35.49 | 35.16 | 27.49 |
| Harold Fannin Jr. | CLE | receptions | 7 | 4.57 | 4.54 | 4.40 | 3.78 | 3.92 | 2.96 |
| Harold Fannin Jr. | CLE | targets | 9 | 8.00 | 7.89 | 7.83 | 6.58 | 7.05 | 4.58 |
| Jerry Jeudy | CLE | receiving_yards | 74 | 77.44 | 75.73 | 78.31 | 63.03 | 58.32 | 43.66 |
| Jerry Jeudy | CLE | receptions | 2 | 6.93 | 6.70 | 6.94 | 6.07 | 5.39 | 4.42 |
| Jerry Jeudy | CLE | targets | 4 | 13.05 | 12.58 | 13.03 | 11.59 | 10.70 | 7.42 |
| KC Concepcion | CLE | receiving_yards | 21 | 4.37 | 3.93 | 4.47 | 3.08 | 4.26 | 21.39 |
| KC Concepcion | CLE | receptions | 3 | 0.39 | 0.34 | 0.35 | 0.36 | 0.39 | 2.12 |
| KC Concepcion | CLE | rush_tds | 1 | 0.00 | 0.00 | 0.01 | 0.00 | 0.00 | 0.01 |
| KC Concepcion | CLE | rush_yards | 6 | 0.53 | 0.55 | 0.67 | 0.77 | 0.90 | 1.58 |
| KC Concepcion | CLE | targets | 8 | 0.66 | 0.57 | 0.64 | 0.62 | 0.67 | 3.45 |
| Malachi Corley | CLE | receiving_yards | 37 | 9.31 | 11.45 | 11.12 | 8.16 | 11.06 | 2.19 |
| Malachi Corley | CLE | receptions | 3 | 0.87 | 1.06 | 0.97 | 0.61 | 0.88 | 0.24 |
| Malachi Corley | CLE | targets | 3 | 1.54 | 1.82 | 1.66 | 1.05 | 1.52 | 0.41 |
| Quinshon Judkins | CLE | receiving_yards | 33 | 12.33 | 12.60 | 12.82 | 15.27 | 11.59 | 15.02 |
| Quinshon Judkins | CLE | receptions | 3 | 1.66 | 1.64 | 1.68 | 1.92 | 1.34 | 1.91 |
| Quinshon Judkins | CLE | rush_tds | 1 | 0.39 | 0.38 | 0.38 | 0.26 | 0.45 | 0.25 |
| Quinshon Judkins | CLE | rush_yards | 38 | 64.18 | 67.78 | 67.22 | 58.81 | 69.58 | 47.10 |
| Quinshon Judkins | CLE | targets | 5 | 2.76 | 2.84 | 2.78 | 2.96 | 2.22 | 2.56 |
| Tylan Wallace | CLE | receiving_yards | 9 | 4.19 | 3.39 | 3.92 | 3.28 | 3.87 | 1.39 |
| Tylan Wallace | CLE | receptions | 2 | 0.41 | 0.30 | 0.34 | 0.29 | 0.36 | 0.13 |
| Tylan Wallace | CLE | targets | 2 | 0.69 | 0.56 | 0.58 | 0.49 | 0.60 | 0.21 |
| C.J. Stroud | HOU | interceptions | 1 | 0.40 | 0.40 | 0.40 | 0.39 | 0.48 | 0.26 |
| C.J. Stroud | HOU | pass_attempts | 38 | 36.28 | 36.45 | 36.31 | 35.56 | 35.95 | 33.01 |
| C.J. Stroud | HOU | pass_completions | 20 | 20.62 | 20.65 | 20.61 | 20.29 | 20.35 | 20.21 |
| C.J. Stroud | HOU | pass_tds | 3 | 1.26 | 1.23 | 1.52 | 1.18 | 1.33 | 1.07 |
| C.J. Stroud | HOU | pass_yards | 211 | 230.00 | 229.88 | 233.74 | 216.13 | 210.75 | 220.06 |
| C.J. Stroud | HOU | rush_yards | 20 | 19.23 | 19.36 | 18.77 | 21.07 | 17.55 | 17.39 |
| Dalton Schultz | HOU | receiving_tds | 1 | 0.22 | 0.20 | 0.28 | 0.19 | 0.16 | 0.20 |
| Dalton Schultz | HOU | receiving_yards | 11 | 40.38 | 41.36 | 42.18 | 39.73 | 38.77 | 36.70 |
| Dalton Schultz | HOU | receptions | 1 | 3.74 | 3.73 | 3.69 | 3.84 | 3.61 | 3.51 |
| Dalton Schultz | HOU | targets | 2 | 6.42 | 6.52 | 6.36 | 6.33 | 6.20 | 5.35 |
| Dare Ogunbowale | HOU | receiving_yards | 13 | - | - | - | - | - | - |
| Dare Ogunbowale | HOU | receptions | 1 | - | - | - | - | - | - |
| Dare Ogunbowale | HOU | rush_yards | 2 | - | - | - | - | - | - |
| Dare Ogunbowale | HOU | targets | 1 | - | - | - | - | - | - |
| Emari Demercado | HOU | receiving_yards | -1 | 2.61 | 2.67 | 2.56 | 3.27 | 1.79 | 1.47 |
| Emari Demercado | HOU | receptions | 1 | 0.35 | 0.34 | 0.37 | 0.47 | 0.36 | 0.21 |
| Emari Demercado | HOU | rush_yards | 16 | 3.13 | 3.35 | 3.62 | 2.13 | 1.25 | 8.04 |
| Emari Demercado | HOU | targets | 2 | 0.58 | 0.59 | 0.59 | 0.76 | 0.60 | 0.30 |
| Kayshon Boutte | HOU | targets | 1 | 0.37 | 0.44 | 0.42 | 0.35 | 0.57 | 1.12 |
| Nico Collins | HOU | receiving_tds | 1 | 0.33 | 0.34 | 0.39 | 0.34 | 0.27 | 0.30 |
| Nico Collins | HOU | receiving_yards | 94 | 63.91 | 63.06 | 64.45 | 58.36 | 51.94 | 64.95 |
| Nico Collins | HOU | receptions | 9 | 5.24 | 5.18 | 5.21 | 4.85 | 4.56 | 5.44 |
| Nico Collins | HOU | targets | 16 | 9.21 | 9.21 | 9.35 | 8.68 | 8.53 | 9.09 |
| Tank Dell | HOU | receiving_yards | 21 | 3.53 | 2.87 | 3.17 | 3.11 | 4.30 | 6.08 |
| Tank Dell | HOU | receptions | 3 | 0.27 | 0.25 | 0.26 | 0.26 | 0.36 | 0.52 |
| Tank Dell | HOU | targets | 4 | 0.50 | 0.45 | 0.48 | 0.40 | 0.61 | 0.94 |
| Woody Marks | HOU | receiving_yards | 15 | 16.54 | 16.24 | 16.54 | 13.73 | 17.37 | 14.16 |
| Woody Marks | HOU | receptions | 1 | 2.19 | 2.23 | 2.18 | 2.08 | 2.33 | 1.96 |
| Woody Marks | HOU | rush_yards | 50 | 109.58 | 107.66 | 110.72 | 104.41 | 104.45 | 78.84 |
| Woody Marks | HOU | targets | 1 | 3.75 | 3.77 | 3.71 | 3.09 | 3.66 | 2.93 |
| Xavier Hutchinson | HOU | receiving_tds | 1 | 0.15 | 0.14 | 0.17 | 0.14 | 0.22 | 0.17 |
| Xavier Hutchinson | HOU | receiving_yards | 58 | 28.44 | 29.06 | 29.65 | 28.03 | 26.92 | 42.03 |
| Xavier Hutchinson | HOU | receptions | 4 | 2.32 | 2.40 | 2.42 | 2.31 | 2.37 | 3.57 |
| Xavier Hutchinson | HOU | targets | 9 | 4.38 | 4.58 | 4.64 | 4.27 | 4.57 | 6.59 |
