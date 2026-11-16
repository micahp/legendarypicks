# Week 10: SF at DAL, SLC model family

**Final:** DAL 40, SF 46 (home win = 0).

Inputs: the prospective snapshots built 2026-11-14 18:54:46Z, week-10 kicker table
(LA = McManus), week-9 streaks and snap counts. Each arm is its own git ref.

## Game level

| Arm | Valid seeds | P(DAL) | P(SF) | P(tie) | Home Brier | DAL mean (P10-P90) | SF mean (P10-P90) | Total | Combined score error |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|
| v1 | 100 | 52.0% | 48.0% | 0.0% | 0.270 | 24.33 (13-35) | 23.92 (13-37) | 48.25 | 37.75 |
| v1.5 | 100 | 58.0% | 42.0% | 0.0% | 0.336 | 24.84 (14-34) | 22.52 (12-33) | 47.36 | 38.64 |
| v1.6 | 100 | 60.0% | 40.0% | 0.0% | 0.360 | 28.87 (18-41) | 24.91 (14-37) | 53.78 | 32.22 |
| v1.7 | 100 | 50.0% | 50.0% | 0.0% | 0.250 | 24.51 (13-38) | 23.03 (10-34) | 47.54 | 38.46 |
| v1.7-pr43 | 100 | 61.0% | 39.0% | 0.0% | 0.372 | 24.50 (14-35) | 20.57 (10-31) | 45.07 | 40.93 |
| v2 | 100 | 44.0% | 55.0% | 1.0% | 0.194 | 22.70 (12-34) | 23.99 (13-34) | 46.69 | 39.31 |

## Player stat accuracy (MAE over graded player-markets)

| Arm | Graded player-markets | MAE |
|---|---:|---:|
| v1 | 61 | 14.878 |
| v1.5 | 61 | 15.244 |
| v1.6 | 61 | 13.774 |
| v1.7 | 61 | 15.406 |
| v1.7-pr43 | 61 | 16.078 |
| v2 | 61 | 13.626 |

## Market grading

Not possible yet: `picks.dev.db` has no `prop_games` row for 2026-11-15
(newest NFL prop game is 2026-11-08), so there are no pre-kickoff lines for
this game. Prop Brier versus the de-vigged market runs once those lines land.

## Graded player-markets (model mean vs actual)

