# Week 10: BUF at NYJ, SLC model family

**Final:** NYJ 12, BUF 31 (home win = 1).

Inputs: the prospective snapshots built 2026-11-14 18:54:46Z, week-10 kicker table
(LA = McManus), week-9 streaks and snap counts. Each arm is its own git ref.

## Game level

| Arm | Valid seeds | P(NYJ) | P(BUF) | P(tie) | Home Brier | NYJ mean (P10-P90) | BUF mean (P10-P90) | Total | Combined score error |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|
| v1 | 1000 | 32.8% | 67.2% | 0.0% | 0.452 | 19.69 (9-31) | 25.09 (14-37) | 44.78 | 13.60 |
| v1.5 | 1000 | 32.1% | 67.9% | 0.0% | 0.461 | 19.62 (9-30) | 24.85 (13-35) | 44.48 | 13.77 |
| v1.6 | 1000 | 33.9% | 66.1% | 0.0% | 0.437 | 20.82 (10-33) | 26.42 (14-38) | 47.24 | 13.39 |
| v1.7 | 1000 | 32.4% | 67.6% | 0.0% | 0.457 | 18.56 (9-30) | 24.43 (13-36) | 42.99 | 13.13 |
| v1.7-pr43 | 1000 | 32.5% | 67.4% | 0.1% | 0.456 | 18.46 (7-30) | 24.87 (13-37) | 43.34 | 12.59 |
| v2 | 1000 | 38.4% | 60.7% | 0.9% | 0.379 | 16.92 (6-27) | 20.53 (10-31) | 37.46 | 15.39 |

## Player stat accuracy (MAE over graded player-markets)

| Arm | Graded player-markets | MAE |
|---|---:|---:|
| v1 | 66 | 16.197 |
| v1.5 | 66 | 16.105 |
| v1.6 | 66 | 16.452 |
| v1.7 | 66 | 15.556 |
| v1.7-pr43 | 66 | 15.543 |
| v2 | 66 | 14.233 |

## Market grading

Not possible yet: `picks.dev.db` has no `prop_games` row for 2026-11-15
(newest NFL prop game is 2026-11-08), so there are no pre-kickoff lines for
this game. Prop Brier versus the de-vigged market runs once those lines land.

## Graded player-markets (model mean vs actual)

