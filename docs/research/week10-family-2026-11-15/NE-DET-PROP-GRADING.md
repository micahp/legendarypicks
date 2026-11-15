# Week 10 NE@DET: prop grading, six SLC arms

Pre-kickoff lines only (captured before 2026-11-15T14:30:00Z). One row per player/market/line;
model probability is the share of 1,000 simulated games over the line, market
probability is the mean de-vigged over probability across books.

## Brier

| Forecast | Graded items | Brier |
|---|---:|---:|
| v1 | 237 | 0.2566 |
| v1.5 | 237 | 0.2585 |
| v1.6 | 237 | 0.2563 |
| v1.7 | 237 | 0.2393 |
| v1.7-pr43 | 237 | 0.2501 |
| v2 | 237 | 0.2391 |
| market | 237 | 0.2506 |
| constant_50 | 237 | 0.2500 |

## Items

| Player | Team | Market | Line | Actual | Over | Books | Market P | v1 | v1.5 | v1.6 | v1.7 | v1.7-pr43 | v2 |
|---|---|---|---:|---:|:--:|---:|---:|---:|---:|---:|---:|---:|---:|
| Amon-Ra St. Brown | DET | receiving_yards | 77.5 | 98 | yes | 9 | 0.50 | 0.59 | 0.60 | 0.63 | 0.55 | 0.51 | 0.56 |
| Amon-Ra St. Brown | DET | receiving_yards | 78.5 | 98 | yes | 12 | 0.50 | 0.58 | 0.59 | 0.62 | 0.53 | 0.50 | 0.56 |
| Amon-Ra St. Brown | DET | receiving_yards | 79.5 | 98 | yes | 10 | 0.50 | 0.57 | 0.58 | 0.61 | 0.53 | 0.49 | 0.55 |
| Amon-Ra St. Brown | DET | receiving_yards | 80.5 | 98 | yes | 6 | 0.51 | 0.57 | 0.57 | 0.61 | 0.52 | 0.48 | 0.54 |
| Amon-Ra St. Brown | DET | receiving_yards | 81.5 | 98 | yes | 10 | 0.50 | 0.56 | 0.57 | 0.60 | 0.51 | 0.47 | 0.53 |
| Amon-Ra St. Brown | DET | receiving_yards | 82.5 | 98 | yes | 8 | 0.50 | 0.55 | 0.56 | 0.59 | 0.50 | 0.46 | 0.52 |
| Amon-Ra St. Brown | DET | receiving_yards | 83.5 | 98 | yes | 3 | 0.50 | 0.55 | 0.56 | 0.59 | 0.50 | 0.45 | 0.51 |
| Amon-Ra St. Brown | DET | receptions | 7.0 | 4 | no | 2 | 0.49 | 0.57 | 0.57 | 0.57 | 0.50 | 0.49 | 0.53 |
| Amon-Ra St. Brown | DET | receptions | 7.5 | 4 | no | 9 | 0.48 | 0.57 | 0.57 | 0.57 | 0.50 | 0.49 | 0.53 |
| Amon-Ra St. Brown | DET | targets | 10.0 | 5 | no | 1 | 0.50 | 0.60 | 0.62 | 0.59 | 0.54 | 0.54 | 0.57 |
| Amon-Ra St. Brown | DET | targets | 10.5 | 5 | no | 1 | 0.50 | 0.60 | 0.62 | 0.59 | 0.54 | 0.54 | 0.57 |
| Brock Wright | DET | receiving_yards | 0.5 | 11 | yes | 1 | 0.50 | 0.70 | 0.71 | 0.67 | 0.67 | 0.66 | 0.49 |
| Isaac TeSlaa | DET | receiving_yards | 13.5 | 19 | yes | 2 | 0.50 | 0.33 | 0.35 | 0.36 | 0.34 | 0.33 | 0.39 |
| Isaac TeSlaa | DET | receiving_yards | 14.5 | 19 | yes | 8 | 0.50 | 0.32 | 0.33 | 0.35 | 0.33 | 0.32 | 0.38 |
| Isaac TeSlaa | DET | receiving_yards | 15.5 | 19 | yes | 11 | 0.50 | 0.30 | 0.32 | 0.33 | 0.32 | 0.30 | 0.36 |
| Isaac TeSlaa | DET | receiving_yards | 16.5 | 19 | yes | 8 | 0.50 | 0.30 | 0.31 | 0.32 | 0.31 | 0.29 | 0.34 |
| Isaac TeSlaa | DET | receiving_yards | 17.5 | 19 | yes | 11 | 0.50 | 0.28 | 0.29 | 0.31 | 0.29 | 0.28 | 0.33 |
| Isaac TeSlaa | DET | receiving_yards | 18.5 | 19 | yes | 7 | 0.50 | 0.27 | 0.28 | 0.29 | 0.27 | 0.27 | 0.31 |
| Isaac TeSlaa | DET | receiving_yards | 19.5 | 19 | no | 3 | 0.50 | 0.26 | 0.27 | 0.29 | 0.26 | 0.26 | 0.28 |
| Isaac TeSlaa | DET | receiving_yards | 20.5 | 19 | no | 7 | 0.50 | 0.26 | 0.27 | 0.28 | 0.25 | 0.26 | 0.27 |
| Isaac TeSlaa | DET | receiving_yards | 21.5 | 19 | no | 6 | 0.50 | 0.25 | 0.25 | 0.27 | 0.24 | 0.24 | 0.26 |
| Isaac TeSlaa | DET | receptions | 1.5 | 2 | yes | 11 | 0.45 | 0.30 | 0.30 | 0.31 | 0.29 | 0.29 | 0.35 |
| Isaac TeSlaa | DET | targets | 2.5 | 5 | yes | 1 | 0.50 | 0.28 | 0.28 | 0.28 | 0.29 | 0.28 | 0.34 |
| Jahmyr Gibbs | DET | receiving_yards | 30.5 | 99 | yes | 7 | 0.50 | 0.62 | 0.61 | 0.64 | 0.62 | 0.62 | 0.62 |
| Jahmyr Gibbs | DET | receiving_yards | 31.5 | 99 | yes | 12 | 0.50 | 0.60 | 0.59 | 0.62 | 0.61 | 0.61 | 0.60 |
| Jahmyr Gibbs | DET | receiving_yards | 32.5 | 99 | yes | 11 | 0.50 | 0.59 | 0.58 | 0.60 | 0.59 | 0.59 | 0.58 |
| Jahmyr Gibbs | DET | receiving_yards | 33.5 | 99 | yes | 5 | 0.49 | 0.58 | 0.57 | 0.59 | 0.57 | 0.57 | 0.57 |
| Jahmyr Gibbs | DET | receiving_yards | 133.5 | 99 | no | 1 | 0.50 | 0.01 | 0.00 | 0.01 | 0.01 | 0.01 | 0.01 |
| Jahmyr Gibbs | DET | receiving_yards | 134.5 | 99 | no | 1 | 0.50 | 0.01 | 0.00 | 0.01 | 0.01 | 0.00 | 0.01 |
| Jahmyr Gibbs | DET | receiving_yards | 135.5 | 99 | no | 1 | 0.49 | 0.01 | 0.00 | 0.00 | 0.01 | 0.00 | 0.01 |
| Jahmyr Gibbs | DET | receiving_yards | 136.5 | 99 | no | 1 | 0.50 | 0.01 | 0.00 | 0.00 | 0.01 | 0.00 | 0.01 |
| Jahmyr Gibbs | DET | receptions | 3.5 | 7 | yes | 2 | 0.58 | 0.69 | 0.70 | 0.71 | 0.69 | 0.68 | 0.68 |
| Jahmyr Gibbs | DET | receptions | 4.5 | 7 | yes | 9 | 0.46 | 0.53 | 0.53 | 0.56 | 0.53 | 0.51 | 0.50 |
| Jahmyr Gibbs | DET | rush_attempts | 20.0 | 22 | yes | 1 | 0.50 | 0.74 | 0.73 | 0.74 | 0.74 | 0.73 | 0.62 |
| Jahmyr Gibbs | DET | rush_attempts | 20.5 | 22 | yes | 8 | 0.48 | 0.74 | 0.73 | 0.74 | 0.74 | 0.73 | 0.62 |
| Jahmyr Gibbs | DET | rushing_receiving_touchdowns | 1.0 | 2 | yes | 1 | 0.50 | 0.36 | 0.33 | 0.36 | 0.35 | 0.34 | 0.23 |
| Jahmyr Gibbs | DET | rushing_receiving_yards | 126.5 | 252 | yes | 1 | 0.50 | 0.66 | 0.66 | 0.69 | 0.70 | 0.68 | 0.56 |
| Jahmyr Gibbs | DET | rushing_receiving_yards | 127.5 | 252 | yes | 7 | 0.50 | 0.66 | 0.66 | 0.69 | 0.70 | 0.67 | 0.55 |
| Jahmyr Gibbs | DET | rushing_receiving_yards | 128.5 | 252 | yes | 6 | 0.50 | 0.66 | 0.65 | 0.68 | 0.69 | 0.66 | 0.54 |
| Jahmyr Gibbs | DET | rushing_receiving_yards | 129.5 | 252 | yes | 8 | 0.50 | 0.65 | 0.64 | 0.67 | 0.68 | 0.65 | 0.54 |
| Jahmyr Gibbs | DET | rushing_receiving_yards | 130.5 | 252 | yes | 7 | 0.50 | 0.64 | 0.63 | 0.66 | 0.67 | 0.64 | 0.53 |
| Jahmyr Gibbs | DET | rushing_receiving_yards | 131.5 | 252 | yes | 5 | 0.50 | 0.64 | 0.62 | 0.66 | 0.67 | 0.64 | 0.52 |
| Jahmyr Gibbs | DET | rushing_receiving_yards | 132.5 | 252 | yes | 7 | 0.50 | 0.63 | 0.61 | 0.65 | 0.66 | 0.63 | 0.52 |
| Jahmyr Gibbs | DET | rushing_receiving_yards | 133.5 | 252 | yes | 8 | 0.50 | 0.63 | 0.61 | 0.64 | 0.66 | 0.62 | 0.51 |
| Jahmyr Gibbs | DET | rushing_receiving_yards | 134.5 | 252 | yes | 8 | 0.50 | 0.62 | 0.60 | 0.63 | 0.66 | 0.61 | 0.50 |
| Jahmyr Gibbs | DET | rushing_receiving_yards | 135.5 | 252 | yes | 5 | 0.50 | 0.61 | 0.60 | 0.62 | 0.65 | 0.60 | 0.50 |
| Jahmyr Gibbs | DET | rushing_receiving_yards | 136.5 | 252 | yes | 2 | 0.50 | 0.61 | 0.59 | 0.62 | 0.64 | 0.59 | 0.49 |
| Jahmyr Gibbs | DET | rushing_yards | 89.5 | 153 | yes | 7 | 0.50 | 0.64 | 0.63 | 0.66 | 0.66 | 0.63 | 0.53 |
| Jahmyr Gibbs | DET | rushing_yards | 90.5 | 153 | yes | 8 | 0.50 | 0.62 | 0.62 | 0.65 | 0.65 | 0.62 | 0.51 |
| Jahmyr Gibbs | DET | rushing_yards | 91.5 | 153 | yes | 7 | 0.50 | 0.62 | 0.62 | 0.65 | 0.64 | 0.61 | 0.50 |
| Jahmyr Gibbs | DET | rushing_yards | 92.5 | 153 | yes | 8 | 0.50 | 0.61 | 0.61 | 0.64 | 0.63 | 0.61 | 0.50 |
| Jahmyr Gibbs | DET | rushing_yards | 93.5 | 153 | yes | 3 | 0.50 | 0.60 | 0.60 | 0.62 | 0.62 | 0.60 | 0.49 |
| Jahmyr Gibbs | DET | rushing_yards | 94.5 | 153 | yes | 3 | 0.50 | 0.60 | 0.60 | 0.62 | 0.62 | 0.60 | 0.48 |
| Jahmyr Gibbs | DET | rushing_yards | 95.5 | 153 | yes | 9 | 0.50 | 0.60 | 0.59 | 0.61 | 0.61 | 0.59 | 0.47 |
| Jahmyr Gibbs | DET | rushing_yards | 96.5 | 153 | yes | 7 | 0.50 | 0.59 | 0.58 | 0.60 | 0.61 | 0.59 | 0.46 |
| Jahmyr Gibbs | DET | rushing_yards | 97.5 | 153 | yes | 11 | 0.50 | 0.58 | 0.57 | 0.59 | 0.60 | 0.58 | 0.45 |
| Jahmyr Gibbs | DET | rushing_yards | 98.5 | 153 | yes | 8 | 0.50 | 0.57 | 0.57 | 0.58 | 0.59 | 0.57 | 0.44 |
| Jahmyr Gibbs | DET | rushing_yards | 99.5 | 153 | yes | 2 | 0.49 | 0.56 | 0.56 | 0.58 | 0.59 | 0.57 | 0.44 |
| Jahmyr Gibbs | DET | rushing_yards | 100.5 | 153 | yes | 3 | 0.50 | 0.55 | 0.54 | 0.57 | 0.59 | 0.56 | 0.43 |
| Jahmyr Gibbs | DET | targets | 5.0 | 8 | yes | 1 | 0.50 | 0.62 | 0.60 | 0.64 | 0.59 | 0.57 | 0.55 |
| Jahmyr Gibbs | DET | total_touchdowns | 0.5 | 2 | yes | 1 | 0.67 | 0.72 | 0.68 | 0.76 | 0.72 | 0.70 | 0.61 |
| Jameson Williams | DET | receiving_yards | 53.5 | 50 | no | 2 | 0.50 | 0.43 | 0.42 | 0.42 | 0.37 | 0.36 | 0.42 |
| Jameson Williams | DET | receiving_yards | 54.5 | 50 | no | 6 | 0.50 | 0.43 | 0.41 | 0.41 | 0.36 | 0.36 | 0.41 |
| Jameson Williams | DET | receiving_yards | 55.5 | 50 | no | 10 | 0.50 | 0.42 | 0.40 | 0.40 | 0.35 | 0.35 | 0.40 |
| Jameson Williams | DET | receiving_yards | 56.5 | 50 | no | 12 | 0.50 | 0.41 | 0.39 | 0.39 | 0.34 | 0.34 | 0.39 |
| Jameson Williams | DET | receiving_yards | 57.5 | 50 | no | 3 | 0.49 | 0.40 | 0.38 | 0.39 | 0.33 | 0.34 | 0.38 |
| Jameson Williams | DET | receiving_yards | 58.5 | 50 | no | 1 | 0.49 | 0.39 | 0.38 | 0.38 | 0.33 | 0.33 | 0.37 |
| Jameson Williams | DET | receptions | 3.5 | 4 | yes | 9 | 0.53 | 0.59 | 0.58 | 0.58 | 0.52 | 0.54 | 0.59 |
| Jameson Williams | DET | targets | 6.0 | 7 | yes | 1 | 0.50 | 0.52 | 0.51 | 0.49 | 0.46 | 0.48 | 0.51 |
| Jared Goff | DET | interceptions_thrown | 0.5 | 2 | yes | 10 | 0.49 | 0.36 | 0.35 | 0.36 | 0.36 | 0.34 | 0.21 |
| Jared Goff | DET | pass_attempts | 34.5 | 31 | no | 9 | 0.51 | 0.66 | 0.68 | 0.67 | 0.54 | 0.56 | 0.51 |
| Jared Goff | DET | pass_attempts | 35.5 | 31 | no | 6 | 0.49 | 0.62 | 0.62 | 0.62 | 0.49 | 0.50 | 0.46 |
| Jared Goff | DET | pass_completions | 21.5 | 20 | no | 1 | 0.52 | 0.82 | 0.83 | 0.83 | 0.73 | 0.75 | 0.69 |
| Jared Goff | DET | pass_completions | 22.5 | 20 | no | 7 | 0.50 | 0.75 | 0.76 | 0.77 | 0.65 | 0.66 | 0.61 |
| Jared Goff | DET | pass_completions | 23.0 | 20 | no | 1 | 0.50 | 0.69 | 0.70 | 0.70 | 0.57 | 0.59 | 0.53 |
| Jared Goff | DET | pass_completions | 23.5 | 20 | no | 1 | 0.47 | 0.69 | 0.70 | 0.70 | 0.57 | 0.59 | 0.53 |
| Jared Goff | DET | pass_completions | 24.0 | 20 | no | 1 | 0.50 | 0.61 | 0.63 | 0.63 | 0.51 | 0.50 | 0.44 |
| Jared Goff | DET | pass_completions | 24.5 | 20 | no | 8 | 0.49 | 0.61 | 0.63 | 0.63 | 0.51 | 0.50 | 0.44 |
| Jared Goff | DET | passing_rushing_yards | 261.5 | 306 | yes | 3 | 0.50 | 0.64 | 0.65 | 0.66 | 0.52 | 0.50 | 0.52 |
| Jared Goff | DET | passing_rushing_yards | 265.5 | 306 | yes | 4 | 0.50 | 0.60 | 0.62 | 0.63 | 0.49 | 0.47 | 0.49 |
| Jared Goff | DET | passing_rushing_yards | 266.5 | 306 | yes | 2 | 0.50 | 0.59 | 0.61 | 0.62 | 0.49 | 0.46 | 0.48 |
| Jared Goff | DET | passing_rushing_yards | 267.5 | 306 | yes | 6 | 0.50 | 0.59 | 0.60 | 0.62 | 0.49 | 0.46 | 0.47 |
| Jared Goff | DET | passing_rushing_yards | 268.5 | 306 | yes | 4 | 0.50 | 0.58 | 0.60 | 0.61 | 0.48 | 0.46 | 0.46 |
| Jared Goff | DET | passing_rushing_yards | 269.5 | 306 | yes | 6 | 0.50 | 0.58 | 0.59 | 0.61 | 0.48 | 0.45 | 0.45 |
| Jared Goff | DET | passing_rushing_yards | 270.5 | 306 | yes | 7 | 0.50 | 0.57 | 0.58 | 0.60 | 0.47 | 0.43 | 0.44 |
| Jared Goff | DET | passing_rushing_yards | 271.5 | 306 | yes | 7 | 0.50 | 0.57 | 0.57 | 0.59 | 0.47 | 0.43 | 0.43 |
| Jared Goff | DET | passing_rushing_yards | 272.5 | 306 | yes | 6 | 0.50 | 0.56 | 0.56 | 0.58 | 0.46 | 0.42 | 0.43 |
| Jared Goff | DET | passing_rushing_yards | 274.5 | 306 | yes | 5 | 0.50 | 0.54 | 0.55 | 0.56 | 0.45 | 0.41 | 0.41 |
| Jared Goff | DET | passing_rushing_yards | 275.5 | 306 | yes | 2 | 0.50 | 0.54 | 0.54 | 0.55 | 0.44 | 0.40 | 0.41 |
| Jared Goff | DET | passing_rushing_yards | 277.5 | 306 | yes | 2 | 0.50 | 0.53 | 0.53 | 0.54 | 0.43 | 0.39 | 0.40 |
| Jared Goff | DET | passing_rushing_yards | 278.5 | 306 | yes | 1 | 0.50 | 0.52 | 0.53 | 0.53 | 0.43 | 0.39 | 0.39 |
| Jared Goff | DET | passing_touchdowns | 1.5 | 3 | yes | 7 | 0.60 | 0.50 | 0.48 | 0.61 | 0.55 | 0.54 | 0.34 |
| Jared Goff | DET | passing_yards | 259.5 | 303 | yes | 1 | 0.50 | 0.59 | 0.59 | 0.61 | 0.47 | 0.44 | 0.46 |
| Jared Goff | DET | passing_yards | 261.5 | 303 | yes | 1 | 0.50 | 0.57 | 0.59 | 0.59 | 0.46 | 0.43 | 0.44 |
| Jared Goff | DET | passing_yards | 262.5 | 303 | yes | 2 | 0.50 | 0.56 | 0.58 | 0.59 | 0.46 | 0.42 | 0.43 |
| Jared Goff | DET | passing_yards | 263.5 | 303 | yes | 1 | 0.50 | 0.55 | 0.57 | 0.58 | 0.45 | 0.41 | 0.43 |
| Jared Goff | DET | passing_yards | 264.5 | 303 | yes | 3 | 0.50 | 0.54 | 0.56 | 0.57 | 0.44 | 0.41 | 0.42 |
| Jared Goff | DET | passing_yards | 265.5 | 303 | yes | 3 | 0.50 | 0.54 | 0.55 | 0.56 | 0.44 | 0.39 | 0.41 |
| Jared Goff | DET | passing_yards | 266.5 | 303 | yes | 6 | 0.50 | 0.53 | 0.55 | 0.55 | 0.43 | 0.39 | 0.40 |
| Jared Goff | DET | passing_yards | 267.5 | 303 | yes | 10 | 0.50 | 0.53 | 0.54 | 0.55 | 0.43 | 0.39 | 0.39 |
| Jared Goff | DET | passing_yards | 268.5 | 303 | yes | 10 | 0.50 | 0.52 | 0.54 | 0.54 | 0.43 | 0.38 | 0.39 |
| Jared Goff | DET | passing_yards | 269.5 | 303 | yes | 9 | 0.50 | 0.52 | 0.53 | 0.53 | 0.42 | 0.38 | 0.39 |
| Jared Goff | DET | passing_yards | 270.5 | 303 | yes | 7 | 0.50 | 0.51 | 0.52 | 0.53 | 0.42 | 0.37 | 0.38 |
| Jared Goff | DET | passing_yards | 271.5 | 303 | yes | 2 | 0.50 | 0.50 | 0.51 | 0.52 | 0.41 | 0.37 | 0.37 |
| Jared Goff | DET | passing_yards | 272.5 | 303 | yes | 2 | 0.50 | 0.50 | 0.51 | 0.51 | 0.41 | 0.36 | 0.36 |
| Jared Goff | DET | passing_yards | 273.5 | 303 | yes | 1 | 0.48 | 0.49 | 0.50 | 0.51 | 0.39 | 0.36 | 0.35 |
| Jared Goff | DET | passing_yards | 274.5 | 303 | yes | 2 | 0.50 | 0.48 | 0.50 | 0.50 | 0.39 | 0.36 | 0.34 |
| Jared Goff | DET | rush_attempts | 1.5 | 1 | no | 2 | 0.50 | 0.54 | 0.55 | 0.52 | 0.51 | 0.53 | 0.56 |
| Jared Goff | DET | rushing_yards | 0.5 | 3 | yes | 7 | 0.48 | 0.77 | 0.78 | 0.77 | 0.76 | 0.74 | 0.81 |
| Sam LaPorta | DET | receiving_yards | 41.5 | 16 | no | 10 | 0.50 | 0.30 | 0.31 | 0.32 | 0.30 | 0.26 | 0.43 |
| Sam LaPorta | DET | receiving_yards | 42.5 | 16 | no | 10 | 0.50 | 0.29 | 0.30 | 0.31 | 0.28 | 0.25 | 0.42 |
| Sam LaPorta | DET | receiving_yards | 43.5 | 16 | no | 12 | 0.50 | 0.27 | 0.28 | 0.30 | 0.27 | 0.23 | 0.41 |
| Sam LaPorta | DET | receiving_yards | 44.5 | 16 | no | 8 | 0.50 | 0.26 | 0.27 | 0.28 | 0.25 | 0.22 | 0.40 |
| Sam LaPorta | DET | receiving_yards | 45.5 | 16 | no | 1 | 0.50 | 0.25 | 0.26 | 0.27 | 0.24 | 0.22 | 0.38 |
| Sam LaPorta | DET | receptions | 3.5 | 1 | no | 5 | 0.58 | 0.43 | 0.42 | 0.43 | 0.42 | 0.38 | 0.61 |
| Sam LaPorta | DET | receptions | 4.0 | 1 | no | 2 | 0.50 | 0.28 | 0.26 | 0.25 | 0.23 | 0.23 | 0.40 |
| Sam LaPorta | DET | receptions | 4.5 | 1 | no | 7 | 0.42 | 0.28 | 0.26 | 0.25 | 0.23 | 0.23 | 0.40 |
| Sam LaPorta | DET | targets | 5.5 | 4 | no | 1 | 0.50 | 0.34 | 0.36 | 0.34 | 0.32 | 0.29 | 0.55 |
| Sione Vaki | DET | receiving_yards | 1.5 | 17 | yes | 2 | 0.50 | 0.15 | 0.16 | 0.16 | 0.17 | 0.15 | 0.39 |
| Sione Vaki | DET | rush_attempts | 3.5 | 6 | yes | 2 | 0.50 | 0.03 | 0.04 | 0.04 | 0.04 | 0.04 | 0.46 |
| Sione Vaki | DET | rushing_receiving_yards | 17.5 | 45 | yes | 2 | 0.50 | 0.07 | 0.08 | 0.08 | 0.08 | 0.09 | 0.45 |
| Sione Vaki | DET | rushing_yards | 10.5 | 28 | yes | 1 | 0.53 | 0.04 | 0.05 | 0.06 | 0.06 | 0.06 | 0.50 |
| Sione Vaki | DET | rushing_yards | 11.5 | 28 | yes | 3 | 0.50 | 0.04 | 0.05 | 0.05 | 0.05 | 0.05 | 0.47 |
| Sione Vaki | DET | rushing_yards | 12.5 | 28 | yes | 10 | 0.50 | 0.04 | 0.05 | 0.05 | 0.05 | 0.05 | 0.44 |
| Sione Vaki | DET | rushing_yards | 13.5 | 28 | yes | 11 | 0.50 | 0.04 | 0.04 | 0.04 | 0.05 | 0.05 | 0.42 |
| Sione Vaki | DET | rushing_yards | 14.5 | 28 | yes | 3 | 0.50 | 0.03 | 0.04 | 0.04 | 0.04 | 0.04 | 0.39 |
| A.J. Brown | NE | receiving_yards | 50.5 | 27 | no | 4 | 0.50 | 0.03 | 0.03 | 0.03 | 0.01 | 0.01 | 0.01 |
| A.J. Brown | NE | receiving_yards | 51.5 | 27 | no | 9 | 0.50 | 0.03 | 0.03 | 0.03 | 0.02 | 0.01 | 0.01 |
| A.J. Brown | NE | receiving_yards | 52.5 | 27 | no | 3 | 0.50 | 0.03 | 0.03 | 0.03 | 0.01 | 0.01 | 0.01 |
| A.J. Brown | NE | receiving_yards | 53.5 | 27 | no | 2 | 0.50 | 0.03 | 0.03 | 0.03 | 0.01 | 0.01 | 0.01 |
| A.J. Brown | NE | receptions | 3.5 | 2 | no | 4 | 0.59 | 0.03 | 0.03 | 0.03 | 0.02 | 0.01 | 0.01 |
| A.J. Brown | NE | receptions | 4.0 | 2 | no | 2 | 0.50 | 0.02 | 0.01 | 0.01 | 0.01 | 0.00 | 0.00 |
| A.J. Brown | NE | receptions | 4.5 | 2 | no | 4 | 0.44 | 0.02 | 0.01 | 0.01 | 0.01 | 0.00 | 0.00 |
| A.J. Brown | NE | targets | 6.5 | 6 | no | 1 | 0.50 | 0.01 | 0.01 | 0.01 | 0.01 | 0.00 | 0.00 |
| Corey Kiner | NE | rush_attempts | 11.5 | 10 | no | 1 | 0.50 | 0.01 | 0.01 | 0.01 | 0.01 | 0.01 | 0.00 |
| Corey Kiner | NE | rush_attempts | 13.0 | 10 | no | 1 | 0.50 | 0.01 | 0.01 | 0.01 | 0.00 | 0.01 | 0.00 |
| Corey Kiner | NE | rush_attempts | 13.5 | 10 | no | 7 | 0.48 | 0.01 | 0.01 | 0.01 | 0.00 | 0.01 | 0.00 |
| Corey Kiner | NE | rushing_yards | 44.5 | 25 | no | 1 | 0.49 | 0.02 | 0.01 | 0.02 | 0.02 | 0.02 | 0.04 |
| Corey Kiner | NE | rushing_yards | 48.5 | 25 | no | 1 | 0.49 | 0.02 | 0.01 | 0.01 | 0.02 | 0.01 | 0.03 |
| Corey Kiner | NE | rushing_yards | 49.5 | 25 | no | 1 | 0.50 | 0.02 | 0.01 | 0.01 | 0.02 | 0.01 | 0.02 |
| Corey Kiner | NE | rushing_yards | 50.5 | 25 | no | 1 | 0.50 | 0.01 | 0.01 | 0.01 | 0.02 | 0.01 | 0.02 |
| Corey Kiner | NE | rushing_yards | 51.5 | 25 | no | 9 | 0.50 | 0.01 | 0.01 | 0.01 | 0.02 | 0.01 | 0.02 |
| Corey Kiner | NE | rushing_yards | 52.5 | 25 | no | 9 | 0.49 | 0.01 | 0.01 | 0.01 | 0.02 | 0.01 | 0.02 |
| Corey Kiner | NE | rushing_yards | 53.5 | 25 | no | 8 | 0.50 | 0.01 | 0.01 | 0.01 | 0.01 | 0.01 | 0.02 |
| Corey Kiner | NE | rushing_yards | 54.5 | 25 | no | 5 | 0.50 | 0.01 | 0.01 | 0.01 | 0.01 | 0.01 | 0.02 |
| DeMario Douglas | NE | receiving_yards | 38.5 | 4 | no | 3 | 0.50 | 0.54 | 0.54 | 0.56 | 0.50 | 0.51 | 0.56 |
| DeMario Douglas | NE | receiving_yards | 39.5 | 4 | no | 8 | 0.50 | 0.53 | 0.53 | 0.55 | 0.49 | 0.49 | 0.55 |
| DeMario Douglas | NE | receiving_yards | 40.5 | 4 | no | 2 | 0.50 | 0.52 | 0.52 | 0.53 | 0.48 | 0.49 | 0.54 |
| DeMario Douglas | NE | receptions | 3.5 | 1 | no | 5 | 0.47 | 0.51 | 0.53 | 0.50 | 0.47 | 0.50 | 0.56 |
| Drake Maye | NE | interceptions_thrown | 0.5 | 0 | no | 8 | 0.53 | 0.49 | 0.50 | 0.47 | 0.46 | 0.45 | 0.60 |
| Drake Maye | NE | pass_attempts | 33.5 | 4 | no | 8 | 0.50 | 0.55 | 0.59 | 0.58 | 0.44 | 0.46 | 0.33 |
| Drake Maye | NE | pass_attempts | 34.5 | 4 | no | 6 | 0.50 | 0.49 | 0.52 | 0.51 | 0.39 | 0.40 | 0.28 |
| Drake Maye | NE | pass_completions | 20.5 | 3 | no | 4 | 0.52 | 0.69 | 0.68 | 0.70 | 0.60 | 0.63 | 0.49 |
| Drake Maye | NE | pass_completions | 21.5 | 3 | no | 8 | 0.51 | 0.61 | 0.60 | 0.63 | 0.52 | 0.53 | 0.42 |
| Drake Maye | NE | pass_completions | 22.5 | 3 | no | 1 | 0.47 | 0.53 | 0.53 | 0.55 | 0.43 | 0.45 | 0.34 |
| Drake Maye | NE | passing_rushing_yards | 282.5 | 59 | no | 1 | 0.50 | 0.59 | 0.58 | 0.61 | 0.45 | 0.47 | 0.31 |
| Drake Maye | NE | passing_rushing_yards | 287.5 | 59 | no | 6 | 0.50 | 0.55 | 0.55 | 0.58 | 0.42 | 0.44 | 0.29 |
| Drake Maye | NE | passing_rushing_yards | 288.5 | 59 | no | 4 | 0.50 | 0.55 | 0.54 | 0.57 | 0.41 | 0.43 | 0.28 |
| Drake Maye | NE | passing_rushing_yards | 289.5 | 59 | no | 6 | 0.50 | 0.54 | 0.54 | 0.57 | 0.40 | 0.42 | 0.28 |
| Drake Maye | NE | passing_rushing_yards | 290.5 | 59 | no | 5 | 0.50 | 0.53 | 0.53 | 0.56 | 0.40 | 0.41 | 0.27 |
| Drake Maye | NE | passing_rushing_yards | 291.5 | 59 | no | 7 | 0.51 | 0.53 | 0.53 | 0.56 | 0.39 | 0.41 | 0.27 |
| Drake Maye | NE | passing_rushing_yards | 292.5 | 59 | no | 3 | 0.50 | 0.53 | 0.52 | 0.55 | 0.38 | 0.41 | 0.27 |
| Drake Maye | NE | passing_rushing_yards | 293.5 | 59 | no | 4 | 0.50 | 0.52 | 0.52 | 0.55 | 0.38 | 0.40 | 0.26 |
| Drake Maye | NE | passing_rushing_yards | 294.5 | 59 | no | 1 | 0.50 | 0.51 | 0.51 | 0.54 | 0.37 | 0.40 | 0.25 |
| Drake Maye | NE | passing_rushing_yards | 295.5 | 59 | no | 3 | 0.50 | 0.51 | 0.51 | 0.53 | 0.37 | 0.39 | 0.24 |
| Drake Maye | NE | passing_rushing_yards | 296.5 | 59 | no | 4 | 0.50 | 0.50 | 0.50 | 0.52 | 0.36 | 0.38 | 0.24 |
| Drake Maye | NE | passing_rushing_yards | 297.5 | 59 | no | 1 | 0.50 | 0.49 | 0.49 | 0.52 | 0.36 | 0.37 | 0.24 |
| Drake Maye | NE | passing_rushing_yards | 298.5 | 59 | no | 2 | 0.50 | 0.49 | 0.49 | 0.51 | 0.34 | 0.36 | 0.23 |
| Drake Maye | NE | passing_touchdowns | 1.5 | 0 | no | 6 | 0.57 | 0.47 | 0.45 | 0.58 | 0.45 | 0.45 | 0.37 |
| Drake Maye | NE | passing_yards | 256.5 | 48 | no | 1 | 0.53 | 0.52 | 0.52 | 0.56 | 0.40 | 0.40 | 0.26 |
| Drake Maye | NE | passing_yards | 257.5 | 48 | no | 4 | 0.51 | 0.51 | 0.51 | 0.55 | 0.39 | 0.39 | 0.25 |
| Drake Maye | NE | passing_yards | 258.5 | 48 | no | 2 | 0.52 | 0.51 | 0.51 | 0.55 | 0.38 | 0.38 | 0.25 |
| Drake Maye | NE | passing_yards | 259.5 | 48 | no | 8 | 0.50 | 0.51 | 0.50 | 0.54 | 0.37 | 0.38 | 0.24 |
| Drake Maye | NE | passing_yards | 260.5 | 48 | no | 9 | 0.50 | 0.50 | 0.49 | 0.54 | 0.36 | 0.37 | 0.23 |
| Drake Maye | NE | passing_yards | 261.5 | 48 | no | 10 | 0.50 | 0.49 | 0.48 | 0.53 | 0.36 | 0.37 | 0.22 |
| Drake Maye | NE | passing_yards | 262.5 | 48 | no | 9 | 0.50 | 0.49 | 0.47 | 0.52 | 0.36 | 0.36 | 0.22 |
| Drake Maye | NE | passing_yards | 263.5 | 48 | no | 6 | 0.50 | 0.49 | 0.47 | 0.51 | 0.35 | 0.36 | 0.21 |
| Drake Maye | NE | passing_yards | 264.5 | 48 | no | 1 | 0.50 | 0.48 | 0.46 | 0.50 | 0.34 | 0.36 | 0.21 |
| Drake Maye | NE | passing_yards | 265.5 | 48 | no | 3 | 0.50 | 0.46 | 0.45 | 0.50 | 0.34 | 0.35 | 0.20 |
| Drake Maye | NE | passing_yards | 266.5 | 48 | no | 2 | 0.50 | 0.46 | 0.44 | 0.49 | 0.33 | 0.35 | 0.20 |
| Drake Maye | NE | rush_attempts | 4.5 | 1 | no | 7 | 0.51 | 0.54 | 0.53 | 0.52 | 0.47 | 0.50 | 0.61 |
| Drake Maye | NE | rushing_yards | 24.5 | 11 | no | 6 | 0.50 | 0.67 | 0.66 | 0.66 | 0.64 | 0.65 | 0.63 |
| Drake Maye | NE | rushing_yards | 25.5 | 11 | no | 10 | 0.50 | 0.66 | 0.64 | 0.64 | 0.62 | 0.63 | 0.62 |
| Drake Maye | NE | rushing_yards | 26.5 | 11 | no | 10 | 0.50 | 0.63 | 0.62 | 0.63 | 0.60 | 0.61 | 0.60 |
| Drake Maye | NE | rushing_yards | 27.5 | 11 | no | 7 | 0.50 | 0.62 | 0.60 | 0.62 | 0.58 | 0.60 | 0.58 |
| Drake Maye | NE | rushing_yards | 28.5 | 11 | no | 3 | 0.50 | 0.59 | 0.59 | 0.60 | 0.57 | 0.58 | 0.57 |
| Drake Maye | NE | rushing_yards | 287.5 | 11 | no | 1 | 0.50 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Drake Maye | NE | rushing_yards | 288.5 | 11 | no | 1 | 0.50 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Drake Maye | NE | rushing_yards | 289.5 | 11 | no | 1 | 0.50 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Drake Maye | NE | rushing_yards | 290.5 | 11 | no | 1 | 0.50 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Drake Maye | NE | rushing_yards | 291.5 | 11 | no | 1 | 0.50 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Eli Raridon | NE | receiving_yards | 24.5 | 6 | no | 1 | 0.50 | 0.03 | 0.04 | 0.04 | 0.03 | 0.04 | 0.10 |
| Eli Raridon | NE | receiving_yards | 25.5 | 6 | no | 10 | 0.50 | 0.03 | 0.04 | 0.04 | 0.03 | 0.03 | 0.09 |
| Eli Raridon | NE | receiving_yards | 26.5 | 6 | no | 7 | 0.50 | 0.03 | 0.04 | 0.04 | 0.03 | 0.03 | 0.08 |
| Eli Raridon | NE | receiving_yards | 27.5 | 6 | no | 9 | 0.50 | 0.03 | 0.03 | 0.04 | 0.03 | 0.02 | 0.08 |
| Eli Raridon | NE | receptions | 2.5 | 1 | no | 6 | 0.42 | 0.03 | 0.03 | 0.02 | 0.02 | 0.02 | 0.07 |
| Eli Raridon | NE | targets | 3.0 | 1 | no | 1 | 0.50 | 0.03 | 0.03 | 0.01 | 0.01 | 0.02 | 0.07 |
| Hunter Henry | NE | receiving_yards | 30.5 | 22 | no | 1 | 0.52 | 0.76 | 0.79 | 0.78 | 0.74 | 0.73 | 0.66 |
| Hunter Henry | NE | receiving_yards | 32.5 | 22 | no | 1 | 0.49 | 0.73 | 0.77 | 0.75 | 0.71 | 0.71 | 0.63 |
| Hunter Henry | NE | receiving_yards | 33.5 | 22 | no | 4 | 0.50 | 0.72 | 0.76 | 0.74 | 0.70 | 0.70 | 0.61 |
| Hunter Henry | NE | receiving_yards | 34.5 | 22 | no | 3 | 0.51 | 0.70 | 0.74 | 0.73 | 0.68 | 0.69 | 0.60 |
| Hunter Henry | NE | receiving_yards | 35.5 | 22 | no | 9 | 0.50 | 0.69 | 0.73 | 0.72 | 0.66 | 0.68 | 0.58 |
| Hunter Henry | NE | receiving_yards | 36.5 | 22 | no | 4 | 0.50 | 0.68 | 0.71 | 0.70 | 0.65 | 0.67 | 0.57 |
| Hunter Henry | NE | receiving_yards | 37.5 | 22 | no | 9 | 0.51 | 0.67 | 0.70 | 0.69 | 0.64 | 0.66 | 0.55 |
| Hunter Henry | NE | receiving_yards | 38.5 | 22 | no | 8 | 0.50 | 0.66 | 0.69 | 0.68 | 0.62 | 0.64 | 0.55 |
| Hunter Henry | NE | receptions | 3.5 | 2 | no | 7 | 0.47 | 0.73 | 0.75 | 0.74 | 0.71 | 0.73 | 0.65 |
| Hunter Henry | NE | targets | 5.0 | 3 | no | 1 | 0.50 | 0.75 | 0.77 | 0.75 | 0.72 | 0.73 | 0.56 |
| Lan Larison | NE | receiving_yards | 12.5 | 15 | yes | 2 | 0.50 | 0.09 | 0.09 | 0.10 | 0.10 | 0.09 | 0.04 |
| Lan Larison | NE | rushing_receiving_yards | 27.5 | 17 | no | 1 | 0.50 | 0.07 | 0.07 | 0.07 | 0.06 | 0.06 | 0.06 |
| Lan Larison | NE | rushing_receiving_yards | 28.5 | 17 | no | 1 | 0.50 | 0.06 | 0.07 | 0.06 | 0.05 | 0.06 | 0.06 |
| Lan Larison | NE | rushing_yards | 12.5 | 2 | no | 2 | 0.50 | 0.07 | 0.08 | 0.07 | 0.07 | 0.07 | 0.18 |
| Lan Larison | NE | total_touchdowns | 0.5 | 1 | yes | 1 | 0.25 | 0.04 | 0.04 | 0.06 | 0.04 | 0.05 | 0.04 |
| Mack Hollins | NE | receiving_yards | 33.5 | 48 | yes | 3 | 0.50 | 0.76 | 0.76 | 0.79 | 0.73 | 0.74 | 0.49 |
| Mack Hollins | NE | receiving_yards | 34.5 | 48 | yes | 7 | 0.50 | 0.76 | 0.75 | 0.78 | 0.72 | 0.73 | 0.48 |
| Mack Hollins | NE | receiving_yards | 35.5 | 48 | yes | 4 | 0.50 | 0.75 | 0.74 | 0.77 | 0.71 | 0.73 | 0.47 |
| Mack Hollins | NE | receptions | 2.5 | 5 | yes | 7 | 0.53 | 0.83 | 0.84 | 0.85 | 0.81 | 0.82 | 0.59 |
| Mack Hollins | NE | targets | 5.0 | 6 | yes | 1 | 0.50 | 0.75 | 0.74 | 0.75 | 0.72 | 0.72 | 0.40 |
| Rhamondre Stevenson | NE | receiving_yards | 19.5 | 1 | no | 3 | 0.51 | 0.54 | 0.54 | 0.55 | 0.55 | 0.54 | 0.52 |
| Rhamondre Stevenson | NE | receiving_yards | 20.5 | 1 | no | 2 | 0.50 | 0.53 | 0.52 | 0.54 | 0.53 | 0.52 | 0.49 |
| Rhamondre Stevenson | NE | receiving_yards | 21.5 | 1 | no | 9 | 0.50 | 0.51 | 0.50 | 0.52 | 0.52 | 0.51 | 0.47 |
| Rhamondre Stevenson | NE | receptions | 2.5 | 1 | no | 2 | 0.58 | 0.60 | 0.60 | 0.60 | 0.58 | 0.59 | 0.61 |
| Rhamondre Stevenson | NE | receptions | 3.5 | 1 | no | 5 | 0.42 | 0.39 | 0.41 | 0.40 | 0.39 | 0.39 | 0.42 |
| Rhamondre Stevenson | NE | rush_attempts | 11.5 | 6 | no | 1 | 0.53 | 0.87 | 0.88 | 0.90 | 0.85 | 0.84 | 0.89 |
| Rhamondre Stevenson | NE | rush_attempts | 12.5 | 6 | no | 6 | 0.47 | 0.83 | 0.84 | 0.85 | 0.80 | 0.80 | 0.86 |
| Rhamondre Stevenson | NE | rush_attempts | 13.5 | 6 | no | 2 | 0.50 | 0.80 | 0.81 | 0.80 | 0.74 | 0.76 | 0.81 |
| Rhamondre Stevenson | NE | rushing_receiving_yards | 69.5 | 5 | no | 4 | 0.50 | 0.78 | 0.79 | 0.79 | 0.76 | 0.75 | 0.80 |
| Rhamondre Stevenson | NE | rushing_receiving_yards | 70.5 | 5 | no | 1 | 0.50 | 0.77 | 0.78 | 0.79 | 0.75 | 0.74 | 0.79 |
| Rhamondre Stevenson | NE | rushing_receiving_yards | 71.5 | 5 | no | 1 | 0.50 | 0.77 | 0.77 | 0.78 | 0.75 | 0.73 | 0.78 |
| Rhamondre Stevenson | NE | rushing_receiving_yards | 72.5 | 5 | no | 6 | 0.50 | 0.76 | 0.76 | 0.77 | 0.74 | 0.72 | 0.78 |
| Rhamondre Stevenson | NE | rushing_receiving_yards | 73.5 | 5 | no | 1 | 0.49 | 0.75 | 0.75 | 0.76 | 0.73 | 0.71 | 0.78 |
| Rhamondre Stevenson | NE | rushing_receiving_yards | 75.5 | 5 | no | 1 | 0.50 | 0.73 | 0.73 | 0.74 | 0.71 | 0.70 | 0.76 |
| Rhamondre Stevenson | NE | rushing_yards | 44.5 | 4 | no | 1 | 0.53 | 0.79 | 0.82 | 0.80 | 0.78 | 0.77 | 0.83 |
| Rhamondre Stevenson | NE | rushing_yards | 45.5 | 4 | no | 1 | 0.52 | 0.79 | 0.81 | 0.79 | 0.77 | 0.76 | 0.82 |
| Rhamondre Stevenson | NE | rushing_yards | 46.5 | 4 | no | 8 | 0.50 | 0.78 | 0.81 | 0.79 | 0.76 | 0.75 | 0.81 |
| Rhamondre Stevenson | NE | rushing_yards | 47.5 | 4 | no | 2 | 0.49 | 0.77 | 0.80 | 0.79 | 0.75 | 0.74 | 0.80 |
| Rhamondre Stevenson | NE | targets | 4.0 | 1 | no | 1 | 0.50 | 0.43 | 0.46 | 0.46 | 0.40 | 0.40 | 0.44 |
| Rhamondre Stevenson | NE | total_touchdowns | 0.5 | 0 | no | 1 | 0.43 | 0.61 | 0.61 | 0.59 | 0.54 | 0.55 | 0.45 |
