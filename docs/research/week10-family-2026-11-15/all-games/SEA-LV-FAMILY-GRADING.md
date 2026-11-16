# Week 10: SEA at LV, SLC model family

**Final:** LV 13, SEA 21 (home win = 0).

Inputs: the prospective snapshots built 2026-11-14 18:54:46Z, week-10 kicker table
(LA = McManus), week-9 streaks and snap counts. Each arm is its own git ref.

## Game level

| Arm | Valid seeds | P(LV) | P(SEA) | P(tie) | Home Brier | LV mean (P10-P90) | SEA mean (P10-P90) | Total | Combined score error |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|
| v1 | 100 | 32.0% | 68.0% | 0.0% | 0.102 | 18.81 (9-27) | 24.23 (15-35) | 43.04 | 9.04 |
| v1.5 | 100 | 30.0% | 70.0% | 0.0% | 0.090 | 20.30 (10-31) | 26.11 (16-38) | 46.41 | 12.41 |
| v1.6 | 100 | 26.0% | 74.0% | 0.0% | 0.068 | 20.35 (11-29) | 26.58 (16-37) | 46.93 | 12.93 |
| v1.7 | 100 | 32.0% | 67.0% | 1.0% | 0.102 | 19.56 (10-30) | 25.28 (14-38) | 44.84 | 10.84 |
| v1.7-pr43 | 100 | 28.0% | 72.0% | 0.0% | 0.078 | 18.74 (9-28) | 25.84 (14-38) | 44.58 | 10.58 |
| v2 | 100 | 45.0% | 54.0% | 1.0% | 0.203 | 20.15 (13-30) | 22.76 (13-33) | 42.91 | 8.91 |

## Player stat accuracy (MAE over graded player-markets)

| Arm | Graded player-markets | MAE |
|---|---:|---:|
| v1 | 63 | 9.904 |
| v1.5 | 63 | 9.994 |
| v1.6 | 63 | 10.004 |
| v1.7 | 63 | 9.496 |
| v1.7-pr43 | 63 | 9.397 |
| v2 | 63 | 9.837 |

## Market grading

Not possible yet: `picks.dev.db` has no `prop_games` row for 2026-11-15
(newest NFL prop game is 2026-11-08), so there are no pre-kickoff lines for
this game. Prop Brier versus the de-vigged market runs once those lines land.

## Graded player-markets (model mean vs actual)

