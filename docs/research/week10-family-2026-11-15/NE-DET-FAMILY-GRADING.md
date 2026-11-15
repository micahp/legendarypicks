# Week 10: NE at DET, SLC model family

**Final:** DET 35, NE 10 (home win = 1).

Inputs: the prospective snapshots built 2026-11-14 18:54:46Z, week-10 kicker table
(LA = McManus), week-9 streaks and snap counts. Each arm is its own git ref.

## Game level

| Arm | Valid seeds | P(DET) | P(NE) | P(tie) | Home Brier | DET mean (P10-P90) | NE mean (P10-P90) | Total | Combined score error |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|
| v1 | 1000 | 58.2% | 41.8% | 0.0% | 0.175 | 25.08 (14-37) | 22.76 (13-34) | 47.84 | 22.68 |
| v1.5 | 1000 | 57.8% | 42.1% | 0.1% | 0.178 | 25.01 (13-36) | 22.78 (12-34) | 47.79 | 22.77 |
| v1.6 | 1000 | 58.7% | 41.3% | 0.0% | 0.171 | 26.83 (16-38) | 24.18 (13-35) | 51.01 | 22.35 |
| v1.7 | 1000 | 65.4% | 34.6% | 0.0% | 0.120 | 25.29 (14-36) | 20.85 (10-32) | 46.14 | 20.56 |
| v1.7-pr43 | 1000 | 63.0% | 37.0% | 0.0% | 0.137 | 25.07 (13-37) | 20.72 (10-31) | 45.80 | 20.65 |
| v2 | 1000 | 57.8% | 41.5% | 0.7% | 0.178 | 22.33 (13-33) | 19.75 (10-30) | 42.09 | 22.43 |

## Player stat accuracy (MAE over graded player-markets)

| Arm | Graded player-markets | MAE |
|---|---:|---:|
| v1 | 77 | 13.062 |
| v1.5 | 77 | 13.104 |
| v1.6 | 77 | 12.983 |
| v1.7 | 77 | 12.692 |
| v1.7-pr43 | 77 | 12.795 |
| v2 | 77 | 12.479 |

## Market grading

Not possible yet: `picks.dev.db` has no `prop_games` row for 2026-11-15
(newest NFL prop game is 2026-11-08), so there are no pre-kickoff lines for
this game. Prop Brier versus the de-vigged market runs once those lines land.

## Graded player-markets (model mean vs actual)