| Player | Team | Market | Actual | v1 | v1.5 | v1.6 | v1.7 | v1.7-pr43 | v2 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| DJ Moore | BUF | receiving_tds | 1 | 0.02 | 0.02 | 0.02 | 0.03 | 0.02 | 0.05 |
| DJ Moore | BUF | receiving_yards | 90 | 3.56 | 3.87 | 3.55 | 3.26 | 3.08 | 12.28 |
| DJ Moore | BUF | receptions | 4 | 0.30 | 0.33 | 0.30 | 0.29 | 0.27 | 1.05 |
| DJ Moore | BUF | rush_yards | 4 | 0.23 | 0.34 | 0.27 | 0.26 | 0.17 | 0.11 |
| DJ Moore | BUF | targets | 6 | 0.48 | 0.56 | 0.49 | 0.52 | 0.46 | 1.73 |
| Dalton Kincaid | BUF | receiving_yards | 58 | 22.90 | 22.90 | 23.67 | 22.77 | 20.78 | 28.45 |
| Dalton Kincaid | BUF | receptions | 2 | 2.25 | 2.30 | 2.29 | 2.26 | 2.14 | 3.08 |
| Dalton Kincaid | BUF | targets | 3 | 3.49 | 3.55 | 3.44 | 3.41 | 3.29 | 4.45 |
| Dawson Knox | BUF | receiving_yards | 7 | 23.88 | 22.07 | 22.49 | 21.33 | 22.20 | 28.10 |
| Dawson Knox | BUF | receptions | 1 | 2.38 | 2.25 | 2.24 | 2.20 | 2.20 | 2.93 |
| Dawson Knox | BUF | targets | 3 | 3.68 | 3.56 | 3.50 | 3.31 | 3.35 | 4.16 |
| Greg Dortch | BUF | targets | 1 | 0.51 | 0.56 | 0.57 | 0.47 | 0.48 | 0.03 |
| James Cook III | BUF | rush_tds | 1 | 0.60 | 0.59 | 0.61 | 0.56 | 0.57 | 0.56 |
| James Cook III | BUF | rush_yards | 157 | 77.41 | 77.42 | 76.28 | 76.62 | 79.09 | 76.52 |
| James Cook III | BUF | targets | 1 | 3.06 | 3.08 | 3.18 | 2.93 | 2.94 | 4.96 |
| Josh Allen | BUF | interceptions | 1 | 0.71 | 0.72 | 0.73 | 0.69 | 0.73 | 0.58 |
| Josh Allen | BUF | pass_attempts | 21 | 38.71 | 39.29 | 38.59 | 37.54 | 37.86 | 35.72 |
| Josh Allen | BUF | pass_completions | 11 | 24.84 | 24.87 | 24.76 | 23.79 | 24.21 | 23.51 |
| Josh Allen | BUF | pass_tds | 1 | 1.44 | 1.42 | 1.76 | 1.55 | 1.63 | 1.05 |
| Josh Allen | BUF | pass_yards | 196 | 269.04 | 266.93 | 271.51 | 252.00 | 256.05 | 241.73 |
| Josh Allen | BUF | rush_tds | 2 | 0.52 | 0.51 | 0.42 | 0.39 | 0.42 | 0.38 |
| Josh Allen | BUF | rush_yards | 5 | 33.91 | 34.15 | 34.87 | 34.66 | 34.49 | 34.20 |
| Keon Coleman | BUF | receiving_yards | 11 | 43.02 | 41.32 | 43.52 | 41.05 | 39.53 | 57.58 |
| Keon Coleman | BUF | receptions | 1 | 3.66 | 3.51 | 3.67 | 3.43 | 3.46 | 5.07 |
| Keon Coleman | BUF | targets | 3 | 6.24 | 6.12 | 6.27 | 6.12 | 6.06 | 8.28 |
| Khalil Shakir | BUF | receiving_yards | 26 | 76.09 | 75.46 | 76.03 | 68.50 | 72.99 | 52.35 |
| Khalil Shakir | BUF | receptions | 2 | 6.43 | 6.38 | 6.33 | 5.98 | 6.29 | 4.58 |
| Khalil Shakir | BUF | rush_yards | 29 | 0.28 | 0.29 | 0.18 | 0.19 | 0.17 | 0.31 |
| Khalil Shakir | BUF | targets | 3 | 9.66 | 9.86 | 9.58 | 9.34 | 9.68 | 6.90 |
| Kyle Allen | BUF | rush_yards | -2 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Ray Davis | BUF | rush_yards | 8 | 13.97 | 13.75 | 15.88 | 14.26 | 13.48 | 5.71 |
| Ty Johnson | BUF | receiving_yards | 4 | 13.87 | 14.31 | 14.18 | 14.26 | 14.68 | 5.64 |
| Ty Johnson | BUF | receptions | 1 | 1.68 | 1.72 | 1.65 | 1.74 | 1.74 | 0.67 |
| Ty Johnson | BUF | targets | 1 | 2.58 | 2.62 | 2.58 | 2.52 | 2.59 | 0.85 |
| Adonai Mitchell | NYJ | receiving_yards | 59 | 43.70 | 44.31 | 43.93 | 37.71 | 39.04 | 27.61 |
| Adonai Mitchell | NYJ | receptions | 3 | 3.84 | 3.80 | 3.86 | 3.49 | 3.55 | 2.66 |
| Adonai Mitchell | NYJ | targets | 8 | 7.36 | 7.25 | 7.23 | 6.77 | 6.96 | 5.15 |
| Andrew Beck | NYJ | rush_yards | 2 | 0.38 | 0.46 | 0.38 | 0.61 | 0.51 | 0.06 |
| Braelon Allen | NYJ | receiving_yards | 6 | 1.91 | 1.91 | 1.91 | 1.81 | 2.11 | 14.31 |
| Braelon Allen | NYJ | receptions | 1 | 0.28 | 0.27 | 0.28 | 0.28 | 0.28 | 1.91 |
| Braelon Allen | NYJ | rush_yards | 40 | 7.10 | 5.98 | 5.88 | 6.01 | 7.04 | 67.25 |
| Braelon Allen | NYJ | targets | 1 | 0.45 | 0.41 | 0.41 | 0.41 | 0.42 | 2.76 |
| Breece Hall | NYJ | receiving_yards | 67 | 19.66 | 19.70 | 20.18 | 20.22 | 20.19 | 13.02 |
| Breece Hall | NYJ | receptions | 4 | 2.79 | 2.83 | 2.81 | 2.88 | 2.86 | 1.82 |
| Breece Hall | NYJ | rush_yards | 41 | 78.51 | 79.09 | 81.37 | 80.53 | 76.34 | 53.38 |
| Breece Hall | NYJ | targets | 4 | 4.23 | 4.26 | 4.27 | 4.10 | 4.08 | 2.44 |
| Cade Klubnik | NYJ | interceptions | 1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Cade Klubnik | NYJ | pass_attempts | 20 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Cade Klubnik | NYJ | pass_completions | 11 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Cade Klubnik | NYJ | pass_yards | 137 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Cade Klubnik | NYJ | rush_yards | 26 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Garrett Wilson | NYJ | receiving_yards | 106 | 49.01 | 48.66 | 51.88 | 44.55 | 44.76 | 65.01 |
| Garrett Wilson | NYJ | receptions | 7 | 4.29 | 4.26 | 4.48 | 3.99 | 3.93 | 6.31 |
| Garrett Wilson | NYJ | targets | 14 | 7.43 | 7.45 | 7.62 | 7.04 | 6.99 | 10.49 |
| Geno Smith | NYJ | pass_attempts | 21 | 39.53 | 39.41 | 39.86 | 37.39 | 37.02 | 32.85 |
| Geno Smith | NYJ | pass_completions | 13 | 23.70 | 23.65 | 24.09 | 22.62 | 22.25 | 20.57 |
| Geno Smith | NYJ | pass_yards | 148 | 236.09 | 235.71 | 244.29 | 218.86 | 216.29 | 193.12 |
| Isaiah Williams | NYJ | receiving_yards | 24 | 32.24 | 31.29 | 35.11 | 27.76 | 29.50 | 14.11 |
| Isaiah Williams | NYJ | receptions | 4 | 2.80 | 2.80 | 3.04 | 2.55 | 2.60 | 1.33 |
| Isaiah Williams | NYJ | targets | 7 | 4.50 | 4.47 | 4.82 | 4.19 | 4.23 | 2.08 |
| Kenyon Sadiq | NYJ | receiving_yards | 3 | 1.80 | 1.80 | 1.50 | 1.90 | 1.63 | 6.27 |
| Kenyon Sadiq | NYJ | receptions | 1 | 0.20 | 0.20 | 0.17 | 0.21 | 0.20 | 0.69 |
| Kenyon Sadiq | NYJ | targets | 2 | 0.34 | 0.33 | 0.33 | 0.35 | 0.30 | 1.06 |
| Mason Taylor | NYJ | receiving_yards | 20 | 28.53 | 28.62 | 28.70 | 27.53 | 26.47 | 26.21 |
| Mason Taylor | NYJ | receptions | 4 | 3.13 | 3.06 | 3.06 | 3.01 | 2.97 | 2.92 |
| Mason Taylor | NYJ | targets | 4 | 5.05 | 4.86 | 5.00 | 4.77 | 4.72 | 4.48 |
