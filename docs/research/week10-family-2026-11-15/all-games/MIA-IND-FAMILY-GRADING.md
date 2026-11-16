# Week 10: MIA at IND, SLC model family

**Final:** IND 24, MIA 22 (home win = 1).

Inputs: the prospective snapshots built 2026-11-14 18:54:46Z, week-10 kicker table
(LA = McManus), week-9 streaks and snap counts. Each arm is its own git ref.

## Game level

| Arm | Valid seeds | P(IND) | P(MIA) | P(tie) | Home Brier | IND mean (P10-P90) | MIA mean (P10-P90) | Total | Combined score error |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|
| v1 | 100 | 47.0% | 53.0% | 0.0% | 0.281 | 19.36 (9-29) | 21.02 (10-30) | 40.38 | 5.62 |
| v1.5 | 100 | 49.0% | 51.0% | 0.0% | 0.260 | 20.73 (10-30) | 22.30 (13-35) | 43.03 | 3.57 |
| v1.6 | 100 | 33.0% | 67.0% | 0.0% | 0.449 | 19.17 (10-31) | 24.33 (13-35) | 43.50 | 7.16 |
| v1.7 | 100 | 40.0% | 60.0% | 0.0% | 0.360 | 19.43 (10-31) | 21.46 (10-35) | 40.89 | 5.11 |
| v1.7-pr43 | 100 | 45.0% | 55.0% | 0.0% | 0.303 | 18.60 (9-28) | 21.54 (10-34) | 40.14 | 5.86 |
| v2 | 100 | 34.0% | 64.0% | 2.0% | 0.436 | 16.67 (6-27) | 21.03 (12-31) | 37.70 | 8.30 |

## Player stat accuracy (MAE over graded player-markets)

| Arm | Graded player-markets | MAE |
|---|---:|---:|
| v1 | 71 | 11.866 |
| v1.5 | 71 | 12.125 |
| v1.6 | 71 | 11.545 |
| v1.7 | 71 | 10.890 |
| v1.7-pr43 | 71 | 10.965 |
| v2 | 71 | 9.897 |

## Market grading

Not possible yet: `picks.dev.db` has no `prop_games` row for 2026-11-15
(newest NFL prop game is 2026-11-08), so there are no pre-kickoff lines for
this game. Prop Brier versus the de-vigged market runs once those lines land.

## Graded player-markets (model mean vs actual)