| Player | Team | Market | Actual | v1 | v1.5 | v1.6 | v1.7 | v1.7-pr43 | v2 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| Brevyn Spann-Ford | DAL | receiving_yards | 26 | 19.10 | 20.90 | 18.09 | 19.71 | 18.58 | 31.91 |
| Brevyn Spann-Ford | DAL | receptions | 1 | 1.75 | 2.03 | 1.68 | 1.87 | 1.72 | 3.18 |
| Brevyn Spann-Ford | DAL | targets | 3 | 2.58 | 2.89 | 2.45 | 2.40 | 2.39 | 4.58 |
| CeeDee Lamb | DAL | receiving_tds | 1 | 0.28 | 0.39 | 0.51 | 0.41 | 0.36 | 0.34 |
| CeeDee Lamb | DAL | receiving_yards | 72 | 59.06 | 59.31 | 70.29 | 54.39 | 54.45 | 76.52 |
| CeeDee Lamb | DAL | receptions | 7 | 4.90 | 4.90 | 5.61 | 4.90 | 4.62 | 7.18 |
| CeeDee Lamb | DAL | targets | 13 | 7.86 | 7.13 | 8.15 | 7.09 | 6.92 | 11.59 |
| Cooper Beebe | DAL | receiving_yards | -6 | - | - | - | - | - | - |
| Dak Prescott | DAL | interceptions | 1 | 0.73 | 0.71 | 0.60 | 0.56 | 0.73 | 0.39 |
| Dak Prescott | DAL | pass_attempts | 51 | 37.07 | 37.44 | 37.07 | 36.20 | 35.34 | 36.59 |
| Dak Prescott | DAL | pass_completions | 30 | 25.05 | 25.53 | 24.86 | 25.23 | 24.21 | 24.68 |
| Dak Prescott | DAL | pass_tds | 5 | 1.66 | 1.62 | 2.09 | 1.70 | 1.67 | 1.26 |
| Dak Prescott | DAL | pass_yards | 343 | 275.40 | 283.70 | 292.48 | 258.28 | 257.41 | 253.81 |
| Dak Prescott | DAL | rush_yards | 7 | 14.30 | 14.87 | 13.13 | 15.25 | 14.45 | 22.51 |
| George Pickens | DAL | receiving_tds | 3 | 0.53 | 0.36 | 0.53 | 0.42 | 0.36 | 0.28 |
| George Pickens | DAL | receiving_yards | 145 | 76.08 | 67.05 | 75.94 | 65.84 | 64.55 | 60.46 |
| George Pickens | DAL | receptions | 11 | 6.01 | 5.65 | 5.82 | 6.00 | 5.60 | 5.17 |
| George Pickens | DAL | targets | 18 | 9.05 | 8.44 | 9.02 | 9.13 | 8.64 | 8.06 |
| Hunter Luepke | DAL | receiving_yards | 6 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Hunter Luepke | DAL | receptions | 1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Hunter Luepke | DAL | rush_yards | 9 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Hunter Luepke | DAL | targets | 1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Israel Abanikanda | DAL | receiving_yards | 2 | - | - | - | - | - | - |
| Israel Abanikanda | DAL | receptions | 1 | - | - | - | - | - | - |
| Israel Abanikanda | DAL | rush_yards | 8 | - | - | - | - | - | - |
| Israel Abanikanda | DAL | targets | 1 | - | - | - | - | - | - |
| Javonte Williams | DAL | receiving_yards | 4 | 30.64 | 28.02 | 28.24 | 26.14 | 29.15 | 23.19 |
| Javonte Williams | DAL | receptions | 1 | 3.94 | 3.79 | 3.40 | 3.74 | 3.60 | 3.30 |
| Javonte Williams | DAL | rush_yards | 63 | 85.12 | 79.60 | 93.06 | 81.65 | 88.58 | 90.87 |
| Javonte Williams | DAL | targets | 1 | 5.26 | 5.28 | 4.86 | 4.90 | 4.80 | 4.29 |
| KaVontae Turpin | DAL | receiving_yards | 10 | 13.63 | 28.38 | 14.75 | 19.17 | 18.56 | 1.63 |
| KaVontae Turpin | DAL | receptions | 1 | 1.15 | 2.18 | 1.21 | 1.59 | 1.54 | 0.18 |
| KaVontae Turpin | DAL | rush_yards | 9 | 3.52 | 2.56 | 4.00 | 3.41 | 3.02 | 0.10 |
| KaVontae Turpin | DAL | targets | 3 | 1.82 | 3.23 | 2.03 | 2.47 | 2.35 | 0.21 |
| Luke Schoonmaker | DAL | receiving_yards | 12 | 33.60 | 35.05 | 33.51 | 30.98 | 26.99 | 16.30 |
| Luke Schoonmaker | DAL | receptions | 1 | 3.29 | 3.05 | 2.95 | 2.93 | 2.91 | 1.70 |
| Luke Schoonmaker | DAL | targets | 2 | 4.72 | 4.57 | 4.45 | 4.17 | 4.32 | 2.24 |
| Ryan Flournoy | DAL | receiving_tds | 1 | 0.14 | 0.11 | 0.20 | 0.17 | 0.12 | 0.16 |
| Ryan Flournoy | DAL | receiving_yards | 71 | 27.53 | 30.18 | 36.53 | 27.58 | 26.43 | 39.98 |
| Ryan Flournoy | DAL | receptions | 6 | 2.38 | 2.29 | 2.71 | 2.56 | 2.19 | 3.66 |
| Ryan Flournoy | DAL | targets | 7 | 3.50 | 3.48 | 3.92 | 3.76 | 3.17 | 5.15 |
| T.J. Bass | DAL | receiving_yards | 1 | - | - | - | - | - | - |
| Brock Purdy | SF | pass_attempts | 28 | 34.92 | 35.40 | 37.52 | 34.24 | 34.77 | 35.66 |
| Brock Purdy | SF | pass_completions | 22 | 24.37 | 24.16 | 26.05 | 23.62 | 23.49 | 24.77 |
| Brock Purdy | SF | pass_tds | 3 | 1.80 | 1.43 | 2.01 | 1.57 | 1.42 | 1.50 |
| Brock Purdy | SF | pass_yards | 389 | 263.72 | 257.32 | 285.50 | 249.79 | 236.22 | 257.94 |
| Brock Purdy | SF | rush_yards | 21 | 22.02 | 21.92 | 21.91 | 20.29 | 20.51 | 27.35 |
| Christian McCaffrey | SF | receiving_tds | 2 | 0.26 | 0.23 | 0.32 | 0.33 | 0.27 | 0.21 |
| Christian McCaffrey | SF | receiving_yards | 161 | 37.64 | 34.57 | 37.53 | 43.36 | 34.05 | 43.25 |
| Christian McCaffrey | SF | receptions | 4 | 4.99 | 4.97 | 5.04 | 5.23 | 5.16 | 4.95 |
| Christian McCaffrey | SF | rush_tds | 1 | 0.84 | 0.84 | 0.76 | 0.87 | 0.76 | 0.67 |
| Christian McCaffrey | SF | rush_yards | 62 | 100.60 | 98.56 | 93.74 | 103.19 | 96.95 | 77.89 |
| Christian McCaffrey | SF | targets | 4 | 6.55 | 6.69 | 6.95 | 6.64 | 6.70 | 6.47 |
| Deebo Samuel Sr. | SF | receiving_tds | 1 | - | - | - | - | - | - |
| Deebo Samuel Sr. | SF | receiving_yards | 31 | - | - | - | - | - | - |
| Deebo Samuel Sr. | SF | receptions | 3 | - | - | - | - | - | - |
| Deebo Samuel Sr. | SF | rush_tds | 1 | - | - | - | - | - | - |
| Deebo Samuel Sr. | SF | rush_yards | 78 | - | - | - | - | - | - |
| Deebo Samuel Sr. | SF | targets | 3 | - | - | - | - | - | - |
| George Kittle | SF | receiving_yards | 74 | 30.22 | 28.58 | 35.02 | 33.97 | 26.30 | 53.09 |
| George Kittle | SF | receptions | 6 | 2.92 | 2.86 | 3.37 | 3.29 | 2.57 | 5.31 |
| George Kittle | SF | targets | 9 | 3.85 | 4.11 | 4.61 | 4.23 | 3.56 | 7.10 |
| Jordan Watkins | SF | receiving_yards | 49 | 5.85 | 3.97 | 9.99 | 5.09 | 8.16 | 30.03 |
| Jordan Watkins | SF | receptions | 2 | 0.41 | 0.38 | 0.72 | 0.51 | 0.65 | 2.45 |
| Jordan Watkins | SF | targets | 3 | 0.56 | 0.59 | 1.04 | 0.77 | 0.94 | 3.61 |
| Kaelon Black | SF | receiving_yards | 13 | 1.45 | 0.96 | 2.58 | 1.38 | 0.95 | 6.04 |
| Kaelon Black | SF | receptions | 2 | 0.12 | 0.15 | 0.30 | 0.24 | 0.23 | 0.73 |
| Kaelon Black | SF | rush_tds | 1 | 0.00 | 0.02 | 0.00 | 0.02 | 0.00 | 0.17 |
| Kaelon Black | SF | rush_yards | 53 | 1.15 | 1.23 | 1.06 | 2.72 | 0.57 | 16.93 |
| Kaelon Black | SF | targets | 2 | 0.18 | 0.24 | 0.40 | 0.31 | 0.28 | 1.07 |
| Keenan Allen | SF | receiving_yards | 61 | 8.38 | 4.43 | 4.84 | 7.24 | 5.14 | 0.00 |
| Keenan Allen | SF | receptions | 5 | 0.72 | 0.52 | 0.48 | 0.55 | 0.46 | 0.00 |
| Keenan Allen | SF | targets | 7 | 0.99 | 0.82 | 0.78 | 0.79 | 0.77 | 0.00 |