| Player | Team | Market | Actual | v1 | v1.5 | v1.6 | v1.7 | v1.7-pr43 | v2 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| Ashton Jeanty | LV | receiving_yards | 46 | 31.55 | 31.11 | 30.84 | 37.66 | 33.99 | 30.67 |
| Ashton Jeanty | LV | receptions | 4 | 4.18 | 4.16 | 4.28 | 4.14 | 4.44 | 3.85 |
| Ashton Jeanty | LV | rush_yards | 18 | 93.68 | 82.03 | 82.48 | 89.64 | 82.31 | 57.31 |
| Ashton Jeanty | LV | targets | 4 | 6.17 | 6.25 | 6.11 | 5.80 | 6.28 | 5.26 |
| Brock Bowers | LV | receiving_yards | 18 | 34.35 | 38.79 | 37.18 | 35.86 | 35.49 | 36.83 |
| Brock Bowers | LV | receptions | 2 | 3.58 | 3.79 | 3.70 | 3.47 | 3.58 | 4.00 |
| Brock Bowers | LV | targets | 2 | 5.44 | 5.27 | 5.40 | 5.10 | 5.12 | 5.62 |
| Cody White | LV | receiving_yards | 22 | 5.17 | 4.04 | 5.09 | 5.63 | 3.67 | 0.00 |
| Cody White | LV | receptions | 1 | 0.50 | 0.45 | 0.49 | 0.55 | 0.36 | 0.00 |
| Cody White | LV | targets | 1 | 0.72 | 0.62 | 0.70 | 0.83 | 0.44 | 0.00 |
| Connor Heyward | LV | receiving_yards | 6 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Connor Heyward | LV | receptions | 2 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Connor Heyward | LV | targets | 2 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Fernando Mendoza | LV | pass_attempts | 29 | 36.60 | 36.67 | 36.82 | 35.63 | 35.26 | 35.62 |
| Fernando Mendoza | LV | pass_completions | 17 | 23.43 | 23.68 | 23.43 | 22.53 | 22.88 | 24.20 |
| Fernando Mendoza | LV | pass_yards | 143 | 238.01 | 241.92 | 239.94 | 231.53 | 227.07 | 233.37 |
| Fernando Mendoza | LV | rush_tds | 1 | 0.15 | 0.20 | 0.15 | 0.13 | 0.14 | 0.23 |
| Fernando Mendoza | LV | rush_yards | 22 | 15.01 | 15.40 | 15.39 | 13.58 | 14.76 | 11.73 |
| Ian Thomas | LV | receiving_yards | 13 | 5.24 | 4.93 | 6.44 | 5.47 | 4.06 | 5.86 |
| Ian Thomas | LV | receptions | 1 | 0.57 | 0.53 | 0.58 | 0.51 | 0.45 | 0.55 |
| Ian Thomas | LV | targets | 1 | 0.80 | 0.87 | 0.95 | 0.75 | 0.66 | 0.74 |
| Jack Bech | LV | receiving_yards | 10 | 32.26 | 20.98 | 23.36 | 24.79 | 26.39 | 13.65 |
| Jack Bech | LV | receptions | 2 | 2.85 | 1.86 | 1.89 | 2.27 | 2.46 | 1.25 |
| Jack Bech | LV | targets | 7 | 4.15 | 2.87 | 2.95 | 3.69 | 3.91 | 1.88 |
| Jalen Nailor | LV | receiving_yards | -1 | 3.86 | 3.30 | 4.77 | 3.76 | 4.36 | 20.18 |
| Jalen Nailor | LV | receptions | 1 | 0.34 | 0.29 | 0.36 | 0.31 | 0.41 | 1.87 |
| Jalen Nailor | LV | targets | 4 | 0.61 | 0.65 | 0.58 | 0.61 | 0.69 | 2.98 |
| Michael Mayer | LV | receiving_yards | 16 | 16.79 | 22.63 | 17.04 | 19.92 | 15.42 | 38.84 |
| Michael Mayer | LV | receptions | 2 | 1.68 | 1.91 | 1.75 | 1.80 | 1.59 | 4.14 |
| Michael Mayer | LV | rush_yards | 2 | 0.54 | 0.26 | 0.47 | 0.74 | 0.40 | 1.31 |
| Michael Mayer | LV | targets | 3 | 2.60 | 3.05 | 2.89 | 2.71 | 2.31 | 5.46 |
| Mike Washington Jr. | LV | receiving_yards | 4 | 2.83 | 1.35 | 2.00 | 1.14 | 1.62 | 7.16 |
| Mike Washington Jr. | LV | receptions | 1 | 0.36 | 0.23 | 0.24 | 0.19 | 0.25 | 0.84 |
| Mike Washington Jr. | LV | rush_yards | 23 | 1.69 | 1.11 | 1.06 | 1.26 | 0.85 | 24.15 |
| Mike Washington Jr. | LV | targets | 1 | 0.51 | 0.44 | 0.37 | 0.28 | 0.36 | 1.19 |
| Tre Tucker | LV | receiving_yards | 9 | 75.04 | 83.10 | 79.45 | 68.94 | 71.21 | 69.09 |
| Tre Tucker | LV | receptions | 1 | 6.62 | 7.42 | 7.08 | 6.39 | 6.62 | 6.50 |
| Tre Tucker | LV | targets | 2 | 10.52 | 12.00 | 11.56 | 10.67 | 11.00 | 10.40 |
| AJ Barner | SEA | receiving_yards | 19 | 38.14 | 40.27 | 37.01 | 38.17 | 37.39 | 34.25 |
| AJ Barner | SEA | receptions | 3 | 3.61 | 3.43 | 3.55 | 3.33 | 3.61 | 3.77 |
| AJ Barner | SEA | targets | 3 | 5.30 | 4.72 | 5.11 | 4.50 | 4.86 | 5.56 |
| Cooper Kupp | SEA | receiving_tds | 1 | 0.21 | 0.24 | 0.27 | 0.34 | 0.25 | 0.21 |
| Cooper Kupp | SEA | receiving_yards | 34 | 40.19 | 43.18 | 44.88 | 42.31 | 36.26 | 40.57 |
| Cooper Kupp | SEA | receptions | 1 | 3.18 | 3.74 | 3.65 | 3.45 | 3.10 | 3.70 |
| Cooper Kupp | SEA | targets | 1 | 4.84 | 5.38 | 5.12 | 5.28 | 4.80 | 5.55 |
| Drew Lock | SEA | pass_attempts | 17 | 34.67 | 33.91 | 35.02 | 33.91 | 33.23 | 32.94 |
| Drew Lock | SEA | pass_completions | 14 | 23.65 | 23.78 | 24.48 | 23.11 | 22.94 | 22.18 |
| Drew Lock | SEA | pass_tds | 2 | 1.38 | 1.48 | 1.74 | 1.61 | 1.62 | 1.18 |
| Drew Lock | SEA | pass_yards | 240 | 268.92 | 262.34 | 282.55 | 247.90 | 251.57 | 225.32 |
| Drew Lock | SEA | rush_yards | 20 | 20.40 | 18.44 | 20.02 | 20.65 | 18.02 | 15.80 |
| Jadarian Price | SEA | receiving_yards | 8 | 2.14 | 2.69 | 3.73 | 2.66 | 1.87 | 3.01 |
| Jadarian Price | SEA | receptions | 1 | 0.29 | 0.40 | 0.38 | 0.53 | 0.30 | 0.41 |
| Jadarian Price | SEA | rush_tds | 1 | 0.00 | 0.02 | 0.03 | 0.02 | 0.03 | 0.16 |
| Jadarian Price | SEA | rush_yards | 36 | 2.06 | 1.21 | 2.78 | 3.03 | 2.55 | 14.77 |
| Jadarian Price | SEA | targets | 1 | 0.43 | 0.58 | 0.51 | 0.73 | 0.40 | 0.54 |
| Jaxon Smith-Njigba | SEA | receiving_tds | 1 | 0.58 | 0.61 | 0.66 | 0.53 | 0.49 | 0.43 |
| Jaxon Smith-Njigba | SEA | receiving_yards | 171 | 107.72 | 106.35 | 110.99 | 82.69 | 96.65 | 89.70 |
| Jaxon Smith-Njigba | SEA | receptions | 8 | 8.75 | 8.56 | 8.78 | 7.14 | 8.06 | 8.05 |
| Jaxon Smith-Njigba | SEA | targets | 10 | 12.85 | 12.45 | 12.51 | 11.17 | 12.07 | 12.11 |
| Rashid Shaheed | SEA | receiving_yards | 8 | 17.80 | 11.89 | 17.11 | 15.00 | 15.52 | 20.61 |
| Rashid Shaheed | SEA | receptions | 1 | 1.31 | 1.14 | 1.28 | 1.23 | 1.34 | 1.73 |
| Rashid Shaheed | SEA | targets | 2 | 2.08 | 1.69 | 1.84 | 1.89 | 1.98 | 2.90 |
| Zach Charbonnet | SEA | rush_yards | 94 | 97.70 | 103.64 | 99.73 | 99.79 | 110.26 | 54.58 |
