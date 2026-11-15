# 2026_10_BUF_NYJ: prop grading, six SLC arms

Pre-kickoff lines only (captured before 2026-11-15T18:00:00Z). One row per player/market/line;
model probability is the share of 1,000 simulated games over the line, market
probability is the mean de-vigged over probability across books.

## Brier

| Forecast | Graded items | Brier |
|---|---:|---:|
| v1 | 192 | 0.4029 |
| v1.5 | 192 | 0.4004 |
| v1.6 | 192 | 0.4068 |
| v1.7 | 192 | 0.3736 |
| v1.7-pr43 | 192 | 0.3798 |
| v2 | 192 | 0.3115 |
| market | 192 | 0.2499 |
| constant_50 | 192 | 0.2500 |

## Items

| Player | Team | Market | Line | Actual | Over | Books | Market P | v1 | v1.5 | v1.6 | v1.7 | v1.7-pr43 | v2 |
|---|---|---|---:|---:|:--:|---:|---:|---:|---:|---:|---:|---:|---:|
| DJ Moore | BUF | receiving_yards | 43.5 | 90 | yes | 1 | 0.50 | 0.02 | 0.02 | 0.02 | 0.02 | 0.01 | 0.07 |
| DJ Moore | BUF | receiving_yards | 44.5 | 90 | yes | 9 | 0.50 | 0.02 | 0.02 | 0.02 | 0.02 | 0.01 | 0.07 |
| DJ Moore | BUF | receiving_yards | 45.5 | 90 | yes | 10 | 0.50 | 0.02 | 0.02 | 0.01 | 0.01 | 0.01 | 0.06 |
| DJ Moore | BUF | receiving_yards | 46.5 | 90 | yes | 8 | 0.50 | 0.02 | 0.01 | 0.01 | 0.01 | 0.01 | 0.05 |
| DJ Moore | BUF | receiving_yards | 47.5 | 90 | yes | 9 | 0.50 | 0.02 | 0.02 | 0.01 | 0.01 | 0.01 | 0.05 |
| DJ Moore | BUF | receiving_yards | 48.5 | 90 | yes | 1 | 0.48 | 0.01 | 0.01 | 0.01 | 0.01 | 0.01 | 0.05 |
| DJ Moore | BUF | receptions | 3.5 | 4 | yes | 10 | 0.49 | 0.01 | 0.02 | 0.01 | 0.01 | 0.02 | 0.05 |
| DJ Moore | BUF | targets | 5.5 | 6 | yes | 1 | 0.50 | 0.01 | 0.02 | 0.02 | 0.01 | 0.02 | 0.03 |
| DJ Moore | BUF | total_touchdowns | 0.5 | 1 | yes | 1 | 0.34 | 0.02 | 0.02 | 0.02 | 0.03 | 0.02 | 0.05 |
| Dalton Kincaid | BUF | receiving_yards | 38.5 | 58 | yes | 3 | 0.50 | 0.20 | 0.20 | 0.21 | 0.21 | 0.18 | 0.27 |
| Dalton Kincaid | BUF | receiving_yards | 39.5 | 58 | yes | 2 | 0.50 | 0.20 | 0.19 | 0.20 | 0.20 | 0.17 | 0.26 |
| Dalton Kincaid | BUF | receiving_yards | 40.5 | 58 | yes | 9 | 0.50 | 0.19 | 0.18 | 0.19 | 0.20 | 0.16 | 0.24 |
| Dalton Kincaid | BUF | receiving_yards | 41.5 | 58 | yes | 10 | 0.50 | 0.17 | 0.17 | 0.18 | 0.18 | 0.14 | 0.23 |
| Dalton Kincaid | BUF | receiving_yards | 42.5 | 58 | yes | 2 | 0.50 | 0.16 | 0.17 | 0.17 | 0.17 | 0.14 | 0.22 |
| Dalton Kincaid | BUF | receiving_yards | 43.5 | 58 | yes | 2 | 0.50 | 0.16 | 0.16 | 0.17 | 0.16 | 0.13 | 0.21 |
| Dalton Kincaid | BUF | receptions | 3.5 | 2 | no | 10 | 0.48 | 0.22 | 0.21 | 0.23 | 0.23 | 0.20 | 0.37 |
| Dalton Kincaid | BUF | targets | 4.5 | 3 | no | 1 | 0.50 | 0.28 | 0.31 | 0.30 | 0.28 | 0.27 | 0.45 |
| Dawson Knox | BUF | receiving_yards | 10.5 | 7 | no | 1 | 0.51 | 0.66 | 0.64 | 0.65 | 0.64 | 0.65 | 0.76 |
| Dawson Knox | BUF | receiving_yards | 11.5 | 7 | no | 10 | 0.50 | 0.64 | 0.62 | 0.63 | 0.62 | 0.62 | 0.74 |
| Dawson Knox | BUF | receiving_yards | 12.5 | 7 | no | 8 | 0.50 | 0.63 | 0.60 | 0.61 | 0.60 | 0.60 | 0.73 |
| Dawson Knox | BUF | receiving_yards | 13.5 | 7 | no | 4 | 0.50 | 0.60 | 0.57 | 0.58 | 0.57 | 0.57 | 0.70 |
| Dawson Knox | BUF | receptions | 1.5 | 1 | no | 10 | 0.48 | 0.62 | 0.59 | 0.60 | 0.60 | 0.59 | 0.75 |
| Dawson Knox | BUF | targets | 2.0 | 3 | yes | 1 | 0.50 | 0.64 | 0.61 | 0.60 | 0.58 | 0.57 | 0.74 |
| Josh Allen | BUF | interceptions_thrown | 0.5 | 1 | yes | 6 | 0.40 | 0.50 | 0.50 | 0.52 | 0.50 | 0.51 | 0.43 |
| Josh Allen | BUF | pass_attempts | 28.5 | 21 | no | 9 | 0.50 | 0.93 | 0.94 | 0.92 | 0.91 | 0.91 | 0.86 |
| Josh Allen | BUF | pass_attempts | 29.0 | 21 | no | 1 | 0.50 | 0.91 | 0.92 | 0.89 | 0.89 | 0.89 | 0.83 |
| Josh Allen | BUF | pass_attempts | 29.5 | 21 | no | 1 | 0.46 | 0.91 | 0.92 | 0.89 | 0.89 | 0.89 | 0.83 |
| Josh Allen | BUF | pass_completions | 19.5 | 11 | no | 9 | 0.50 | 0.86 | 0.87 | 0.87 | 0.82 | 0.84 | 0.77 |
| Josh Allen | BUF | pass_completions | 20.0 | 11 | no | 1 | 0.50 | 0.81 | 0.81 | 0.81 | 0.74 | 0.79 | 0.72 |
| Josh Allen | BUF | pass_completions | 20.5 | 11 | no | 7 | 0.48 | 0.81 | 0.81 | 0.81 | 0.74 | 0.79 | 0.72 |
| Josh Allen | BUF | passing_rushing_yards | 256.5 | 201 | no | 2 | 0.50 | 0.77 | 0.78 | 0.79 | 0.69 | 0.72 | 0.61 |
| Josh Allen | BUF | passing_rushing_yards | 257.5 | 201 | no | 3 | 0.50 | 0.77 | 0.77 | 0.79 | 0.69 | 0.71 | 0.61 |
| Josh Allen | BUF | passing_rushing_yards | 258.5 | 201 | no | 2 | 0.50 | 0.77 | 0.76 | 0.78 | 0.68 | 0.71 | 0.59 |
| Josh Allen | BUF | passing_rushing_yards | 260.5 | 201 | no | 1 | 0.50 | 0.75 | 0.74 | 0.77 | 0.67 | 0.69 | 0.58 |
| Josh Allen | BUF | passing_rushing_yards | 261.5 | 201 | no | 3 | 0.50 | 0.75 | 0.74 | 0.76 | 0.67 | 0.69 | 0.57 |
| Josh Allen | BUF | passing_rushing_yards | 262.5 | 201 | no | 7 | 0.50 | 0.75 | 0.73 | 0.75 | 0.67 | 0.68 | 0.56 |
| Josh Allen | BUF | passing_rushing_yards | 263.5 | 201 | no | 6 | 0.50 | 0.74 | 0.73 | 0.75 | 0.66 | 0.68 | 0.55 |
| Josh Allen | BUF | passing_rushing_yards | 264.5 | 201 | no | 5 | 0.50 | 0.74 | 0.73 | 0.75 | 0.65 | 0.67 | 0.55 |
| Josh Allen | BUF | passing_rushing_yards | 265.5 | 201 | no | 3 | 0.50 | 0.73 | 0.72 | 0.74 | 0.64 | 0.66 | 0.54 |
| Josh Allen | BUF | passing_rushing_yards | 266.5 | 201 | no | 5 | 0.50 | 0.73 | 0.71 | 0.74 | 0.64 | 0.66 | 0.53 |
| Josh Allen | BUF | passing_rushing_yards | 267.5 | 201 | no | 4 | 0.50 | 0.72 | 0.71 | 0.73 | 0.63 | 0.65 | 0.53 |
| Josh Allen | BUF | passing_rushing_yards | 268.5 | 201 | no | 4 | 0.50 | 0.72 | 0.70 | 0.73 | 0.62 | 0.64 | 0.52 |
| Josh Allen | BUF | passing_rushing_yards | 269.5 | 201 | no | 4 | 0.50 | 0.71 | 0.70 | 0.72 | 0.62 | 0.64 | 0.52 |
| Josh Allen | BUF | passing_touchdowns | 1.5 | 1 | no | 9 | 0.56 | 0.45 | 0.44 | 0.57 | 0.47 | 0.52 | 0.27 |
| Josh Allen | BUF | passing_yards | 226.5 | 196 | no | 2 | 0.50 | 0.77 | 0.75 | 0.77 | 0.66 | 0.69 | 0.58 |
| Josh Allen | BUF | passing_yards | 227.5 | 196 | no | 7 | 0.50 | 0.76 | 0.74 | 0.76 | 0.66 | 0.69 | 0.58 |
| Josh Allen | BUF | passing_yards | 228.5 | 196 | no | 6 | 0.50 | 0.76 | 0.73 | 0.76 | 0.65 | 0.68 | 0.58 |
| Josh Allen | BUF | passing_yards | 230.5 | 196 | no | 1 | 0.50 | 0.75 | 0.72 | 0.75 | 0.63 | 0.67 | 0.56 |
| Josh Allen | BUF | passing_yards | 231.5 | 196 | no | 4 | 0.50 | 0.74 | 0.72 | 0.74 | 0.63 | 0.67 | 0.55 |
| Josh Allen | BUF | passing_yards | 232.5 | 196 | no | 3 | 0.50 | 0.74 | 0.72 | 0.74 | 0.62 | 0.66 | 0.55 |
| Josh Allen | BUF | passing_yards | 233.5 | 196 | no | 5 | 0.50 | 0.73 | 0.71 | 0.73 | 0.61 | 0.65 | 0.54 |
| Josh Allen | BUF | passing_yards | 234.5 | 196 | no | 7 | 0.50 | 0.73 | 0.71 | 0.73 | 0.60 | 0.65 | 0.54 |
| Josh Allen | BUF | passing_yards | 235.5 | 196 | no | 9 | 0.50 | 0.72 | 0.70 | 0.71 | 0.60 | 0.64 | 0.53 |
| Josh Allen | BUF | passing_yards | 236.5 | 196 | no | 1 | 0.50 | 0.71 | 0.70 | 0.70 | 0.59 | 0.64 | 0.52 |
| Josh Allen | BUF | passing_yards | 237.5 | 196 | no | 2 | 0.50 | 0.70 | 0.69 | 0.70 | 0.58 | 0.63 | 0.51 |
| Josh Allen | BUF | passing_yards | 250.5 | 196 | no | 1 | 0.50 | 0.61 | 0.61 | 0.62 | 0.51 | 0.54 | 0.41 |
| Josh Allen | BUF | rush_attempts | 6.5 | 5 | no | 8 | 0.52 | 0.26 | 0.24 | 0.26 | 0.22 | 0.23 | 0.37 |
| Josh Allen | BUF | rush_attempts | 7.0 | 5 | no | 1 | 0.50 | 0.14 | 0.13 | 0.13 | 0.11 | 0.13 | 0.26 |
| Josh Allen | BUF | rush_attempts | 7.5 | 5 | no | 1 | 0.48 | 0.14 | 0.13 | 0.13 | 0.11 | 0.13 | 0.26 |
| Josh Allen | BUF | rushing_yards | 25.5 | 5 | no | 1 | 0.50 | 0.61 | 0.62 | 0.62 | 0.65 | 0.61 | 0.61 |
| Josh Allen | BUF | rushing_yards | 26.5 | 5 | no | 4 | 0.50 | 0.59 | 0.60 | 0.60 | 0.63 | 0.58 | 0.59 |
| Josh Allen | BUF | rushing_yards | 27.5 | 5 | no | 10 | 0.50 | 0.56 | 0.59 | 0.59 | 0.61 | 0.57 | 0.57 |
| Josh Allen | BUF | rushing_yards | 28.5 | 5 | no | 9 | 0.50 | 0.55 | 0.57 | 0.57 | 0.58 | 0.55 | 0.56 |
| Josh Allen | BUF | rushing_yards | 29.5 | 5 | no | 5 | 0.49 | 0.53 | 0.54 | 0.55 | 0.56 | 0.54 | 0.54 |
| Keon Coleman | BUF | receiving_yards | 22.5 | 11 | no | 3 | 0.50 | 0.64 | 0.64 | 0.66 | 0.62 | 0.63 | 0.83 |
| Keon Coleman | BUF | receiving_yards | 23.5 | 11 | no | 3 | 0.50 | 0.63 | 0.63 | 0.66 | 0.61 | 0.62 | 0.82 |
| Keon Coleman | BUF | receiving_yards | 26.5 | 11 | no | 9 | 0.50 | 0.60 | 0.60 | 0.61 | 0.57 | 0.58 | 0.79 |
| Keon Coleman | BUF | receiving_yards | 27.5 | 11 | no | 9 | 0.50 | 0.59 | 0.59 | 0.60 | 0.56 | 0.56 | 0.78 |
| Keon Coleman | BUF | receiving_yards | 28.5 | 11 | no | 9 | 0.50 | 0.57 | 0.58 | 0.58 | 0.55 | 0.56 | 0.77 |
| Keon Coleman | BUF | receiving_yards | 29.5 | 11 | no | 1 | 0.47 | 0.56 | 0.56 | 0.57 | 0.54 | 0.54 | 0.75 |
| Keon Coleman | BUF | receptions | 2.5 | 1 | no | 5 | 0.43 | 0.59 | 0.58 | 0.59 | 0.56 | 0.56 | 0.83 |
| Keon Coleman | BUF | targets | 3.5 | 3 | no | 2 | 0.50 | 0.71 | 0.68 | 0.68 | 0.67 | 0.67 | 0.89 |
| Khalil Shakir | BUF | receiving_yards | 39.5 | 26 | no | 9 | 0.51 | 0.78 | 0.76 | 0.77 | 0.71 | 0.74 | 0.58 |
| Khalil Shakir | BUF | receiving_yards | 40.5 | 26 | no | 7 | 0.51 | 0.77 | 0.75 | 0.77 | 0.70 | 0.73 | 0.57 |
| Khalil Shakir | BUF | receiving_yards | 41.5 | 26 | no | 9 | 0.50 | 0.76 | 0.75 | 0.76 | 0.70 | 0.72 | 0.56 |
| Khalil Shakir | BUF | receiving_yards | 42.5 | 26 | no | 8 | 0.50 | 0.76 | 0.74 | 0.75 | 0.69 | 0.71 | 0.55 |
| Khalil Shakir | BUF | receiving_yards | 43.5 | 26 | no | 10 | 0.50 | 0.75 | 0.73 | 0.74 | 0.68 | 0.70 | 0.53 |
| Khalil Shakir | BUF | receiving_yards | 44.5 | 26 | no | 10 | 0.50 | 0.74 | 0.72 | 0.73 | 0.67 | 0.70 | 0.52 |
| Khalil Shakir | BUF | receiving_yards | 45.5 | 26 | no | 2 | 0.50 | 0.73 | 0.70 | 0.72 | 0.66 | 0.69 | 0.51 |
| Khalil Shakir | BUF | receptions | 3.5 | 2 | no | 8 | 0.53 | 0.80 | 0.77 | 0.77 | 0.75 | 0.76 | 0.61 |
| Khalil Shakir | BUF | targets | 5.0 | 3 | no | 1 | 0.50 | 0.78 | 0.79 | 0.79 | 0.78 | 0.79 | 0.61 |
| Khalil Shakir | BUF | total_touchdowns | 0.5 | 0 | no | 1 | 0.31 | 0.31 | 0.32 | 0.37 | 0.35 | 0.33 | 0.21 |
| Ray Davis | BUF | rush_attempts | 2.5 | 3 | yes | 2 | 0.50 | 0.42 | 0.39 | 0.44 | 0.41 | 0.38 | 0.20 |
| Ray Davis | BUF | rushing_yards | 6.5 | 8 | yes | 3 | 0.50 | 0.46 | 0.42 | 0.48 | 0.43 | 0.43 | 0.32 |
| Ray Davis | BUF | rushing_yards | 9.5 | 8 | no | 3 | 0.50 | 0.39 | 0.37 | 0.42 | 0.38 | 0.38 | 0.22 |
| Ty Johnson | BUF | receiving_yards | 13.5 | 4 | no | 1 | 0.51 | 0.39 | 0.39 | 0.39 | 0.40 | 0.39 | 0.15 |
| Ty Johnson | BUF | receiving_yards | 14.5 | 4 | no | 3 | 0.50 | 0.37 | 0.37 | 0.37 | 0.38 | 0.37 | 0.14 |
| Ty Johnson | BUF | receiving_yards | 15.5 | 4 | no | 9 | 0.50 | 0.34 | 0.35 | 0.35 | 0.36 | 0.35 | 0.13 |
| Ty Johnson | BUF | receiving_yards | 16.5 | 4 | no | 1 | 0.50 | 0.32 | 0.34 | 0.34 | 0.34 | 0.34 | 0.12 |
| Ty Johnson | BUF | receptions | 1.5 | 1 | no | 6 | 0.58 | 0.47 | 0.47 | 0.44 | 0.49 | 0.47 | 0.15 |
| Ty Johnson | BUF | targets | 2.5 | 1 | no | 1 | 0.50 | 0.44 | 0.46 | 0.42 | 0.42 | 0.45 | 0.08 |
| Adonai Mitchell | NYJ | receiving_yards | 33.5 | 59 | yes | 1 | 0.50 | 0.51 | 0.54 | 0.53 | 0.48 | 0.48 | 0.33 |
| Adonai Mitchell | NYJ | receiving_yards | 34.5 | 59 | yes | 7 | 0.50 | 0.50 | 0.53 | 0.52 | 0.47 | 0.47 | 0.32 |
| Adonai Mitchell | NYJ | receiving_yards | 35.5 | 59 | yes | 8 | 0.50 | 0.48 | 0.52 | 0.50 | 0.46 | 0.46 | 0.32 |
| Adonai Mitchell | NYJ | receiving_yards | 36.5 | 59 | yes | 9 | 0.50 | 0.47 | 0.50 | 0.49 | 0.44 | 0.45 | 0.30 |
| Adonai Mitchell | NYJ | receiving_yards | 37.5 | 59 | yes | 5 | 0.50 | 0.45 | 0.49 | 0.48 | 0.43 | 0.43 | 0.29 |
| Adonai Mitchell | NYJ | receptions | 2.5 | 3 | yes | 5 | 0.54 | 0.63 | 0.64 | 0.65 | 0.59 | 0.60 | 0.46 |
| Adonai Mitchell | NYJ | targets | 5.5 | 8 | yes | 2 | 0.50 | 0.59 | 0.60 | 0.59 | 0.56 | 0.59 | 0.39 |
| Braelon Allen | NYJ | receiving_yards | 6.5 | 6 | no | 9 | 0.50 | 0.11 | 0.10 | 0.11 | 0.10 | 0.11 | 0.60 |
| Braelon Allen | NYJ | receiving_yards | 7.5 | 6 | no | 4 | 0.50 | 0.09 | 0.09 | 0.10 | 0.08 | 0.10 | 0.57 |
| Braelon Allen | NYJ | receiving_yards | 8.5 | 6 | no | 3 | 0.50 | 0.08 | 0.08 | 0.08 | 0.07 | 0.10 | 0.53 |
| Braelon Allen | NYJ | receptions | 1.5 | 1 | no | 8 | 0.48 | 0.06 | 0.06 | 0.06 | 0.06 | 0.06 | 0.55 |
| Braelon Allen | NYJ | rush_attempts | 8.5 | 8 | no | 1 | 0.50 | 0.05 | 0.04 | 0.04 | 0.03 | 0.04 | 0.80 |
| Braelon Allen | NYJ | rushing_receiving_yards | 41.5 | 46 | yes | 1 | 0.50 | 0.06 | 0.05 | 0.05 | 0.05 | 0.06 | 0.81 |
| Braelon Allen | NYJ | rushing_receiving_yards | 42.5 | 46 | yes | 4 | 0.50 | 0.06 | 0.04 | 0.04 | 0.04 | 0.06 | 0.80 |
| Braelon Allen | NYJ | rushing_receiving_yards | 43.5 | 46 | yes | 6 | 0.50 | 0.06 | 0.04 | 0.04 | 0.04 | 0.06 | 0.79 |
| Braelon Allen | NYJ | rushing_receiving_yards | 44.5 | 46 | yes | 7 | 0.50 | 0.05 | 0.04 | 0.04 | 0.04 | 0.05 | 0.78 |
| Braelon Allen | NYJ | rushing_receiving_yards | 45.5 | 46 | yes | 5 | 0.50 | 0.05 | 0.04 | 0.04 | 0.04 | 0.05 | 0.77 |
| Braelon Allen | NYJ | rushing_receiving_yards | 49.5 | 46 | no | 2 | 0.50 | 0.05 | 0.03 | 0.04 | 0.04 | 0.04 | 0.72 |
| Braelon Allen | NYJ | rushing_receiving_yards | 50.5 | 46 | no | 2 | 0.50 | 0.04 | 0.03 | 0.04 | 0.04 | 0.04 | 0.71 |
| Braelon Allen | NYJ | rushing_yards | 31.5 | 40 | yes | 5 | 0.50 | 0.07 | 0.06 | 0.06 | 0.06 | 0.07 | 0.80 |
| Braelon Allen | NYJ | rushing_yards | 32.5 | 40 | yes | 4 | 0.50 | 0.07 | 0.05 | 0.06 | 0.06 | 0.07 | 0.79 |
| Braelon Allen | NYJ | rushing_yards | 33.5 | 40 | yes | 10 | 0.50 | 0.07 | 0.05 | 0.05 | 0.06 | 0.07 | 0.78 |
| Braelon Allen | NYJ | rushing_yards | 34.5 | 40 | yes | 8 | 0.50 | 0.07 | 0.05 | 0.05 | 0.05 | 0.06 | 0.77 |
| Braelon Allen | NYJ | rushing_yards | 35.5 | 40 | yes | 8 | 0.50 | 0.07 | 0.05 | 0.05 | 0.05 | 0.06 | 0.76 |
| Braelon Allen | NYJ | rushing_yards | 37.5 | 40 | yes | 3 | 0.50 | 0.06 | 0.05 | 0.05 | 0.05 | 0.05 | 0.74 |
| Breece Hall | NYJ | receiving_yards | 13.5 | 67 | yes | 1 | 0.50 | 0.54 | 0.55 | 0.54 | 0.56 | 0.55 | 0.39 |
| Breece Hall | NYJ | receiving_yards | 14.5 | 67 | yes | 8 | 0.50 | 0.52 | 0.53 | 0.52 | 0.54 | 0.52 | 0.36 |
| Breece Hall | NYJ | receiving_yards | 15.5 | 67 | yes | 4 | 0.51 | 0.48 | 0.50 | 0.49 | 0.51 | 0.50 | 0.34 |
| Breece Hall | NYJ | receiving_yards | 16.5 | 67 | yes | 11 | 0.50 | 0.46 | 0.48 | 0.47 | 0.50 | 0.47 | 0.32 |
| Breece Hall | NYJ | receiving_yards | 17.5 | 67 | yes | 9 | 0.50 | 0.44 | 0.45 | 0.45 | 0.48 | 0.46 | 0.30 |
| Breece Hall | NYJ | receiving_yards | 18.5 | 67 | yes | 1 | 0.51 | 0.42 | 0.43 | 0.42 | 0.46 | 0.44 | 0.28 |
| Breece Hall | NYJ | receptions | 2.5 | 4 | yes | 10 | 0.49 | 0.52 | 0.52 | 0.50 | 0.52 | 0.50 | 0.28 |
| Breece Hall | NYJ | rush_attempts | 13.5 | 11 | no | 9 | 0.49 | 0.59 | 0.62 | 0.62 | 0.62 | 0.57 | 0.35 |
| Breece Hall | NYJ | rushing_receiving_yards | 64.5 | 108 | yes | 1 | 0.50 | 0.71 | 0.70 | 0.73 | 0.73 | 0.69 | 0.46 |
| Breece Hall | NYJ | rushing_receiving_yards | 71.5 | 108 | yes | 2 | 0.50 | 0.65 | 0.65 | 0.67 | 0.67 | 0.64 | 0.40 |
| Breece Hall | NYJ | rushing_receiving_yards | 72.5 | 108 | yes | 7 | 0.50 | 0.65 | 0.64 | 0.66 | 0.66 | 0.62 | 0.39 |
| Breece Hall | NYJ | rushing_receiving_yards | 73.5 | 108 | yes | 3 | 0.50 | 0.64 | 0.63 | 0.65 | 0.66 | 0.62 | 0.38 |
| Breece Hall | NYJ | rushing_receiving_yards | 74.5 | 108 | yes | 9 | 0.50 | 0.63 | 0.63 | 0.64 | 0.65 | 0.61 | 0.37 |
| Breece Hall | NYJ | rushing_receiving_yards | 75.5 | 108 | yes | 10 | 0.50 | 0.62 | 0.62 | 0.63 | 0.64 | 0.60 | 0.36 |
| Breece Hall | NYJ | rushing_receiving_yards | 76.5 | 108 | yes | 3 | 0.50 | 0.61 | 0.61 | 0.63 | 0.63 | 0.59 | 0.36 |
| Breece Hall | NYJ | rushing_receiving_yards | 77.5 | 108 | yes | 3 | 0.50 | 0.60 | 0.60 | 0.62 | 0.62 | 0.58 | 0.34 |
| Breece Hall | NYJ | rushing_receiving_yards | 78.5 | 108 | yes | 3 | 0.50 | 0.59 | 0.59 | 0.61 | 0.61 | 0.57 | 0.34 |
| Breece Hall | NYJ | rushing_yards | 46.5 | 41 | no | 2 | 0.50 | 0.68 | 0.71 | 0.70 | 0.71 | 0.69 | 0.50 |
| Breece Hall | NYJ | rushing_yards | 52.5 | 41 | no | 9 | 0.50 | 0.62 | 0.64 | 0.65 | 0.66 | 0.62 | 0.42 |
| Breece Hall | NYJ | rushing_yards | 53.5 | 41 | no | 8 | 0.50 | 0.62 | 0.63 | 0.64 | 0.65 | 0.61 | 0.41 |
| Breece Hall | NYJ | rushing_yards | 54.5 | 41 | no | 10 | 0.50 | 0.61 | 0.62 | 0.63 | 0.64 | 0.61 | 0.41 |
| Breece Hall | NYJ | rushing_yards | 55.5 | 41 | no | 8 | 0.50 | 0.61 | 0.62 | 0.62 | 0.64 | 0.60 | 0.40 |
| Breece Hall | NYJ | rushing_yards | 56.5 | 41 | no | 8 | 0.50 | 0.60 | 0.61 | 0.61 | 0.63 | 0.60 | 0.39 |
| Breece Hall | NYJ | targets | 3.0 | 4 | yes | 1 | 0.50 | 0.56 | 0.56 | 0.54 | 0.54 | 0.53 | 0.25 |
| Breece Hall | NYJ | targets | 3.5 | 4 | yes | 1 | 0.50 | 0.56 | 0.56 | 0.54 | 0.54 | 0.53 | 0.25 |
| Breece Hall | NYJ | total_touchdowns | 0.5 | 0 | no | 1 | 0.44 | 0.45 | 0.47 | 0.45 | 0.41 | 0.41 | 0.27 |
| Garrett Wilson | NYJ | receiving_yards | 53.5 | 106 | yes | 2 | 0.50 | 0.38 | 0.38 | 0.42 | 0.33 | 0.33 | 0.58 |
| Garrett Wilson | NYJ | receiving_yards | 57.5 | 106 | yes | 3 | 0.50 | 0.35 | 0.34 | 0.39 | 0.28 | 0.31 | 0.53 |
| Garrett Wilson | NYJ | receiving_yards | 58.5 | 106 | yes | 1 | 0.51 | 0.33 | 0.33 | 0.38 | 0.28 | 0.30 | 0.53 |
| Garrett Wilson | NYJ | receiving_yards | 59.5 | 106 | yes | 6 | 0.50 | 0.33 | 0.32 | 0.37 | 0.27 | 0.29 | 0.52 |
| Garrett Wilson | NYJ | receiving_yards | 60.5 | 106 | yes | 10 | 0.50 | 0.32 | 0.31 | 0.35 | 0.27 | 0.28 | 0.51 |
| Garrett Wilson | NYJ | receiving_yards | 61.5 | 106 | yes | 11 | 0.50 | 0.31 | 0.30 | 0.34 | 0.26 | 0.28 | 0.50 |
| Garrett Wilson | NYJ | receiving_yards | 62.5 | 106 | yes | 6 | 0.50 | 0.30 | 0.29 | 0.33 | 0.25 | 0.27 | 0.48 |
| Garrett Wilson | NYJ | receiving_yards | 63.5 | 106 | yes | 5 | 0.50 | 0.29 | 0.28 | 0.33 | 0.25 | 0.26 | 0.48 |
| Garrett Wilson | NYJ | receptions | 5.5 | 7 | yes | 10 | 0.47 | 0.29 | 0.30 | 0.33 | 0.26 | 0.25 | 0.58 |
| Garrett Wilson | NYJ | targets | 7.5 | 14 | yes | 1 | 0.50 | 0.44 | 0.44 | 0.46 | 0.40 | 0.40 | 0.74 |
| Garrett Wilson | NYJ | targets | 8.0 | 14 | yes | 1 | 0.50 | 0.36 | 0.36 | 0.38 | 0.33 | 0.31 | 0.66 |
| Geno Smith | NYJ | interceptions_thrown | 0.5 | 0 | no | 10 | 0.50 | 0.53 | 0.55 | 0.54 | 0.53 | 0.55 | 0.29 |
| Geno Smith | NYJ | pass_attempts | 31.5 | 21 | no | 9 | 0.51 | 0.86 | 0.83 | 0.84 | 0.78 | 0.77 | 0.55 |
| Geno Smith | NYJ | pass_attempts | 32.0 | 21 | no | 1 | 0.50 | 0.82 | 0.80 | 0.79 | 0.73 | 0.72 | 0.49 |
| Geno Smith | NYJ | pass_attempts | 32.5 | 21 | no | 7 | 0.48 | 0.82 | 0.80 | 0.79 | 0.73 | 0.72 | 0.49 |
| Geno Smith | NYJ | pass_completions | 19.5 | 13 | no | 2 | 0.51 | 0.78 | 0.77 | 0.80 | 0.73 | 0.70 | 0.57 |
| Geno Smith | NYJ | pass_completions | 20.5 | 13 | no | 8 | 0.48 | 0.72 | 0.71 | 0.75 | 0.67 | 0.62 | 0.50 |
| Geno Smith | NYJ | pass_completions | 21.5 | 13 | no | 2 | 0.46 | 0.65 | 0.65 | 0.68 | 0.57 | 0.54 | 0.41 |
| Geno Smith | NYJ | passing_touchdowns | 1.5 | 0 | no | 7 | 0.36 | 0.28 | 0.28 | 0.43 | 0.33 | 0.32 | 0.17 |
| Geno Smith | NYJ | passing_yards | 216.5 | 148 | no | 1 | 0.50 | 0.61 | 0.62 | 0.66 | 0.49 | 0.47 | 0.30 |
| Geno Smith | NYJ | passing_yards | 217.5 | 148 | no | 5 | 0.50 | 0.60 | 0.62 | 0.65 | 0.49 | 0.46 | 0.29 |
| Geno Smith | NYJ | passing_yards | 218.5 | 148 | no | 7 | 0.50 | 0.60 | 0.60 | 0.65 | 0.48 | 0.46 | 0.29 |
| Geno Smith | NYJ | passing_yards | 219.5 | 148 | no | 6 | 0.50 | 0.59 | 0.60 | 0.65 | 0.47 | 0.45 | 0.28 |
| Geno Smith | NYJ | passing_yards | 220.5 | 148 | no | 11 | 0.50 | 0.59 | 0.59 | 0.64 | 0.46 | 0.45 | 0.28 |
| Geno Smith | NYJ | passing_yards | 221.5 | 148 | no | 8 | 0.50 | 0.58 | 0.58 | 0.63 | 0.46 | 0.43 | 0.27 |
| Geno Smith | NYJ | passing_yards | 222.5 | 148 | no | 7 | 0.50 | 0.58 | 0.57 | 0.63 | 0.45 | 0.42 | 0.26 |
| Geno Smith | NYJ | passing_yards | 223.5 | 148 | no | 9 | 0.50 | 0.57 | 0.57 | 0.62 | 0.44 | 0.42 | 0.26 |
| Geno Smith | NYJ | passing_yards | 224.5 | 148 | no | 3 | 0.50 | 0.56 | 0.56 | 0.61 | 0.43 | 0.41 | 0.25 |
| Geno Smith | NYJ | passing_yards | 225.5 | 148 | no | 3 | 0.50 | 0.56 | 0.56 | 0.60 | 0.43 | 0.41 | 0.24 |
| Geno Smith | NYJ | passing_yards | 226.5 | 148 | no | 1 | 0.50 | 0.55 | 0.55 | 0.59 | 0.42 | 0.40 | 0.24 |
| Kenyon Sadiq | NYJ | receiving_yards | 15.5 | 3 | no | 2 | 0.50 | 0.04 | 0.04 | 0.04 | 0.05 | 0.04 | 0.15 |
| Kenyon Sadiq | NYJ | receiving_yards | 16.5 | 3 | no | 3 | 0.50 | 0.04 | 0.04 | 0.03 | 0.04 | 0.03 | 0.14 |
| Kenyon Sadiq | NYJ | receiving_yards | 17.5 | 3 | no | 3 | 0.50 | 0.03 | 0.04 | 0.03 | 0.04 | 0.03 | 0.13 |
| Kenyon Sadiq | NYJ | receiving_yards | 19.5 | 3 | no | 1 | 0.51 | 0.03 | 0.03 | 0.03 | 0.03 | 0.02 | 0.11 |
| Kenyon Sadiq | NYJ | receiving_yards | 20.5 | 3 | no | 8 | 0.50 | 0.03 | 0.02 | 0.02 | 0.03 | 0.01 | 0.10 |
| Kenyon Sadiq | NYJ | receiving_yards | 21.5 | 3 | no | 9 | 0.50 | 0.02 | 0.02 | 0.02 | 0.03 | 0.01 | 0.09 |
| Kenyon Sadiq | NYJ | receiving_yards | 22.5 | 3 | no | 8 | 0.50 | 0.02 | 0.02 | 0.02 | 0.02 | 0.01 | 0.08 |
| Kenyon Sadiq | NYJ | receiving_yards | 23.5 | 3 | no | 8 | 0.50 | 0.02 | 0.02 | 0.02 | 0.02 | 0.01 | 0.07 |
| Kenyon Sadiq | NYJ | receptions | 2.5 | 1 | no | 6 | 0.45 | 0.01 | 0.01 | 0.01 | 0.01 | 0.01 | 0.05 |
| Kenyon Sadiq | NYJ | targets | 3.5 | 2 | no | 1 | 0.50 | 0.01 | 0.01 | 0.01 | 0.02 | 0.01 | 0.04 |
| Mason Taylor | NYJ | receiving_yards | 15.5 | 20 | yes | 10 | 0.50 | 0.67 | 0.69 | 0.68 | 0.68 | 0.64 | 0.64 |
| Mason Taylor | NYJ | receiving_yards | 16.5 | 20 | yes | 1 | 0.50 | 0.65 | 0.67 | 0.66 | 0.65 | 0.62 | 0.62 |
| Mason Taylor | NYJ | receiving_yards | 17.5 | 20 | yes | 1 | 0.47 | 0.62 | 0.66 | 0.64 | 0.63 | 0.60 | 0.60 |
| Mason Taylor | NYJ | receiving_yards | 18.5 | 20 | yes | 1 | 0.46 | 0.60 | 0.63 | 0.62 | 0.61 | 0.58 | 0.57 |
| Mason Taylor | NYJ | receiving_yards | 20.5 | 20 | no | 3 | 0.50 | 0.58 | 0.58 | 0.58 | 0.57 | 0.54 | 0.54 |
| Mason Taylor | NYJ | receiving_yards | 21.5 | 20 | no | 3 | 0.50 | 0.55 | 0.56 | 0.56 | 0.54 | 0.52 | 0.52 |
| Mason Taylor | NYJ | receptions | 1.5 | 4 | yes | 5 | 0.62 | 0.78 | 0.76 | 0.77 | 0.76 | 0.76 | 0.76 |
| Mason Taylor | NYJ | receptions | 2.0 | 4 | yes | 1 | 0.50 | 0.56 | 0.56 | 0.57 | 0.56 | 0.54 | 0.55 |
| Mason Taylor | NYJ | receptions | 2.5 | 4 | yes | 5 | 0.39 | 0.56 | 0.56 | 0.57 | 0.56 | 0.54 | 0.55 |
| Mason Taylor | NYJ | targets | 3.5 | 4 | yes | 1 | 0.50 | 0.67 | 0.65 | 0.67 | 0.66 | 0.64 | 0.62 |