| Player | Team | Market | Actual | v1 | v1.5 | v1.6 | v1.7 | v1.7-pr43 | v2 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| Anthony Gould | IND | receiving_yards | 28 | 6.42 | 5.06 | 5.33 | 6.02 | 5.96 | 0.24 |
| Anthony Gould | IND | receptions | 2 | 0.54 | 0.58 | 0.47 | 0.60 | 0.53 | 0.07 |
| Anthony Gould | IND | targets | 4 | 0.86 | 0.86 | 0.74 | 0.91 | 0.93 | 0.08 |
| Ashton Dulin | IND | receiving_yards | 30 | 10.47 | 7.37 | 11.91 | 8.19 | 8.98 | 12.78 |
| Ashton Dulin | IND | receptions | 1 | 1.00 | 0.71 | 1.01 | 0.86 | 0.90 | 1.18 |
| Ashton Dulin | IND | targets | 2 | 1.61 | 1.29 | 1.61 | 1.55 | 1.42 | 2.09 |
| Daniel Jones | IND | interceptions | 2 | 0.54 | 0.52 | 0.55 | 0.41 | 0.52 | 0.62 |
| Daniel Jones | IND | pass_attempts | 22 | 34.97 | 34.34 | 35.03 | 31.74 | 33.25 | 33.12 |
| Daniel Jones | IND | pass_completions | 11 | 20.91 | 20.84 | 21.09 | 19.25 | 19.98 | 20.21 |
| Daniel Jones | IND | pass_tds | 1 | 0.90 | 1.13 | 1.09 | 0.96 | 0.97 | 0.82 |
| Daniel Jones | IND | pass_yards | 108 | 218.36 | 224.42 | 218.84 | 193.13 | 200.51 | 196.13 |
| Daniel Jones | IND | rush_yards | 9 | 16.72 | 19.18 | 16.75 | 18.18 | 16.34 | 12.76 |
| Deion Burks | IND | targets | 2 | 0.59 | 1.17 | 0.90 | 0.81 | 0.83 | 0.83 |
| Drew Ogletree | IND | receiving_yards | 5 | 1.69 | 1.63 | 1.90 | 2.66 | 0.92 | 2.53 |
| Drew Ogletree | IND | receptions | 1 | 0.23 | 0.15 | 0.20 | 0.28 | 0.14 | 0.28 |
| Drew Ogletree | IND | targets | 2 | 0.33 | 0.24 | 0.36 | 0.42 | 0.19 | 0.47 |
| Jonathan Taylor | IND | receiving_yards | 20 | 23.62 | 24.61 | 23.96 | 20.88 | 23.79 | 22.94 |
| Jonathan Taylor | IND | receptions | 2 | 3.27 | 3.04 | 3.03 | 2.76 | 3.18 | 2.86 |
| Jonathan Taylor | IND | rush_yards | 83 | 96.25 | 105.65 | 89.92 | 101.47 | 100.12 | 78.16 |
| Jonathan Taylor | IND | targets | 4 | 4.91 | 4.65 | 4.47 | 4.12 | 4.54 | 4.10 |
| Laquon Treadwell | IND | receiving_tds | 1 | 0.01 | 0.02 | 0.03 | 0.01 | 0.03 | 0.20 |
| Laquon Treadwell | IND | receiving_yards | 24 | 6.36 | 4.96 | 8.87 | 7.45 | 5.39 | 54.15 |
| Laquon Treadwell | IND | receptions | 3 | 0.57 | 0.49 | 0.77 | 0.58 | 0.53 | 5.48 |
| Laquon Treadwell | IND | targets | 3 | 0.97 | 0.80 | 1.23 | 0.92 | 0.97 | 9.50 |
| Nick Westbrook-Ikhine | IND | targets | 1 | 0.88 | 1.18 | 0.87 | 0.71 | 0.89 | 0.20 |
| Seth McGowan | IND | rush_tds | 1 | 0.00 | 0.03 | 0.00 | 0.01 | 0.00 | 0.12 |
| Seth McGowan | IND | rush_yards | 77 | 2.24 | 1.94 | 0.31 | 1.19 | 1.29 | 8.75 |
| Tyler Warren | IND | receiving_yards | 1 | 49.30 | 46.32 | 45.94 | 44.08 | 39.10 | 43.99 |
| Tyler Warren | IND | receptions | 2 | 4.31 | 4.08 | 4.37 | 4.05 | 3.72 | 4.63 |
| Tyler Warren | IND | rush_yards | 3 | 0.08 | 0.21 | 0.13 | 0.54 | 0.13 | 0.65 |
| Tyler Warren | IND | targets | 3 | 6.89 | 6.75 | 6.94 | 6.34 | 5.95 | 7.10 |
| Caleb Douglas | MIA | receiving_yards | 71 | 8.50 | 7.52 | 10.31 | 10.03 | 8.05 | 24.64 |
| Caleb Douglas | MIA | receptions | 3 | 0.68 | 0.79 | 0.86 | 0.88 | 0.65 | 2.44 |
| Caleb Douglas | MIA | targets | 8 | 1.05 | 1.16 | 1.28 | 1.17 | 1.03 | 3.78 |
| DJ Herman | MIA | receiving_yards | 10 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| DJ Herman | MIA | receptions | 1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| DJ Herman | MIA | targets | 1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Greg Dulcich | MIA | targets | 2 | 4.45 | 4.45 | 3.97 | 3.62 | 4.25 | 4.74 |
| Jalen Reagor | MIA | targets | 1 | - | - | - | - | - | - |
| Jalen Tolbert | MIA | receiving_tds | 1 | 0.03 | 0.02 | 0.04 | 0.01 | 0.04 | 0.00 |
| Jalen Tolbert | MIA | receiving_yards | 49 | 8.51 | 10.15 | 7.10 | 6.00 | 6.18 | 1.81 |
| Jalen Tolbert | MIA | receptions | 2 | 0.82 | 0.89 | 0.63 | 0.65 | 0.61 | 0.26 |
| Jalen Tolbert | MIA | targets | 2 | 1.24 | 1.42 | 0.96 | 0.98 | 0.88 | 0.46 |
| Jaylen Wright | MIA | receiving_yards | 17 | 3.39 | 4.10 | 2.91 | 2.81 | 3.29 | 2.33 |
| Jaylen Wright | MIA | receptions | 2 | 0.52 | 0.43 | 0.38 | 0.40 | 0.35 | 0.24 |
| Jaylen Wright | MIA | rush_yards | -2 | 19.08 | 19.56 | 23.58 | 22.20 | 21.09 | 10.56 |
| Jaylen Wright | MIA | targets | 2 | 0.71 | 0.58 | 0.59 | 0.56 | 0.48 | 0.39 |
| Kaytron Allen | MIA | receiving_yards | -4 | 1.47 | 0.87 | 0.75 | 2.80 | 1.64 | 0.22 |
| Kaytron Allen | MIA | receptions | 1 | 0.22 | 0.09 | 0.10 | 0.36 | 0.21 | 0.02 |
| Kaytron Allen | MIA | targets | 1 | 0.30 | 0.16 | 0.17 | 0.43 | 0.24 | 0.02 |
| Kevin Coleman Jr. | MIA | receiving_yards | 6 | 9.50 | 9.90 | 8.94 | 8.58 | 6.17 | 15.14 |
| Kevin Coleman Jr. | MIA | receptions | 1 | 0.80 | 0.79 | 0.80 | 0.75 | 0.73 | 1.53 |
| Kevin Coleman Jr. | MIA | targets | 6 | 1.25 | 1.14 | 1.06 | 1.19 | 1.11 | 2.66 |
| Kyle McCord | MIA | pass_attempts | 32 | 33.55 | 33.37 | 31.64 | 31.04 | 32.00 | 29.34 |
| Kyle McCord | MIA | pass_completions | 17 | 23.81 | 23.20 | 22.56 | 21.86 | 22.26 | 19.53 |
| Kyle McCord | MIA | pass_yards | 209 | 236.77 | 237.83 | 225.91 | 212.18 | 214.69 | 182.24 |
| Kyle McCord | MIA | rush_tds | 1 | 0.20 | 0.17 | 0.18 | 0.20 | 0.18 | 0.34 |
| Kyle McCord | MIA | rush_yards | 4 | 12.21 | 16.27 | 13.36 | 16.96 | 13.87 | 26.41 |
| Malik Washington | MIA | pass_attempts | 1 | 0.01 | 0.01 | 0.00 | 0.00 | 0.01 | 0.02 |
| Malik Washington | MIA | pass_completions | 1 | 0.01 | 0.00 | 0.00 | 0.00 | 0.00 | 0.02 |
| Malik Washington | MIA | pass_tds | 1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.01 |
| Malik Washington | MIA | pass_yards | 34 | 0.06 | 0.00 | 0.00 | 0.00 | 0.00 | 0.14 |
| Malik Washington | MIA | receiving_yards | 50 | 130.81 | 127.82 | 128.45 | 114.46 | 118.62 | 79.21 |
| Malik Washington | MIA | receptions | 3 | 11.77 | 11.22 | 11.52 | 10.58 | 11.20 | 7.71 |
| Malik Washington | MIA | targets | 3 | 16.34 | 16.18 | 15.83 | 15.41 | 16.45 | 11.66 |
| Ollie Gordon II | MIA | receiving_yards | 39 | 3.62 | 2.76 | 2.13 | 3.28 | 3.02 | 9.69 |
| Ollie Gordon II | MIA | receptions | 4 | 0.47 | 0.40 | 0.35 | 0.43 | 0.40 | 1.29 |
| Ollie Gordon II | MIA | rush_yards | 76 | 17.01 | 21.48 | 19.82 | 18.01 | 24.98 | 52.65 |
| Ollie Gordon II | MIA | targets | 5 | 0.64 | 0.58 | 0.47 | 0.60 | 0.58 | 1.78 |
| Will Kacmarek | MIA | receiving_yards | 5 | 4.54 | 3.41 | 3.76 | 4.40 | 3.64 | 5.61 |
| Will Kacmarek | MIA | receptions | 1 | 0.37 | 0.36 | 0.41 | 0.53 | 0.39 | 0.60 |
| Will Kacmarek | MIA | targets | 1 | 0.53 | 0.51 | 0.51 | 0.70 | 0.64 | 0.91 |