| Player | Team | Market | Actual | v1 | v1.5 | v1.6 | v1.7 | v1.7-pr43 | v2 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| Amon-Ra St. Brown | DET | receiving_tds | 2 | 0.50 | 0.56 | 0.66 | 0.56 | 0.52 | 0.39 |
| Amon-Ra St. Brown | DET | receiving_yards | 98 | 95.64 | 95.34 | 99.08 | 87.20 | 85.24 | 90.18 |
| Amon-Ra St. Brown | DET | receptions | 4 | 8.45 | 8.55 | 8.51 | 7.89 | 7.82 | 7.90 |
| Amon-Ra St. Brown | DET | targets | 5 | 12.22 | 12.29 | 12.24 | 11.60 | 11.56 | 11.75 |
| Brock Wright | DET | receiving_yards | 11 | 14.93 | 15.37 | 14.28 | 14.21 | 13.68 | 7.24 |
| Brock Wright | DET | receptions | 2 | 1.52 | 1.53 | 1.46 | 1.41 | 1.40 | 0.74 |
| Brock Wright | DET | targets | 2 | 2.13 | 2.17 | 2.04 | 1.96 | 1.95 | 1.02 |
| Isaac TeSlaa | DET | receiving_tds | 1 | 0.07 | 0.08 | 0.10 | 0.08 | 0.10 | 0.06 |
| Isaac TeSlaa | DET | receiving_yards | 19 | 13.28 | 14.48 | 14.68 | 12.82 | 13.62 | 14.47 |
| Isaac TeSlaa | DET | receptions | 2 | 1.22 | 1.27 | 1.25 | 1.16 | 1.23 | 1.27 |
| Isaac TeSlaa | DET | targets | 5 | 1.86 | 1.89 | 1.90 | 1.85 | 1.96 | 2.07 |
| Jacob Saylors | DET | rush_yards | 9 | 2.01 | 1.83 | 1.88 | 2.25 | 2.13 | 0.42 |
| Jahmyr Gibbs | DET | receiving_yards | 99 | 42.98 | 41.81 | 43.79 | 42.98 | 42.70 | 41.16 |
| Jahmyr Gibbs | DET | receptions | 7 | 4.94 | 4.86 | 4.99 | 4.86 | 4.78 | 4.60 |
| Jahmyr Gibbs | DET | rush_tds | 2 | 1.00 | 0.99 | 1.03 | 1.01 | 0.96 | 0.80 |
| Jahmyr Gibbs | DET | rush_yards | 153 | 111.93 | 112.74 | 114.28 | 117.38 | 114.98 | 97.17 |
| Jahmyr Gibbs | DET | targets | 8 | 6.61 | 6.54 | 6.70 | 6.29 | 6.18 | 6.00 |
| Jameson Williams | DET | receiving_yards | 50 | 52.02 | 52.71 | 51.98 | 46.93 | 47.62 | 52.00 |
| Jameson Williams | DET | receptions | 4 | 4.67 | 4.63 | 4.58 | 4.22 | 4.22 | 4.52 |
| Jameson Williams | DET | targets | 7 | 7.33 | 7.28 | 7.22 | 6.74 | 6.95 | 7.26 |
| Jared Goff | DET | interceptions | 2 | 0.45 | 0.44 | 0.46 | 0.45 | 0.43 | 0.24 |
| Jared Goff | DET | pass_attempts | 31 | 38.20 | 38.08 | 38.04 | 35.92 | 36.07 | 35.20 |
| Jared Goff | DET | pass_completions | 20 | 26.42 | 26.25 | 26.33 | 24.86 | 24.73 | 24.03 |
| Jared Goff | DET | pass_tds | 3 | 1.57 | 1.54 | 1.87 | 1.68 | 1.67 | 1.16 |
| Jared Goff | DET | pass_yards | 303 | 274.18 | 274.05 | 279.47 | 257.14 | 254.72 | 253.92 |
| Jared Goff | DET | rush_yards | 3 | 9.30 | 9.69 | 9.16 | 9.68 | 9.38 | 9.59 |
| Joshua Dobbs | DET | pass_attempts | 1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Joshua Dobbs | DET | pass_completions | 1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Joshua Dobbs | DET | pass_yards | 7 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Joshua Dobbs | DET | rush_yards | -2 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Sam LaPorta | DET | receiving_yards | 16 | 32.26 | 32.42 | 32.94 | 31.67 | 30.80 | 41.33 |
| Sam LaPorta | DET | receptions | 1 | 3.33 | 3.29 | 3.32 | 3.22 | 3.19 | 4.16 |
| Sam LaPorta | DET | targets | 4 | 4.70 | 4.76 | 4.69 | 4.48 | 4.42 | 5.99 |
| Sione Vaki | DET | receiving_yards | 17 | 2.27 | 2.37 | 2.23 | 2.43 | 2.43 | 5.86 |
| Sione Vaki | DET | receptions | 1 | 0.28 | 0.27 | 0.27 | 0.29 | 0.26 | 0.65 |
| Sione Vaki | DET | rush_yards | 28 | 1.42 | 1.83 | 2.17 | 1.85 | 1.91 | 15.60 |
| Sione Vaki | DET | targets | 1 | 0.42 | 0.38 | 0.38 | 0.39 | 0.35 | 0.87 |
| A.J. Brown | NE | receiving_yards | 27 | 6.08 | 6.02 | 5.89 | 4.69 | 4.46 | 4.75 |
| A.J. Brown | NE | receptions | 2 | 0.48 | 0.46 | 0.45 | 0.40 | 0.35 | 0.37 |
| A.J. Brown | NE | targets | 6 | 0.73 | 0.71 | 0.69 | 0.67 | 0.56 | 0.69 |
| Corey Kiner | NE | rush_yards | 25 | 3.29 | 2.92 | 3.19 | 3.11 | 2.81 | 10.18 |
| DeMario Douglas | NE | receiving_yards | 4 | 50.58 | 51.92 | 50.91 | 46.02 | 46.87 | 50.69 |
| DeMario Douglas | NE | receptions | 1 | 3.99 | 4.09 | 3.96 | 3.82 | 3.90 | 4.24 |
| DeMario Douglas | NE | targets | 3 | 6.01 | 6.12 | 5.99 | 5.88 | 6.04 | 6.65 |
| Drake Maye | NE | pass_attempts | 4 | 34.65 | 34.84 | 34.81 | 33.04 | 33.14 | 30.73 |
| Drake Maye | NE | pass_completions | 3 | 22.90 | 23.00 | 22.99 | 21.79 | 22.01 | 20.62 |
| Drake Maye | NE | pass_yards | 48 | 262.46 | 260.85 | 265.85 | 240.26 | 242.16 | 218.28 |
| Drake Maye | NE | rush_yards | 11 | 37.28 | 36.43 | 36.46 | 35.26 | 35.59 | 36.45 |
| Efton Chism III | NE | targets | 1 | 0.68 | 0.67 | 0.70 | 0.64 | 0.61 | 2.51 |
| Eli Raridon | NE | receiving_yards | 6 | 3.11 | 3.15 | 3.17 | 2.73 | 2.83 | 8.70 |
| Eli Raridon | NE | receptions | 1 | 0.28 | 0.30 | 0.28 | 0.26 | 0.29 | 0.88 |
| Eli Raridon | NE | targets | 1 | 0.46 | 0.45 | 0.41 | 0.38 | 0.42 | 1.32 |
| Hunter Henry | NE | receiving_yards | 22 | 54.60 | 56.51 | 57.03 | 51.88 | 52.14 | 45.82 |
| Hunter Henry | NE | receptions | 2 | 5.05 | 5.21 | 5.16 | 4.90 | 4.95 | 4.49 |
| Hunter Henry | NE | targets | 3 | 7.63 | 7.83 | 7.77 | 7.26 | 7.32 | 6.10 |
| Kyle Williams | NE | targets | 1 | 2.86 | 2.80 | 2.87 | 2.66 | 2.72 | 2.10 |
| Lan Larison | NE | receiving_tds | 1 | 0.02 | 0.02 | 0.03 | 0.02 | 0.03 | 0.01 |
| Lan Larison | NE | receiving_yards | 15 | 3.09 | 3.05 | 3.47 | 3.04 | 3.33 | 1.42 |
| Lan Larison | NE | receptions | 2 | 0.36 | 0.36 | 0.41 | 0.37 | 0.38 | 0.20 |
| Lan Larison | NE | rush_yards | 2 | 3.10 | 3.20 | 2.78 | 2.65 | 2.44 | 5.88 |
| Lan Larison | NE | targets | 3 | 0.52 | 0.53 | 0.59 | 0.54 | 0.53 | 0.29 |
| Mack Hollins | NE | receiving_yards | 48 | 71.07 | 70.24 | 69.91 | 65.07 | 64.95 | 39.13 |
| Mack Hollins | NE | receptions | 5 | 5.61 | 5.62 | 5.50 | 5.25 | 5.26 | 3.33 |
| Mack Hollins | NE | targets | 6 | 8.71 | 8.86 | 8.66 | 8.30 | 8.34 | 5.22 |
| Reggie Gilliam | NE | receiving_yards | 6 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Reggie Gilliam | NE | receptions | 1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Reggie Gilliam | NE | targets | 1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Rhamondre Stevenson | NE | receiving_yards | 1 | 26.82 | 26.68 | 27.98 | 26.88 | 26.21 | 25.25 |
| Rhamondre Stevenson | NE | receptions | 1 | 3.10 | 3.21 | 3.23 | 3.14 | 3.15 | 3.29 |
| Rhamondre Stevenson | NE | rush_yards | 4 | 81.24 | 82.13 | 82.77 | 78.88 | 79.70 | 82.97 |
| Rhamondre Stevenson | NE | targets | 1 | 4.34 | 4.43 | 4.48 | 4.15 | 4.15 | 4.40 |
| Tommy DeVito | NE | interceptions | 1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Tommy DeVito | NE | pass_attempts | 24 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Tommy DeVito | NE | pass_completions | 12 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Tommy DeVito | NE | pass_tds | 1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Tommy DeVito | NE | pass_yards | 81 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Tommy DeVito | NE | rush_yards | 19 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
